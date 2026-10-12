"""HTTP from the stack network; no privileged credentials or public ports."""
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError
from uuid import uuid4


def request(url, method='GET', body=None, headers=None):
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=payload, method=method, headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, None


def verify(stack):
    permissions = os.environ['PERMISSIONS_BASE_URL']
    printscript = os.environ['PRINTSCRIPT_BASE_URL']
    status, health = request(permissions + '/actuator/health')
    assert status == 200 and health['status'] == 'UP'
    print('PASS Permissions datasource HTTP health', flush=True)
    status, result = request(printscript + '/validate', 'POST', {'code': 'println(1);', 'version': '1.0'})
    assert status == 200 and result['valid'] is True
    print('PASS PrintScript internal HTTP validation', flush=True)
    if stack == 'snippet-searcher-dev':
        from smoke_tests import main
        if main() != 0:
            raise RuntimeError("Fallaron contratos HTTP de dev")
        key = str(uuid4())
        status, created = request('http://snippets-service:8080/snippets', 'POST',
            {'name': 'infra-bootstrap-probe', 'description': None, 'language': 'printscript', 'version': '1.0', 'code': 'println(1);'},
            {'Idempotency-Key': key, 'X-Dev-Actor-Id': 'infra-bootstrap-probe'})
        assert status == 201 and created.get('id')
        print(f"PASS Snippets creation/internal clients SQL/storage id={created['id']}", flush=True)
        status, owner = request(permissions + '/ownership/' + created['id'])
        assert status == 200 and owner['ownerId'] == 'infra-bootstrap-probe'
        print('PASS Snippets to Permissions ownership', flush=True)
    else:
        status, _ = request(permissions + '/ownership/' + str(uuid4()))
        assert status == 404
        print('PASS prod ownership query (no write)', flush=True)


if __name__ == '__main__':
    verify(sys.argv[1])
