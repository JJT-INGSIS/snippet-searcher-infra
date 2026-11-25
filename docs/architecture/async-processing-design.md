# Procesamiento asíncrono

[ADR-001](adr-001-async-processing.md) · [Operación](../operations.md#datos-y-redis)

| Evento | Alcance | Resultado |
| --- | --- | --- |
| `FormattingRulesChanged` | Snippets propios del dueño para un lenguaje y versión | Variante formateada, con el original intacto |
| `LintRulesChanged` | Mismo alcance por dueño, lenguaje y versión | Cumplimiento y diagnósticos |
| `ParserVersionActivated` | Ámbito administrativo por lenguaje y versiones | Revalidación de código existente |
| `SnippetUpdated` | Snippet editado y snapshot del trabajo | Resultado de los tests automáticos del update |

## Entrega y recuperación

1. Snippets confirma el cambio y registra trabajo y outbox en PostgreSQL en la
   misma transacción. El usuario puede consultar después el progreso autorizado.
2. El publicador entrega el evento por Redis Streams. La entrega puede repetirse
   y el consumidor contrasta el evento con el trabajo durable antes de procesar.
3. El consumidor toma el trabajo con una reserva y persiste el avance por
   elemento. Resuelve el ACK mediante el estado durable. Un fallo transitorio
   recuperable puede dejar pendiente la entrega. Un estado `UNKNOWN` persistido
   puede confirmar la entrega de Redis y seguir reconciliándose desde PostgreSQL.
4. El procesamiento remoto durable utiliza un ID de operación y revisión de
   procesador. Si una respuesta es incierta, se reconcilia el estado de la
   operación antes de repetir trabajo o liberar su reserva.

## Snapshots, selección y vigencia

El resultado se vincula al contenido, configuración y revisión de procesador
que correspondan a su tipo. Los cambios posteriores pueden reemplazar o volver
obsoleto un trabajo. El worker vuelve a verificar las referencias al publicar,
y las consultas vuelven a comprobar vigencia antes de presentar resultados.
El repositorio de Snippets contiene los contratos de
[outbox](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/background-outbox.md),
[consumo](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/background-consumer.md)
y [tests automáticos](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/automatic-tests.md).

El despliegue de una versión de PrintScript por sí solo no encola una
revalidación. La activación requiere una acción operativa explícita y comprobable.
Los detalles de ejecución interactiva y del canal NDJSON están en el
[contrato de ejecución](execution-contract.md).
