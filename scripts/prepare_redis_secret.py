"""Generate one protected 256-bit Redis credential; never print its value."""
import argparse
import os
from pathlib import Path
import secrets


def create(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(secrets.token_hex(32))
        output.flush()
        os.fsync(output.fileno())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    create(args.path)
    print('Secreto generado; no se sobrescribe ni imprime una credencial existente.')
