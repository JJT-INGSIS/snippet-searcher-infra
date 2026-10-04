# Tests: creación y ejecución

`snippets-service` conserva las definiciones y compara salidas reales con esperadas. `Language`, módulo interno, delega la ejecución a PrintScript por HTTP; los tests automáticos se ejecutan después de confirmar una actualización.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as Storage FUTURO
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
        S->>S: Comparar outputs y persistir resultado con revisión
        S-->>UI: Aprobado, fallido o no completado
    else Tests automáticos - US16
        Note over S: La actualización autorizada ya fue confirmada
        S->>S: Fijar revisión guardada y obtener sus tests
        Note over S,ST: Uso futuro: recuperar el contenido confirmado
        loop Cada test del snippet
            S->>L: Ejecutar código con inputs
            L->>PS: HTTP con código, versión e inputs
            PS-->>L: Outputs o error
            L-->>S: Resultado
            S->>S: Comparar y guardar resultado sin revertir update
        end
        S-->>UI: Estado del guardado separado del resultado de tests
    end
```

- **Requerimientos:** crear un test requiere ser owner y admite expectativas que no se cumplan; ejecutar manualmente requiere acceso y entrega output incremental en la futura US9. US16 ejecuta todos los tests tras actualizar, sin revertir el guardado.
- **Propuestas:** fijar revisión de código y definición del test; comparar secuencias respetando orden y cantidad. La normalización de outputs y el alcance de “un test a la vez” deben acordarse con la UI.
- **Errores y persistencia:** una diferencia de outputs es test fallido; una caída o timeout deja la ejecución no completada. Los resultados viven en BD snippets y nunca se muestran como actuales si corresponden a otra revisión. La ejecución postcommit puede ser síncrona si es acotada; pasarla a segundo plano exige registrar trabajo pendiente durable.

[Volver a la referencia de arquitectura](../README.md)
