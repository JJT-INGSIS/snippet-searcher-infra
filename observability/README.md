# SNI-82 — Salud de bases, Redis y storage

La instalación DEV aprobada el 10/11/2026 se documenta en
[runtime/README.md](runtime/README.md): agente independiente fuera de Swarm y colector
privado. El bundle original de abajo sigue describiendo sus colectores; la recepción
en New Relic continúa pendiente de una clave de ingesta accesible.

Bundle candidato, probado localmente el 09/11/2026. No instala el agente de SNI-80,
no configura una cuenta New Relic, no modifica CD ni se aplica automáticamente a
DEV/PROD. **Recepción/entidades en New Relic pendientes** de instalar/verificar el agente de
SNI-80. SNI-79 ya está integrado: ver la [base común](../docs/architecture/observability-baseline.md). No se marca
SNI-82 Done sólo por renderizar este bundle o ejecutar colectores standalone.

## Decisiones y frontera

Thiago aprobó integraciones oficiales New Relic con un probe de storage, frente a
Collector, y probe del volumen con synthetic funcional separado, frente a ampliar
Snippets. Se reduce código de recolección y no se agrega API interna; se aceptan
configuración ligada al proveedor y que el probe local no prueba el adaptador de
Snippets. Marco: trade-offs y decisiones, capítulos 2/21 del
[índice del libro](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).
La aplicación concreta es del proyecto, no una prescripción del libro.

[Inventario de fuentes y dependencias](../docs/observability/sni-82-dependencies.md).
El operador confirma la release efectiva y proveedor activo antes de elegir targets;
`config.example.json` es un ejemplo local/Redis, no inventario de VMs encendidas.

## Señales y límites

| Fuente | Señal | Interpretación |
| --- | --- | --- |
| nri-postgresql 2.32.1 | PostgresqlInstanceSample / PostgresqlDatabaseSample, `db.connections`, `db.maxconnections`, tamaño y contadores nativos | Bases separadas; una conexión del monitor puede aparecer en el conteo |
| Query acotada nativa | PgCustomQuerySample.`blocked_sessions` | Sesiones esperando Lock en esa base; no SQL de usuarios ni textos de consultas |
| nri-redis 1.16.2 | RedisSample, memoria, clientes, rechazos, `db.aofLastWriteStatus` y `db.aofLastBgrewriteStatus` | INFO autenticado, sin leer keys ni CONFIG; disco mediante montaje aparte |
| Flex + storage_health.py local | SnippetStorageSample, `up`, bytes/inodos disponibles y roundtrip de fixture | Escribe/fsync/lee bytes exactos/elimina en `.sni82-probe`; no lee objetos de aplicación |
| Flex + storage_health.py asset | Misma muestra, read/write/delete de fixture por API real | Recorre Asset → backend activo; no usa SDK Azure ni credenciales del blob |
| Flex filesystem | Capacidad/inodos del filesystem montado | Sólo lectura; `up=1` significa que se pudo medir, no que haya espacio suficiente |

`durationMs` de storage mide ese chequeo. Los contadores de tiempo de lectura/escritura
PostgreSQL no son latencia de una consulta HTTP ni uso de pool JDBC: pool y latencia
JDBC corresponden a instrumentación de aplicación SNI-81. Antes de interpretar I/O
de PostgreSQL, revisar su configuración efectiva (`SHOW track_io_timing`); un cero
no acredita baja latencia. No se activan flags de bases ni extensiones para inventar
esa cobertura. El cierre integrado debe contrastar esas señales con SNI-81.

Las métricas oficiales pueden faltar aunque el proceso termine con código 0:
se verificó PostgreSQL detenido con JSON de métricas vacío. No llenar esa ausencia
con cero ni atribuirle éxito. Usar pérdida de señal por componente, junto con agente/
host de SNI-80, logs de integración y la verificación inicial de sus entidades.

## Paquete y configuración

Python 3.12 y agente Infrastructure >=1.41 para secretos por comando; Flex debe estar
disponible. Binarios oficiales amd64/arm64 fijados por SHA-256 en
[integrations.lock.json](integrations.lock.json). El instalador prepara un directorio
nuevo, verifica archivo completo y sólo extrae binario/definición esperados. No
sobrescribe instalaciones ni cambia un agente en ejecución.

```sh
python3 scripts/install_observability_integrations.py \
  --architecture amd64 --directory /ruta/nueva/sni82-paquetes
python3 scripts/observability_config.py \
  --config /ruta/config-dev-revisada.json \
  --runtime-config /etc/snippet-observability/config.json \
  --scripts-path /opt/snippet-observability > /ruta/sni82-integrations.yml
```

El JSON emitido es YAML válido para integrations.d. SNI-80 incorpora el subtree
`var/db/newrelic-infra/newrelic-integrations` al agente con sus binarios/definiciones,
los módulos `storage_health.py`, `observability_config.py`, `asset_probe.py` a
`/opt/snippet-observability`, y la configuración pública al path indicado. El ejemplo
usa 60 segundos; es un candidato, no una cadencia ya aplicada. Se acepta 30–300s,
para revisar contra presupuesto y ventana de detección de SNI-79/86.

Cada target tiene una sola integración. Cada probe Flex es independiente: un montaje
bloqueado no impide medir los demás. El proceso local tiene deadline 25s y la
integración 30s; peticiones Asset tienen timeout 5s por operación. Una falla operativa
emite `up=0` con motivo acotado; una configuración inválida no fabrica una muestra.
No habilitar debug ni registrar stdout de comandos de secretos. El resultado Flex
incluye errores aun con exit code 0; verificar muestras `up` y ausencia de errores,
no sólo el status del proceso.

## Identidad, redes y permisos

Thiago aprobó el 10/11/2026 `pg_read_all_stats` con credencial dedicada y query
monitoring desactivado. Se descartó la función SECURITY DEFINER restringida para
evitar un objeto SQL adicional que mantener y revisar. Se acepta que la credencial
pueda consultar metadatos/textos SQL, aunque el colector no los envíe. No permite
leer tablas de aplicación. El perfil fue probado en QA; su instalación efectiva
en cada ambiente todavía requiere revisar sus credenciales y ejecutar el runbook.


- `environment`, `service`, `version` son dimensiones acotadas. No incluir snippet,
  job, UUID de intento ni código en métricas. Los labels de la integración y la
  decoración real del agente deben verificarse al recibir la primera muestra.
- Los alias privados `dev-snippets-db`, `prod-snippets-db`, etc. evitan reutilizar
  nombres remotos nativos entre ambientes. Overlays optativos:
  `swarm/stack.observability.yaml` sobre stack base, y
  `stack.observability-redis.yaml` después del overlay Redis. Conservan nombres
  existentes y no publican puertos. Cambiar `environment` no reescribe los hosts:
  config PROD debe referenciar explícitamente sus alias.
- El agente debe resolver esos nombres desde la red privada correspondiente; para
  Redis, `redis_internal`. Un agente nativo en el host no obtiene automáticamente
  DNS de Swarm. SNI-80 debe revisar su ubicación y acceso: este bundle no publica
  bases en loopback/Internet para resolverlo ni define otro agente competidor.
- Montar sólo los volúmenes seleccionados. Bases/Redis/Azurite sólo lectura para
  capacidad; volumen de contenido con escritura para la carpeta exclusiva del
  probe, sin modificar propietarios/permisos del directorio de aplicación.
- Una sola instancia de probe por ambiente. Asset usa exclusivamente el contenedor
  `infra-sni82-dev|prod` y una key fija de diagnóstico. Un write incierto puede dejar
  ese único objeto; el ciclo siguiente lo reemplaza con nonce nuevo y confirma
  bytes/borrado. No borrar contenedores ni buscar/limpiar objetos de usuarios.
- PostgreSQL: ejecutar explícitamente `sql/postgresql-monitor.sql` en cada cluster,
  como operador, con variable psql `database` y secreto por entorno del proceso
  `OBS_MONITOR_PASSWORD`. Crea `nri_monitor` sin privilegios de admin ni SELECT de
  aplicación; otorga CONNECT y pg_read_all_stats. Este último permite metadatos de
  sesiones, incluidos textos accesibles por SQL: proteger la credencial. No se
  recolectan esos textos ni se habilita query monitoring, tablas, bloat o extensiones.
  Si el rol existe, el script falla para revisar sus permisos; no lo reutiliza ni
  rota contraseñas silenciosamente.
- Redis: secreto adicional `obs_redis_password`, 64 hex sin newline. El entrypoint
  sólo si existe agrega `nri_monitor` con hash y `INFO/PING`, sin keys, escrituras,
  CONFIG ni pub/sub. Sin ese secreto conserva el comportamiento anterior. Una credencial de monitoreo
  mal formada deshabilita sólo ese usuario y registra un error sin su valor; no
  detiene el Redis de aplicación ni usa su credencial como fallback. El overlay
  no crea el secreto ni activa al agente. Aplicar/rotar requiere operación revisada.
- Cada ambiente tiene archivos/secrets separados. El YAML sólo contiene referencias;
  el agente lee mediante secret commands, TTL 1m. Licencia de ingesta y credencial
  administrativa de New Relic pertenecen a SNI-79/80, no a este config público.

Para Asset, sustituir el target local por `{"kind":"asset","service":"asset-service",
"baseUrl":"http://asset-service:8080"}` y agregar el filesystem de Azurite sólo
si es su backend activo. No monitorear un proveedor opcional como si fuera activo.

## Comprobación e ingesta pendiente

[Evidencia local](../docs/evidence/sni82-2026-11-09.json): binarios oficiales Linux
amd64 sobre Docker local, PostgreSQL 18.6, Redis 7.4.7, Asset y Azurite reales.
Incluye bloqueo real, denegación de SELECT de aplicación y keys/CONFIG Redis,
filesystem de sólo lectura, pérdida de base/Redis/Azurite, AOF lleno en tmpfs de
8 MiB exclusivo y recuperación. Flex standalone aceptó las muestras verdaderas.
No certifica performance de VMs, ingesta, entidades ni alertas New Relic.

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/verify_observability.py --architecture amd64 \
  --evidence /tmp/sni82-evidence.json
```

El segundo comando descarga paquetes fijados, crea un proyecto `sni82-qa-*` sin
puertos de host, usa sólo fixtures/credenciales efímeros y detiene sus contenedores
al terminar. Conserva volúmenes y workspace privado para revisar fallos. No usarlo
como instalador en una VM ni conectarlo a bases compartidas.

Con SNI-79/80, confirmar en New Relic una primera muestra por cada componente activo
con ambiente/versión correctos, y ejecutar una falla/recuperación controlada en DEV.
Registrar consultas/rango, entidades, tags y tiempo de pérdida de señal. Descubrimiento:

```sql
FROM PostgresqlDatabaseSample SELECT keyset() SINCE 15 minutes ago
FROM PgCustomQuerySample SELECT latest(blocked_sessions) FACET entityName SINCE 15 minutes ago
FROM RedisSample SELECT latest(db.aofLastWriteStatus), latest(system.usedMemoryBytes) FACET entityName SINCE 15 minutes ago
FROM SnippetStorageSample SELECT latest(up), latest(availableBytes), latest(durationMs) FACET environment, service SINCE 15 minutes ago
```

Las tres primeras son consultas de descubrimiento: verificar el atributo de ambiente
recibido antes de transformarlas en alertas o mezclar datos de DEV/PROD. Para nativas,
no sustituir una muestra perdida por conexiones cero. Para filesystem, alertar por
capacidad según SNI-86, no sólo `up`. Registrar fuente única por señal: estas
integraciones para motor/AOF; probe para integridad/volumen; SNI-80 para host; SNI-81
para pool/JDBC. Cuantificar CPU/memoria/ingesta del piloto antes de promover PROD.
SNI-87 prueba aviso/diagnóstico; SNI-88 conserva la promoción y autorización propias.

Fuentes: [estadísticas y permisos PostgreSQL 18](https://www.postgresql.org/docs/18/runtime-config-statistics.html),
[PostgreSQL](https://docs.newrelic.com/install/postgresql/),
[Redis](https://docs.newrelic.com/docs/infrastructure/host-integrations/host-integrations-list/redis/redis-integration/),
[secret commands](https://docs.newrelic.com/docs/infrastructure/host-integrations/installation/secrets-management/),
[Flex](https://github.com/newrelic/nri-flex/blob/master/docs/basic-tutorial.md).
