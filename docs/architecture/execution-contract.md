# SNI-45 — Contrato de tests y ejecución incremental

Estado: **contrato v1 aprobado por Thiago para revisión del equipo** el 24 de
octubre de 2026. Es una entrega de diseño y fixtures, no endpoints implementados,
ejecución integrada ni aprobación de los demás responsables.

Fuente de verdad del contrato: este documento y sus
[fixtures](../contracts/execution-v1.json). Los repos consumidores deben enlazar
esta versión en vez de mantener copias divergentes o un repositorio de DTOs.

## Canal aprobado

El 24 de octubre de 2026, Thiago respondió «sí» a la propuesta de utilizar
**streaming con `fetch` para recibir eventos y POST separados para entregar inputs**.

La UI se comunica únicamente con Snippets. Language adapta la comunicación HTTP
con PrintScript; el navegador no controla directamente el intérprete.

Motivo: recibir outputs antes de terminar y conservar headers de identidad y
autorización en el transporte HTTP existente, sin introducir WebSocket.
No se colocan tokens ni identidades confiadas en querystrings.

Alternativas consideradas:

- Polling de eventos: simplifica el intercambio HTTP y recuperar desde una posición,
  pero agrega requests y latencia entre producir y mostrar cada salida.
- WebSocket: ofrece un canal bidireccional, pero exige gestionar su conexión,
  autorización y recuperación, sin una necesidad adicional identificada por ahora.

Costos aceptados: el cliente debe procesar fragmentos y límites de eventos, tratar
desconexiones y manejar reconexión explícitamente. NGINX debe permitir entregar
eventos sin acumularlos. Cerrar un stream no acredita cancelar el trabajo real.

Thiago aprobó además el framing NDJSON, capacidad acotada y límites configurables
el 24 de octubre de 2026, respondiendo «s» a las tres propuestas. Cambiar el canal
o framing más adelante afectaría UI, Snippets, Language y el proxy.

En el mensaje siguiente «sí», Thiago aprobó una réplica inicial por coordinador,
buffer de 256 eventos/256 KiB, retención terminal de 60 s, snapshot comprobado con
hasta tres intentos, comparación exacta, sobrantes informativos, entorno vacío y
no repetir automáticamente un inicio incierto. El registro de decisiones del final
resume sus costos; no supone aprobación del equipo ni autoriza despliegues.

## Restricciones comprobadas

- `ProgramOutput.writeLine(line)` permite observar cada salida mediante callback.
- `ProgramInput.readLine(prompt)` es síncrono y devuelve un string o `null`.
- `Interpreter.interpret` no expone una operación pública de cancelación. SNI-47
  debe demostrar interrupción y liberación efectivas; no basta cerrar HTTP o marcar
  el resultado como cancelado.
- Las definiciones pertenecen a Snippets; PrintScript interpreta, y Permissions
  conserva las relaciones de acceso. Este ticket no agrega storage ni un broker.

Fuentes locales revisadas: `printscript-runtime` e `interpreter` del repositorio
PrintScript. La verificación de SNI-47 deberá usar la dependencia publicada que
realmente consume el servicio, no asumir equivalencia con un checkout local.

## Decisiones aprobadas, todavía sin implementación runtime

### Framing

NDJSON: un objeto JSON por línea con tipo y secuencia. Reutiliza JSON y
evita implementar el framing SSE, pero requiere ensamblar líneas entre fragmentos
y programar replay/reconexión. SSE con `fetch` conserva un formato estandarizado
para eventos e IDs, aunque requiere su parser y no obtiene automáticamente el
comportamiento de `EventSource`.

### Capacidad y desconexiones

Una ejecución activa por actor y cuatro globales inicialmente,
sin cola; rechazar capacidad agotada. Conservar la sesión durante una
ventana de reconexión de 15 segundos y cancelarla si no se recupera el consumidor.
Es más acotado que mantener sesiones indefinidas, pero una desconexión prolongada
puede interrumpir el trabajo. Una nueva ejecución requiere una acción explícita,
no un reinicio automático al reconectar. La restricción inicial de una réplica
por coordinador hace aplicable el límite; escalar exige revisar este contrato.

### Límites iniciales configurables

120 segundos totales, 30 segundos por espera de input, código de hasta
1 MiB UTF-8, cada input de hasta 8 KiB UTF-8 y salida acumulada de hasta 1 MiB UTF-8.
Buffer limitado a 256 eventos y 256 KiB serializados. Alcanzar
un límite debe tener resultado explícito, no perder eventos silenciosamente.

Los valores acotan recursos y facilitan pruebas, pero restringen programas largos
y usuarios que tarden en responder. Los defaults pueden cambiarse por
configuración; los consumidores deberán conocer los límites efectivos.

Los bytes de código, input y salida se cuentan en UTF-8 decodificado, no por
caracteres ni tamaño de JSON. Los bytes del buffer sí incluyen la representación
serializada. Aplicar ambas cotas (eventos y bytes), no elegir solo una.

## API y responsabilidades

Las siguientes rutas constituyen el contrato para revisión del equipo,
no rutas implementadas. Se reutilizan UUID canónicos y Problem Details como
convenciones existentes. UI usa prefijo relativo `/api`; las rutas de la tabla
son las que recibe Snippets después de que NGINX quite ese prefijo.

| Método y ruta Snippets | Entrada | Respuesta de contrato |
| --- | --- | --- |
| POST `/snippets/{snippetId}/tests` | `inputs`, `expectedOutputs`: arrays de strings obligatorios | 201, definición con `id` y `snippetId` |
| GET `/snippets/{snippetId}/tests` | — | 200, `{items: [...]}`; vacío real `items: []` |
| POST `/snippets/{snippetId}/tests/{testId}/executions` | `{}` | 201, descriptor de sesión |
| POST `/snippets/{snippetId}/executions` | `{}` | 201, descriptor interactivo |
| GET `/executions/{executionId}` | — | 200, descriptor y último estado conocido |
| GET `/executions/{executionId}/events?after={seq}` | cursor numérico, default 0 | 200 NDJSON |
| POST `/executions/{executionId}/inputs` | `{requestId, value}` | 200, aceptación/repetición compatible |
| POST `/executions/{executionId}/cancel` | `{}` | 202, cancelación solicitada; no acredita trabajo liberado |

No aceptar código, owner, actor ni resultados en el body público de inicio. El
actor viene del contexto ya establecido: header de desarrollo solo en dev, sin
actor por defecto. No introducir Auth0 como parte de este contrato.

Crear una definición requiere ownership; listar y empezar una ejecución requieren
lectura. Snippets comprueba pertenencia del test al snippet, existencia confirmada
y acceso antes de recuperar código o invocar Language. Un destinatario compartido
puede ejecutar pero no crear/modificar tests. Los tests conservan orden, duplicados,
vacíos y Unicode; guardar una expectativa no ejecuta ni exige que el test pase.

El descriptor contiene `executionId`, `snippetId`, `mode` (`TEST`/`INTERACTIVE`),
`state`, `snapshot`, `limits` efectivos y `lastSeq`; en modo TEST incluye `testId`.
No exponer el ID interno de PrintScript ni referencias privadas de almacenamiento.
`snapshot` contiene `language`, `version`, `codeHash` y, en TEST, `testHash`.
Estados activos: STARTING, RUNNING, WAITING_INPUT y CANCELLING; los estados
terminales son los outcomes definidos más abajo. UNKNOWN es la observación del
cliente cuando no pudo conocer un terminal, no un éxito ni un intérprete activo
confirmado. Los cuerpos desconocidos y campos de actor/owner se rechazan, no se ignoran.

La API interna usa las mismas operaciones bajo `/executions` en
PrintScript, pero el inicio recibe `{code, version, mode, inputs}`: `inputs` es
obligatorio en TEST, está ausente en INTERACTIVE. No recibe identidad ni UUID de
snippet. Language selecciona PrintScript por lenguaje/capacidad y traduce fallas;
PrintScript selecciona versión explícita `1.0`/`1.1`, sin default. No afirmar input
interactivo o readEnvironment para una versión que no los soporte.

El descriptor interno contiene `executionId`, `mode`, `state`, `limits` efectivos
y `lastSeq`, sin snapshot ni IDs de negocio. El ID público de cada evento se
traduce en Language/Snippets antes de entregarlo al navegador. Los POST de input
responden `{requestId, accepted: true}` para aceptación y repetición compatible;
cancel responde `{state}`. Cancelar una sesión ya terminal conserva ese estado,
no publica otro terminal; consultar un descriptor expirado devuelve 404.

Snippets asigna un UUID público y mantiene su asociación al actor y al ID interno.
El UUID **no es una credencial**: cada lectura, reconexión, input y cancelación
verifica actor de la sesión y acceso vigente. El owner del snippet no obtiene
control automático de una sesión iniciada por otro lector.

Un fallo al crear por timeout es resultado incierto. No reintentar automáticamente
el POST ni crear otra sesión silenciosamente. Este contrato no ofrece inicio
idempotente ni garantiza exactamente una ejecución por request. Ante timeout,
conservar la incertidumbre, no indicar «no ejecutado». El cupo puede seguir ocupado
hasta que el trabajo termine o se verifique su cancelación.

## Eventos y estados

`Content-Type: application/x-ndjson`, UTF-8, un JSON completo y LF por evento.
Dentro de un string, los saltos de línea están escapados. El cliente debe tolerar
que un carácter UTF-8 o una línea se repartan entre lecturas; no usar `response.json()`
ni suponer un evento por chunk. No se aceptan líneas vacías ni JSON truncado como
eventos válidos. La conexión debe entregar cada output sin esperar al final.

Campos comunes: `executionId`, `seq` entero positivo, `type`, `data`. La secuencia
es contigua desde 1 por sesión y no se reinicia al reconectar. Es independiente de
los IDs de inputs. No ordenarla por timestamps ni por llegada de distintos POST.

| Tipo | Data | Efecto |
| --- | --- | --- |
| `started` | `{mode}` | primer evento, estado RUNNING |
| `output` | `{text}` | una llamada a `writeLine`, sin agregar/quitar texto |
| `input-required` | `{requestId, prompt}` | WAITING_INPUT, solo INTERACTIVE |
| `input-accepted` | `{requestId}` | RUNNING, no emitir el valor sensible |
| `heartbeat` | `{}` | mantiene el transporte; no cambia el estado |
| `terminal` | `{outcome, reason, ...}` | exactamente uno, último evento |

`outcome`: `COMPLETED`, `PROGRAM_ERROR`, `INPUT_EXHAUSTED`, `LIMIT_EXCEEDED`,
`CANCELLED`, `TECHNICAL_FAILURE` o `INTERRUPTED`. `reason` es un identificador
estable, nunca el mensaje humano. Estado final corresponde al outcome; los
diagnósticos opcionales conservan `rule`, `message`, `line`, `column` desde 1.
Un EOF sin terminal no significa éxito: consultar estado/reconectar según política.
En el stream no se inserta un Problem Details entre eventos después del 200;
la falla se expresa como terminal si el servidor puede comunicarla.

Solo Snippets agrega en TEST, tras terminación normal, `comparison` con
`PASSED`/`FAILED`. PrintScript no conoce expectativas ni decide el resultado.
Error del programa, agotamiento de inputs, timeout o falla técnica no se convierten
en assertion fallida. La salida observada antes de una falla permanece parcial.

La comparación es igualdad exacta de arrays de outputs: orden,
cantidad y texto; sin trim, normalización Unicode ni deduplicación. Las listas
vacías son válidas. Inputs predeterminados se consumen en orden; agotarlos termina
con INPUT_EXHAUSTED sin esperar al navegador. Los sobrantes se informan
como `unusedInputs` y no fallan por sí solos.

### Input y cancelación

Cada solicitud interactiva tiene UUID `requestId`; solo hay una pendiente por
sesión. Repetir el mismo requestId y valor devuelve aceptación compatible
sin consumir dos inputs; otro valor o requestId fuera de turno es 409. El string
vacío es un input, no ausencia ni EOF. No aceptar inputs adelantados ni para TEST.

Solicitar cancelación coloca estado CANCELLING. El terminal CANCELLED se emite
solo al verificar que el intérprete ya terminó y liberó sus recursos. Una carrera
con terminación conserva el primer resultado final fijado de forma atómica.
SNI-47 debe cubrir espera de input, cómputo y buffer lleno. No basta cancelar un
Future: el worker debe detenerse efectivamente y no dejar sesiones huérfanas.

## Desconexiones, límites y reinicio

La ventana aprobada de reconexión es de 15 s desde detectar desconexión; también
aplica a una sesión creada que nunca abre el stream. El timeout total de 120 s
incluye input y reconexión; nunca se extiende por actividad del cliente. En TEST
no se emite input-required: los inputs vienen del test.

Replay: un consumidor activo por sesión, cursor `after` con último
evento aplicado, eventos posteriores solamente. El replay usa un anillo acotado
por las cotas de buffer; cursor anterior al historial retenido devuelve 409
`event-history-unavailable`, no empieza de cero ni inventa eventos. La UI deduplica
por seq. Si un consumidor no logra seguir, terminar explícitamente por límite de
buffer; reservar espacio/control independiente para poder comunicar el terminal.
Reconexión no reinicia el programa. Una cancelación solicitada al vencer la ventana
debe liberar realmente el worker antes de liberar el cupo.

El historial de eventos ya entregados se puede desalojar por antigüedad para
respetar las cotas: los 15 s permiten reconectar, no garantizan conservar todos
los outputs de esos 15 s. Desalojar historial no permite perder eventos pendientes
de entrega al consumidor conectado; si esos pendientes llenan el buffer, finalizar
con LIMIT_EXCEEDED (`event-buffer-exceeded`). Una reconexión con cursor mayor que
lastSeq es 400 `invalid-cursor`; un segundo consumidor activo es 409
`execution-consumer-conflict`. Validar actor antes de revelar cursores/estado.

Retener descriptor, historial acotado e IDs de input por 60 s tras el
terminal y luego eliminar los datos transitorios. No confundir esta retención con
persistencia de definiciones: estas sí son durables en Snippets (SNI-46). Este
contrato no exige persistencia histórica de resultados; al expirar la sesión se
pierde su resultado transitorio. Agregar un histórico sería otro alcance. Reiniciar
PrintScript pierde las sesiones activas; Snippets informa INTERRUPTED si puede
determinar el reinicio, o TECHNICAL_FAILURE/estado desconocido ante comunicación
incierta, nunca COMPLETED. Reiniciar Snippets no permite recuperar asociaciones
perdidas: una sesión no encontrada no autoriza crear otra ni controlar un ID interno.

Se usa inicialmente una sola instancia de cada coordinador de ejecución. Sin esa
restricción o una coordinación adicional, «una por actor/cuatro globales» no sería
cierto. Desplegar réplicas sin resolver esto no satisface el contrato.

Snippets reserva atómicamente el cupo por actor para TEST e INTERACTIVE juntos;
PrintScript reserva atómicamente el máximo global de intérpretes para ambos modos.
La reserva incluye estados de arranque, WAITING_INPUT y CANCELLING. Un inicio
rechazado libera su reserva; una respuesta perdida no prueba que corresponda
liberarla. No liberar cupos por desconexión antes de detener el trabajo.
Los buffers/retenciones son por sesión y por salto de transporte; no por usuario.
Los descriptores terminales no consumen cupo de ejecución, pero sí tienen limpieza.

El despliegue posterior debe evitar dos coordinadores simultáneos con contadores
independientes, también durante rolling updates. Un reemplazo interrumpe las
sesiones activas; `replicas: 1` con actualización start-first no acredita por sí
solo el límite global. Este ticket no modifica la estrategia de despliegue.

## Snapshot y vigencia del resultado

Se necesita un snapshot coherente de código, lenguaje y versión, más una copia
inmutable de la definición del test en ese inicio. Identidad de contrato:
`sha256-v1:` + SHA-256 de JSON compacto UTF-8 `[language, version, code]`, sin
normalizar strings ni ASCII-escape, más hash independiente `[inputs, expectedOutputs]`.
Los UUID del snippet/test no son una revisión del contenido.
La serialización usa escapes JSON estándar para comillas, backslash y controles;
no escapa `/` ni caracteres Unicode no ASCII y no inserta espacios ni BOM. Los
vectores en fixtures fijan el cálculo para proveedores y consumidores.

Hoy metadatos y referencia se consultan por operaciones separadas; combinarlas
sin coordinación no garantiza snapshot. Una actualización también puede borrar
el blob anterior. SNI-48/49 deben resolver lectura coherente y retención durante
esa lectura, o rechazar/reintentar de forma acotada sin ejecutar una mezcla.
No mantener una transacción de BD durante toda la ejecución ni prometer un
versionado histórico que no existe.

Mecanismo aprobado: leer lenguaje, versión y referencia juntos
en una única consulta; leer ese blob inmutable; verificar nuevamente la tupla de
referencia/lenguaje/versión antes de iniciar. Si cambió o el blob fue eliminado por
un update concurrente, repetir como máximo tres veces y luego devolver conflicto,
sin iniciar el intérprete. Tras obtenerlo, conservar el código en memoria de esa
ejecución. Requiere un lector coherente en Snippets, no sumar consultas independientes
al caso de uso ni modificar Asset. Si el fallo es técnico, devolver falla técnica,
no atribuirlo automáticamente a una actualización concurrente.

Si cambia el contenido o definición durante la ejecución, los eventos pertenecen
al snapshot original. Antes de presentar el resultado como vigente se verifica
su identidad contra el snapshot actual; si no puede comprobarse, vigencia UNKNOWN,
no vigente por defecto. Un resultado viejo puede mostrarse identificado como tal.

## Seguridad, errores y proxy

Proveedor de `readEnvironment`: vacío; en 1.1 una variable ausente
produce error del programa con diagnóstico existente. No usar System.getenv,
no aceptar mapa de entorno desde UI y no exponer secretos de VM/servicio.

Errores previos al stream usan `application/problem+json`, con `type`, `title`,
`status`, `detail`, `instance`. `type` estable bajo `urn:snippets:problem:` (interno:
`urn:printscript:problem:`). Consumidores deciden por type/status, no por detail.

| HTTP | Categorías |
| --- | --- |
| 400 | `invalid-request`, `invalid-cursor` |
| 401 | `identity-required` |
| 403 | `access-denied`, `execution-actor-mismatch` |
| 404 | `snippet-not-found`, `test-not-found`, `execution-not-found` |
| 409 | `execution-already-active`, `input-conflict`, `event-history-unavailable`, `execution-consumer-conflict`, `snapshot-conflict` |
| 413 | `payload-too-large` |
| 422 | `unsupported-capability`, `unsupported-version`, `invalid-code` |
| 429 | `execution-capacity-exhausted` |
| 503 | `dependency-unavailable` |
| 504 | `dependency-timeout` |

Estos errores no cambian el contrato existente de POST /validate: código inválido
allí continúa siendo 200 con valid:false; Language lo traduce en su borde.
Un input timeout o límite del programa iniciado es evento terminal, no un HTTP 504
retroactivo. No exponer código/output ni existencia privada al actor incorrecto.

SNI-52 configura las rutas de eventos sin buffering ni caché/reintentos, incluyendo
la conexión Snippets–PrintScript. Heartbeat de transporte cada 10 s como
evento `heartbeat` con data `{}` y seq normal; no output ni avance de input.
Permite mantener vivo el canal bajo el timeout de inactividad de NGINX, sin
confundirlo con el deadline total. No cambiar el proxy en este ticket.

## Fixtures y comprobación

Desde la raíz de infra: `python3 -B -m unittest discover -s scripts -p 'test_execution_contract.py' -v`.
Los fixtures incluyen éxito, comparación fallida, espera de input, actor incorrecto,
timeout, EOF sin terminal y cambio de snapshot. Las pruebas verifican consistencia,
fragmentación UTF-8/NDJSON y comparación exacta. **No ejecutan PrintScript, HTTP,
autorización ni un backend:** no sustituyen las pruebas reales de SNI-47/48/49/53.
Los diagnósticos del ejemplo de runtime son ilustrativos: SNI-47 conserva los
identificadores reales de la biblioteca, no implementa la regla ficticia del fixture.

Verificación local del 24 de octubre de 2026: 20 pruebas específicas y 119 pruebas
totales de infra, todas exitosas; ejecutar nuevamente el comando de regresión indicado en
la entrega si cambia un fixture. La suite existente descubre automáticamente el
archivo nuevo en CI, sin modificar el workflow ni credenciales.

## Registro de decisiones y entrega al equipo

Las aprobaciones anteriores de Thiago se aplican a este diseño, no a despliegues.
Se registraron siguiendo la skill `design-tradeoffs`.

| Elección | Alternativa descartada | Motivo y costo aceptado | Revisar cuando |
| --- | --- | --- | --- |
| fetch + NDJSON + POST de inputs | polling, SSE framing, WebSocket | HTTP y JSON existentes; parser incremental/reconexión propios | otra necesidad bidireccional o incompatibilidad real |
| Una réplica por coordinador, 1 por actor/4 globales sin cola | coordinación distribuida o cola | menos infraestructura; menor disponibilidad/escalado y rechazo en saturación | se necesiten réplicas o mayor capacidad |
| Replay limitado, 60 s de retención, 256 eventos/256 KiB | historial durable o ilimitado | memoria acotada; no toda desconexión puede recuperarse | necesidad de resultados históricos/reanudación |
| Snapshot verificado, hasta tres lecturas | histórico completo o transacción larga | conserva coherencia sin histórico; puede rechazar bajo concurrencia | se necesiten revisiones históricas o aumenten conflictos |
| Comparación exacta, sobrantes informativos | normalizar texto o fallar por inputs sobrantes | predecible; espacios/Unicode distintos fallan y sobrantes no diagnostican error | cambie el requisito funcional |
| Entorno vacío | variables runtime o allowlist | evita exponer secretos/configuración; readEnvironment no encuentra valores | se acuerden variables públicas explícitas |
| Sin repetición automática del inicio | inicio idempotente durable | evita duplicar por retry sin añadir persistencia; resultado incierto tras timeout | se requiera recuperación transparente |

Rutas, estados y nombres concretan el contrato siguiendo las convenciones de
UUID, headers y Problem Details existentes; no acreditan aprobación de los demás
responsables. Compartir esta entrega con SNI-46/47/48/49/50/51/52 para revisión y
desarrollo paralelo. SNI-53 debe verificar los proveedores reales juntos.

La entrega local de documentación y fixtures está preparada; no se cambió el estado
del ticket en Linear. No hay endpoints runtime nuevos, despliegues ni garantías
de reanudación durable. Los repos de Snippets/PrintScript deben enlazar este
contrato en sus entregas; no se modifican aquí sus branches ni pipelines locales.

Referencias: [NDJSON](https://github.com/ndjson/ndjson-spec),
[streaming con fetch](https://developer.mozilla.org/en-US/docs/Web/API/Streams_API/Using_readable_streams).

