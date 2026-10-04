# Formatting y reprocesamiento masivo

[Volver al índice de arquitectura](../README.md)

US11 permite configurar reglas predefinidas; US12 exige reprocesar sin hacer esperar al usuario y con recuperación ante fallos. US13 requiere conservar la descarga original y la formateada. El procesamiento masivo es **futuro**; la secuencia siguiente es una **propuesta de diseño**.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant P as permissions-service
    participant B as Proceso de fondo en snippets - FUTURO
    participant ST as Storage de cátedra - FUTURO
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
        S->>S: Guardar configuración y trabajo pendiente en una transacción local
        break Fallo de persistencia local
            S-->>UI: Cambio de reglas no confirmado
        end
        S-->>UI: Configuración guardada, procesamiento pendiente

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
            B-->>ST: Uso futuro al recuperar original
            ST-->>B: Contenido
            B->>L: Formatear con reglas del trabajo
            L->>PS: HTTP con código, versión y reglas
            PS-->>L: Código formateado o error
            L-->>B: Resultado

            alt Procesamiento exitoso y resultado vigente
                B-->>ST: Uso futuro al conservar contenido formateado
                B->>S: Publicar derivado sólo si siguen vigentes código y reglas
                S->>S: Guardar progreso del elemento
            else Código o reglas cambiaron
                B->>S: Descartar resultado y dejar revisión vigente pendiente
            else Fallo individual
                B->>S: Guardar error, reintentar o saltar y continuar
            end
        end
        B->>S: Registrar finalización o errores parciales
    end
```

- **Propuesta:** las reglas pertenecen al owner por lenguaje y versión; afectan sus snippets propios. Reprocesar al habilitar o deshabilitar reglas. Este alcance debe confirmarse con la UI.
- **Propuesta:** preservar el original y producir una variante formateada vinculada a la revisión de código y reglas. El storage es una dependencia futura: sus mensajes sólo indican momentos de uso, sin definir su contrato.
- **Requerimiento US12:** conservar avance y recuperarse de fallos. **Propuesta:** trabajo durable dentro de snippets-service, llamadas HTTP por elemento y publicación condicionada a revisiones vigentes. Un fallo de permissions deja el trabajo pendiente; un fallo individual no detiene todo el lote. No se elige todavía broker ni infraestructura.
