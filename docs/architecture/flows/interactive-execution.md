# Ejecución interactiva

El [contrato de ejecución](../execution-contract.md) describe las dos APIs,
los eventos y los límites. La UI recibe NDJSON con `fetch` y usa POST para
inputs y cancelación.

PrintScript conserva el estado transitorio del intérprete. `snippets-service` autoriza el inicio, asocia la ejecución al usuario y transmite outputs y solicitudes de input mediante `Language`, su módulo interno.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as SnippetContentStorage
    participant L as Language interno
    participant PS as printscript-service

    UI->>S: Iniciar ejecución del snippet
    S->>S: Comprobar existencia
    break Snippet inexistente
        S-->>UI: Error sin ejecutar
    end
    S->>P: Verificar acceso por HTTP
    P-->>S: Decisión
    break Sin acceso o permisos no verificables
        S-->>UI: Error sin recuperar ni procesar contenido
    end

    S->>S: Fijar revisión del código
    S->>ST: Leer el contenido de la revisión seleccionada
    ST-->>S: Código
    S->>L: Iniciar ejecución con código y versión
    L->>PS: Iniciar por HTTP
    PS-->>L: Ejecución iniciada o error
    L-->>S: Resultado de inicio
    break Código inválido, versión no soportada o fallo técnico
        S-->>UI: Error de inicio
    end
    S->>S: Asociar ejecución con actor y snippet
    S-->>UI: Descriptor de la ejecución
    UI->>S: Abrir canal de eventos con cursor

    loop Mientras la ejecución está activa
        alt Se produce una salida
            PS-->>L: Output
            L-->>S: Output
            S-->>UI: Mostrar output
        else Se requiere input
            PS-->>L: Solicitud de input
            L-->>S: Solicitud de input
            S-->>UI: Solicitar valor
            UI->>S: Input para ejecución
            S->>S: Verificar actor de la sesión
            break Actor no autorizado para esa ejecución
                S-->>UI: Rechazar input sin entregarlo al intérprete
            end
            S->>L: Entregar input autorizado
            L->>PS: Continuar con valor por HTTP
        end
    end

    PS-->>L: Finalización o error
    L-->>S: Estado final
    S-->>UI: Ejecución terminada o interrumpida
```

Cerrar el stream permite una reconexión acotada por cursor. La cancelación
es una operación separada. La ejecución conserva el snapshot del inicio y
distingue errores del programa, límites y fallas técnicas.

[Volver a la referencia de arquitectura](../README.md)
