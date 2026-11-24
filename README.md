# Snippet Searcher Infra

Este repositorio define el entorno local con Docker Compose, la configuración de
Swarm para DEV y PROD y las herramientas de despliegue, recuperación e
instrumentación. Los servicios conservan su código y Dockerfile en sus repositorios.

| Qué buscás | Dónde está |
| --- | --- |
| Servicios, responsabilidades y flujos de usuario | [Arquitectura](docs/architecture/README.md) |
| Azure, SSH, DNS, NGINX, TLS, datos y Redis | [Operación de infraestructura](docs/operations.md) |
| Publicación, promoción por digest y recuperación | [Despliegues](docs/deployment.md) |
| New Relic, alertas y verificación previa a la defensa | [Observabilidad](docs/observability/README.md) |
| Tenant, aplicaciones, directorio y Terraform | [Auth0](auth0/README.md) |

## Entorno local

Usá Docker con contenedores Linux, Buildx y Compose. CI usa Compose v5.1.1.
Cloná [Snippets](https://github.com/JJT-INGSIS/snippets-service),
[Permissions](https://github.com/JJT-INGSIS/permissions-service),
[PrintScript](https://github.com/JJT-INGSIS/printscript-service) y, para usar la
interfaz, [UI](https://github.com/JJT-INGSIS/snippet-searcher-ui) como carpetas
hermanas de Infra. Los builds toman sus respectivos checkouts.

1. Creá `.env` a partir de [`.env.example`](.env.example) si todavía no existe.
2. Completá `GITHUB_ACTOR`, `GITHUB_TOKEN` y las contraseñas de los dos PostgreSQL.
   Usá un token con lectura de los paquetes privados requeridos por Gradle.
   Compose entrega las credenciales de GitHub como secretos del build. Mantené
   el archivo local fuera de Git.
3. Elegí el entorno que necesitás.

```bash
docker compose up -d --build
docker compose --profile ui --profile ingress up -d --build
```

El primer comando inicia los backends y sus bases. El segundo incluye UI y
NGINX, con la aplicación en `http://localhost:8088/`. Los puertos del Compose
están ligados a loopback.

| Servicio | Acceso local predeterminado |
| --- | --- |
| Snippets | `127.0.0.1:8080` |
| Permissions | `127.0.0.1:8081` |
| PrintScript | `127.0.0.1:8082` |
| PostgreSQL de Snippets | `127.0.0.1:5432` |
| PostgreSQL de Permissions | `127.0.0.1:5433` |

`AUTH_MODE=dev` habilita la identidad local por `X-Dev-Actor-Id`. Para usarla
desde la UI, configurá `UI_DEV_ACTOR`. Los despliegues con Auth0 usan los
parámetros de su ambiente. Podés cambiar los puertos de las bases con
`SNIPPETS_DB_PORT` y `PERMISSIONS_DB_PORT` sin alterar su puerto interno.

[Compose](compose.yaml) usa almacenamiento local en el volumen `snippets_content`
por defecto. El perfil `assets` instala Asset Service y Azurite. Para usar
ese proveedor en un entorno local nuevo, configurá `STORAGE_PROVIDER=asset`;
cambiarlo en un entorno con datos requiere una migración. [Redis local y datos](docs/operations.md#datos-y-redis).

## Comprobaciones

```bash
docker compose config --quiet
docker compose ps
docker compose logs --tail=100 snippets-service
docker compose run --rm smoke-tests
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

Ejecutá la suite Python completa en Linux con Docker Compose. El smoke test
comprueba PrintScript y Permissions desde la red interna. Crea
un registro sintético de ownership en la base local. Para comprobar la API y la
UI de forma integrada, usá los casos de aceptación de sus propios repositorios.
`docker compose down` detiene el entorno y conserva los volúmenes. Las variables
`POSTGRES_*` inicializan bases nuevas.

[CI de Infra](.github/workflows/ci.yml) valida Compose, Swarm, configuraciones y
tests Python. También ejecuta pruebas aisladas de dependencias y proxy, y valida
Auth0 con un proveedor simulado. La verificación de VMs y los despliegues se
hacen por los procedimientos de operación.
