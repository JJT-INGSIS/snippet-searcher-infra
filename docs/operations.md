# Operación de infraestructura

[Inicio](../README.md) · [Despliegues y recuperación](deployment.md) ·
[Observabilidad](observability/README.md)

## Ambientes y acceso

Las VMs y su red se administran en Azure. En este repositorio se versionan la
configuración del stack y sus herramientas. Terraform cubre los recursos de
[Auth0](../auth0/README.md) y [New Relic](../observability/newrelic/README.md)
descritos en sus módulos.

| Ambiente | Grupo y VM | Ingreso |
| --- | --- | --- |
| DEV | `rg-snippet-dev` / `vm-snippet-dev` | `https://jjt-snippets-dev.duckdns.org` |
| PROD | `rg-snippet-prod` / `vm-snippet-prod` | `https://jjt-snippets-prod.duckdns.org` |

Cada VM es manager de su propio Swarm. Una sola VM por ambiente implica que una
caída del host o de su disco afecta al stack completo. Azure IAM y el acceso SSH
se administran por separado. Ingresá como `azureuser` por el puerto 22, con una
clave autorizada y la identidad del host verificada. El repo conserva las claves
públicas de host verificadas para SSH en [`ssh_known_hosts`](ssh_known_hosts).
Si no coinciden, corroborá el cambio desde Azure antes de actualizar la referencia.
Cada integrante conserva su clave privada. El acceso del CD usa su propia identidad.

Los hostnames de DuckDNS apuntan a las IP públicas reservadas en Azure. Si cambia
la IP de salida de un integrante, actualizá únicamente su origen autorizado en la
NSG del ambiente. Revisá la regla específica de HTTPS DEV y la de SSH que
corresponda. Conservá el alcance de los demás orígenes, incluido el monitoreo
hasta que se verifiquen sus checks. PROD publica el ingreso web. Verificá lo
efectivo en Azure y Swarm antes de dar por vigente una regla o puerto.

```bash
az vm get-instance-view -g rg-snippet-dev -n vm-snippet-dev --query 'instanceView.statuses[].displayStatus' -o tsv
sudo docker info --format '{{.Name}} {{.Swarm.ControlAvailable}}'
sudo docker stack services snippet-searcher-dev
```

Usá `az vm start` o `az vm deallocate` con el grupo y la VM correctos cuando
corresponda operar ese ambiente. Coordiná el silenciamiento de alertas antes
de una desasignación planificada. Al arrancar, comprobá servicios, ingreso,
certificado, muestras nuevas y ausencia de operaciones de despliegue pendientes.

## Ingreso y TLS

[NGINX](../nginx/) sirve la UI bajo `/` y elimina el prefijo `/api/` al reenviar
a Snippets. Permissions, PrintScript y las bases quedan en redes internas.
El puerto 80 atiende ACME y redirige a HTTPS. Las rutas públicas se sirven en 443.
Las rutas de eventos conservan NDJSON sin buffering ni compresión, sin caché ni
reintentos del proxy, con 60 s de timeout de inactividad. Consultá el
[contrato de ejecución](architecture/execution-contract.md) para el heartbeat y
el cursor. `/healthz` verifica el proxy. `/api/languages` comprueba además el
recorrido hasta Snippets.

En la VM, desde la revisión de Infra correspondiente:

```bash
sudo -n python3 -B scripts/certificates.py status dev
sudo -n systemctl status snippet-certificates@dev.timer
sudo -n journalctl -u snippet-certificates@dev.service -n 50
curl --fail --show-error https://jjt-snippets-dev.duckdns.org/api/languages
```

Reemplazá el ambiente y hostname para PROD. Certbot usa webroot ACME, imagen
fijada por digest y un timer de systemd. La recarga valida NGINX y usa el lock
de despliegue. Para diagnosticar renovación, revisá DNS, 80, webroot y logs.
`renew <env> --dry-run` usa staging. Si se perdió el par certificado/clave,
restaurá el estado HTTP de ACME antes de emitir y volver a aplicar `--tls`.
Los comandos `issue`, `renew`, `reload` y `status` están en
[`certificates.py`](../scripts/certificates.py). El instalador de unidades y
configuración está en [`install_certificates.sh`](../scripts/install_certificates.sh).
Verificá HTTPS desde fuera con TLS válido.

Validación aislada del proxy: `python3 -B scripts/verify_nginx.py` y
`python3 -B scripts/verify_https.py`.

## Datos y Redis

Cada PostgreSQL tiene volumen y credenciales propios. Conservá los volúmenes,
los secretos y el origen de backups al reemplazar una tarea o recuperar un
release. Las imágenes anteriores no revierten los datos ni las migraciones.
Consultá primero el manifiesto confirmado y la configuración real del servicio.

Snippets usa `SnippetContentStorage`. El proveedor `local` usa un volumen y
`asset` usa Asset Service con su backend persistente. Agregar el overlay de
[Asset](../swarm/stack.asset.yaml) instala el runtime. Cambiar de proveedor
con datos exige copiar y verificar referencias y contenido antes del corte.
Las pruebas `validate_asset_config.py` y `verify_asset_persistence.py` se
ejecutan en un proyecto aislado.

Redis es privado y autenticado. El [overlay de Redis](../swarm/stack.redis.yaml)
monta el volumen persistente y usa un secreto. El
[overlay de procesamiento](../swarm/stack.background.yaml) habilita publicador y
consumidor por separado. Verificá el release efectivo, sus flags y la salud de
Redis antes de atribuir un lote pendiente a un worker. En local:

```bash
python3 scripts/prepare_redis_secret.py secrets/redis_password
docker compose -f compose.yaml -f compose.redis.yaml up -d redis
```

El uso de los backends con Redis y las opciones de capacidad se configuran en
[`compose.redis.yaml`](../compose.redis.yaml). Para diagnosticar, revisá espacio,
memoria, persistencia AOF y avance del outbox/stream. La política `noeviction`
preserva claves en saturación a costa de rechazar nuevas escrituras. Resolvé
la causa antes de habilitar consumo nuevamente.

[`redis_storage.py`](../scripts/redis_storage.py) permite generar un respaldo
RDB desde un contenedor y restaurarlo en un volumen nuevo con el secreto del
ambiente. Usá un destino privado, comprobá el respaldo en aislamiento y
conservá el volumen anterior hasta verificar el candidato. Las pruebas
`validate_redis.py` y `verify_redis_persistence.py` cubren configuración,
restauración, límite de memoria y AOF lleno sin actuar en DEV o PROD.
