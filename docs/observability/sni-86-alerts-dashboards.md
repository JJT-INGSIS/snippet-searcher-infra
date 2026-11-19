# SNI-86 · Dashboards, SLO y alertas en DEV

Estos tableros usan las señales de [SNI-80](sni-80-dev-instrumentation.md),
[SNI-81](sni-81-apm-traces.md), [SNI-82](sni-82-dependencies.md),
[SNI-83](sni-83-background-signals.md), [SNI-84](sni-84-synthetics-dev.md)
y [SNI-85](../../observability/newrelic/README.md). El código de esta entrega
vive en [Terraform](../../observability/newrelic/sni-86/). La cuenta es
`8718557` (US).

## Tableros

| Tablero | Qué permite comprobar |
| --- | --- |
| Aplicación y experiencia | Resultado de checks de UI/API y listado autenticado, SLO y presupuesto, tráfico, códigos HTTP, latencias p50/p95/p99, errores APM, dependencias del alta, rendimiento web y errores JavaScript |
| Dependencias y procesamiento | Consultas JDBC, conexiones y bloqueos PostgreSQL, Redis y AOF, salud de storage, outbox, lag/PEL, estado, edad y progreso de jobs, y capacidad retenida |
| Infraestructura y entrega | CPU, memoria, última muestra, réplicas, salidas fallidas, OOM e imagen observada frente a la imagen del release |

Todos tienen el selector **Ambiente**. DEV es el valor inicial. PROD depende de
la telemetría que habilite SNI-88. Los gráficos de SLO conservan siete días
aunque cambie el rango general. Sin resultados, comprobar la última muestra y
el volumen antes de interpretar un gráfico vacío. p95 y p99 son exploratorios
cuando hay pocas solicitudes. Los tableros se comparten en la cuenta con permiso
de lectura.

En un alta fallida, copiar el `request_id` de NGINX y buscar el Trace ID con:

```sql
FROM Transaction SELECT traceId, outcome, duration
WHERE appName = 'snippets-service (dev)' AND request.id = '<REQUEST_ID>'
SINCE 1 hour ago
```

Abrir esa traza y revisar los spans de validación, storage y ownership.
Cruzar con `Span.trace.id` y `Log.trace.id` según
[SNI-81](sni-81-apm-traces.md#consultas). Un span de transporte
`External/UnknownHost/JavaHttpClient/failed` requiere mirar su span padre y los
logs para saber si era Permissions o PrintScript. Para jobs, seguir
`correlation.id`, `event.id` y `job.id` en transacciones y logs tal como
describe [SNI-83](sni-83-background-signals.md#correlación).

### Despliegues y versiones

En Infraestructura y entrega, `image` es la imagen de la tarea, `expectedImage`
la del manifiesto que conoce el host y `imageState` su comparación. Contrastar
cambios de imagen y tareas fallidas con la hora y conclusión del último CD en
GitHub Actions. La condición de desvío espera cinco minutos para tolerar la
convergencia del rolling update. `unknown` requiere comprobar si el colector
tiene acceso al release.

Un fallo de CD antes de cambiar el host se detecta en el check fallido de
GitHub Actions. Las muestras del host solo cubren cambios que llegan a la VM.
Para diagnosticar una imagen atrasada, abrir el último CD del servicio:
[Infra](https://github.com/JJT-INGSIS/snippet-searcher-infra/actions),
[Snippets](https://github.com/JJT-INGSIS/snippets-service/actions),
[Permissions](https://github.com/JJT-INGSIS/permissions-service/actions),
[PrintScript](https://github.com/JJT-INGSIS/printscript-service/actions) o
[UI](https://github.com/JJT-INGSIS/snippet-searcher-ui/actions).

## SLI y objetivos

Ventana móvil de **7 días** y objetivos iniciales de DEV. El tablero muestra
el denominador, el mínimo y el presupuesto disponible, calculado como
`válidos × (1 - objetivo/100) - fallas`. Los resultados de los ensayos quedan
en la historia de DEV. Las ventanas de mantenimiento silencian avisos
y conservan datos y antecedentes. Cero muestras significa que no se puede
calcular disponibilidad. Con menos de 100 solicitudes de API o 25 resultados
de Cypress, el porcentaje y el presupuesto son orientativos. El último
resultado de Cypress se muestra con su fecha y duración. Las fallas por
categoría se cuentan aparte como historial de siete días.

| SLI | Definición | Objetivo | Interpretación |
| --- | --- | --- | --- |
| Disponibilidad HTTP de la API | Ingreso NGINX en rutas `api` y `executions`. Éxito 2xx, falla técnica 5xx. Excluir `/api/languages`, redirecciones y 4xx. Un stream abierto con 2xx certifica HTTP, y un error posterior se investiga en APM. Una VM sin ingreso la detectan los monitores públicos. | 99% | Con 100 solicitudes, presupuesto de 1 falla. Por debajo de 100, mostrar el volumen y tratar el porcentaje como exploratorio. |
| Disponibilidad del listado autenticado | `SnippetFunctionalCheck` con `environment='dev'` y `checkName='snippet-searcher-dev-functional-listing'`. Denominador `SUCCESS + FAILURE`. Solo SUCCESS es bueno. Cypress comprueba el fixture por el flujo real. | 96% | Cada seis horas se esperan alrededor de 28 slots en siete días continuos. Con 25 resultados se tolera una falla. Por debajo de 25, mostrar cobertura insuficiente y contrastar con la alerta de 13 h sin resultados. |

Con las consultas de verificación se observaron 160 HTTP válidos, 3 fallas
(98,125%) y p95 de 695 ms. El chequeo funcional tenía 5 resultados y el último
fue SUCCESS. Esa muestra incluye pruebas y queda por debajo del mínimo para
evaluar el objetivo. Para expresar cuánto más rápido se consumió presupuesto en
una ventana, dividir la proporción observada de fallas por el presupuesto
proporcional (0,01 API; 0,04 funcional). Con 160 solicitudes repartidas en una
semana y solo 5 checks funcionales, una alarma de burn rate sobre ventanas
cortas produciría saltos dominados por pocas muestras. Se documenta la fórmula
y se priorizan las alertas de disponibilidad y fallas técnicas sostenidas.

## Destinos y respuesta

- **Crítica** · workflow de disponibilidad DEV. Correo al equipo y push a
  Juanfran en aperturas y cierres.
- **Warning** · workflow de warnings DEV, solo correo al equipo. Los eventos
  de pérdida de señal pueden figurar como críticos en New Relic; se enrutan
  según la política.
- **Informativa** · conservar en tableros, logs y GitHub Actions. Una
  recuperación cierra el incidente asociado.
- Los dueños son referentes técnicos. Responde el integrante disponible.

Las condiciones nuevas reutilizan ambas políticas. Las reglas de UI, API, TLS
y listado de SNI-84/85 siguen en las políticas en que fueron creadas. En el
correo, abrir el incidente para ver la descripción de la condición y el
runbook. Un aviso de pérdida de señal indica ausencia de datos después de
haberlos recibido al menos una vez.

| Condición DEV | Nivel y destino | Responsable | Primer diagnóstico / criterio de recuperación |
| --- | --- | --- | --- |
| UI/API pública falla | Crítica · correo y push | Juanfran | Aplicación y experiencia. Abrir resultado, contrastar ambas rutas y revisar HTTPS, reglas de Azure, proxy o servicio según el resultado. Recuperación con check exitoso. |
| Certificado falla | Warning · correo | Juanfran | Aplicación y experiencia. Revisar conectividad, cadena y vencimiento en el resultado. Recuperación con check TLS exitoso. |
| Listado devuelve FAILURE / 13 h sin resultados | Crítica · correo y push | Juanfran | Aplicación y experiencia. Leer `failureCategory`; si falta señal revisar timer/reportador. Confirmar un SUCCESS y presencia del fixture. |
| PrintScript o otro servicio sin réplica (dos ventanas de 1 min) | Crítica · correo y push | Thiago | Infraestructura y entrega. Identificar servicio, imagen y tarea; si es PrintScript, revisar también alta y traza. Recuperar réplicas y operación real. |
| Storage de contenidos falla dos ventanas de 1 min | Crítica · correo y push | Thiago | Dependencias y procesamiento. Revisar probe, volumen y permisos. Recuperar lectura, escritura y comprobación del contenido. |
| VM sin SystemSample 5 min | Crítica · correo y push | Thiago | Infraestructura y entrega. Contrastar Azure y monitores públicos para distinguir caída de VM de agente caído. Recuperación con nueva muestra y endpoints sanos. |
| Consumidor atrasado: lag conocido >0 y edad elegible >300 s durante cinco ventanas de 1 min | Crítica · correo y push | Juanchi | Dependencias y procesamiento. Comprobar outbox, Redis y último worker. Recuperación al consumir y ver lag/edad a nivel normal. |
| Redis con entregas en PEL más de 60 s sin nueva entrega durante cinco ventanas de 1 min | Warning · correo | Juanchi | Dependencias y procesamiento. Revisar PEL, reclamos, ACK y progreso del job. Recuperación: la PEL se vacía o baja el idle. Confirmar ACK o avance; el reclamo reinicia el idle. |
| Colector Swarm ausente 10 min / muestreador sin outbox 5 min | Warning · correo | Thiago / Juanchi | Infraestructura y entrega / Dependencias y procesamiento. Distinguir deploy transitorio de colector detenido. Recuperación con muestras nuevas. |
| Outbox >60 s / RUNNING sin progreso >60 s / error del muestreador, cada uno sostenido 5 min | Warning · correo | Juanchi | Dependencias y procesamiento. Revisar escritura a Redis y reintentos, lease y trazas del job o el aspecto del muestreador. Recuperación con edad dentro del límite, avance o muestras sanas. |
| Poco espacio (<15% por 5 min), CPU ≥85% o memoria ≥90% por 10 min | Warning · correo | Thiago | Dependencias y procesamiento / Infraestructura y entrega. Identificar volumen o recurso, crecimiento, tareas y OOM. Recuperación al volver a la banda segura. |
| PostgreSQL con sesiones bloqueadas por 5 min | Warning · correo | Thiago | Dependencias y procesamiento. Identificar base, bloqueos y consultas. Recuperación con `blocked_sessions=0`. |
| Imagen distinta del release por 5 min | Warning · correo | Thiago | Infraestructura y entrega. Buscar CD, comparar digests y tareas. Recuperar rollout y comprobar `match`. |
| Dos POST con 5xx en 5 min; o >5% 5xx / >5% de solicitudes >2 s en 5 min con al menos 20 solicitudes válidas | Warning · correo | Juanchi | Aplicación y experiencia. Separar rechazo de negocio de falla técnica, abrir el request/traza y corregir dependencia. Recuperación con ventana representativa normal; comprobar una alta luego de un corte. |

Los umbrales de trabajos salen de la cadencia de SNI-83: un muestreo por
minuto, reclamo desde 30 s, pendiente del publicador normalmente de pocos
segundos. Cinco ventanas sobre el atraso elegible de cinco minutos implican
del orden de diez minutos desde que queda pendiente, más la agregación y la
entrega. Un despliegue puede interrumpir un minuto. El cálculo combina lag
con edad en la misma ventana; una medición desconocida queda sin valor. Para
la prueba de SNI-87 hay que esperar ambas etapas y reservar la ventana y la
cuota para restaurar.

La condición de PEL cubre mensajes que Redis ya entregó y sigue esperando
confirmar, incluso con lag cero o desconocido. SNI-83 observó reclamos
normales cerca de 30 s. Exigir más de 60 s de inactividad durante cinco
ventanas consecutivas evita avisos por reclamos transitorios. El muestreador
inspecciona un subconjunto acotado de la PEL y Redis reinicia el idle tras
cada reclamo. Para pendientes que se reclaman repetidamente, contrastar
con el progreso del job y los logs del consumidor.

Los umbrales de recursos anticipan agotamiento y toleran picos breves.
El umbral inicial de latencia de 2 s es casi tres veces el p95 de 695 ms medido.
El warning de latencia evalúa la proporción que supera 2 s. El mínimo de
20 observaciones evita que una sola solicitud abra la alerta de proporción.
Los monitores públicos y el chequeo autenticado siguen cubriendo caída en
momentos de bajo tráfico. Un 4xx esperado o un listado vacío de otra cuenta
no abre alertas de disponibilidad.

## Cobertura por dependencia

| Camino | Señal principal | Primera respuesta |
| --- | --- | --- |
| Navegador → DNS/TLS/proxy/UI | Checks públicos, certificado, HTTP de ingreso y Browser | Juanfran compara los monitores y abre el detalle de TLS, NGINX o UI según el resultado. |
| UI → Auth0 → listado | Evento funcional autenticado y categoría de resultado | Juanfran revisa login, callback o presencia del fixture según la categoría. Las credenciales quedan en el runner. |
| NGINX → Snippets / ejecución | HTTP por ruta, latencia, errores y réplicas | Juanchi toma el request ID, sigue APM y valida la operación que falló. |
| Snippets → Permissions / PrintScript | Spans HTTP, errores del alta y réplicas por servicio | Juanchi rastrea el tramo de la dependencia. Thiago comprueba tareas, DNS interno y release del destino. |
| Snippets / Permissions → cada base | Réplicas, conexiones y bloqueos por base, spans JDBC | Thiago identifica la base y revisa pool, conectividad, bloqueo o presión de disco. |
| Snippets → volumen de contenido | Probe de lectura/escritura/contenido, espacio y span de alta | Thiago revisa disponibilidad, permisos y espacio del volumen activo. |
| Publicador → Redis → consumidor → trabajo | Outbox, Redis/AOF, lag/PEL, progreso, reservas y trazas del trabajo | Thiago revisa Redis si el agente muestra fallo. Juanchi identifica si el evento se publicó, se entregó o dejó de progresar. |
| VM → New Relic | Frescura de SystemSample, Swarm y muestreador; monitores públicos | Thiago compara telemetría interna y externa para distinguir VM caída de colector detenido. |
| GitHub Actions → release en la VM | Resultado de CD, intervalos con más de una imagen y comparación real/esperada | Thiago abre el último CD y cruza versión, tareas y hora con el tablero. |

## Apagado planificado de DEV

Antes del apagado, programar una regla de silenciamiento con fin conocido
en **Alerts → Muting rules** para las condiciones de ambas políticas DEV.
Cubrir la VM, Swarm, muestreador, checks y funcionalidades. Revisar que
el vencimiento deje margen para arrancar VM y telemetría. Si se enciende antes,
comprobar SystemSample, Swarm, UI, API y check funcional, y luego terminar
el silencio. La situación de mantenimiento debe quedar visible en el
incidente. Para el ensayo de SNI-87, comprobar que las condiciones bajo
prueba quedan fuera del silencio y que ambos workflows están activos.

## Comprobación y entrega a SNI-87

1. Desde New Relic comprobar condición, ambiente, política y destino. Desde
   cada tablero, seleccionar DEV y revisar un intervalo con VM activa.
2. Para el consumidor, comparar el valor de la consulta de Terraform con
   el ensayo del 18/11 y con un intervalo sano. Para PrintScript,
   comprobar `desired` y `running` por separado: el corte a cero puede
   producir `0/0`.
3. El ensayo de incidente real, entrega al teléfono y restauración lo
   ejecuta [SNI-87](sni-87-failure-acceptance.md), incluyendo SNI-85 para
   listado. Registrar primera señal, alerta, aviso, diagnóstico y cierre.
4. Si el chequeo funcional no llega, buscar `SnippetFunctionalCheck` y el
   timer del runner. El histórico del listado no depende de `SyntheticCheck`.
   La instrumentación Browser mide la UI por separado.

## Verificación del 19/11/2026

- Terraform validado. NerdGraph aceptó las 52 consultas de condiciones,
  gráficos y SLO. Se crearon 17 condiciones, 3 tableros y 2 SLO.
  Un plan posterior con refresh devolvió cero cambios.
- El workflow crítico sigue habilitado con correo y push en apertura y cierre.
  Warnings conserva solo correo. Comprobadas las dos condiciones habilitadas
  de SNI-85 (IDs `69952989` y `69953021`).
- Al reprocesar la telemetría histórica del 18/11, la consulta de consumidor
  devolvió 323, 383, 443 y 503 s con el outbox en cero. Se observaron cuatro
  ventanas por encima de 300 s en la muestra disponible. Confirmar la quinta
  ventana y el disparo efectivo durante SNI-87.
- Condiciones para el ensayo: PrintScript `69984637` y consumidor
  `69984639`, ambas en política `8318071`.
- Tableros activos: [Aplicación y experiencia](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTkz),
  [Dependencias y procesamiento](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTky),
  [Infraestructura y entrega](https://one.newrelic.com/redirect/entity/ODcxODU1N3xWSVp8REFTSEJPQVJEfGRhOjEzNTk1OTkx).
  Los SLO HTTP y funcional quedaron asociados a Snippets DEV con IDs
  `2916897` y `2916896`, respectivamente.
- Las comprobaciones se ejecutaron sobre la cuenta New Relic con el historial
  disponible. La prueba con corte controlado y confirmación de recepción
  corresponde a SNI-87.

Documentación de New Relic: [condiciones NRQL](https://docs.newrelic.com/docs/alerts/create-alert/create-alert-condition/create-nrql-alert-conditions/),
[variables de tableros](https://docs.newrelic.com/docs/query-your-data/explore-query-data/dashboards/dashboard-template-variables/),
[niveles de servicio](https://docs.newrelic.com/docs/service-level-management/create-slm/).
