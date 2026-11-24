# Observabilidad y respuesta

[Inicio](../../README.md) · [Runtime de agentes](../../observability/runtime/README.md) ·
[Terraform y chequeos](../../observability/newrelic/README.md)

## Señales

| Señal | Origen y uso |
| --- | --- |
| VM, contenedores y Swarm | Agente de infraestructura y `SnippetSwarmSample`. Revisar frescura, réplicas, fallos y digests efectivos. |
| PostgreSQL, Redis y storage | Colector privado. Revisar conexiones, bloqueos, espacio y probe de contenido. Redis aplica cuando el runtime está activo. |
| APM y trazas | Agentes Java de Snippets, PrintScript y Permissions. Un alta correlaciona las llamadas mediante `trace.id`. |
| Logs | El agente de la JVM reenvía logs de aplicación. Fluent Bit reenvía logs seleccionados de host e ingreso. El `X-Request-ID` de NGINX enlaza el ingreso con la transacción. |
| Experiencia | Browser registra rendimiento y errores JS. Los Pings públicos comprueban UI y HTTP de API. Cypress comprueba el listado y detalle autenticados al publicar `SnippetFunctionalCheck`. |
| Trabajos | `SnippetBackgroundSample` describe outbox, lag y mensajes pendientes de ACK, progreso durable y capacidad. El muestreo puede seguir activo con el consumidor detenido. |

Usá los tableros de [Aplicación y experiencia](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTkz),
[Dependencias y procesamiento](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTky)
e [Infraestructura y entrega](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTkx).
Seleccioná DEV o PROD y verificá fecha, muestra y entidad. El filtro usa
nombres APM por ambiente y los atributos de ámbito de cada evento.

## Diagnóstico de alertas

| Condición | Primera acción | Confirmar recuperación |
| --- | --- | --- |
| UI/API pública o TLS | Revisar Ping, DNS, NSG, TLS, NGINX y `/api/languages`. | Acceso externo y nuevos checks válidos. |
| Sin señal de VM o réplicas | Revisar Azure, agente y colector. Con muestras activas, comparar réplicas disponibles/deseadas y tareas de Swarm. | Muestras nuevas y stack saludable. |
| Error técnico de dependencia | Seguir APM y logs correlacionados. Contrastar conexiones, bloqueos y probe de storage. | Petición funcional sana y señal de dependencia recuperada. |
| Fallo funcional autenticado | Revisar `failureCategory`. Para ausencia, inspeccionar el timer y el envío de eventos en el host. | Evento `SUCCESS` del chequeo correspondiente. |
| Outbox, Redis o jobs | Separar atraso de publicación, lag, mensajes pendientes de ACK, ítems RUNNING sin progreso y capacidad agotada. | El trabajo avanza y baja el atraso sin perder ítems pendientes. |

Las críticas usan correo grupal y push cuando está configurado para el
ambiente. Warnings se avisan por correo. Los eventos informativos quedan en
el tablero o en los registros. El responsable técnico orienta el diagnóstico
y puede responder cualquier integrante disponible. La entrega que marca
New Relic y la recepción humana se comprueban por separado. El canal móvil
verificado es push. Tras recuperar, confirmá también el cierre del incidente.

Antes de apagar una VM por mantenimiento, coordiná el silencio acotado al
ambiente y a las condiciones afectadas. Al encenderla, comprobá la salud,
reactivá los avisos y verificá muestras nuevas. Una pérdida de señal también
puede significar un fallo de ingesta.

## SLI y presupuesto de errores

| SLI de siete días | Muestra válida | Objetivo y volumen para interpretarlo |
| --- | --- | --- |
| API HTTP | Ingreso API/ejecuciones. Éxito 2xx y fallas 5xx. Excluye health público `/api/languages`, redirecciones y 4xx. | 99%. Debajo de 100 solicitudes, el porcentaje es orientativo. |
| Listado autenticado | `SUCCESS` sobre `SUCCESS + FAILURE` para el chequeo del ambiente. | 96%. Debajo de 25 resultados, el porcentaje es orientativo. La ausencia se alerta aparte. |

Un stream que falla después de abrir con 2xx se diagnostica en APM y logs.
Una fórmula en un tablero puede calcular el SLI aunque el SLO nativo
correspondiente todavía no esté provisionado.

## Evidencia y defensa

- **DEV.** Se verificó un alta `201` con el Trace ID
  `124cd1d367b6804c467d9acd307f6a32` y spans en los tres backends.
  `FROM Span SELECT count(*) WHERE trace.id = '<trace-id>' FACET appName`
  permite comprobar el recorrido en la ventana de la muestra. Si se toma otro
  alta, buscar su `X-Request-ID` en `Transaction` por `request.id`.
  El corte de UI abrió y cerró un incidente y el equipo confirmó correo.
  Los ensayos de [fallas funcionales y de procesamiento](../evidence/sni87-dev-2026-11-19.json)
  documentan también dependencia caída, fixture ausente y consumidor detenido.
- **PROD.** El [registro del 23/11](../evidence/sni89-prod-2026-11-23.json)
  acredita Pings sanos, telemetría y un ensayo de falta de réplica de UI que
  abrió una alerta, produjo correo y push, recuperó la UI y cerró el incidente.
  [Incidente](https://aiops.service.newrelic.com/accounts/8718557/incidents/949a7fc6-c98c-4b52-8973-4e45b07fd703/redirect).
  En ese relevamiento el storage era local y Redis/Asset no estaban activos.
  Quedaban por acreditar el chequeo autenticado y SLO nativo de PROD, la
  pérdida independiente del colector y la falla SQL con réplica sana.

Antes de la defensa y después de promover, verificá el inventario real, los
digests, datos recientes, checks de ambos ambientes y rutas de notificación.
Usá [las consultas de PROD](../../observability/newrelic/prod-defense.nrql)
y [las consultas de dependencias DEV](../../observability/runtime/dependencies-dev.nrql).
Para mostrar un incidente, se puede usar la evidencia registrada junto con
las comprobaciones sanas del día. Cualquier ensayo nuevo requiere acordar el
alcance, tener un plan de restauración y evitar datos reales.
