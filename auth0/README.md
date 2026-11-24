# Auth0

Snippet Searcher usa un tenant compartido con una SPA y una API por ambiente. DEV y PROD tienen client IDs, audiences y URLs de aplicación propios.

## Recursos administrados

[`main.tf`](main.tf) administra la SPA pública de DEV, su API con RS256 y la asociación de la SPA a la conexión de usuarios existente. También administra el cliente M2M del directorio de DEV y su grant `read:users` para Auth0 Management API. Los recursos ya existentes se adoptan mediante importación si faltan en el estado.

La SPA usa Authorization Code con PKCE. Su client ID es público. El backend usa una credencial M2M separada para buscar destinatarios al compartir. La credencial del operador de Terraform es independiente de ambas.

El módulo administra recursos de DEV. La configuración pública aprobada para el despliegue vive en [DEV](development.public.json) y [PROD](production.public.json). Esos archivos registran el dominio, el issuer, la audience y las URLs autorizadas del ambiente.

## Configuración en runtime

1. [`auth_rollout.py`](../scripts/auth_rollout.py) toma la configuración pública del ambiente, comprueba el ingreso HTTPS y genera un manifiesto de release. PROD exige la confirmación administrativa registrada en su JSON.
2. Swarm entrega `AUTH_MODE`, `AUTH_ISSUER` y `AUTH_AUDIENCE` a Snippets. El backend valida el access token y toma el actor de `sub`.
3. Swarm entrega `UI_AUTH_DOMAIN`, `UI_AUTH_CLIENT_ID` y `UI_AUTH_AUDIENCE` a la UI, que genera `/app-config.json` al arrancar. El callback es `/auth/callback` y el retorno de logout es `/`.

El render valida que la UI y la API usen parámetros del mismo ambiente. El secreto del directorio llega a Snippets como secreto del stack. Los parámetros públicos se aplican al desplegar la release, después de revisar el manifiesto.

## Verificación y operación

Desde la raíz de infra, con Terraform 1.13.x y el proveedor Auth0 1.56.0 fijado en el lockfile:

```powershell
terraform -chdir=auth0 init -backend=false -input=false -lockfile=readonly
terraform -chdir=auth0 fmt -check -recursive
terraform -chdir=auth0 validate
terraform -chdir=auth0 test
```

Las pruebas usan un proveedor simulado y no requieren credenciales de Auth0. Para un plan real de DEV, usá [`development.tfvars.example`](development.tfvars.example) como base para el archivo local `development.tfvars` y cargá `AUTH0_CLIENT_ID` y `AUTH0_CLIENT_SECRET` solo en el proceso de Terraform. Confirmá el tenant y revisá el plan antes de cualquier apply. Guardá el estado local, los planes y la credencial en almacenamiento protegido.

Para preparar el manifiesto de runtime se usa `scripts/bootstrap_swarm.py plan` con `--auth0-dev` o `--auth0-prod`, según el ambiente. Revisá el candidato y usá el alcance de infraestructura `--auth-only` cuando corresponda. Este alcance modifica Snippets y UI y conserva las imágenes. Ver [despliegues y recuperación](../docs/deployment.md#cambios-al-stack).

Verificá `identity.mode=auth0` en `/app-config.json`, la ruta pública `/api/languages` y el 401 de una consulta protegida sin credencial. Después completá el login y comprobá un listado autenticado. Validá también la búsqueda de destinatarios cuando se configura el directorio. Evitá registrar tokens o datos OAuth. [Contrato de autorización](../docs/architecture/authentication-authorization-contract.md).
