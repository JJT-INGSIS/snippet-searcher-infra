# Revalidación ante una nueva versión del parser

[Volver al índice de arquitectura](../README.md)

La consigna exige revalidar al cambiar el parser. La [ADR-001 / SNI-27](../adr-001-async-processing.md)
aprueba una **activación administrativa explícita**, seguida de outbox y evento
`ParserVersionActivated` por Redis Streams. El deploy por sí solo no dispara trabajo.
Runtime futuro sobre snippets del ámbito afectado, sin cambiar su versión declarada
de lenguaje. Garantías comunes en el [diseño mínimo](../async-processing-design.md).

```mermaid
sequenceDiagram
    actor O as Operador autorizado
    participant S as snippets-service
    participant P as Publicador outbox en snippets - FUTURO
    participant R as Redis Streams - FUTURO
    participant B as Proceso de fondo en snippets - FUTURO
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
    B->>R: ACK después de persistir estado terminal
```

- **Aprobado SNI-27:** activación de sistema autorizada y auditable, con alcance por lenguaje/versiones afectadas para todos los owners; separada de desplegar imágenes. No usa tokens de usuario ni headers dev en workers. El mecanismo administrativo se concreta en la implementación, sin inventar un usuario global.
- **Propuesta:** distinguir versión del lenguaje, versión del procesador y revisión del contenido. Conservar los snippets que pasan a ser inválidos y sus diagnósticos; no migrar lenguaje, borrar contenido ni reejecutar automáticamente tests o formatting sin otro requerimiento.
- **Aprobado SNI-27:** outbox, Redis Streams y progreso durable en PostgreSQL; continuar ante errores individuales. Language selecciona la integración; PrintScript valida por HTTP y no consume Redis. La identidad verificable del procesador es una capacidad interna pendiente; el diagrama no afirma que esté disponible actualmente. Reutilizar storage y recuperación del diseño común.
