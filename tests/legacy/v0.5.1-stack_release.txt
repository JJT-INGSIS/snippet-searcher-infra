"""Pure selection of exact release references; atomic record I/O at the boundary."""
import json
import os
import re
from uuid import uuid4

SERVICES = ('snippets-service', 'permissions-service', 'printscript-service')
DATABASE_SERVICES = ('snippets-db', 'permissions-db')
STACK_SERVICES = (*SERVICES, *DATABASE_SERVICES)
VARIABLES = ('SNIPPETS_IMAGE', 'PERMISSIONS_IMAGE', 'PRINTSCRIPT_IMAGE')
DIGEST = r'sha256:[a-f0-9]{64}'


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('environment') not in {'dev', 'prod'}:
        raise ValueError('El ambiente debe ser dev o prod')
    images = manifest.get('images')
    if not isinstance(images, dict) or set(images) != set(SERVICES):
        raise ValueError('Indicar exactamente las tres aplicaciones')
    for service in SERVICES:
        if not isinstance(images[service], str) or not re.fullmatch(
            rf'ghcr\.io/jjt-ingsis/{service}@{DIGEST}', images[service]
        ):
            raise ValueError(f'{service}: se requiere su paquete exacto por digest')
    database = manifest.get('database_image')
    if not isinstance(database, str) or not re.fullmatch(rf'postgres:18\.6-bookworm@{DIGEST}', database):
        raise ValueError('PostgreSQL 18.6-bookworm requiere digest exacto')
    return {**dict(zip(VARIABLES, (images[service] for service in SERVICES))),
            'POSTGRES_IMAGE': database, 'DEPLOY_ENV': manifest['environment']}


def select_release(requested, previous):
    validate_manifest(requested)
    if previous is None:
        return {**requested}
    validate_manifest(previous)
    if previous['environment'] != requested['environment']:
        raise ValueError('El registro pertenece a otro ambiente')
    # Reapplying infrastructure takes current app AND database references.
    return {**requested, **previous, 'images': {**previous['images']},
            'database_image': previous['database_image']}


def update_service(previous, service, image):
    if service not in SERVICES:
        raise ValueError('Servicio desconocido')
    changed = {**previous, 'images': {**previous['images'], service: image}}
    validate_manifest(changed)
    return changed


def write_record(path, record):
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        with temporary.open('x') as output:
            os.chmod(temporary, 0o600)
            json.dump(record, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_promotion(prod, dev):
    validate_manifest(prod)
    validate_manifest(dev)
    if prod['environment'] != 'prod' or dev['environment'] != 'dev':
        raise ValueError('La promoción requiere dev a prod')
    if dev.get('checks', {}).get('sql_and_internal_http') != 'passed':
        raise ValueError('Falta evidencia confirmada de dev')
    if prod['images'] != dev['images'] or prod['database_image'] != dev['database_image']:
        raise ValueError('Prod debe usar exactamente los digests comprobados en dev')
