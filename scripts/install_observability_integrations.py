"""Stage checksum-pinned official integrations in a NEW directory; no agent/deploy changes."""

import argparse
import hashlib
import io
import json
import os
import ssl
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

LOCK = Path(__file__).resolve().parent.parent / "observability/integrations.lock.json"


def download(url):
    context = ssl.create_default_context()
    if Path("/etc/ssl/cert.pem").exists():
        context.load_verify_locations("/etc/ssl/cert.pem")
    with urlopen(url, context=context, timeout=30) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("Integration archive too large")
    return data


def stage_archive(data, digest, tool, root):
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Integration checksum mismatch")
    definition = tool.removeprefix("nri-") + "-definition.yml"
    allowed = {
        f"var/db/newrelic-infra/newrelic-integrations/bin/{tool}",
        f"var/db/newrelic-infra/newrelic-integrations/{definition}",
    }
    found = set()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            name = member.name.removeprefix("./")
            if name not in allowed:
                continue
            if not member.isfile() or name in found or member.size > 32 * 1024 * 1024:
                raise ValueError("Invalid integration member")
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            target.chmod(0o755 if "/bin/" in name else 0o644)
            found.add(name)
    if found != allowed:
        raise ValueError("Integration binary/definition missing")


def install(root, architecture):
    if root.exists() or root.is_symlink():
        raise ValueError("Staging directory already exists; will not overwrite it")
    lock = json.loads(LOCK.read_text())
    with tempfile.TemporaryDirectory(
        prefix=".sni82-install-", dir=root.parent
    ) as temporary:
        for tool, package in lock.items():
            asset = package["assets"][architecture]
            if not asset["url"].startswith(
                f"https://github.com/newrelic/{tool}/releases/download/v{package['version']}/"
            ):
                raise ValueError("Unexpected integration source")
            stage_archive(
                download(asset["url"]), asset["sha256"], tool, Path(temporary)
            )
        os.rename(temporary, root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--architecture", choices=["amd64", "arm64"], required=True)
    args = parser.parse_args()
    try:
        install(args.directory.absolute(), args.architecture)
    except (ValueError, OSError, tarfile.TarError):
        raise SystemExit(
            "Official integration staging failed; no live agent modified"
        ) from None
