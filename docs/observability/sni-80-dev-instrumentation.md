# SNI-80 — Instrumentar la VM de DEV, Swarm y el ingreso NGINX

Revisión de fuentes: 16/11/2026, infra dev `7dc6ca4`; aplicado en DEV el 17/11/2026 desde `1db4634`.
Estado: **aplicado y verificado en DEV (17/11/2026). PROD sin aplicar (SNI-88).**

Completa lo que el runtime de SNI-82 dejó pendiente
([runbook](../../observability/runtime/README.md)): logs del ingreso y del host,
fallas de tareas y OOM, versión esperada contra la que corre, pérdida de señal y
medición de costo. Sigue la [base común de SNI-79](../architecture/observability-baseline.md):
en la matriz de fallas, ingreso, VM, agente y despliegue son de Juanchi.

## Punto de partida

| Pieza | Estado al empezar | Fuente |
| --- | --- | --- |
| Agente de infraestructura | Contenedor oficial fuera de Swarm; métricas de host y contenedores; ingesta verificada en DEV el 16/11 | `observability/runtime/agent.compose.yaml`, PR #51 |
| Muestra de Swarm | `SnippetSwarmSample`: servicio, imagen, réplicas corriendo y deseadas | `observability/runtime/swarm.sh` |
| Logs | El contenedor del agente no trae forwarder: no llega ningún log | Runbook de SNI-82 |
| NGINX | Log `ingress` en texto `clave=valor` a stdout, con `$request_id`; `X-Request-ID` solo hacia el upstream | `nginx/nginx.conf`, `nginx/templates/routes.conf.template` |
| Release esperado | `swarm/dev-release.json` con imagen y digest por servicio | CD de SNI-43 |
| Licencia | Solo en `/etc/snippet-observability/dev/agent.json`, root 0600 | `scripts/start_observability_dev.py` |

## Señales nuevas

| Señal | Origen | Destino en New Relic | Para qué |
| --- | --- | --- | --- |
| Pedido de ingreso | Log JSON de NGINX | `Log` con `logtype=nginx-ingress` | Errores y latencia por ruta y upstream; correlación por `request_id` |
| OOM del kernel | journald, transporte `kernel` | `Log` con `logtype=host-kernel` | Distinguir un OOM de otra caída |
| Eventos de Docker | journald, unidad `docker.service` | `Log` con `logtype=host-docker` | Reinicios y errores del motor |
| Tareas fallidas | `swarm_sample.py` | `SnippetSwarmSample` (campos nuevos) | Último error y código de salida; 137 es SIGKILL, el OOM se confirma con `host-kernel` |
| Versión esperada | `swarm_sample.py` + release confirmado | `SnippetSwarmSample` (campos nuevos) | Detectar un deploy que no convergió |
| Pérdida de señal | Ausencia de `SystemSample` / `SnippetSwarmSample` / `Log` | Consultas NRQL | Base de las alertas de SNI-86 |

### Log de ingreso

Una línea JSON por pedido:

| Campo | Contenido |
| --- | --- |
| `request_id` | Generado por NGINX; también vuelve al cliente en `X-Request-ID` |
| `time` | ISO 8601 |
| `method`, `path` | Método y URI **sin query string** |
| `route` | `api`, `executions` o `ui` |
| `status` | Estado devuelto al cliente |
| `upstream`, `upstream_status` | Dirección y estado del upstream (varios si hubo reintento) |
| `request_time`, `upstream_connect_time`, `upstream_response_time` | Segundos |
| `bytes_sent` | Tamaño de la respuesta |

No se registran IP del cliente, `Authorization`, cookies, query string, `Referer`
ni `User-Agent`. Un `X-Request-ID` que mande el cliente se ignora: el identificador
siempre lo genera NGINX.

## Diseño

```mermaid
flowchart LR
  nginx["NGINX (Swarm)"] -->|stdout JSON| docker["journald / Docker"]
  kernel["Kernel OOM"] --> docker
  docker --> fb["Fluent Bit (fuera de Swarm)"]
  fb -->|Log API| nr["New Relic 8718557"]
  agent["Agente de infraestructura"] -->|SystemSample, ContainerSample, SnippetSwarmSample| nr
  release["release.json confirmado por el CD"] -.->|imagen esperada| agent
```

Fluent Bit corre como contenedor aparte, fuera de Swarm, igual que el agente: si el
stack cae, el forwarder sigue informando. Usa la imagen oficial de Fluent Bit
(`fluent/fluent-bit:5.1.5`, fijada por digest), que ya trae la salida `nrlogs` de New
Relic y la lectura de journald; la imagen de New Relic solo agrega ese mismo plugin.
NGINX pasa a escribir en journald (driver `journald`, tag `snippet-ingress`), así
Fluent Bit lee una sola fuente y no necesita el socket de Docker.

No hay clave nueva. Al arrancar, un script como root lee la licencia de `agent.json`
y genera `/etc/snippet-observability/dev/logs-license.conf` (root, 0600, sin pisar
uno existente), que Fluent Bit monta en solo lectura. La licencia no queda en la
imagen, en el Compose, en variables de entorno ni en el repo.

La muestra de Swarm pasa de `swarm.sh` a `swarm_sample.py` (el agente ya trae
Python), que reutiliza `expected_images` del CD para comparar contra el release
confirmado en `~azureuser/.local/state/snippet-searcher/dev/release.json`.

## Decisiones

Aprobadas por Juan el 16/11/2026 («dale, aprobadas las 9»).

| # | Decisión | Alternativa descartada | Costo aceptado |
| --- | --- | --- | --- |
| O1 | Fluent Bit oficial con su salida `nrlogs`, contenedor fuera de Swarm, reutilizando la licencia de la VM | Cambiar el agente a la instalación nativa con forwarder incluido; imagen de New Relic con el mismo plugin | Un contenedor más y un archivo derivado de la licencia |
| O2 | Solo líneas de acceso de NGINX y, de journald, OOM del kernel y eventos de Docker | Todos los logs de contenedores | Los logs de las aplicaciones quedan para SNI-81 |
| O3 | Log JSON de NGINX con ruta, upstream y tiempos, sin query, IP ni credenciales; `X-Request-ID` generado y devuelto al cliente | Mantener el formato `clave=valor` y parsearlo | Cambia el formato que otros scripts podrían leer |
| O4 | `SnippetSwarmSample` suma tareas fallidas recientes, último error y código de salida; OOM del kernel por log | Un colector nuevo para tareas | Una llamada más a la API de Docker por intervalo |
| O5 | Imagen esperada desde el release confirmado contra la que corre; diagnóstico de etapa del CD documentado | Marcadores de deploy de New Relic | Los marcadores quedan como propuesta aparte |
| O6 | Consultas NRQL de pérdida de señal, sin crear alertas | Crear las alertas acá | Las alertas son de SNI-86 |
| O7 | Medición antes/después de ingesta, CPU y RAM contra el presupuesto de 10 GB/mes | Estimar sin medir | Una ventana de medición en DEV |
| O8 | PROD parametrizado, sin aplicar | Activar PROD con un flag | PROD necesita su propio inventario (SNI-88) |
| O9 | Operaciones en Azure y en la VM solo por Juan o con aprobación paso a paso | Automatizarlas desde el repo | Pasos manuales en el runbook |

## Fronteras

- SNI-79: cuenta, nombres de entidades y presupuesto.
- SNI-81: APM, trazas y logs de las aplicaciones. Este ticket deja el `request_id`
  del ingreso listo para correlacionar.
- SNI-82: el agente y el colector ya instalados; no se cambia su configuración salvo
  `swarm.sh`, que se reemplaza por `swarm_sample.py`.
- SNI-86: dashboards, SLO y alertas sobre estas señales.
- SNI-87: ensayo de fallas.

## Privacidad y presupuesto

- Ningún log lleva IP, tokens, cookies, query string ni cuerpos.
- Los logs de journald se filtran en origen: solo OOM del kernel y la unidad de Docker.
- Límites de memoria y CPU para Fluent Bit, y buffer en disco acotado.
- Referencia de SNI-79: 10 GB/mes, con avisos a 5 y 8 GB. La medición de O7 se anota
  en este documento.

## Forwarder de logs

| Pieza | Valor |
| --- | --- |
| Imagen | `fluent/fluent-bit:5.1.5@sha256:2740f387…e7b4` (multi-arquitectura) |
| Contenedor | `snippet-observability-dev-logs`, fuera de Swarm, `restart: unless-stopped` |
| Privilegios | Raíz de solo lectura, sin capacidades, `no-new-privileges`, sin socket de Docker |
| Montajes | `/var/log/journal` y `/etc/machine-id` en solo lectura; config, parser e include de licencia en solo lectura; volumen propio para cursores y buffer |
| Límites | 128 MiB, 0,25 CPU; 8 MiB en memoria por entrada de NGINX, 2 MiB por entrada de host; buffer en disco de hasta 256 MiB |
| Lectura | Desde el final del journal (`Read_From_Tail`): no reenvía historia vieja al arrancar |
| Envío | `nrlogs` a `log-api.newrelic.com` (cuenta US), gzip, hasta 5 reintentos |
| Archivos | [fluent-bit.conf](../../observability/logs/fluent-bit.conf), [parsers-ingress.conf](../../observability/logs/parsers-ingress.conf), [forwarder.compose.yaml](../../observability/logs/forwarder.compose.yaml) |

[start_log_forwarder_dev.py](../../scripts/start_log_forwarder_dev.py), con `sudo`:

| Acción | Qué hace |
| --- | --- |
| `start` | Exige `agent.json` (no crea una licencia), copia los archivos a `/opt/snippet-observability/dev/logs-v1` (si ya existen, tienen que ser idénticos), genera el include de licencia 0600 sin pisar uno existente, levanta el contenedor y comprueba que corre |
| `remove` | `docker compose down` sin `-v` y borra solo el include de licencia; conserva el volumen de estado y los archivos instalados |

`--environment prod` existe pero no se aplica en este ticket: falla mientras no haya
un `agent.json` de PROD (SNI-88).

## Muestra de Swarm

[swarm_sample.py](../../observability/runtime/swarm_sample.py) corre dentro del agente cada
60 segundos y emite una fila por servicio del stack `snippet-searcher-dev`:

| Campo | Contenido |
| --- | --- |
| `service`, `image` | Nombre corto e imagen de la especificación vigente |
| `expectedImage`, `imageState` | Imagen del release confirmado; `match`, `mismatch` o `unknown` (sin release o servicio fuera de él, como `certbot`) |
| `running`, `desired` | Tareas corriendo y réplicas deseadas |
| `failedTasks` | Tareas `failed` o `rejected` en los últimos 10 minutos |
| `lastError`, `lastExitCode` | De la falla más reciente; el error se recorta a 200 caracteres |
| `oomKilled` | 1 si alguna de esas fallas salió con 137 (SIGKILL). Lo produce un OOM, pero también un `docker kill` o un apagado que supera el timeout: es una señal para investigar y se confirma con el log `host-kernel` |

La comparación usa el digest cuando las dos referencias lo tienen. Un nombre de servicio
o imagen con caracteres inesperados hace fallar la muestra entera: no se emiten datos a
medias. No lee environment, secretos ni la especificación completa.

En una VM nueva, `prepare_observability_dev.py` ya instala el script. En la VM de DEV
actual, que tiene `runtime-v1`, se aplica con
[upgrade_observability_runtime_dev.py](../../scripts/upgrade_observability_runtime_dev.py):

| Acción | Qué hace |
| --- | --- |
| `upgrade` | Copia `runtime-v1` a `runtime-v2` sin tocar el original, agrega `swarm_sample.py` y `stack_release.py`, vuelve a generar `integrations.json` con versión `sni80-runtime-v2` y recrea el agente con el mismo proyecto Compose, licencia y volumen de estado |
| `revert` | Recrea el agente con `runtime-v1`; `runtime-v2` queda para inspección |

## Aplicar el NGINX nuevo con el monitoreo instalado

Desde SNI-82 (PR #52), `deploy --infrastructure` se niega a reaplicar el stack
completo en DEV mientras está instalado el monitoreo: el release no registra los alias
de las bases y Redis, ni el entrypoint y el secreto de monitoreo de Redis, y
reaplicarlos los borraría. El cambio de este ticket solo toca NGINX, así que se agrega
un camino acotado:

```bash
sudo -n python3 -B scripts/bootstrap_swarm.py deploy candidate-dev.json --infrastructure --proxy-only
```

| Regla | Detalle |
| --- | --- |
| Qué se permite | Solo cambiar los nombres y hashes de configs ya registradas de NGINX; cualquier otro cambio respecto del release confirmado (imágenes, hostname, TLS, componentes, storage, UI, auth, configs nuevas o quitadas) se rechaza antes de tocar Docker |
| Qué se despliega | Un documento de stack con **solo** el servicio `nginx`, sin `--prune`: bases, Redis, alias y demás servicios no se tocan |
| Diario y verificación | Los mismos de `deploy --infrastructure`: lock compartido con el CD, `pending.json`, verificación del inventario completo y recibo |
| Recuperación | Si la verificación falla, vuelve a desplegar solo `nginx` con el release anterior; el driver `journald` sale del stack del checkout y se mantiene |
| Plan | `bootstrap_swarm.py plan` con `--nginx-host`, `--tls` y `--config-version 2`: renombra solo las configs cuyo contenido cambió (`nginx_main`, `nginx_routes`); si `v2` ya existe con otro contenido, el deploy falla y se usa la versión siguiente |

Es la misma técnica que el corte de Redis (despliegue parcial sin `--prune`). Reconciliar
el manifiesto con el monitoreo sigue siendo un pendiente de SNI-82.

El 17/11 el primer intento se frenó en el control de callers, sin aplicar nada: los
cuatro servicios ya llaman al workflow central `v0.6.5` (SNI-82, que fija la infra
`9cd0e2d` con la compatibilidad del monitoreo), pero `redis_cd.VERSION` seguía en
`v0.6.4`. Se actualizó a `v0.6.5` después de comprobar contra GitHub que esa release
fija una infra con el contrato Redis completo; `v0.6.4` ahora se rechaza como caller viejo.

## Consultas de pérdida de señal y diagnóstico

Son consultas, no alertas: las alertas son de SNI-86. La ventana sigue a SNI-79
(3–5 minutos, con muestras cada 60 segundos). Los nombres se comprobaron con `keyset()`
en DEV: en `Log` y `SnippetSwarmSample`, `environment` y `service` llegan como atributos
directos y el `service` de cada fila no lo pisa el atributo fijo del agente; las
etiquetas de la integración quedan aparte como `label.environment`, `label.service` y
`label.version`. `imageState IS NOT NULL` deja afuera muestras del `swarm.sh` anterior.

| Para qué | NRQL |
| --- | --- |
| Host sin señal | `SELECT count(*) FROM SystemSample WHERE environment = 'dev' SINCE 5 minutes ago` → 0 |
| Muestra de Swarm sin señal | `SELECT count(*) FROM SnippetSwarmSample WHERE environment = 'dev' SINCE 5 minutes ago` → 0 |
| Forwarder sin señal | `SELECT count(*) FROM Log WHERE logtype = 'nginx-ingress' AND environment = 'dev' SINCE 5 minutes ago` → 0. Solo vale con tráfico constante (synthetic de SNI-84): sin pedidos también da 0 |
| Servicio sin réplicas | `SELECT latest(running), latest(desired) FROM SnippetSwarmSample WHERE environment = 'dev' AND imageState IS NOT NULL FACET service SINCE 5 minutes ago`: `running < desired` es una caída; `desired = 0` es un servicio apagado a mano (`scale=0` baja las dos) |
| Versión que no convergió | `SELECT latest(imageState), latest(image), latest(expectedImage) FROM SnippetSwarmSample WHERE environment = 'dev' AND imageState IS NOT NULL FACET service SINCE 10 minutes ago` |
| Reinicios y OOM | `SELECT max(failedTasks), max(oomKilled), latest(lastError) FROM SnippetSwarmSample WHERE environment = 'dev' AND imageState IS NOT NULL FACET service SINCE 30 minutes ago` |
| OOM del kernel | `SELECT message FROM Log WHERE logtype = 'host-kernel' AND environment = 'dev' SINCE 1 day ago` |
| Errores y latencia por ruta | `SELECT percentage(count(*), WHERE status >= 500), percentile(request_time, 95) FROM Log WHERE logtype = 'nginx-ingress' FACET route TIMESERIES SINCE 1 hour ago` |
| Upstream caído | `SELECT count(*) FROM Log WHERE logtype = 'nginx-ingress' AND status IN (502, 503, 504) FACET route, upstream_status SINCE 1 hour ago` |
| Un pedido puntual | `SELECT * FROM Log WHERE request_id = '<X-Request-ID de la respuesta>'` |
| Ingesta (O7) | `SELECT count(*), bytecountestimate() / 1000 AS 'KB' FROM Log, SnippetSwarmSample SINCE 30 minutes ago FACET eventType()`; total de la cuenta con `SELECT sum(GigabytesIngested) FROM NrConsumption WHERE productLine = 'DataPlatform' FACET usageMetric SINCE 1 day ago` (llega con demora) |

### Etapa del CD

| Etapa | Cómo se ve | Dónde mirar |
| --- | --- | --- |
| GitHub Actions | El workflow falla; en la VM nada cambia y `imageState` sigue en `match` con la imagen anterior | La ejecución del workflow |
| GHCR | La tarea nueva queda `rejected` con un error de imagen | `failedTasks` y `lastError` |
| SSH / VM | El workflow falla en el paso remoto; el release confirmado no cambia | Log del workflow y `logs/` del estado del CD en la VM |
| Actualización en Swarm | Tareas `failed`, posible rollback automático | `failedTasks`, `lastExitCode`, `oomKilled` |
| Convergencia | `running < desired`, o `mismatch` sostenido después de confirmar el release | `SnippetSwarmSample` por servicio |

Los marcadores de deploy de New Relic quedan como propuesta aparte (O5).

## Reversión

| Qué | Cómo |
| --- | --- |
| Forwarder | `sudo python3 scripts/start_log_forwarder_dev.py remove` |
| Log JSON de NGINX | Plan con los archivos anteriores de `nginx/` y `--config-version 3` (vuelve a contenido viejo con nombre nuevo) y `deploy --infrastructure --proxy-only`; para volver a `json-file`, quitar `logging` de `stack.ingress.yaml` en ese checkout. Las configs `v1` siguen creadas en Swarm |
| Muestra de Swarm | `sudo python3 scripts/upgrade_observability_runtime_dev.py revert`: el agente vuelve a `runtime-v1` y a `swarm.sh` |

No usar `down -v`, podas globales ni borrar volúmenes de aplicación. Al terminar una
sesión, detener y desasignar la VM en Azure.

## Aplicar en DEV

Orden usado el 17/11/2026, todo con la VM encendida por Juan y por SSH como `azureuser`.
El orden importa: Fluent Bit no arranca si el journal no tiene entradas de NGINX (con
`Read_From_Tail` y sin cursor, un filtro sin coincidencias no recibe nada hasta reiniciar).

1. Clonar la rama en `~/sni80-infra` y verificar el commit.
2. Plan: `python3 -B scripts/bootstrap_swarm.py plan ~/.local/state/snippet-searcher/dev/release.json --nginx-host jjt-snippets-dev.duckdns.org --tls --config-version 2 > ~/sni80-candidate-dev.json`.
3. `sudo -n python3 -B scripts/bootstrap_swarm.py deploy ~/sni80-candidate-dev.json --infrastructure --proxy-only`.
4. Hacer un pedido y comprobar `sudo journalctl --no-pager -q -n 2 -o cat CONTAINER_TAG=snippet-ingress`.
5. `sudo python3 -B scripts/start_log_forwarder_dev.py start`.
6. `sudo python3 -B scripts/upgrade_observability_runtime_dev.py upgrade`.
7. Detener y desasignar la VM.

En DEV el 443 solo admite las IPs del equipo (regla `AllowTeamWeb`, ver
[SNI-39](../sni-39-dns-red.md)). Desde otra IP el pedido queda colgado; para probar sin
tocar el NSG: `curl --resolve jjt-snippets-dev.duckdns.org:443:127.0.0.1 https://jjt-snippets-dev.duckdns.org/api/languages`
desde la VM, que pasa por el mismo NGINX, certificado y `server_name`.

## Verificación

| Qué | Resultado |
| --- | --- |
| Tests | 272 pruebas de `scripts/`: log JSON y `X-Request-ID`, forwarder (config, contenedor, licencia, arranque), muestra de Swarm, actualización del runtime, `--proxy-only` y callers `v0.6.5` |
| NGINX real local | `verify_nginx.py`: líneas JSON con los 12 campos, las tres rutas, sin query, y el `X-Request-ID` de la respuesta igual al que recibe el upstream |
| Forwarder local | `verify_log_forwarder.py`: NGINX real → journald aislado → contenedor de Fluent Bit de producción; solo campos permitidos, línea mal formada descartada, solo OOM del kernel y warnings de Docker, sin historia, query, campos del driver ni licencia |
| Muestra en la imagen del agente | Los tests de `swarm_sample.py` pasan con el Python 3.14 de `newrelic/infrastructure` |

### DEV, 17/11/2026 (UTC)

| Paso | Resultado |
| --- | --- |
| Estado inicial | Marcador `sni82-runtime-v1`, 8 servicios `1/1`, release confirmado con las 5 configs de NGINX en `v1`, sin operaciones pendientes |
| Primer deploy | Frenado en el control de callers (`v0.6.4` contra `v0.6.5`) antes de tocar nada; corregido en `redis_cd.py` |
| Deploy `--proxy-only` | `exit 0`; verificación SQL, Permissions, UI y proxy/TLS internos en PASS; `nginx_main` y `nginx_routes` en `v2`; driver `journald` con tag `snippet-ingress`; alias `dev-snippets-db`, `dev-permissions-db` y `dev-redis` intactos |
| Pedido real | `X-Request-ID: d7a4d780…` en la respuesta y la misma línea JSON en journald con `route: api`, `status: 200` |
| Forwarder | Arrancado a las 14:03; include de licencia `-rw------- root root`; sin errores |
| Logs en New Relic | `keyset()` de `Log`: solo los 12 campos permitidos, `logtype`, `environment`, `service` y los que agrega New Relic; sin IP, `CONTAINER_*` ni `_HOSTNAME`; `status`, `request_time` y `bytes_sent` numéricos |
| Agente `runtime-v2` | Recreado a las 14:07 con etiqueta `sni80-runtime-v2`; 8 servicios `match`, `1/1`, sin fallas; en New Relic una fila por servicio con `FACET service` |
| Caída de UI | `scale=0` de 14:08:54 a 14:13:41: `SnippetSwarmSample` con `running` y `desired` en 0 de 14:08 a 14:12 y de vuelta en 1; `Log` con 7 pedidos `502/502` y 1 `504/504` en `route = 'ui'`, y `200` al restaurar |
| Agente detenido | 14:16:23 a 14:21:25: `SnippetSwarmSample` en 0 durante 5 minutos y `SystemSample` durante 6; `Log` siguió llegando (2 por minuto), el forwarder no depende del agente |
| Cierre | VM detenida y desasignada |

### Medición (O7)

| Qué | Antes | Después |
| --- | --- | --- |
| Agente | 0,03 % CPU, 138,7 MiB | 0,06–0,08 % CPU, 135,2 MiB (16,6 MiB recién reiniciado) |
| Fluent Bit | — | 0,11–0,14 % CPU, 8,5–8,8 MiB de 128 MiB; 44 KB de estado en disco |
| `SnippetSwarmSample` | — | ~1,1 KB por evento, 8 por minuto: ~0,39 GB/mes con la VM encendida todo el mes |
| `Log` de NGINX | — | ~0,44 KB por pedido: ~13 MB/mes con 1.000 pedidos por día, ~0,13 GB con 10.000 |
| Kernel y Docker | — | 0 eventos en la ventana medida |

En el peor caso SNI-80 suma ~0,4–0,5 GB/mes, un 5 % de los 10 GB de referencia y lejos
del aviso de 5 GB. La mayor parte del peso de la muestra son los atributos que el agente
agrega a todo evento. DEV pasa la mayor parte del tiempo desasignada, así que el
consumo real es menor.

### Pendientes

- Alertas sobre estas consultas: SNI-86.
- Ensayo de fallas con aviso real: SNI-87.
- PROD: inventario propio y `agent.json` de PROD (SNI-88).
- Reconciliar el manifiesto con el monitoreo de SNI-82, para volver a usar `deploy --infrastructure` completo.
