# Linting y reprocesamiento masivo

[Volver al índice de arquitectura](../README.md)

US14 configura reglas por HTTP síncrono; US15 evalúa snippets en segundo plano con
recuperación. Los resultados alimentan listado y detalle. La [ADR-001 / SNI-27](../adr-001-async-processing.md)
aprueba `LintRulesChanged` + outbox + Redis Streams; el runtime es **futuro**.
Garantías comunes en el [diseño mínimo](../async-processing-design.md).

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant O as Publicador outbox en snippets - FUTURO
    participant R as Redis Streams - FUTURO
    participant B as Proceso de fondo en snippets - FUTURO
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

        O->>S: Leer outbox confirmado
        O->>R: Publicar LintRulesChanged
        B->>R: Leer mediante Consumer Group
        R-->>B: Evento
        B->>S: Deduplicar y retomar trabajo durable
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
            L->>PS: HTTP con código, versión y reglas
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
        B->>R: ACK después de persistir estado terminal
    end
```

- **Propuesta:** configuración por owner, lenguaje y versión; sólo se procesan sus snippets propios. El catálogo y significado de reglas pertenecen a PrintScript; la selección y los resultados persistidos pertenecen a snippets-service.
- **Requerimiento:** linting informa infracciones. **Propuesta:** distinguir cumple, incumple, pendiente y no evaluado por error. Una caída del procesador no significa incumplimiento; linting no modifica el código ni reemplaza la validación del parser.
- **Aprobado SNI-27:** progreso en PostgreSQL, outbox y Consumer Groups en Redis Streams; workers dentro de Snippets con HTTP por elemento. Caída de Permissions deja trabajo recuperable sin ACK prematuro; resultados superados no se publican como actuales. Se usa la abstracción de storage existente. El diagrama simplifica reentregas: aplicar deduplicación, reservas y recuperación del diseño común.
