# Formatting y reprocesamiento masivo

[Volver al índice de arquitectura](../README.md)

US11 configura reglas por HTTP síncrono; US12 reprocesa sin hacer esperar al usuario
y con recuperación. US13 conserva original y formateado. La [ADR-001 / SNI-27](../adr-001-async-processing.md)
aprueba `FormattingRulesChanged` + outbox + Redis Streams; el runtime es **futuro**.
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

    UI->>S: Cambiar reglas de formatting
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
        S-->>UI: Configuración guardada, procesamiento pendiente

        O->>S: Leer outbox confirmado
        O->>R: Publicar FormattingRulesChanged
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
            B->>ST: Recuperar revisión original retenida
            ST-->>B: Contenido
            B->>L: Formatear con reglas del trabajo
            L->>PS: HTTP con código, versión y reglas
            PS-->>L: Código formateado o error
            L-->>B: Resultado

            alt Procesamiento exitoso y resultado vigente
                B->>ST: Conservar contenido formateado
                B->>S: Publicar derivado sólo si siguen vigentes código y reglas
                S->>S: Guardar progreso del elemento
            else Código o reglas cambiaron
                B->>S: Descartar resultado y dejar revisión vigente pendiente
            else Fallo individual
                B->>S: Guardar error, reintentar o saltar y continuar
            end
        end
        B->>S: Registrar finalización o errores parciales
        B->>R: ACK después de persistir estado terminal
    end
```

- **Propuesta:** las reglas pertenecen al owner por lenguaje y versión; afectan sus snippets propios. Reprocesar al habilitar o deshabilitar reglas. Este alcance debe confirmarse con la UI.
- **Diseño:** preservar original y producir un derivado vinculado a código, reglas y procesador. Reutilizar `SnippetContentStorage`; publicación de referencia condicionada a vigencia, sin eliminar blobs ante escritura incierta.
- **Aprobado SNI-27:** trabajo durable en PostgreSQL, outbox transaccional y Consumer Groups en Redis Streams; PrintScript sigue por HTTP. Un fallo de Permissions deja trabajo recuperable sin ACK prematuro; un fallo individual no detiene el lote. El diagrama simplifica la publicación/reentrega: aplicar deduplicación, reservas y recuperación del diseño común.
