# Linting y reprocesamiento masivo

[Volver al índice de arquitectura](../README.md)

US14 permite configurar reglas predefinidas; US15 exige evaluarlas sobre los snippets sin hacer esperar al usuario y con recuperación ante fallos. Los resultados alimentan listado y detalle. El reprocesamiento masivo es **futuro**; la secuencia siguiente es una **propuesta de diseño**.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant B as Proceso de fondo en snippets - FUTURO
    participant ST as Storage de cátedra - FUTURO
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
        S->>S: Guardar configuración y trabajo pendiente en una transacción local
        break Fallo de persistencia local
            S-->>UI: Cambio de reglas no confirmado
        end
        S-->>UI: Configuración guardada, evaluación pendiente

        B->>S: Retomar trabajo durable
        S->>P: Obtener IDs propios del usuario
        P-->>S: IDs o error transitorio
        break No se pudieron consultar los permisos
            S->>S: Conservar trabajo pendiente para reintentar
        end
        S->>S: Seleccionar lenguaje y versión afectados
        S-->>B: Elementos pendientes y revisión de reglas

        loop Cada snippet pendiente
            B->>S: Obtener revisión y metadatos
            B-->>ST: Uso futuro al recuperar contenido
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
    end
```

- **Propuesta:** configuración por owner, lenguaje y versión; sólo se procesan sus snippets propios. El catálogo y significado de reglas pertenecen a PrintScript; la selección y los resultados persistidos pertenecen a snippets-service.
- **Requerimiento:** linting informa infracciones. **Propuesta:** distinguir cumple, incumple, pendiente y no evaluado por error. Una caída del procesador no significa incumplimiento; linting no modifica el código ni reemplaza la validación del parser.
- **Requerimiento US15:** progreso durable y recuperación de fallos. **Propuesta:** proceso de fondo dentro de snippets-service con HTTP por elemento, sin elegir todavía broker. Ante caída de permissions, mantener el trabajo pendiente. Ante resultados obsoletos, evaluar la revisión vigente. El storage futuro sólo participa al recuperar contenido; su contrato queda pendiente.
