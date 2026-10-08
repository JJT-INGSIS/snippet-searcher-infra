# Snippet Searcher Infra

Configuración del entorno local de Snippet Searcher. Este repositorio contiene el único Compose del proyecto y permite levantar todo el entorno o seleccionar un servicio con sus dependencias. Cada servicio conserva su código y Dockerfile en su propio repositorio.

## Documentación de arquitectura

[Componentes y flujos en Mermaid](./docs/architecture/README.md): diagramas editables del diseño de servicios, permisos, tests, formatting, linting y revalidación. Las dependencias y capacidades futuras están marcadas; estos diagramas no describen únicamente lo que ya está configurado en Compose.

## Alcance actual

| Contenedor | Función | Acceso desde la computadora |
| --- | --- | --- |
| `snippets-service` | Aplicación de snippets | `http://localhost:8080` |
| `snippets-db` | PostgreSQL de snippets | `localhost:5432` por defecto |
| `permissions-service` | Aplicación de permisos | `http://localhost:8081` |
| `permissions-db` | PostgreSQL de permisos | `localhost:5433` por defecto |
| `printscript-service` | Validación de PrintScript 1.0 y 1.1 | `http://localhost:8082` |

Ambas bases usan `postgres:18.6-bookworm`, con contraseñas y volúmenes independientes. Los puertos se publican solo en `127.0.0.1`.

PrintScript no necesita base de datos ni variables de runtime. Snippets recibe los destinos HTTP internos de Permissions y PrintScript mediante configuración externa. Los clientes de negocio que consumirán esas variables se implementan en SNI-7/SNI-9; configurar los destinos no significa que Snippets ya realice esas llamadas. Este entorno es de desarrollo local.

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

Se espera HTTP 200 con `status` igual a `UP`. La salud de permisos incluye su datasource. Snippets todavía no expone un endpoint de salud de base: su arranque y un HTTP 404 en `/` no prueban una consulta real desde Spring a PostgreSQL.

Para abrir una sesión SQL:

```bash
docker compose exec snippets-db psql -U snippets -d snippets
docker compose exec permissions-db psql -U permissions -d permissions
```

Desde IntelliJ o DBeaver, usar los puertos de la tabla, los nombres de base y usuario `snippets` o `permissions`, y la contraseña correspondiente de `.env`.

Dentro de la red de Compose, las aplicaciones usan `snippets-db:5432` y `permissions-db:5432`. Las direcciones internas son `http://snippets-service:8080`, `http://permissions-service:8080` y `http://printscript-service:8080`. Los puertos publicados `8081` y `8082` se usan desde el host.

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

La comprobación ocurre desde la red interna de Compose. No demuestra que Snippets ya tenga implementados los clientes o casos de uso; revisar su arranque en los logs y las dos bases saludables en `docker compose ps`. Un `404` en `/` de Snippets no demuestra conexión a PostgreSQL. PrintScript no tiene endpoint de salud; se comprueba mediante su endpoint funcional `/validate`.

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

Las bases conservan sus datos en `snippets_data` y `permissions_data`. Para eliminar **todos los datos de ambas bases de este entorno**:

```bash
docker compose down --volumes
```

Las variables `POSTGRES_*` inicializan un volumen vacío. Cambiar la contraseña en `.env` no modifica una base existente: cambiarla mediante SQL o recrear el volumen solo si sus datos son descartables.

## Evolución

- Implementar en Snippets los clientes que consumen `PERMISSIONS_BASE_URL` y `PRINTSCRIPT_BASE_URL` (SNI-7/SNI-9).
- Al publicar imágenes, definir cómo consumir versiones desde el registro y cómo desplegar por ambiente.

Las verificaciones de código siguen en los repositorios de los servicios y en sus workflows de CI.

## Branches, CI y ambientes — SNI-23

Infra también usa ramas cortas desde `dev`, PR a dev y promoción mediante PR `dev` → `main`. La branch dev versiona cambios destinados al ambiente de desarrollo; main corresponde a producción y sigue siendo la default branch. El Compose existente sigue siendo local: el stack de Swarm y sus recursos se incorporan en SNI-24.

Usar squash para cambios individuales y merge commit para promociones. Si main recibe un cambio propio, incorporarlo a dev mediante PR. Proteger dev/main con PR, check requerido y actualización con la base, sin aprobación humana obligatoria.

`.github/workflows/ci.yml` ejecuta en PRs a dev/main, pushes a ambas y ejecución manual:

1. Instala Docker Compose `v5.1.1`, la versión ya verificada para este entorno.
2. Ejecuta `docker compose config --quiet` con valores ficticios para resolver variables.
3. Ejecuta los tests existentes de `scripts/`, sin contenedores ni HTTP real.

El CI no necesita `.env` ni secrets reales; no clona servicios, construye imágenes, levanta bases ni publica paquetes. La validación de Compose no verifica sus Dockerfiles ni la conectividad real: esas comprobaciones siguen en los servicios y en el runner integrado. SNI-24 añadirá la validación de `stack.yaml` cuando exista.

Después de la primera ejecución verde, agregar el check `Validate infrastructure` como requerido en dev/main, confirmando su nombre exacto en GitHub. No seleccionar un check antes de que exista ni exigir jobs de publicación de los servicios en este repo.

Crear GitHub Environments `dev` limitado a la branch dev y `prod` limitado a main, sin revisores obligatorios. Preparar nombres de configuración para la operación remota: variables `SSH_HOST`, `SSH_USER`, `SSH_PORT`; secrets `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`. Los datos reales provienen de SNI-20 y se cargan/verifican con SNI-24/SNI-25. El `.env` local no se usa como configuración de las VMs.

## Imágenes publicadas y entrega a Swarm

Cada servicio publica desde su propio pipeline a GHCR después de CI exitoso en dev:

```text
ghcr.io/jjt-ingsis/snippets-service
ghcr.io/jjt-ingsis/permissions-service
ghcr.io/jjt-ingsis/printscript-service
```

SNI-23 prepara los callers de la versión central `v0.3.0`; hay que integrar/publicar esa versión y comprobar las primeras imágenes antes de disponer de esos paquetes para el despliegue. El tag `v0.2.0` ya existente pertenece a otro trabajo y se conserva.

Thiago recibe por servicio el `image-ref` exacto (`imagen@sha256:...`), sus plataformas y origen. Antes de usarlo, confirmar la arquitectura de las VMs y la visibilidad/acceso de cada paquete. Las imágenes se configuran al ejecutarse: datasource, URLs internas y demás datos del ambiente siguen fuera de la imagen.

SNI-24 crea redes, bases, volúmenes, secretos y los tres servicios de aplicación en Swarm usando imágenes del registro, sin construir en la VM. Realiza el primer despliegue y comprueba dev antes de usar esos mismos digests en prod. SNI-25 agregará despliegues SSH automáticos que actualizan solo una aplicación por vez y registran la versión vigente; reaplicar infra deberá preservar esas referencias para no revertir aplicaciones.

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

Contrato de publicación, outputs, reglas y orden de integración: [github-workflows](https://github.com/JJT-INGSIS/github-workflows/blob/main/README.md). El despliegue en VMs y la evidencia dev → prod se comprueban en SNI-24/SNI-25; no se consideran hechos por agregar CI o publicar imágenes.
