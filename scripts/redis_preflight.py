"""Fail before installing Redis when the Docker filesystem or host has no reserve."""
import shutil
from pathlib import Path

MIN_DISK_BYTES = 512 * 1024 * 1024
MIN_AVAILABLE_MEMORY_BYTES = 384 * 1024 * 1024


def require_capacity(docker_root, disk_usage=shutil.disk_usage, meminfo=Path('/proc/meminfo')):
    if disk_usage(docker_root).free < MIN_DISK_BYTES:
        raise ValueError('Redis requiere al menos 512 MiB libres en el filesystem de Docker')
    values = dict(line.split(':', 1) for line in meminfo.read_text().splitlines())
    available = int(values['MemAvailable'].strip().split()[0]) * 1024
    if available < MIN_AVAILABLE_MEMORY_BYTES:
        raise ValueError('Redis requiere margen de al menos 384 MiB de RAM disponible')
