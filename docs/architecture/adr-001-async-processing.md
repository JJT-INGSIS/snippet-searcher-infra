# ADR-001 — HTTP síncrono y procesamiento por eventos con Redis Streams

- **Estado:** aceptada; implementación pendiente.
- **Fecha:** 29 de octubre de 2026.
- **Ticket:** [SNI-27](https://linear.app/snippet-searcher/issue/SNI-27/t2-a1-decidir-comunicacion-sincrona-y-asincrona-y-alcance-de-redis).
- **Aprobación:** Juan Francisco Siaba confirmó en el chat de SNI-27 la arquitectura híbrida, los tres casos asíncronos y el uso de eventos de dominio, Redis Streams, Consumer Groups y Transactional Outbox. El 29/10 autorizó documentar y cerrar esta decisión; la creación de tickets y la implementación quedan para después.

## Contexto

El comportamiento por defecto es HTTP síncrono: permite confirmar el resultado de
operaciones puntuales con menos estados, dependencias y carga operativa. Crear y
actualizar snippets exige validar el parser y confirmar la persistencia necesaria;
una falla de storage o Permissions conserva el tratamiento actual de resultados
inciertos. La ejecución incremental US9/10 tiene un contrato propio por HTTP y
NDJSON, separado de la entrega durable de trabajos.

Hay tres excepciones: cambios de reglas de formato/lint que afectan muchos
snippets, revalidación al activar un parser y ejecución automática de tests tras
actualizar. Su duración depende del trabajo acumulado. Deben continuar o recuperar
progreso ante fallos sin hacer depender la operación principal de su finalización.

## Decisión

Adoptar **HTTP síncrono + Event-Driven Architecture + Redis Streams** exclusivamente
para los tres casos acordados. Los eventos describen hechos confirmados. Snippets
registra cambio, trabajo raíz e intención de publicar en una transacción local de
PostgreSQL; un publicador entrega el outbox a Redis después del commit.

| Caso de uso | Mecanismo y respuesta | Responsable | Tratamiento de fallos |
| --- | --- | --- | --- |
| Crear, actualizar, validar, listar, consultar, compartir y autorizar | HTTP síncrono; éxito sólo según el contrato vigente | Snippets, Language, storage y Permissions en sus fronteras actuales | Errores explícitos; conservar idempotencia de creación e incertidumbre de escrituras |
| Configurar reglas de formato/lint | HTTP síncrono; configuración confirmada, reprocesamiento pendiente | Snippets; PrintScript valida las capacidades del lenguaje | Configuración rechazada o commit fallido no genera evento |
| US12: cambio de formato | `FormattingRulesChanged`; progreso y resultado posteriores | Workers de Snippets → Language → PrintScript HTTP | Avance por snippet, reintentos acotados y publicación condicionada a vigencia |
| US15: cambio de lint | `LintRulesChanged`; diagnósticos posteriores | Workers de Snippets → Language → PrintScript HTTP | Incumplimiento y falla técnica diferentes; progreso parcial |
| Activación de parser | Activación administrativa explícita y síncrona; `ParserVersionActivated` para revalidar | Snippets registra activación; workers coordinan validación HTTP | Conservar snippets inválidos y diagnósticos; un deploy no dispara la revalidación |
| US16: tests tras actualizar | Update confirmado; `SnippetUpdated` ejecuta los tests del snapshot guardado | Snippets coordina y compara; PrintScript ejecuta | Resultados no revierten el guardado; un inicio incierto se reconcilia sin repetición automática |
| US8–10: definiciones y ejecución manual/interactiva | Definiciones por HTTP; sesiones y NDJSON según contrato existente | Snippets y PrintScript | Conservar permisos, límites, cancelación, replay y tratamiento de incertidumbre |

Los consumidores usan Consumer Groups y entrega **at-least-once**, con deduplicación
persistente. PostgreSQL es la fuente de verdad de trabajos, progreso y resultados.
Inicialmente habrá un stream y un grupo por ambiente, con handlers explícitos por
tipo de evento dentro de Snippets. Otro consumidor funcional independiente tendrá
su propio grupo cuando se justifique. `SnippetUpdated` sólo dispara US16.

El [diseño mínimo](async-processing-design.md) define eventos, transacciones, ACK,
recuperación, revisiones, backpressure, identidad y aceptación futura.

## Responsabilidades y límites

- **Snippets:** publica hechos, coordina trabajos y persiste progreso/resultados; los workers son parte de esta aplicación, sin microservicios por consumidor.
- **PrintScript:** mantiene capacidades de lenguaje por HTTP. Language sigue siendo interno de Snippets. PrintScript no conoce Redis, ownership ni las expectativas de tests.
- **Permissions:** conserva ownership y autorización; cada servicio accede sólo a su base.
- **UI:** consulta progreso por polling autorizado en Snippets, separando operación confirmada de procesamiento pendiente/completado/fallido.
- **Infra:** incorpora Redis persistente al Compose y al stack existente de cada ambiente, en las mismas VMs y sin exposición pública. Inventario, probes, secretos y CD deben admitirlo antes de activarlo.

No se implementa Event Sourcing, no se reemplaza NDJSON y no se agregan reacciones
de lint/formato a cada `SnippetUpdated`. La validación sintáctica al guardar sigue
siendo síncrona. Los derivados individuales de lint/formato, cuando se implementen,
siguen síncronos; esta ADR no amplía las tres excepciones.

## Alternativas consideradas

| Alternativa | Beneficio | Motivo para descartarla en estas excepciones |
| --- | --- | --- |
| Todo síncrono | Menos infraestructura y estados | Ata la respuesta a lotes o a múltiples programas; no resuelve recuperación/progreso por sí sola |
| Trabajo durable sólo en PostgreSQL | Aprovecha la base y evita operar un broker | Viable y más simple de operar; se elige Redis Streams para la distribución por grupos y el aprendizaje del mecanismo provisto por la cátedra, aceptando su costo |
| Redis sin outbox | Menos componentes de aplicación | Deja una ventana entre confirmar el cambio y publicar el evento |
| Tareas sólo en memoria o auto-ACK | Inicio sencillo | Un reinicio puede perder trabajos; recibir un mensaje no prueba procesamiento persistido |

## Consecuencias y condiciones de revisión

- **Desacoplamiento temporal:** la operación principal confirma su cambio sin esperar tareas secundarias. Redis puede estar temporalmente caído y quedar publicación pendiente en PostgreSQL.
- **Resiliencia:** outbox, progreso y recuperación permiten retomar trabajos confirmados; se requiere operar y probar esos mecanismos.
- **Escalabilidad y backpressure:** Consumer Groups distribuye entrega; el ritmo real se limita según capacidad de Snippets/PrintScript. Agregar workers no aumenta por sí solo esa capacidad.
- **Consistencia eventual:** resultados pueden llegar después o quedar obsoletos; la UI debe mostrar su estado y revisión.
- **Orquestación y coreografía:** los eventos habilitan reacciones; Snippets coordina cada trabajo mediante las capacidades existentes.
- **Costos aceptados:** Redis, persistencia, reintentos, duplicados, trazabilidad, retención, recuperación y mantenimiento adicionales. Los snapshots y la auditoría consumen almacenamiento.
- No se promete exactly-once, orden global, consistencia inmediata, alta disponibilidad automática ni reanudación garantizada de programas PrintScript.

Revisar límites, partición de consumidores y despliegue si aumentan las réplicas o
la carga. Cambiar de transporte exigiría sustituir publicador/consumidores y
coordinar eventos pendientes; datos y resultados permanecen en PostgreSQL. Las
políticas de retención y contratos públicos de progreso se concretarán en el
trabajo posterior, sin hacer de esta ADR una implementación.

## Cierre y trabajo posterior

SNI-27 entrega esta ADR, el diseño mínimo y los flujos alineados. No exige desplegar
Redis ni verificar las funcionalidades futuras. Los frentes y dependencias están
delimitados en el [diseño](async-processing-design.md#trabajo-posterior), sin crear
issues nuevos ni bloquear el cierre actual de US8–10 o los flujos síncronos.

## Fundamentos

- [AWS: importancia de arquitecturas asíncronas](https://aws.amazon.com/es/blogs/aws-spanish/importancia-de-arquitecturas-asincronas-en-los-sistemas-distribuidos/): desacoplamiento y control del ritmo de procesamiento.
- [AWS: Transactional Outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html): escritura dual, rollback y duplicados.
- [Spring Data Redis Streams](https://docs.spring.io/spring-data/redis/reference/redis/redis-streams.html): Consumer Groups, pendientes y ACK explícito después del procesamiento.
- [Redis: XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/) y [persistencia](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/): recuperación y límites de durabilidad.
- [Ejemplo de la cátedra, revisión citada en SNI-27](https://github.com/austral-ingsis/class-redis-streams/tree/c22b911154ec18f438eec96d16312a30878cc177): referencia didáctica, no garantía de recuperación por copiar auto-ACK.
