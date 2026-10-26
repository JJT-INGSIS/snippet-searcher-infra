# SNI-24 — Stack y bootstrap manual dev/prod

> Antecedente del bootstrap base de cinco servicios. Para operar el inventario
> ampliado usar la [guía SNI-43](sni-43-cd.md), scripts nuevos y el registro real
> de la VM. Los JSON de este documento no reemplazan las referencias vigentes.

## Alcance y referencias

Cambios locales preparados en `feat/sni-24-swarm-bootstrap`, sin commit, push ni merge. Se conserva `compose.yaml` para desarrollo local. El despliegue usa [`swarm/stack.yaml`](../swarm/stack.yaml), cinco servicios y referencias exactas; no construye imágenes en las VMs ni activa CD. El usuario confirmó usar los paquetes públicos actuales de GHCR. No se requieren tokens de build ni login al registro público.

[`dev-release.json`](../swarm/dev-release.json) y [`prod-release.json`](../swarm/prod-release.json) fijan las imágenes por digest. Snippets corresponde a `sha-4cfefe7dee404a55ab56074647af7957ab360162`, que incorpora storage y creación; Permissions y PrintScript usan los digests entregados por SNI-23. Se verificaron los cuatro manifiestos y `linux/amd64` el 12/10/2026. Prod sólo se habilita con el registro confirmado de dev y las mismas cuatro referencias exactas.

## Recursos y configuración por ambiente

| Dato | dev | prod |
| --- | --- | --- |
| VM | `vm-snippet-dev` | `vm-snippet-prod` |
| Stack | `snippet-searcher-dev` | `snippet-searcher-prod` |
| Perfil Spring | `dev` | `prod` |
| Registro confirmado | `/home/azureuser/.local/state/snippet-searcher/dev/release.json` | `/home/azureuser/.local/state/snippet-searcher/prod/release.json` |
| Bloqueo de operación | `dev/deploy.lock` bajo la ruta anterior | `prod/deploy.lock` bajo la ruta anterior |
| Volúmenes | `snippet-searcher-dev_snippets_data`, `snippet-searcher-dev_permissions_data`, `snippet-searcher-dev_snippets_content` | Los mismos sufijos con prefijo `snippet-searcher-prod_` |

Servicios completos: `<stack>_snippets-service`, `<stack>_permissions-service`, `<stack>_printscript-service`, `<stack>_snippets-db`, `<stack>_permissions-db`. Cada Swarm tiene secretos externos `snippets_db_password` y `permissions_db_password` propios, creados en la VM y nunca registrados en Git/MD/Linear. Aunque los nombres se repiten, los Swarms, discos y valores son independientes.

Spring consume `SPRING_CONFIG_IMPORT=configtree:/run/secrets/` y el archivo `spring.datasource.password`; PostgreSQL consume `POSTGRES_PASSWORD_FILE=/run/secrets/db_password`. Los destinos internos son `http://permissions-service:8080` y `http://printscript-service:8080`; JDBC usa `snippets-db:5432/snippets` o `permissions-db:5432/permissions`.

Snippets monta `snippets_content` en `/var/lib/snippets/content`, con `STORAGE_LOCAL_DIRECTORY` explícito. El volumen nuevo copia el directorio preparado en la imagen para `10001:10001`; la verificación exige que el proceso tenga uid 10001 y permiso de escritura. Este contrato proviene de `docs/storage.md` de Snippets (SNI-8); no se usa un bind mount de código. No modificar ni borrar volúmenes existentes para corregir permisos sin diagnosticar sus datos.

Las bases usan PostgreSQL 18.6-bookworm y no publican puertos. Las aplicaciones publican 8080–8082 en la VM para túneles SSH; las reglas Azure de SNI-20 siguen bloqueando acceso HTTP público. No abrir esos puertos a Internet ni los de Docker/Swarm. El perfil `dev` permite identidad de pruebas; nunca usar `X-Dev-Actor-Id` como autenticación de producción. En prod, la creación con esa identidad permanece deshabilitada.

## Preparar e iniciar

Encender sólo dev en Azure. Usar SSH estricto con [`ssh_known_hosts`](./ssh_known_hosts), usuario `azureuser`, puerto 22 y la clave privada propia. Copiar únicamente `swarm/` y `scripts/` a `/home/azureuser/snippet-searcher-infra-sni24/`; no copiar `.env`, repos de aplicaciones ni claves.

Dentro de dev:

```sh
cd ~/snippet-searcher-infra-sni24
sudo -n bash scripts/prepare_swarm_vm.sh dev
sudo -n python3 scripts/bootstrap_swarm.py preflight swarm/dev-release.json
sudo -n python3 scripts/bootstrap_swarm.py deploy swarm/dev-release.json
sudo -n docker stack services snippet-searcher-dev
```

El preparador conserva secretos existentes, crea los ausentes y agrega `database=true` al nodo. Si encuentra un volumen de base y falta su secreto, falla: recuperar la contraseña original. No regenerarla. El preflight valida hostname/manager/nodo/secretos, renderiza el stack y descarga cada imagen para `linux/amd64`; aún no modifica los servicios.

El deploy toma el bloqueo del ambiente, elige referencias vigentes, comprueba preflight, aplica el stack, espera convergencia estable durante 60 segundos y verifica SQL/HTTP. Sólo después confirma el registro y guarda una copia en `history/<id>.json`. Un fallo conserva el registro anterior; el stack puede haber cambiado parcialmente, por lo que hay que revisar las tareas antes de reintentar.

Después de verificar dev, obtener una copia de su `release.json` (no contiene secretos), desasignar dev y encender prod. Copiar esa evidencia junto con los scripts y el manifiesto:

```sh
cd ~/snippet-searcher-infra-sni24
sudo -n bash scripts/prepare_swarm_vm.sh prod
sudo -n python3 scripts/bootstrap_swarm.py deploy swarm/prod-release.json --dev-record verified-dev-release.json
sudo -n docker stack services snippet-searcher-prod
```

No promocionar si el registro no confirma las pruebas de dev o si difiere cualquier digest, incluido PostgreSQL.

## Verificación

`wait_for_stack.py` compara los cinco digests, réplicas y estados de tareas; falla ante pausa/rollback inesperado o timeout. `verify_stack.py` espera healthchecks y comprueba SQL autenticado por TCP en ambas bases, migraciones aplicadas, evidencia JDBC de Snippets y permiso de escritura de su volumen.

Un servicio temporal Python, sin secretos ni puertos publicados, opera desde `<stack>_default`. En dev ejecuta los contratos existentes de Permissions/PrintScript y crea un snippet de prueba para comprobar llamadas internas, metadatos, ownership y storage. Deja datos de prueba identificados con UUID en la evidencia. En prod usa comprobaciones de lectura y validación; no crea snippets ni ownership de prueba.

Healthchecks de base: `pg_isready`. Permissions: HTTP 200 en `/actuator/health`, que incluye datasource. Snippets y PrintScript: respuesta HTTP usando Bash `/dev/tcp`, sin instalar curl ni reconstruir imágenes. Esos dos checks verifican escucha HTTP; la evidencia SQL y los contratos se comprueban aparte. No se asume `depends_on` ni orden de arranque: reinicios y la verificación final cubren disponibilidad tardía. Aplicaciones con límite 768 MiB y actualización start-first/rollback; bases con límite 512 MiB y stop-first.

La red overlay se conserva sin `attachable`: el verificador corre como servicio Swarm y se elimina al terminar. Se descartó hacer la red attachable sólo para una prueba, porque Swarm ya permite adjuntar el servicio de verificación sin ampliar ese acceso.

## Registro y actualización independiente

`release.json` tiene `environment`, `images` (mapa de las tres aplicaciones), `database_image`, fecha UTC y resultados de verificación. No contiene credenciales. `stack_release.py` centraliza el inventario controlado de servicios, validación, selección inmutable y reemplazo atómico del archivo. Los verificadores consumen ese inventario compartido; no deciden por separado qué servicios pertenecen al stack. Se elige un conjunto cerrado de cinco servicios porque es el alcance acordado; extenderlo requiere revisar el contrato de infraestructura, no agregar detección genérica de servicios.

Reaplicar infra lee ese registro bajo `deploy.lock`, conservando referencias de aplicaciones **y PostgreSQL** aunque el manifiesto local sea anterior. Para cambiar explícitamente una sola aplicación, preparar un manifiesto con el nuevo digest y ejecutar:

```sh
sudo -n python3 scripts/bootstrap_swarm.py deploy swarm/dev-release.json --service printscript-service
```

Sólo toma del manifiesto la referencia del servicio indicado; conserva las otras dos y la base desde el registro. Al aplicar un stack con especificaciones idénticas para los demás servicios, Swarm no debe recrear sus tareas; la evidencia de SNI-24 comprueba ese comportamiento. No usar un manifiesto antiguo como rollback implícito.

SNI-25 debe reutilizar el mismo bloqueo y contrato: leer estado después de adquirir el lock, actualizar sólo la referencia objetivo, verificar el resultado y escribir atómicamente. No escribir el registro antes de confirmar ejecución ni hacer read-modify-write fuera del bloqueo. La opción de un registro por servicio se descartó para conservar una instantánea coherente de todo el ambiente con un contrato pequeño y serializado.

## Operación, persistencia y límites

Para revisar: `sudo docker stack services <stack>`, `sudo docker service ps --no-trunc <servicio>` y logs acotados. No adjuntar valores de secretos a la evidencia. Para mantenimiento, escalar el servicio seleccionado a cero; para recuperarlo, reaplicar infra desde el registro. Eso no elimina sus volúmenes. No usar `down --volumes`, `volume prune` ni borrar bases para resolver fallos.

La persistencia se verifica con `sudo python3 scripts/verify_persistence.py <stack>`, recreando las tareas de base y comprobando que las migraciones y datos de prueba permanecen. No se elimina contenido ni se recrean volúmenes. Al terminar las comprobaciones, desasignar ambas VMs desde Azure; el estado del stack y los datos quedan en sus discos, sin disponibilidad mientras están apagadas.

Hay un solo nodo por ambiente: ni PostgreSQL ni el storage local se replican. Mantener copias de seguridad coordinadas de datos y estado antes de operaciones destructivas. No asumir que otra VM verá estos volúmenes.

## Validación local y evidencia

```sh
bash -n scripts/prepare_swarm_vm.sh
python3 scripts/validate_stack.py
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

El CI existente incorpora renderizado de ambos ambientes y conserva los tests existentes; no publica ni despliega. Validación local final: 29 tests exitosos, sintaxis Bash y renderizado dev/prod correctos. El CI remoto no se ejecutó porque estos cambios no están publicados.

La evidencia remota se registra en [`sni-24-evidencia.md`](./sni-24-evidencia.md), con fechas, imágenes, servicios, SQL/HTTP, persistencia, actualizaciones independientes y estado final. Esa evidencia se completa con resultados reales; el renderizado por sí solo no acredita un despliegue.

Referencias: [despliegue de stacks](https://docs.docker.com/engine/swarm/stack-deploy/), [secretos Swarm](https://docs.docker.com/engine/swarm/secrets/), [actualización de servicios](https://docs.docker.com/reference/cli/docker/service/update/).
