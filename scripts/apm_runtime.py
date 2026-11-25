from stack_release import SERVICES, apm_enabled

LICENSE_SECRET = 'snippet-observability-{environment}-newrelic-license'


def license_secret(environment):
    return LICENSE_SECRET.format(environment=environment)


def apm_services(application=None):
    if application is None:
        return SERVICES
    return (application,) if application in SERVICES else ()


def require_apm_configuration(release, docker_json, application=None):
    expected = apm_enabled(release)
    secret = license_secret(release['environment'])
    stack = f'snippet-searcher-{release["environment"]}'
    for name in apm_services(application):
        spec = docker_json('service', 'inspect', f'{stack}_{name}')[0]['Spec']['TaskTemplate']['ContainerSpec']
        values = dict(entry.split('=', 1) for entry in spec.get('Env', []))
        secrets = {entry.get('SecretName') for entry in spec.get('Secrets', [])}
        enabled = values.get('NEW_RELIC_ENABLED', 'false') == 'true'
        if enabled != expected or (secret in secrets) != expected:
            raise ValueError(f'{name}: APM efectivo distinto del registro')
        if expected and values.get('NEW_RELIC_ENVIRONMENT') != release['environment']:
            raise ValueError(f'{name}: APM con otro ambiente')
