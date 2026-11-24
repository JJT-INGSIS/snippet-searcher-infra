# Sharing y permisos

[Volver al índice](../README.md)

El dueño comparte un snippet confirmado con otro usuario. El directorio de
Auth0 permite buscar destinatarios por medio de Snippets.

```mermaid
sequenceDiagram
    actor UI as Usuario mediante UI
    participant S as snippets-service
    participant U as Directorio Auth0
    participant P as permissions-service

    UI->>S: Buscar destinatarios
    S->>U: Consultar candidatos
    U-->>S: Usuarios con IDs de Auth0
    S-->>UI: Destinatarios seleccionables
    UI->>S: Compartir snippet con el ID del destinatario
    S->>S: Comprobar estado del snippet y destinatario
    S->>P: Registrar acceso compartido con el actor autenticado
    P->>P: Verificar ownership y persistir el share
    P-->>S: Resultado de la operación
    S-->>UI: Confirmación o error
```

El share permite lectura y ejecución autorizada. Edición y sharing quedan a
cargo del dueño. Permissions conserva las relaciones de forma idempotente. El
contenido y los tests siguen asociados al original.
[Contrato de Snippets](https://github.com/JJT-INGSIS/snippets-service/blob/dev/docs/sharing.md) ·
[Contrato de Permissions](https://github.com/JJT-INGSIS/permissions-service/blob/dev/docs/access.md).
