from stack_release import background_environment

SNIPPETS = 'snippets-service'
PRINTSCRIPT = 'printscript-service'
SNIPPETS_KEYS = ('SNIPPETS_OUTBOX_ENABLED', 'SNIPPETS_WORKER_ENABLED')
PRINTSCRIPT_KEYS = ('PRINTSCRIPT_OPERATIONS_ENABLED',)


def background_services(application=None):
    services = {SNIPPETS: SNIPPETS_KEYS, PRINTSCRIPT: PRINTSCRIPT_KEYS}
    if application is None:
        return services
    return {application: services[application]} if application in services else {}


def require_background_configuration(release, docker_json, application=None):
    expected = background_environment(release)
    stack = f'snippet-searcher-{release["environment"]}'
    for name, keys in background_services(application).items():
        spec = docker_json('service', 'inspect', f'{stack}_{name}')[0]['Spec']['TaskTemplate']['ContainerSpec']
        values = dict(entry.split('=', 1) for entry in spec.get('Env', []))
        for key in keys:
            if values.get(key, 'false') != expected[key]:
                raise ValueError(f'{name}: procesamiento de fondo efectivo distinto del registro ({key})')
