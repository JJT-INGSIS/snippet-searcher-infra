# Tests: creación y ejecución

US8–10 se precisan en el [contrato SNI-45](../execution-contract.md).
Canal aprobado: NDJSON con `fetch`, inputs mediante POST, snapshot y comparación.
US16 permanece fuera de SNI-45 y usa la [ADR-001 / SNI-27](../adr-001-async-processing.md):
`SnippetUpdated`, outbox y Redis Streams después de confirmar una actualización.
Es diseño futuro; no acredita workers ni aceptación funcional integrada.

`snippets-service` conserva las definiciones y compara salidas reales con esperadas. `Language`, módulo interno, delega la ejecución a PrintScript por HTTP; los tests automáticos se ejecutan después de confirmar una actualización.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as SnippetContentStorage
    participant O as Publicador outbox en snippets - FUTURO
    participant R as Redis Streams - FUTURO
    participant B as Worker de Snippets - FUTURO
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
    else Ejecutar test manual - US9 FUTURO
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
        Note over S,ST: Uso futuro: recuperar contenido de esa revisión
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
            L->>PS: HTTP con código, versión e inputs
            PS-->>L: Outputs o error
            L-->>B: Resultado
            B->>S: Comparar y persistir resultado/progreso sin revertir update
        end
        B->>S: Persistir estado terminal del trabajo
        B->>R: ACK explícito
        UI->>S: Polling de progreso autorizado
        S-->>UI: Estado del trabajo separado del guardado
    end
```

- **Requerimientos:** crear un test requiere ser owner y admite expectativas que no se cumplan; ejecutar manualmente requiere acceso y entrega output incremental en la futura US9. US16 ejecuta todos los tests tras actualizar, sin revertir el guardado.
- **Contrato US8–10 aprobado por Thiago:** snapshot coherente de código y definición; comparación exacta de secuencias, sin normalización. Una ejecución activa por actor y cuatro globales inicialmente, con un coordinador por servicio y sin cola. Ver detalles y trade-offs en SNI-45; no son capacidades runtime ya verificadas.
- **Errores y persistencia:** diferencia de outputs tras finalización normal es test fallido; falla técnica o inicio incierto es otro resultado. El canal del intérprete conserva retención acotada; no confundirla con auditoría de negocio. SNI-48 tiene historial durable interno aprobado y PR #47 en revisión al consultar Linear el 29/10/2026; verificar integración antes de reutilizarlo.
- **Aprobado SNI-27 / US16 futuro:** cada update confirmado conserva trabajo y snapshot durable de código/tests. Una edición posterior puede borrar el blob activo anterior: retener la referencia necesaria hasta completar el trabajo. Resultados históricos no se presentan como actuales. Reentregar un evento no autoriza repetir un inicio PrintScript incierto. Backpressure, ACK y recuperación están en el [diseño mínimo](../async-processing-design.md).

[Volver a la referencia de arquitectura](../README.md)
