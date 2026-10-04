# Ejecución interactiva — US10 futura

PrintScript conserva el estado transitorio del intérprete. `snippets-service` autoriza el inicio, asocia la ejecución al usuario y transmite outputs y solicitudes de input mediante `Language`, su módulo interno.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as Storage FUTURO
    participant L as Language interno
    participant PS as printscript-service

    Note over UI,PS: Workflow futuro: ejecución interactiva de US10
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
    Note over S,ST: Uso futuro: recuperar contenido de esa revisión
    S->>L: Iniciar ejecución con código y versión
    L->>PS: Iniciar por HTTP
    PS-->>L: Ejecución iniciada o error
    L-->>S: Resultado de inicio
    break Código inválido, versión no soportada o fallo técnico
        S-->>UI: Error de inicio
    end
    S->>S: Asociar ejecución con actor y snippet
    S-->>UI: Ejecución iniciada

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

- **Requerimiento:** US10 necesita outputs e inputs durante la ejecución. La forma concreta del canal incremental debe acordarse con la UI; una respuesta final única no cumple el flujo.
- **Propuestas:** permitir ejecución a quien tiene acceso, fijar la revisión ejecutada y verificar la asociación usuario/ejecución al recibir inputs. No se requiere persistir sesiones como datos de negocio ni reanudarlas tras reiniciar el intérprete.
- **Errores:** distinguir error del programa, caída del servicio y límite de ejecución; informar terminación sin dejar a la UI esperando indefinidamente. Definir límites de tiempo, espera de input y salida antes de implementar.

[Volver a la referencia de arquitectura](../README.md)
