# Creación y actualización de snippets

[Volver al índice](../README.md)

US1–4 permiten guardar código del editor o de un archivo. Ambos usan los
contratos de creación y actualización de Snippets.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant PS as PrintScript por Language
    participant ST as SnippetContentStorage

    UI->>S: Crear o actualizar con datos y código
    opt Actualización
        S->>P: Verificar ownership del actor
        P-->>S: Decisión
    end
    S->>PS: Validar código con lenguaje y versión
    PS-->>S: Validación o diagnósticos
    break Permiso denegado, código inválido o falla técnica
        S-->>UI: Error sin confirmar la escritura
    end
    opt Creación
        S->>S: Reservar el alta con la clave de idempotencia
    end
    S->>ST: Guardar el contenido candidato
    ST-->>S: Referencia o error
    opt Creación
        S->>P: Registrar owner del snippet
        P-->>S: Ownership confirmado o error
    end
    alt Escritura confirmada
        S->>S: Confirmar la referencia en PostgreSQL
        opt Actualización con trabajo automático
            Note over S: El update y el trabajo con outbox se registran juntos
        end
        S->>PS: Evaluar lint del código guardado con las reglas aplicables
        PS-->>S: Resultado de lint o falla técnica
        S-->>UI: Guardado confirmado
    else Escritura interrumpida o rechazada
        S-->>UI: Error o resultado incierto según la operación
    end
```

Un alta parcial queda fuera de las consultas hasta confirmarse. El mismo
pedido de creación puede retomarse con la misma identidad y clave de
idempotencia. En un update, la confirmación comprueba la revisión que se está
reemplazando. PostgreSQL, Permissions y storage tienen transacciones separadas.
Las infracciones de lint y los [tests automáticos](tests.md) no revierten el
guardado confirmado.
