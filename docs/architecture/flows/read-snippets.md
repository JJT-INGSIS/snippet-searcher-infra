# Búsqueda, visualización y descarga

`permissions-service` determina el universo accesible mediante IDs; `snippets-service` aplica filtros y orden, y entrega contenido y resultados vigentes. La descarga formateada puede requerir procesamiento puntual mediante el módulo interno `Language`.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant ST as Storage FUTURO
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
        S->>S: Paginar si corresponde
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
        S->>S: Obtener metadatos, tests y resultados vigentes
        Note over S,ST: Uso futuro: recuperar contenido solicitado

        opt Descarga formateada sin derivado vigente
            S->>L: Formatear original con versión y reglas aplicables
            L->>PS: HTTP con código, versión y reglas
            PS-->>L: Código formateado o error
            L-->>S: Resultado normalizado
            break Formatting no completado
                S-->>UI: Error de descarga formateada
            end
            Note over S,ST: Uso futuro: conservar derivado cuando corresponda
        end

        S-->>UI: Detalle o archivo original/formateado solicitado
    end
```

- **Requerimientos:** US5–6 incluyen propios, compartidos, filtros, orden, tests e infracciones; US13 permite descargar original y formateado. Los diagnósticos deben corresponder al contenido mostrado.
- **Propuestas:** resolver autorización antes de filtros, orden y eventual paginación; no cargar todos los contenidos ni ejecutar lint en cada listado. Obtener IDs accesibles alcanza inicialmente, sujeto al volumen real.
- **Errores y vigencia:** si permissions o storage fallan, informar indisponibilidad. No entregar un derivado viejo como actual; un fallo de formatting no elimina el original. Un resultado de lint pendiente o fallido técnicamente no equivale a incumplimiento.

[Volver a la referencia de arquitectura](../README.md)
