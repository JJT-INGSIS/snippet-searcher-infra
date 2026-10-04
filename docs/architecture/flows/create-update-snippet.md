# Creación y actualización de snippets

[Volver al índice](../README.md)

**Fuente:** US1–4. Archivo y editor comparten el mismo caso de uso. La secuencia de alta provisional y el lint inicial síncrono son propuestas; el storage es una dependencia futura.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant L as Language interno
    participant PS as printscript-service
    participant ST as Storage FUTURO

    UI->>S: Crear o actualizar con datos y código
    opt Actualización
        S->>S: Comprobar existencia y revisión vigente
        break Snippet inexistente
            S-->>UI: Error de inexistencia
        end
        S->>P: Verificar ownership del actor
        P-->>S: Decisión o error técnico
        break Sin permiso o permisos indisponibles
            S-->>UI: Error sin modificar el snippet
        end
    end

    S->>L: Validar candidato con lenguaje y versión
    L->>PS: Código y versión por HTTP
    PS-->>L: Validación o diagnósticos
    L-->>S: Resultado normalizado
    break Código inválido, versión no soportada o fallo técnico
        S-->>UI: Rechazo o error técnico, sin confirmar cambios
    end

    S->>L: Lintear con reglas aplicables
    L->>PS: Código, versión y reglas por HTTP
    PS-->>L: Cumplimiento, infracciones o error técnico
    L-->>S: Resultado
    break Fallo técnico de lint antes del guardado
        S-->>UI: No se pudo completar la operación
    end

    S->>S: Preparar alta provisional o nueva revisión
    S-->>ST: Uso futuro al guardar contenido
    ST-->>S: Resultado del uso de storage
    break Fallo de persistencia
        S->>S: Conservar estado recuperable y revisión anterior
        S-->>UI: Guardado no confirmado
    end

    opt Creación
        S->>P: Registrar owner para snippet ID, sin duplicarlo
        P->>P: Persistir en BD permissions
        P-->>S: Ownership confirmado o error
        break Fallo al registrar ownership
            S->>S: Mantener alta provisional fuera de consultas
            S-->>UI: Alta no confirmada
        end
    end

    S->>S: Confirmar revisión activa en BD snippets
    alt Confirmación exitosa
        opt Actualización
            S->>S: Disparar todos los tests después del commit
        end
        S-->>UI: Guardado confirmado y estados de procesamiento
    else Conflicto de revisión o fallo de persistencia
        S->>S: Preservar estado previo y recuperar operación parcial
        S-->>UI: Operación no confirmada
    end
```

- La validación del parser debe devolver regla, línea y columna cuando el código es inválido. Las infracciones de lint no impiden guardar un código válido.
- No hay transacción distribuida entre snippets, permissions y storage. La recuperación exacta del contenido queda pendiente del contrato de storage; no se asume atomicidad ni versionado del bucket.
- El update valida el candidato completo, incluso si cambia lenguaje/versión. Los [tests automáticos](./tests.md) no revierten el guardado y los resultados de revisiones anteriores dejan de ser actuales.
