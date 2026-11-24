# ADR-001 · HTTP y procesamiento asíncrono

## Decisión

Usar HTTP para operaciones puntuales y Redis Streams con grupos de consumidores
para lotes cuyo trabajo puede continuar después de responder al usuario.
Snippets confirma cambios de reglas de formato o lint, activaciones de parser y
ediciones con tests automáticos mediante una transacción de PostgreSQL que
incluye el trabajo y el outbox. El publicador y el consumidor se ejecutan en
Snippets. PrintScript procesa operaciones de lenguaje por HTTP.

## Motivo y costo

Separar el lote del pedido HTTP permite devolver el guardado confirmado, limitar
el trabajo simultáneo y recuperar el progreso tras una interrupción. Redis
agrega una dependencia operativa y permite reentregas. PostgreSQL conserva el
estado de negocio, las reservas y los resultados. La aplicación debe tolerar una
publicación repetida y comprobar la vigencia antes de exponer el resultado.

[Contratos, vigencia y recuperación](async-processing-design.md) ·
[Configuración y diagnóstico de Redis](../operations.md#datos-y-redis).
