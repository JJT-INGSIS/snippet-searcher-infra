# Revalidación ante una nueva versión del parser

[Volver al índice de arquitectura](../README.md)

Una activación administrativa explícita registra el evento
`ParserVersionActivated`. El worker revalida los snippets del ámbito afectado
y conserva su versión declarada de lenguaje. El despliegue de una imagen por
sí solo no encola trabajo. [Procesamiento asíncrono](../async-processing-design.md).

```mermaid
sequenceDiagram
    actor O as Operador autorizado
    participant S as snippets-service
    participant P as Publicador outbox en Snippets
    participant R as Redis Streams
    participant B as Worker de Snippets
    participant ST as SnippetContentStorage
    participant L as Language interno
    participant PS as printscript-service

    O->>S: Activar explícitamente una revisión del parser
    S->>S: Autorizar y comprobar identidad disponible del procesador
    S->>S: Commit de activación, trabajo y outbox
    break Fallo de persistencia local
        S-->>O: Trabajo no confirmado
    end
    S-->>O: Activación confirmada, revalidación pendiente
    P->>S: Leer outbox confirmado
    P->>R: Publicar ParserVersionActivated
    B->>R: Leer mediante Consumer Group
    R-->>B: Evento
    B->>S: Deduplicar y retomar pendientes del ámbito afectado

    loop Cada snippet pendiente
        S-->>B: Revisión de contenido y versión declarada del lenguaje
        B->>ST: Recuperar esa revisión
        ST-->>B: Código
        B->>L: Validar con el procesador actualizado
        L->>PS: HTTP con código y versión declarada del lenguaje
        PS-->>L: Validación, diagnósticos y versión real del procesador
        L-->>B: Resultado

        alt Evaluación completada con revisión y procesador esperados
            B->>S: Guardar resultado y progreso sin modificar el contenido
            Note over S: Conservar también los snippets que ahora resultan inválidos
        else Cambió el contenido o el procesador no es el esperado
            B->>S: Descartar resultado y dejar evaluación correcta pendiente
        else Fallo técnico individual
            B->>S: Guardar error, reintentar o saltar y continuar
        end
    end
    B->>S: Registrar finalización o errores parciales
    opt Estado terminal o recuperación UNKNOWN persistida
        B->>R: ACK de la entrega
    end
```

La activación usa un comando interno auditable, un ámbito por lenguaje y
versiones, y una identidad verificable del parser. La revalidación conserva
el código y guarda diagnósticos aunque el snippet pase a ser inválido.
[Comando y contrato en Snippets](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/parser-revalidation.md).
