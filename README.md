# Snippet Searcher Infra

Configuración del entorno local compartido de Snippet Searcher. Este repositorio coordina los contenedores; cada servicio conserva su código, Dockerfile y Compose independiente.

## Alcance actual

| Contenedor | Función | Acceso desde la computadora |
| --- | --- | --- |
| `snippets-service` | Aplicación de snippets | `http://localhost:8080` |
| `snippets-db` | PostgreSQL de snippets | `localhost:5432` |
| `permissions-service` | Aplicación de permisos | `http://localhost:8081` |
| `permissions-db` | PostgreSQL de permisos | `localhost:5433` por defecto |

Ambas bases usan `postgres:18.6-bookworm`, con contraseñas y volúmenes independientes. Los puertos se publican solo en `127.0.0.1`.

El servicio de PrintScript se incorporará cuando tenga su Dockerfile. Este entorno todavía no configura contratos HTTP entre aplicaciones ni representa un despliegue de producción.

## Requisitos y repositorios

- Docker Desktop iniciado con contenedores Linux y Buildx.
- Docker Compose 5.3.1 como versión de referencia: su implementación permite leer los secretos de build desde `.env`.
- Acceso de lectura a `gradle-conventions` en GitHub Packages.
- Los servicios clonados y actualizados como carpetas hermanas:

```text
snippet-searcher/
├── snippet-searcher-infra/
├── snippets-service/
└── permissions-service/
```

Desde la carpeta padre, si todavía faltan los servicios:

```bash
git clone https://github.com/JJT-INGSIS/snippets-service.git
git clone https://github.com/JJT-INGSIS/permissions-service.git
```

Los contextos de construcción son `../snippets-service` y `../permissions-service`, relativos a este Compose. Docker construye el contenido actual de esos checkouts, incluidos los cambios locales; no descarga automáticamente el código de GitHub.

En Windows, el wrapper `gradlew` de cada servicio debe tener saltos de línea LF. Snippets ya lo define mediante `.gitattributes`. Al preparar este entorno, permisos todavía no tenía esa regla y su Dockerfile ejecutaba `./gradlew` directamente: si el checkout tiene CRLF, convertir `gradlew` a LF desde el editor antes del build. La regla compartida debe incorporarse en el repositorio de permisos.

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
- `GITHUB_TOKEN`: PAT con `read:packages` y acceso a las convenciones publicadas.
- `SNIPPETS_DB_PASSWORD`: contraseña elegida para la base de snippets.
- `PERMISSIONS_DB_PASSWORD`: contraseña elegida para la base de permisos.

Si Windows u otro proceso impide publicar el puerto `5433`, definir `PERMISSIONS_DB_PORT=15433` en `.env`, o elegir otro puerto disponible. Usar ese puerto para conectarse desde IntelliJ o DBeaver. Dentro de Docker, permisos sigue usando `permissions-db:5432`.

Este `.env` pertenece a infra. Compose no toma automáticamente los `.env` de los servicios. Cada integrante prepara su archivo; está ignorado por Git y contiene credenciales locales en texto plano que no deben compartirse.

Compose entrega las credenciales de GitHub como secretos de BuildKit únicamente al construir. No se pasan como variables de runtime de las aplicaciones. Los contextos de build son los repositorios de los servicios, por lo que el `.env` de infra no se envía como parte de esos contextos.

No hay que cargar estas variables manualmente en PowerShell para usar Compose. Si existen variables con los mismos nombres en la sesión, sus valores tienen prioridad sobre `.env`. Actualizar el token cuando venza o se revoque.

## Construir e iniciar

Antes de levantar infra, detener cualquier Compose individual o contenedor que publique `8080`, `8081`, `5432` o `5433`. Por ejemplo, ejecutar `docker compose down` desde `snippets-service` para detener su entorno independiente conservando sus datos.

Desde este repositorio:

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
```

La primera ejecución construye las imágenes. Para incorporar cambios del código o de los Dockerfiles:

```bash
docker compose up --build -d
```

Cada aplicación espera a que su propia base esté saludable. No se agrega una dependencia de arranque entre aplicaciones, porque todavía no hay un contrato que la requiera.

El proyecto se llama `snippet-searcher-infra`. Sus volúmenes son independientes de los de los Compose individuales: los datos creados en el entorno de snippets no aparecen automáticamente en este entorno.

## Logs y comprobaciones

```bash
docker compose logs -f snippets-service permissions-service
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

Dentro de la red de Compose, las aplicaciones usan `snippets-db:5432` y `permissions-db:5432`. Las direcciones internas de las aplicaciones son `http://snippets-service:8080` y `http://permissions-service:8080`; el puerto local `8081` no se usa entre contenedores.

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

- Incorporar PrintScript cuando tenga Dockerfile.
- Configurar las llamadas entre servicios cuando sus contratos estén definidos.
- Al publicar imágenes, definir cómo consumir versiones desde el registro y cómo desplegar por ambiente.

Las verificaciones de código siguen en los repositorios de los servicios y en sus workflows de CI.
