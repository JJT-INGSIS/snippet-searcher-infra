# SNI-83 — Outbox, Redis Streams y progreso durable de los jobs

Revisión de fuentes: 17/11/2026. Snippets `ed6a249`, infra `fef79e1`, gradle-conventions `8395716`.
Estado: **en desarrollo. Diseño aprobado; nada aplicado todavía.**

Un cambio de reglas puede guardarse, publicar su evento y quedar sin procesar mientras la
API y Redis siguen disponibles. Este ticket separa tres cosas que hoy no se distinguen:
**publicación** (outbox → Redis), **entrega** (Redis → consumidor, con ACK) y **progreso**
(trabajo durable en PostgreSQL). Continúa [SNI-81](sni-81-apm-traces.md), que dejó APM y el
`request.id` del ingreso, y entrega las señales a SNI-86 (alertas) y SNI-87 (ensayo de
«consumidor detenido»).

## Punto de partida

| Pieza | Estado | Consecuencia |
| --- | --- | --- |
| Activación en DEV | `SNIPPETS_OUTBOX_ENABLED`, `SNIPPETS_WORKER_ENABLED` y `PRINTSCRIPT_OPERATIONS_ENABLED` valen `false` por defecto; ni el stack ni el release los activan ([SNI-79](../architecture/observability-baseline.md)) | Para la prueba real hay que prenderlos en DEV |
| `event_outbox` | Pendiente = `published_at IS NULL`; `attempts`, `next_attempt_at`, `lease`, `last_error` (código); índice parcial sobre los pendientes | Pendientes y su edad se cuentan sin recorrer la historia |
| `background_jobs` | Estados `PENDING`, `RUNNING`, `RETRY`, `UNKNOWN`, `COMPLETED`, `PARTIAL`, `FAILED`, `SUPERSEDED`; `reaction`, `next_attempt_at`, `lease_until`, `updated_at`; índice parcial sobre los no terminados | Trabajos por tipo y estado, edad y progreso, acotados |
| `background_job_items` | Estado por elemento y `updated_at` | Último progreso durable de un trabajo |
| `execution_permits` | `RESERVED`, `UNKNOWN`, `RELEASED`, sin vencimiento | Reservas que retienen capacidad |
| Publicador | `@Scheduled` cada 2 s, lote de 10, backoff exponencial hasta 5 min | Un pendiente de más de un minuto ya no es el ciclo normal |
| Consumidor | Grupo `snippet-processing-v1`, lease y reclamo a 30 s, 5 reintentos, Lettuce nativo (`xautoclaim`) | `XINFO GROUPS` y `XPENDING` disponibles sin dependencias nuevas |
| `correlationId` | `UUID.randomUUID()` en `FormattingRulesChangedJob` y `LintingRulesChangedJob` | No se puede ir del pedido HTTP al evento |
| Logs | Publicador y consumidor ya escriben `eventId`, `jobId` y `correlationId` en el mensaje | El reenvío de New Relic (0.3.0) solo deja pasar `request.id`, `operation`, `outcome` y `duration.ms` del MDC |

## Decisiones

Aprobadas por Juan el 17/11/2026.

| # | Decisión | Alternativa descartada | Costo aceptado |
| --- | --- | --- | --- |
| B1 | Muestreador dentro de Snippets cada 60 s, independiente del publicador y del consumidor, con consultas acotadas a PostgreSQL y Redis; emite `SnippetBackgroundSample` por la API del agente | Colector de SNI-82 (Flex) con permisos de lectura sobre tablas de negocio | Si Snippets se cae no hay muestras: lo cubren `SnippetSwarmSample` (SNI-80) y la regla de ausencia |
| B2 | Una fila por aspecto (`outbox`, `stream`, `jobs` por tipo y estado, `capacity`); ceros explícitos; lag desconocido como flag, nunca como cero; ausencia = el muestreador no corre | Emitir solo cuando hay pendientes | Unos pocos eventos por minuto |
| B3 | Solo trabajos sin terminar, outbox sin publicar y terminados de los últimos 15 min; timeout corto; ante falla, `samplerError` en lugar de valores | Recorrer toda la historia | Los terminados viejos no entran |
| B4 | `correlationId` de un cambio de reglas derivado del `X-Request-ID` de NGINX (128 bits → UUID) o aleatorio si no hay; atributos `event.id`, `job.id` y `correlation.id` en la transacción del `PUT`; ciclo del publicador y turno del consumidor como transacciones de fondo con esos atributos e intento; MDC | Mantenerlo aleatorio y solo loguear la pareja | Un ID del pedido viaja en el evento (no es contenido) |
| B5 | `gradle-conventions` 0.3.1 reenvía además `correlation.id`, `event.id`, `job.id` y `attempt` del MDC | Buscar por texto en el mensaje | Una versión más |
| B6 | Activación por release: `background: {publisher, consumer}`, overlay con las tres variables y `deploy --infrastructure --background-only` (Snippets y PrintScript); pausar el consumidor = `consumer: false` | Prenderlo a mano en la VM | Más código en infra; prender el procesamiento real en DEV se coordina con el equipo |
| B7 | Umbrales iniciales a medir en DEV: pendiente de publicación > 60 s; PEL con idle > 60 s; trabajo elegible > 5 min o con lease y sin progreso > 60 s; sostenido = 5 muestras seguidas | Fijarlos sin medir | Una ventana de prueba |
| B8 | Tests con PostgreSQL y Redis reales (Testcontainers) armando cada estado, más una prueba local con el colector falso de SNI-81 | Probar solo en DEV | Tests más largos |
| B9 | Operaciones en la VM y en Azure por Juan con OK paso a paso; PROD parametrizado y apagado; alertas en SNI-86 | — | — |

## Señales

`SnippetBackgroundSample`, una fila por aspecto y muestra:

| `aspect` | Campos | Qué distingue |
| --- | --- | --- |
| `outbox` | `pending`, `oldestPendingSeconds`, `retrying`, `failingReasons` | Publicación atrasada |
| `stream` | `lagKnown`, `lag`, `entriesRead`, `pending`, `oldestPendingIdleSeconds`, `consumers` | Entrega sin ACK (PEL) y atraso del grupo, por separado |
| `jobs` | `reaction`, `state`, `count`, `oldestEligibleSeconds`, `lastProgressSeconds`, `backoff` | Trabajo que dejó de avanzar, reintentos y `UNKNOWN` sostenido |
| `jobs-finished` | `reaction`, `state`, `count` (últimos 15 min) | `PARTIAL` y `FAILED` recientes |
| `capacity` | `heldBackground`, `unknownPermits`, `oldestHeldSeconds` | Reservas que siguen reteniendo capacidad |

Todas las filas llevan `environment`, `service` y `samplerError`. Un valor que no se pudo
medir no se reemplaza por cero.

| Situación | Cómo se ve |
| --- | --- |
| Cola vacía y sana | `pending = 0`, `lag = 0`, sin trabajos elegibles |
| Publicación atrasada | `outbox.pending > 0` con edad creciente; el stream no recibe |
| Entrega sin ACK | `stream.pending > 0` con idle creciente |
| Consumidor detenido | `stream.lag` crece y el trabajo `PENDING` envejece; el outbox sigue en 0 |
| Trabajo trabado | Trabajo con lease y `lastProgressSeconds` creciendo |
| Lag desconocido | `lagKnown = false` y sin `lag` |
| Muestreador caído | Ausencia de muestras |

## Correlación

| Paso | Identificador |
| --- | --- |
| Pedido | `request_id` en el log de NGINX y `request.id` en la transacción del `PUT` de reglas |
| Evento | `correlationId` = el `request.id` como UUID; `event.id` y `job.id` en la transacción del `PUT` |
| Publicación | Transacción de fondo con `event.id`, `job.id`, `correlation.id` e intento |
| Turno del consumidor | Transacción de fondo con los mismos atributos y el intento del trabajo |
| Logs | MDC con esas claves, reenviadas por el agente |

## Fronteras

- SNI-57/58: no se cambia el comportamiento del outbox ni del consumidor; solo se observa.
- SNI-74: la activación de Auth0 en DEV también toca Snippets y el release; el paso en DEV
  se hace después y sin deploys en paralelo.
- SNI-86: alertas y dashboards sobre estas señales.
- SNI-87: ensayo de «consumidor detenido con Redis y publicador operativos».

## Verificación

Pendiente.
