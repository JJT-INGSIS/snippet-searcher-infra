# Búsqueda, visualización y descarga

`permissions-service` determina el universo accesible mediante IDs; `snippets-service` aplica filtros y orden, y entrega contenido y resultados vigentes. La descarga formateada puede requerir procesamiento puntual mediante el módulo interno `Language`.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as SnippetContentStorage
    participant L as Language interno
    participant PS as printscript-service

    UI->>S: Solicitar lista, detalle o descarga

    alt Listado o búsqueda
        S->>P: IDs accesibles por actor y relación por HTTP
        P-->>S: IDs propios, compartidos o ambos
        break No se pudo resolver acceso
            S-->>UI: Indisponibilidad, sin fingir lista vacía
        end
        S->>S: Consultar BD restringida a IDs autorizados
        S->>S: Aplicar filtros y orden globales
        S->>S: Paginar los resultados
        S-->>UI: Metadatos y estados de lint
    else Detalle o descarga
        S->>S: Comprobar existencia del snippet
        break Snippet inexistente
            S-->>UI: Error sin contenido
        end
        S->>P: Verificar acceso al snippet por HTTP
        P-->>S: Decisión y relación necesaria
        break Sin acceso o permisos no verificables
            S-->>UI: Error sin recuperar ni procesar contenido
        end
        alt Detalle o descarga del original
            S->>ST: Leer contenido original
            ST-->>S: Contenido o error
            S-->>UI: Detalle con código, metadatos, estado de lint y capacidades, o error
            Note over UI: La UI genera el archivo original a partir del detalle
        else Descarga formateada
            S->>S: CurrentStoredVariant busca el derivado y verifica su vigencia
            opt La variante coincide con el contenido, las reglas y el procesador consultado
                S->>ST: Leer contenido derivado
                ST-->>S: Contenido o error
                S->>S: Si se leyó, recargar el snippet confirmado y volver a comprobar vigencia
            end
            opt No hay una variante almacenada utilizable
                S->>ST: FormatSavedSnippet lee el contenido original
                ST-->>S: Contenido o error
                S->>L: Formatear con la versión y las reglas del dueño
                L->>PS: HTTP con código, versión y reglas
                PS-->>L: Código formateado o error
                L-->>S: Resultado normalizado
                S->>S: Revalidar contenido y reglas antes de responder
            end
            S-->>UI: Código formateado y metadatos en JSON, o error
            Note over UI: Si hay éxito, la UI genera el archivo descargable
        end
    end
```

- US5–6 cubren listado y detalle de snippets propios y compartidos, con filtros, orden y estado de lint. US13 permite descargar el original y el formateado.
- La autorización delimita el listado antes de aplicar filtros, orden y paginación. El listado usa metadatos y estados de lint ya registrados.
- `CurrentStoredVariant` compara la referencia al original, el lenguaje, la versión, la revisión de reglas del dueño y la revisión consultada del procesador. Después de leer el derivado, vuelve a comprobar la base con el snippet y las reglas recargados y la misma revisión del procesador.
- `FormatSavedSnippet` formatea bajo demanda cuando falta un derivado utilizable, sin persistir una variante. Si cambia el contenido o las reglas durante el formateo, vuelve a intentar con la revisión actual o informa que el resultado perdió vigencia. Una falla de formato conserva el original.
- Los fallos de acceso o de lectura del contenido necesario se informan como errores. El estado de lint distingue resultados pendientes, fallas técnicas e infracciones.

- Los contratos implementados de listado y detalle están en [reading.md de Snippets](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/reading.md). La consulta de IDs accesibles está en [access.md de Permissions](https://github.com/JJT-INGSIS/permissions-service/blob/dev/docs/access.md).

[Volver a la referencia de arquitectura](../README.md)
