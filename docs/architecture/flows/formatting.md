# Formatting y reprocesamiento masivo

[Volver al índice de arquitectura](../README.md)

US11 configura reglas por HTTP síncrono; US12 reprocesa sin hacer esperar al usuario
y con recuperación. US13 conserva el original y permite descargar el formateado.
El procesamiento implementa `FormattingRulesChanged`, outbox y Redis Streams según
la [ADR-001](../adr-001-async-processing.md). Las garantías comunes están en el
[diseño de procesamiento asíncrono](../async-processing-design.md).

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

    UI->>S: Guardar reglas para un lenguaje y una versión
    S->>L: Validar la selección del dueño para ese lenguaje y versión
    L->>PS: Comprobar reglas predefinidas
    PS-->>L: Configuración admitida o errores
    L-->>S: Resultado

    alt Configuración inválida o servicio indisponible
        S-->>UI: Error, conservar configuración anterior
    else Configuración admitida
        break La selección de reglas sigue igual
            S-->>UI: Configuración sin cambios y sin trabajo nuevo
        end
        S->>S: Guardar configuración, revisión, trabajo y outbox en una transacción
        break Fallo de persistencia local
            S-->>UI: Cambio de reglas no confirmado
        end
        S-->>UI: Reglas guardadas e ID del trabajo
        Note over UI,S: La UI consulta el progreso por separado

        O->>S: Leer outbox confirmado
        O->>R: Publicar FormattingRulesChanged
        B->>R: Leer mediante Consumer Group
        R-->>B: Evento
        B->>S: Deduplicar y retomar trabajo durable
        break La revisión de reglas del trabajo quedó obsoleta
            B->>S: FormattingRulesChangedHandler descarta el lote como SUPERSEDED
            B->>R: ACK después de persistir el estado
        end
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
            B->>L: Preparar formateo con la revisión verificada del procesador
            L->>PS: Operación durable por HTTP con código, versión, reglas y revisión esperada
            PS-->>L: Código formateado o error
            L-->>B: Resultado

            alt Formateo exitoso
                B->>ST: Guardar contenido derivado
                B->>S: Verificar la base y publicar la referencia si sigue vigente
                S->>S: Guardar progreso o descartar el resultado obsoleto
            else Fallo individual
                B->>S: Guardar error, reintentar o saltar y continuar
            end
        end
        B->>S: Persistir el progreso y el estado del trabajo
        opt Estado terminal o recuperación UNKNOWN persistida
            B->>R: ACK de la entrega
        end
    end
```

- **Alcance.** Las reglas se guardan por dueño, lenguaje y versión. Un cambio efectivo al habilitar o deshabilitar reglas encola el reformateo de los snippets propios de ese alcance. El guardado queda confirmado al terminar la transacción y el progreso del lote se consulta aparte.
- **Vigencia.** `FormattingBasis` vincula el derivado con la referencia al original, el lenguaje, la versión, la revisión de reglas y la revisión del procesador. La operación remota valida la revisión esperada de PrintScript. Al publicar, `JdbcFormattedVariants` comprueba en la transacción la referencia y los metadatos actuales del snippet y la revisión de reglas. Al reutilizar el derivado, la descarga también comprueba la revisión consultada del procesador.
- **Persistencia y recuperación.** PostgreSQL guarda reglas, trabajo y outbox en la misma transacción. Redis Streams entrega el evento mediante un grupo de consumidores y el progreso durable permite retomar el lote. Un fallo transitorio de Permissions deja el trabajo pendiente. Un fallo individual puede registrarse y el lote sigue con los demás snippets. El derivado se guarda por separado en `SnippetContentStorage`, se conserva el original y una escritura incierta conserva los blobs.
