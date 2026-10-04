# Sharing y permisos

El owner comparte un snippet existente con otro usuario. `permissions-service` verifica ownership y registra el acceso en una misma operación; el contenido y los tests no se copian.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant U as Usuarios y Auth0 FUTURO
    participant P as permissions-service

    opt Buscar destinatario cuando exista integración de usuarios
        UI->>S: Buscar usuarios por texto
        S->>U: Consultar candidatos
        U-->>S: Usuarios con ID estable
        S-->>UI: Destinatarios seleccionables
    end

    UI->>S: Compartir snippet ID con destinatario ID
    S->>S: Comprobar existencia y estado activo
    break Snippet inexistente
        S-->>UI: Error sin modificar accesos
    end

    S->>P: Compartir con actor, snippet ID y destinatario ID por HTTP
    P->>P: Verificar ownership del actor
    break Actor no owner
        P-->>S: Acceso denegado
        S-->>UI: Error sin modificar accesos
    end

    P->>P: Persistir share en su BD sin duplicados
    alt Persistencia confirmada
        P-->>S: Acceso compartido confirmado
        S-->>UI: Snippet compartido
    else Fallo de persistencia o indisponibilidad
        P-->>S: Error o resultado no confirmado
        S-->>UI: Compartir no confirmado
    end
```

- **Decisión existente:** `permissions-service` conserva ownership y sharing; no autentica ni es dueño de perfiles. La búsqueda de destinatarios dependerá de la integración futura de usuarios.
- **Requerimiento / propuesta:** compartir permite leer snippet y tests; US9 permite ejecutar tests con acceso. No concede edición ni volver a compartir. Se propone que repetir el mismo share sea idempotente.
- **Errores:** verificar existencia en snippets no reemplaza la comprobación de ownership en permissions. Ante un timeout no se confirma éxito; un reintento idempotente permite resolver el resultado sin duplicar accesos.

[Volver a la referencia de arquitectura](../README.md)
