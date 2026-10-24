# Snippet Searcher Infra

Configuración del entorno local de Snippet Searcher. Este repositorio contiene el único Compose del proyecto y permite levantar todo el entorno o seleccionar un servicio con sus dependencias. Cada servicio conserva su código y Dockerfile en su propio repositorio.

## Acceso a las VMs — SNI-20

[Inventario y acceso SSH de dev/prod](./docs/sni-20-acceso-vms.md): identidades de host verificadas por Azure, configuración para SNI-25, altas y revocación de claves públicas individuales, túneles HTTP y arranque/desasignación. La guía registra las comprobaciones realizadas y las pruebas del equipo pendientes para cerrar SNI-20.

## Docker y Swarm — SNI-21

[Operación y verificación de los Swarms](./docs/sni-21-docker-swarm.md): inventario, acceso mediante sudo, prueba temporal de creación/actualización de servicios y secretos, limpieza y recuperación básica.

## Documentación de arquitectura

[Componentes y flujos en Mermaid](./docs/architecture/README.md): diagramas editables del diseño de servicios, permisos, tests, formatting, linting y revalidación. Las dependencias y capacidades futuras están marcadas; estos diagramas no describen únicamente lo que ya está configurado en Compose.

## Alcance actual

### Entrada HTTP NGINX — SNI-38

[Contrato, decisiones, pruebas y coordinación](docs/sni-38-nginx.md).
[Guía desde cero usando estos archivos](docs/nginx-desde-cero.md).
Perfil local opcional `ingress`: `localhost:8088`, UI `/` → `ui:8080`, `/api/` →
Snippets sin ese prefijo. No requiere certificados para probar transporte.
El candidato `swarm/stack.ingress.yaml` retira puertos públicos de las aplicaciones;
no está activado en VMs ni debe aplicarse antes de integrar SNI-43.

```bash
python3 -B scripts/validate_nginx_config.py
python3 -B scripts/verify_nginx.py
```

La aceptación usa NGINX real con upstreams controlados, tarda más de un minuto por
el timeout real de 60 s y no sustituye pruebas funcionales de UI/Snippets.

### Asset Service — SNI-33

[Runtime, pruebas, configuración y transición](docs/sni-33-asset.md). Compose incluye
Asset Service oficial + Azurite persistente bajo el perfil opcional `assets`, sin
puertos públicos. Snippets conserva `local` por defecto; levantar el runtime no
migra datos ni activa el proveedor. `swarm/stack.asset.yaml` prepara la ampliación
sin alterar el stack operativo de SNI-25: no desplegarlo hasta integrar SNI-43.

Prueba aislada sin credenciales ni reconstruir aplicaciones:

```bash
python3 -B scripts/validate_asset_config.py
python3 -B scripts/verify_asset_persistence.py
```

La prueba reemplaza sus contenedores para comprobar persistencia, retira sólo sus
contenedores/red y conserva su volumen. No toca dev/prod ni los datos del entorno habitual.

| Contenedor | Función | Acceso desde la computadora |
| --- | --- | --- |
| `snippets-service` | Aplicación de snippets | `http://localhost:8080` |
| `snippets-db` | PostgreSQL de snippets | `localhost:5432` por defecto |
| `permissions-service` | Aplicación de permisos | `http://localhost:8081` |
| `permissions-db` | PostgreSQL de permisos | `localhost:5433` por defecto |
| `printscript-service` | Validación de PrintScript 1.0 y 1.1 | `http://localhost:8082` |

Ambas bases usan `postgres:18.6-bookworm`, con contraseñas y volúmenes independientes. Los puertos se publican solo en `127.0.0.1`.

Snippets guarda el código de los snippets en archivos, dentro del volumen `snippets_content`, montado en `/var/lib/snippets/content`. La imagen crea ese directorio para el usuario `10001`, que ejecuta el servicio, y ya define `STORAGE_LOCAL_DIRECTORY`; el volumen hereda ese dueño en su primer uso. El contrato está en [`docs/storage.md` de snippets-service](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/storage.md).

PrintScript no necesita base de datos ni variables de runtime. Snippets recibe los destinos HTTP internos de Permissions y PrintScript mediante configuración externa y los usa al crear un snippet: valida el código en PrintScript y registra el owner en Permissions.

Este entorno es de desarrollo local. Compose activa en Snippets el perfil Spring `dev` mediante `SPRING_PROFILES_ACTIVE`. Ese perfil habilita la identidad de desarrollo por el header `X-Dev-Actor-Id`; sin él, `POST /snippets` responde `401`. No es autenticación y no debe activarse en producción: el stack de Swarm de SNI-24 debe decidir el perfil de cada ambiente de forma explícita.

## Requisitos y repositorios

- Docker Desktop iniciado con contenedores Linux y Buildx.
- Docker Compose 5.1.1 como versión verificada: su implementación permite leer los secretos de build desde `.env`.
- Acceso de lectura a `gradle-conventions` y a `io.github.jjt-ingsis.printscript:printscript-v1:1.1.0` en GitHub Packages.
- Los servicios clonados y actualizados como carpetas hermanas:

```text
snippet-searcher/
├── snippet-searcher-infra/
├── snippets-service/
├── permissions-service/
└── printscript-service/
```

Desde la carpeta padre, si todavía faltan los servicios:

```bash
git clone https://github.com/JJT-INGSIS/snippets-service.git
git clone https://github.com/JJT-INGSIS/permissions-service.git
git clone https://github.com/JJT-INGSIS/printscript-service.git
```

Los contextos de construcción son `../snippets-service`, `../permissions-service` y `../printscript-service`, relativos a este Compose. Docker construye el contenido actual de esos checkouts, incluidos los cambios locales; no descarga automáticamente el código de GitHub.

Los tres servicios garantizan LF para `gradlew` mediante `.gitattributes`. En un checkout anterior de Windows que conserve CRLF, volver a obtener el wrapper desde Git sólo si no hay cambios locales que preservar. Los scripts Python y YAML de infra también se normalizan a LF.

No hace falta instalar Java ni Gradle en la computadora para construir mediante Docker.

## Configuración local, una sola vez

Desde la raíz de este repositorio, en PowerShell:

```powershell
Copy-Item .env.example .env
```

En macOS/Linux:

```bash
cp .env.example .env
```

Si `.env` ya existe, editarlo sin sobrescribirlo. Completar:

- `GITHUB_ACTOR`: usuario de GitHub dueño del token.
- `GITHUB_TOKEN`: PAT con `read:packages` y acceso a las convenciones y a la biblioteca PrintScript publicadas.
- `SNIPPETS_DB_PASSWORD`: contraseña elegida para la base de snippets.
- `PERMISSIONS_DB_PASSWORD`: contraseña elegida para la base de permisos.

Si otro proceso ocupa `5432` o `5433`, definir `SNIPPETS_DB_PORT=15432` o `PERMISSIONS_DB_PORT=15433` en `.env`, respectivamente, o elegir otros puertos disponibles. Usar esos puertos para conectarse desde IntelliJ o DBeaver. Dentro de Docker, las bases siguen usando `snippets-db:5432` y `permissions-db:5432`.

Este `.env` pertenece a infra. Compose no toma automáticamente los `.env` de los servicios. Cada integrante prepara su archivo; está ignorado por Git y contiene credenciales locales en texto plano que no deben compartirse.

Compose entrega las credenciales de GitHub como secretos de BuildKit únicamente al construir. No se pasan como variables de runtime de las aplicaciones. Los contextos de build son los repositorios de los servicios, por lo que el `.env` de infra no se envía como parte de esos contextos.

No hay que cargar estas variables manualmente en PowerShell para usar Compose. Si existen variables con los mismos nombres en la sesión, sus valores tienen prioridad sobre `.env`. Actualizar el token cuando venza o se revoque.

Destinos HTTP opcionales, compartidos por Snippets y la verificación:

| Variable | Default dentro de Docker |
| --- | --- |
| `PERMISSIONS_BASE_URL` | `http://permissions-service:8080` |
| `PRINTSCRIPT_BASE_URL` | `http://printscript-service:8080` |

Usar nombres de servicio y puertos internos. `localhost` dentro de Snippets apunta al mismo contenedor, no a Permissions o PrintScript. Para un futuro cliente ejecutado en el host, los destinos serán `http://localhost:8081` y `http://localhost:8082`; esos valores no sirven para las llamadas entre contenedores. Las URLs deben ser HTTP/HTTPS sin credenciales, query ni fragmento.

## Construir e iniciar

Los puertos configurados deben estar disponibles en la computadora. Por defecto se publican `8080`, `8081`, `8082`, `5432` y `5433`; los dos últimos pueden cambiarse mediante `SNIPPETS_DB_PORT` y `PERMISSIONS_DB_PORT`.

Desde este repositorio:

```bash
docker compose config --quiet
docker compose build printscript-service
docker compose build snippets-service
docker compose build permissions-service
docker compose up -d
docker compose ps
```

Construir cada imagen por separado evita que Snippets y PrintScript compitan por la misma caché de Gradle de BuildKit (`/root/.gradle`), lo que puede causar un timeout de bloqueo al construir en paralelo. Para incorporar cambios del código o de los Dockerfiles, repetir:

```bash
docker compose build printscript-service
docker compose build snippets-service
docker compose build permissions-service
docker compose up -d
```

Snippets y Permissions esperan a que su propia base esté saludable. PrintScript arranca sin base. No se agregan dependencias de arranque entre las aplicaciones: la disponibilidad HTTP se comprueba en la verificación. `smoke-tests` tiene un perfil opcional y no arranca con el entorno habitual.

El proyecto se llama `snippet-searcher-infra`. Tanto el arranque completo como el individual usan los mismos volúmenes de este proyecto. Las bases creadas anteriormente con otros nombres de proyecto no se importan automáticamente.

### Levantar un servicio con su base

Desde este mismo repositorio, para trabajar solo con snippets:

```bash
docker compose up -d snippets-service
```

Para trabajar solo con permisos:

```bash
docker compose up -d permissions-service
```

Para trabajar sólo con PrintScript:

```bash
docker compose up --build -d printscript-service
```

Al seleccionar Snippets o Permissions, Compose levanta también su base, declarada en `depends_on`; PrintScript no necesita una. El uso cotidiano no requiere activar el perfil `verification` ni mantener otro Compose. Si se cambió el código y hay que reconstruir, agregar `--build`, por ejemplo:

```bash
docker compose up --build -d snippets-service
```

Seleccionar un servicio no detiene otros contenedores que ya estén ejecutándose. Para pasar del entorno completo a solo snippets:

```bash
docker compose down
docker compose up -d snippets-service
```

`down` conserva los datos mientras no se use `--volumes`. El `.env` de infra debe estar completo, incluso al seleccionar un servicio, porque Compose procesa la configuración del archivo entero.

## Logs y comprobaciones

```bash
docker compose logs -f snippets-service permissions-service printscript-service
```

`Ctrl+C` deja de seguir los logs y mantiene los contenedores en ejecución. Revisar que Spring haya arrancado y que las dos bases aparezcan como `healthy` en `docker compose ps`.

Para comprobar permisos desde PowerShell:

```powershell
Invoke-RestMethod http://localhost:8081/actuator/health
```

En macOS/Linux:

```bash
curl --fail http://localhost:8081/actuator/health
```

Se espera HTTP 200 con `status` igual a `UP`. La salud de permisos incluye su datasource. Snippets no expone un endpoint de salud: su arranque y un HTTP 404 en `/` no prueban una consulta real desde Spring a PostgreSQL. [Crear un snippet](#crear-un-snippet) sí la prueba.

Para abrir una sesión SQL:

```bash
docker compose exec snippets-db psql -U snippets -d snippets
docker compose exec permissions-db psql -U permissions -d permissions
```

Desde IntelliJ o DBeaver, usar los puertos de la tabla, los nombres de base y usuario `snippets` o `permissions`, y la contraseña correspondiente de `.env`.

Dentro de la red de Compose, las aplicaciones usan `snippets-db:5432` y `permissions-db:5432`. Las direcciones internas son `http://snippets-service:8080`, `http://permissions-service:8080` y `http://printscript-service:8080`. Los puertos publicados `8081` y `8082` se usan desde el host.

## Crear un snippet

Con el entorno completo levantado, desde la computadora:

```bash
curl -i -X POST http://localhost:8080/snippets \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 7c9e6679-7425-40de-944b-e07fc1f90ae7' \
  -H 'X-Dev-Actor-Id: dev-local' \
  -d '{"name":"Example","description":null,"language":"printscript","version":"1.0","code":"println(1);"}'
```

Se espera `201` con el `id` del snippet. Repetir el mismo pedido responde `200` con el mismo `id`: la `Idempotency-Key` identifica el alta. Para crear otro snippet, usar otro UUID como clave.

El pedido recorre los tres servicios: Snippets valida el código en PrintScript, guarda los metadatos en `snippets-db` y el código en el volumen `snippets_content`, y registra el owner en Permissions. Para ver el owner registrado, con el `id` de la respuesta:

```bash
curl http://localhost:8081/ownership/<id>
```

Si Permissions o PrintScript no están disponibles, Snippets responde `502` y el alta queda pendiente; repetir el pedido con la misma clave la completa. Después de reiniciar un contenedor, ese reintento puede tardar unos 10 segundos en funcionar, porque Java recuerda durante ese lapso que el nombre del servicio no se resolvía. El contrato completo está en [`docs/creation.md` de snippets-service](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/creation.md).

## Actualizar un snippet

Con el `id` que devolvió la creación, y la misma identidad que lo creó:

```bash
curl -i -X PUT http://localhost:8080/snippets/<id> \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-Actor-Id: dev-local' \
  -d '{"name":"Renamed","description":null,"language":"printscript","version":"1.1","code":"println(2);"}'
```

Se espera `200` con los datos nuevos. El pedido reemplaza todo: el código, el nombre, la descripción, el lenguaje y la versión. No lleva `Idempotency-Key`; repetirlo deja el mismo resultado.

Snippets le pregunta a Permissions si esa identidad es el owner. El mismo pedido con otro valor en `X-Dev-Actor-Id` responde `403` y no cambia nada. Con Permissions detenido responde `502`, no `403`: que el servicio no conteste no dice nada sobre el permiso. Un `id` inexistente responde `404` y un código inválido `422`; en ningún caso se modifica el snippet. El contrato completo está en [`docs/update.md` de snippets-service](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/update.md).

## Verificación HTTP automatizada

Después de preparar `.env`, reconstruir el entorno y ejecutar:

```bash
docker compose config --quiet
docker compose build printscript-service
docker compose build snippets-service
docker compose build permissions-service
docker compose up -d
docker compose --profile verification run --rm smoke-tests
docker compose ps
```

El perfil agrega únicamente un contenedor temporal `python:3.13-alpine`, con `scripts/` montado como sólo lectura y las mismas URLs que Snippets. No recibe credenciales de Packages ni contraseñas de las bases. Su comando levanta las aplicaciones y sus dependencias si todavía no están iniciadas. No presupone que las imágenes de las aplicaciones tengan curl, Python o shell de diagnóstico.

El runner espera hasta 60 segundos por cada servicio HTTP, reintentando conexiones fallidas y respuestas `5xx`. Una respuesta de cliente inesperada o un contrato inválido falla la comprobación. Revisa ambos servicios, informa `PASS`/`FAIL` para cada uno y termina con código `0` sólo si los dos pasan.

- **PrintScript:** valida versiones 1.0 y 1.1; comprueba `200` con código inválido y sus diagnósticos; y verifica `422` con `supportedVersions`. No compara la redacción de mensajes.
- **Permissions:** comprueba relación inexistente, registro, reintento idempotente, consulta, permiso permitido/denegado y conflicto conservando el owner original. También verifica `/actuator/health` con estado `UP`.

Cada ejecución genera un UUID nuevo y deja una relación de prueba con owner `infra-smoke-test` en la base de Permissions. El UUID se muestra en la salida. No se borra información ni se recrean bases o volúmenes para verificar el entorno.

La comprobación ocurre desde la red interna de Compose. El runner todavía no llama a Snippets: su creación y su actualización se comprueban con los pedidos de [Crear un snippet](#crear-un-snippet) y [Actualizar un snippet](#actualizar-un-snippet), o con `CreationLiveTest` y `UpdateLiveTest` de snippets-service, que usan estos mismos contenedores de Permissions y PrintScript. Un `404` en `/` de Snippets no demuestra conexión a PostgreSQL. PrintScript no tiene endpoint de salud; se comprueba mediante su endpoint funcional `/validate`.

Contratos: [PrintScript](https://github.com/JJT-INGSIS/printscript-service/blob/main/docs/validation.md) y [Permissions](https://github.com/JJT-INGSIS/permissions-service/blob/main/docs/ownership.md). También están disponibles en `docs/` de los clones hermanos.

Los tests del runner se pueden ejecutar sin Docker ni credenciales, con Python 3.10 o superior:

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

Estas pruebas usan respuestas simuladas y verifican reintentos, timeouts, errores de contrato, idempotencia y códigos de salida. No sustituyen la ejecución integrada contra las aplicaciones reales.

## Detener y conservar los datos

```bash
docker compose down
```

Las bases conservan sus datos en `snippets_data` y `permissions_data`, y el código de los snippets en `snippets_content`. Recrear o reconstruir un contenedor no los borra. Para eliminar **todos los datos de este entorno, incluido el código de los snippets**:
```bash
docker compose down --volumes
```

Las variables `POSTGRES_*` inicializan un volumen vacío. Cambiar la contraseña en `.env` no modifica una base existente: cambiarla mediante SQL o recrear el volumen solo si sus datos son descartables.

## Evolución

- Incorporar la creación y la actualización de snippets al runner de verificación.
- Al publicar imágenes, definir cómo consumir versiones desde el registro y cómo desplegar por ambiente.

Las verificaciones de código siguen en los repositorios de los servicios y en sus workflows de CI.

## Branches, CI y ambientes — SNI-23

Infra también usa ramas cortas desde `dev`, PR a dev y promoción mediante PR `dev` → `main`. La branch dev versiona cambios destinados al ambiente de desarrollo; main corresponde a producción y dev es la default branch. Compose es local; SNI-24 conserva el stack independiente de cada VM.

Usar squash para cambios individuales y merge commit para promociones. Si main recibe un cambio propio, incorporarlo a dev mediante PR. Proteger dev/main con PR, check requerido y actualización con la base, sin aprobación humana obligatoria.

`.github/workflows/ci.yml` ejecuta en PRs a dev/main, pushes a ambas y ejecución manual:

1. Instala Docker Compose `v5.1.1`, la versión ya verificada para este entorno.
2. Ejecuta `docker compose config --quiet` con valores ficticios para resolver variables.
3. Valida el stack de Swarm para ambos ambientes y la sintaxis del script de preparación.
4. Ejecuta tests de HTTP, contratos de release, evidencia histórica, bloqueo y recuperación de CD sin conexión a VMs.

El CI no necesita `.env` ni secrets reales; no clona servicios, construye imágenes, levanta bases ni publica paquetes. La validación de Compose no verifica sus Dockerfiles ni la conectividad real: esas comprobaciones siguen en los servicios y en el runner integrado. También se valida `swarm/stack.yaml`, sin aplicar cambios remotos.

Después de la primera ejecución verde, agregar el check `Validate infrastructure` como requerido en dev/main, confirmando su nombre exacto en GitHub. No seleccionar un check antes de que exista ni exigir jobs de publicación de los servicios en este repo.

Crear GitHub Environments `dev` limitado a la branch dev y `prod` limitado a main, sin revisores obligatorios. Preparar nombres de configuración para la operación remota: variables `SSH_HOST`, `SSH_USER`, `SSH_PORT`; secrets `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`. Los datos reales provienen de SNI-20 y se cargan/verifican con SNI-24/SNI-25. El `.env` local no se usa como configuración de las VMs.

## Imágenes publicadas y entrega a Swarm

Cada servicio publica desde su propio pipeline a GHCR después de CI exitoso en dev:

```text
ghcr.io/jjt-ingsis/snippets-service
ghcr.io/jjt-ingsis/permissions-service
ghcr.io/jjt-ingsis/printscript-service
```

SNI-23 publicó y comprobó imágenes con workflows v0.3.1. SNI-25 original está integrado con workflows v0.4.0; su habilitación remota requiere credenciales y pruebas reales. La simplificación actual propone una versión nueva del central (v0.5.0) después de integrar y fijar esta revisión de infra. Se conservan los tags anteriores.

Thiago recibe por servicio el `image-ref` exacto (`imagen@sha256:...`), sus plataformas y origen. Antes de usarlo, confirmar la arquitectura de las VMs y la visibilidad/acceso de cada paquete. Las imágenes se configuran al ejecutarse: datasource, URLs internas y demás datos del ambiente siguen fuera de la imagen.

SNI-24 crea redes, bases, volúmenes, secretos y los tres servicios de aplicación en Swarm usando imágenes del registro, sin construir en la VM. Realiza el primer despliegue y comprueba dev antes de usar esos mismos digests en prod. SNI-25 prepara despliegues SSH por aplicación, con evidencia histórica y recuperación. Reaplicar infra conserva las referencias vigentes y se detiene si hay una operación CD pendiente.

Para comprobar localmente una imagen descargada por digest, se puede usar un override temporal fuera de Git sobre el Compose local. Ejemplo de su contenido:

```yaml
services:
  snippets-service:
    image: ghcr.io/jjt-ingsis/snippets-service@sha256:<digest-de-actions>
```

Guardar, por ejemplo, como `../published-images.local.yaml` y, desde infra, ejecutar:

```bash
docker compose -f compose.yaml -f ../published-images.local.yaml pull snippets-service
docker compose -f compose.yaml -f ../published-images.local.yaml up --no-build -d snippets-service
docker compose logs snippets-service
```

La opción `--no-build` permite usar esa imagen sin reconstruir el checkout local. Cambiar el servicio y digest para probar permisos o PrintScript. El datasource y las dependencias de Compose permanecen configurados como en el entorno local. Después, los comandos habituales sin el override vuelven a usar la construcción local; para recuperar ese entorno, ejecutar su build y `up -d` habituales.

Contrato de publicación, reglas y orden de integración: [github-workflows](https://github.com/JJT-INGSIS/github-workflows/blob/main/README.md). El despliegue en VMs y la evidencia dev → prod se comprueban en SNI-24/SNI-25; no se consideran hechos por agregar CI o publicar imágenes.

## CD por servicio — SNI-25

El [manual SNI-25](docs/sni-25-cd.md) explica configuración, contrato de evidencia,
actualización independiente, bloqueo compartido, journal y reconciliación SSH.
Los scripts no crean infraestructura y no usan la comparación de stack completo
para promover una sola aplicación. No se modifican los manifiestos ni los recursos
Swarm de SNI-24.

El YAML coordina Actions y comandos pequeños. Publicación y selección pasan un
solo descriptor interno al despliegue; los scripts comparten identidad y contratos,
inspeccionan la imagen una vez en el runner y conservan el journal como única fuente
del recibo SSH. Los detalles y comandos están en el manual, sin cambiar el flujo
de promoción ni las garantías de recuperación.

Las pruebas locales cubren promoción exacta, rechazo sin evidencia, recuperación,
interrupciones y preservación de las otras imágenes. El 13/10/2026 se activó y se
verificó `Do not allow bypassing the above settings` en main de los tres servicios;
los administradores también deben cumplir PR y CI. Producción permanece
deshabilitada: los secrets y las pruebas reales dev → prod siguen pendientes. El workflow
central debe fijarse al commit de infra que integre estos archivos antes de habilitar CD.
