# SNI-82 — Relevamiento de salud de dependencias

Revisión de fuentes: 09/11/2026, infra dev `773e1ae`.
Estado: **recolector/probe aprobados; permisos PostgreSQL pendientes. Bundle probado localmente; ingesta real pendiente de SNI-79/80**.
No acredita el estado efectivo de las VMs, instrumentación ni recepción en New Relic.

## Componentes que debe distinguir la cobertura

| Componente | Configuración del repo | Persistencia | Límite del chequeo actual |
| --- | --- | --- | --- |
| PostgreSQL de Snippets | `snippets-db:5432`, base `snippets`; usuario de aplicación `snippets` | `snippets_data`, `/var/lib/postgresql` | `pg_isready` comprueba disponibilidad para conexiones, no bloqueos, capacidad ni pool de la aplicación |
| PostgreSQL de Permissions | `permissions-db:5432`, base `permissions`; usuario de aplicación `permissions` | `permissions_data`, `/var/lib/postgresql` | Debe tener identidad y métricas propias aunque comparta VM con la otra base |
| Redis, sólo si el overlay está aplicado | `redis:6379`, red `redis_internal`, AUTH mediante secreto, AOF `everysec`, `noeviction` | `redis_data`, `/data` | PING no acredita persistencia AOF sana ni capacidad disponible |
| Storage local, sólo si es el proveedor seleccionado | `snippets_content` en Snippets, directorio `/var/lib/snippets/content` | `snippets_content` | Un proceso vivo no acredita escritura, integridad ni espacio disponible |
| Asset, sólo si está seleccionado/activo | API interna `asset-service:8080`; management 9090 | Backend configurado por `AZURE_HOST` | Health management no reemplaza escribir/leer contenido por la API de Asset |
| Azurite, cuando es el backend activo de Asset | Blob interno 10000, `AZURE_HOST=http://azurite` | `asset_blobs`, `/data` | Una respuesta HTTP 400/403 del listener sólo prueba que responde; no verifica un blob de prueba |

Fuentes: [stack base](../../swarm/stack.yaml),
[Redis](../../swarm/stack.redis.yaml), [Asset](../../swarm/stack.asset.yaml),
[Compose](../../compose.yaml) y [Redis Compose](../../compose.redis.yaml).
El stack no publica puertos de bases ni Redis. Compose local liga los puertos de
bases a loopback; eso no habilita acceso remoto para monitoreo.

Los manifiestos bootstrap dev/prod conservan la misma imagen PostgreSQL
`18.6-bookworm` por digest y fecha de selección 12/10/2026. Redis está fijado a
`7.4.7-alpine`. Son referencias del repo, no evidencia de las versiones desplegadas
hoy. No se sustituye la inspección de la release efectiva/tareas por estos archivos.
La compatibilidad del recolector elegido se deberá probar con esas versiones.

## Fronteras con otros tickets

- SNI-79 define la base común de cuenta, entidades, presupuesto e inventario efectivo.
- SNI-80 prepara agente/host/Swarm y disco. SNI-82 necesita mapear cada volumen al
  filesystem y capacidad efectivos de su nodo; tamaño lógico de una base y espacio
  libre de filesystem son señales diferentes.
- Conexiones y sesiones PostgreSQL no son utilización del pool JDBC. El pool pertenece
  a la instrumentación de las aplicaciones; no se inventará esa medida desde SQL.
- SNI-86 consume las señales para dashboards/alertas; no se crean políticas duplicadas.
- El synthetic funcional de SNI-85 cubre la aplicación. El probe local
  de SNI-82 opera sobre el volumen desde infraestructura; no amplía el adaptador de Snippets.
- SNI-87 ensaya fallas con ventana/datos de prueba y notificación reales. Todavía no
  hay evidencia de New Relic que permita ejecutar ni cerrar esa aceptación.
- SNI-88 promueve una configuración revisada a PROD. No se activa producción como
  efecto de preparar estos archivos.

## Reutilización y pendientes

Existe [asset_probe.py](../../scripts/asset_probe.py): prepara contenido vacío,
Unicode y JSON aparente en un contenedor exclusivo, verifica bytes/hash y permite
limpieza limitada a su manifiesto. No es un monitor periódico ni una integración de
New Relic. Se aprovechará su contrato HTTP; no se duplicará el cliente de blobs ni
se accederá directamente a datos de usuarios.

No hay agente New Relic, integraciones, roles de monitoreo de bases, usuario Redis
separado ni credencial de ingesta declarados en el dev revisado. No se usarán las
credenciales de aplicación/administración como sustituto de las de observabilidad.
Thiago aprobó el 09/11/2026 integraciones oficiales New Relic + probe de storage,
y probe del volumen con synthetic funcional separado. El bundle, permisos,
cadencia parametrizada, límites y evidencia están en [el runbook](../../observability/README.md).
La cuenta/agente y la recepción por ambiente todavía deben verificarse con SNI-79/80.

Marco de análisis: capítulos 2 (trade-offs) y 21 (decisiones), según el
[índice editorial de Fundamentals of Software Architecture, 2nd ed.](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).
Se eligieron integraciones oficiales frente a Collector para reducir procesos y
configuración propia, aceptando dependencia de New Relic. El probe del volumen
evita ampliar Snippets, a costo de no recorrer su adaptador; SNI-85 conserva ese
chequeo funcional. Son elecciones de Thiago, no recomendaciones atribuidas al libro.

Referencias técnicas consultadas:
[PostgreSQL New Relic](https://docs.newrelic.com/install/postgresql/),
[Redis New Relic](https://docs.newrelic.com/docs/infrastructure/host-integrations/host-integrations-list/redis/redis-integration/),
[Flex](https://docs.newrelic.com/docs/infrastructure/host-integrations/host-integrations-list/flex-integration-tool-build-your-own-integration/).
