"""One-shot storage samples for New Relic Flex. Never reads application objects."""

import argparse
import json
import os
import signal
import time
from pathlib import Path
from uuid import uuid4

import asset_probe


class ProbeFailure(Exception):
    pass


def filesystem(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstatvfs(descriptor)
    finally:
        os.close(descriptor)
    return {
        "availableBytes": info.f_bavail * info.f_frsize,
        "totalBytes": info.f_blocks * info.f_frsize,
        "availableInodes": info.f_favail,
    }


def local(path):
    # The configured mount and private directory must not resolve through symlinks.
    root = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = None
    name = uuid4().hex
    created = False
    try:
        try:
            os.mkdir(".sni82-probe", mode=0o700, dir_fd=root)
        except FileExistsError:
            pass
        directory = os.open(
            ".sni82-probe", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root
        )
        payload = ("sni82:" + uuid4().hex + ":¡Hola 🌎!\n").encode()
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        created = True
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, "rb") as incoming:
            if incoming.read(len(payload) + 1) != payload:
                raise ProbeFailure("content-mismatch")
        os.unlink(name, dir_fd=directory)
        created = False
        return {
            **filesystem(path),
            "writeOk": 1,
            "readOk": 1,
            "contentOk": 1,
            "deleteOk": 1,
        }
    finally:
        if created and directory is not None:
            try:
                os.unlink(name, dir_fd=directory)
            except OSError:
                pass
        if directory is not None:
            os.close(directory)
        os.close(root)


def asset(base, environment, timeout):
    # A stable private fixture bounds abandoned writes after a transport interruption.
    # Only one scheduled instance may own each environment's fixture.
    path = (
        "/v1/asset/infra-sni82-" + environment + "/00000000-0000-4000-8000-000000000082"
    )
    payload = asset_probe.envelope("sni82:" + uuid4().hex + ":¡Hola 🌎!\n")
    try:
        written = asset_probe.request(base, path, "PUT", payload, timeout=timeout)
        if written.status not in (200, 201, 204):
            raise ProbeFailure("write-failed")
        read = asset_probe.request(base, path, timeout=timeout)
        if read.status != 200:
            raise ProbeFailure("read-failed")
        if read.body != payload:
            raise ProbeFailure("content-mismatch")
        deleted = asset_probe.request(base, path, "DELETE", timeout=timeout)
        if deleted.status not in (204, 404):
            raise ProbeFailure("delete-failed")
        absent = asset_probe.request(base, path, timeout=timeout)
        if absent.status != 404:
            raise ProbeFailure("delete-unconfirmed")
        return {"writeOk": 1, "readOk": 1, "contentOk": 1, "deleteOk": 1}
    except asset_probe.ProbeFailure as error:
        raise ProbeFailure("transport-failed") from error


def sample(settings):
    began = time.monotonic()
    value = {
        key: settings[key] for key in ("environment", "service", "version", "kind")
    }
    try:
        if settings["kind"] in ("local", "filesystem"):
            value.update(filesystem(settings["path"]))
        if settings["kind"] == "asset":
            parsed = (
                asset_probe.base_url("STORAGE_ASSET_BASE_URL")
                if "baseUrl" not in settings
                else settings["baseUrl"]
            )
            # Reuse the existing URL validator without using a process proxy or credentials.
            from urllib.parse import urlsplit

            url = urlsplit(parsed)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.path not in ("", "/")
                or url.query
                or url.fragment
            ):
                raise ValueError("Invalid Asset URL")
            details = asset(
                parsed.rstrip("/"),
                settings["environment"],
                settings.get("timeoutSeconds", 5),
            )
        elif settings["kind"] == "local":
            details = local(settings["path"])
        else:
            details = filesystem(settings["path"])
        value.update(details, up=1, reason="ok")
    except ProbeFailure as error:
        value.update(up=0, reason=str(error))
    except (OSError, TimeoutError):
        value.update(up=0, reason="io-failed")
    value["durationMs"] = round((time.monotonic() - began) * 1000, 3)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--service", required=True)
    args = parser.parse_args()
    # Validation and identity are shared with the config generator.
    from observability_config import validate

    config = validate(json.loads(args.config.read_text()))
    selected = next(
        (s for s in config["storage"] if s["service"] == args.service), None
    )
    if selected is None:
        raise ValueError("Unknown storage service")

    def expired(*_):
        raise TimeoutError("Probe deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(25)
    try:
        print(
            json.dumps(
                sample(
                    {
                        **selected,
                        "environment": config["environment"],
                        "version": config["version"],
                    }
                )
            )
        )
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, StopIteration):
        # No config content, URL, object body or exception details in telemetry/logs.
        raise SystemExit("Invalid storage probe configuration") from None
