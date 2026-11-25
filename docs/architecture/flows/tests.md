# Tests: creación y ejecución

El [contrato de ejecución](../execution-contract.md) describe el canal NDJSON,
el snapshot y la comparación de resultados. Los tests automáticos usan
`SnippetUpdated`, outbox y Redis Streams al confirmar una actualización
según el [modelo asíncrono](../async-processing-design.md).

`snippets-service` conserva las definiciones y compara salidas reales con esperadas. `Language`, módulo interno, delega la ejecución a PrintScript por HTTP; los tests automáticos se ejecutan después de confirmar una actualización.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as SnippetContentStorage
    participant O as Publicador outbox en Snippets
    participant R as Redis Streams
    participant B as Worker de Snippets
    participant L as Language interno
    participant PS as printscript-service

    alt Crear test
        UI->>S: Snippet ID, inputs y outputs esperados ordenados
        S->>S: Comprobar existencia del snippet
        break Snippet inexistente
            S-->>UI: Error sin guardar test
        end
        S->>P: Verificar ownership por HTTP
        P-->>S: Decisión
        break Sin ownership o permisos no verificables
            S-->>UI: Error sin guardar test
        end
        S->>S: Validar estructura y persistir en BD snippets
        S-->>UI: Test creado sin exigir que pase
    else Ejecutar test manual
        UI->>S: Ejecutar test
        S->>S: Comprobar snippet y pertenencia del test
        break Recurso inexistente
            S-->>UI: Error sin ejecutar
        end
        S->>P: Verificar acceso por HTTP
        P-->>S: Decisión
        break Sin acceso o permisos no verificables
            S-->>UI: Error sin recuperar ni ejecutar contenido
        end
        S->>S: Fijar revisión del código y definición del test
        S->>ST: Leer el original asociado al snapshot
        ST-->>S: Código
        S->>L: Ejecutar código con inputs del test
        L->>PS: HTTP con código, versión e inputs
        loop Cada output producido
            PS-->>L: Output ordenado
            L-->>S: Output
            S-->>UI: Output incremental
        end
        PS-->>L: Terminación o error
        L-->>S: Resultado de ejecución
        S->>S: Comparar outputs y asociar resultado al snapshot
        S-->>UI: Aprobado, fallido o no completado
    else Tests automáticos - US16
        Note over S: Update autorizado y validado por el flujo síncrono actual
        S->>S: Commit de revisión, snapshot/tests, trabajo y outbox
        S-->>UI: Update confirmado, procesamiento pendiente
        O->>S: Leer outbox confirmado
        O->>R: Publicar SnippetUpdated
        B->>R: Leer mediante Consumer Group
        R-->>B: Evento
        B->>S: Deduplicar y recuperar trabajo/snapshot durable
        B->>ST: Leer referencia de código retenida
        ST-->>B: Código del update confirmado
        loop Cada test del snapshot
            B->>L: Ejecutar código con inputs y capacidad disponible
            L->>PS: Operación durable con código, versión e inputs
            PS-->>L: Outputs o error
            L-->>B: Resultado
            B->>S: Comparar y persistir resultado/progreso sin revertir update
        end
        B->>S: Persistir progreso y estado del trabajo
        opt Estado terminal o recuperación UNKNOWN persistida
            B->>R: ACK de la entrega
        end
        UI->>S: Polling de progreso autorizado
        S-->>UI: Estado del trabajo separado del guardado
    end
```

El dueño administra los tests. Un usuario con acceso puede ejecutar un test
del snippet. La comparación usa la secuencia exacta de outputs. Una
discrepancia tras terminar normalmente se distingue de una falla técnica.

Los tests automáticos usan el código y las definiciones del snapshot del
update. Una edición posterior invalida su vigencia para el resultado actual.
El guardado del snippet se confirma en una operación separada del resultado
del lote.

[Volver a la referencia de arquitectura](../README.md)
