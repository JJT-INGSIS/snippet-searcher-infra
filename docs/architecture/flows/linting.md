# Linting y reprocesamiento masivo

[Volver al índice de arquitectura](../README.md)

US14 configura reglas por HTTP síncrono; US15 evalúa snippets en segundo plano con
recuperación. Los resultados alimentan listado y detalle. El evento
`LintRulesChanged` usa outbox y Redis Streams según el
[modelo de procesamiento asíncrono](../async-processing-design.md).

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant O as Publicador outbox en Snippets
    participant R as Redis Streams
    participant B as Worker de Snippets
    participant ST as SnippetContentStorage
    participant L as Language interno
    participant PS as printscript-service

    UI->>S: Cambiar reglas de linting
    S->>L: Validar selección para lenguaje y versión
    L->>PS: Comprobar reglas predefinidas
    PS-->>L: Configuración admitida o errores
    L-->>S: Resultado

    alt Configuración inválida o servicio indisponible
        S-->>UI: Error, conservar configuración anterior
    else Configuración admitida
        S->>S: Commit de configuración, revisión, trabajo y outbox
        break Fallo de persistencia local
            S-->>UI: Cambio de reglas no confirmado
        end
        S-->>UI: Configuración guardada, evaluación pendiente
        Note over UI,S: Una selección sin cambios no crea un lote nuevo

        O->>S: Leer outbox confirmado
        O->>R: Publicar LintRulesChanged
        B->>R: Leer mediante Consumer Group
        R-->>B: Evento
        B->>S: Retomar trabajo durable y comprobar revisión de reglas
        S->>P: Obtener IDs propios del usuario
        P-->>S: IDs o error transitorio
        break No se pudieron consultar los permisos
            S->>S: Conservar trabajo pendiente para reintentar
        end
        S->>S: Seleccionar lenguaje y versión afectados
        S-->>B: Elementos pendientes y revisión de reglas

        loop Cada snippet pendiente
            B->>S: Obtener revisión y metadatos
            B->>ST: Recuperar revisión de contenido
            ST-->>B: Código
            B->>L: Lintear con reglas del trabajo
            L->>PS: Operación durable con código, versión, reglas y revisión del procesador
            PS-->>L: Cumplimiento, infracciones o error
            L-->>B: Resultado

            alt Evaluación exitosa y código y reglas vigentes
                B->>S: Guardar estado, diagnósticos y progreso en BD snippets
            else Código o reglas cambiaron
                B->>S: Descartar resultado y dejar evaluación vigente pendiente
            else Fallo individual
                B->>S: Guardar error, reintentar o saltar y continuar
            end
        end
        B->>S: Registrar finalización o errores parciales
        opt Estado terminal o recuperación UNKNOWN persistida
            B->>R: ACK de la entrega
        end
    end
```

- Las reglas se guardan por dueño, lenguaje y versión. Se evalúan los snippets
  propios de ese alcance y sólo se exponen resultados vigentes.
- Una falla técnica se distingue de una infracción. El lint conserva el código
  original. PrintScript conoce el catálogo y Snippets persiste el resultado.
- La evaluación se recupera desde el trabajo durable y verifica vigencia al
  publicar, incluyendo la revisión de código, reglas y procesador.
