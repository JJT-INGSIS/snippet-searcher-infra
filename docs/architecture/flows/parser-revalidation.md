# Revalidación ante una nueva versión del parser

[Volver al índice de arquitectura](../README.md)

La consigna general exige revalidar snippets cuando cambia el parser. La secuencia es una **propuesta de procesamiento futuro**: trabajo durable sobre todos los snippets del lenguaje afectado, sin cambiar su versión declarada de lenguaje.

```mermaid
sequenceDiagram
    actor O as Operación interna de actualización
    participant S as snippets-service
    participant B as Proceso de fondo en snippets - FUTURO
    participant ST as Storage de cátedra - FUTURO
    participant L as Language interno
    participant PS as printscript-service

    O->>S: Nueva versión del parser para un lenguaje
    S->>S: Guardar trabajo de revalidación en BD snippets
    break Fallo de persistencia local
        S-->>O: Trabajo no confirmado
    end
    S-->>O: Trabajo registrado
    B->>S: Retomar pendientes de todos los snippets afectados

    loop Cada snippet pendiente
        S-->>B: Revisión de contenido y versión declarada del lenguaje
        B-->>ST: Uso futuro al recuperar esa revisión
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
```

- **Requerimiento de la consigna:** revalidar ante cambios del parser. **Propuesta:** disparador interno y alcance por lenguaje, para todos los owners. No requiere inventar un rol global de administrador ni consultar permisos de un usuario.
- **Propuesta:** distinguir versión del lenguaje, versión del procesador y revisión del contenido. Conservar los snippets que pasan a ser inválidos y sus diagnósticos; no migrar lenguaje, borrar contenido ni reejecutar automáticamente tests o formatting sin otro requerimiento.
- **Propuesta:** reutilizar el procesamiento durable de lotes, conservar avances y continuar ante errores individuales. Language selecciona la integración; PrintScript procesa por HTTP. El storage futuro sólo aparece al recuperar contenido y no se define su interfaz.
