# Preparación de Auth0 — SNI-71

Módulo de desarrollo, Terraform 1.13.x (validado con 1.13.5) y proveedor oficial
Auth0 1.56.0 fijado en el lockfile. Implementa configuración; no implementa el
login de UI ni la seguridad de Snippets. Ver el
[contrato compartido](../docs/architecture/authentication-authorization-contract.md).

## Qué administra

- Aplicación React SPA, código de autorización y autenticación de cliente `none`.
- Callbacks `/auth/callback`, retorno de logout `/` y origins exactos.
- API Snippets con RS256, audience explícita y TTL obligatorio sin valor inventado.
- Asociación de esta SPA a una conexión de usuarios Auth0 existente. Usa el
  recurso singular `auth0_connection_client`, sin reemplazar las asociaciones
  de otras aplicaciones. No administrar esa misma conexión con el recurso plural.

No administra tenant global, usuarios/contraseñas, roles por snippet, miembros del
dashboard, conexiones sociales, M2M de negocio, refresco offline ni producción.
La base de credenciales de usuarios pertenece a Auth0. El nombre dev no demuestra
por sí solo que el tenant elegido sea correcto: revisarlo antes de plan/apply.

## Verificar sin cuenta de Auth0

```powershell
terraform -chdir=auth0 init -backend=false -input=false -lockfile=readonly
terraform -chdir=auth0 fmt -check -recursive
terraform -chdir=auth0 validate
terraform -chdir=auth0 test
```

Ejecutar desde la raíz de infra. Las pruebas usan `mock_provider`: no necesitan
credenciales ni contactan el tenant. Los dominios `.invalid`, `con_fixture` y TTL
de prueba son fixtures, no valores aprobados para aplicar. Init sólo descarga
el proveedor firmado y verifica el lockfile.

## Paso del usuario: crear cuenta y tenant

1. Crear la cuenta personal en Auth0 y un tenant compartido del proyecto para DEV
   y PROD, según decisión del usuario del 07/11/2026.
   Elegir conscientemente nombre/región: conservar el dominio asignado exactamente.
   Nombre sugerido si está disponible: `jjt-snippet-searcher` (sin sufijo de ambiente).
2. Invitar a Juanchi y Thiago como miembros del tenant, cada uno con su propia
   cuenta. Mantener dos administradores. Según el dashboard, se hace en Teams
   o Settings → Tenant Members; no compartir la cuenta ni su contraseña.
3. Confirmar la conexión Database de Auth0 que se utilizará para usuarios de
   Snippet Searcher (habitualmente existe una inicial). Anotar su ID `con_...`.
   No crear tablas/passwords en PostgreSQL ni usuarios mediante Terraform.
4. Compartir únicamente el dominio y el ID de conexión (datos no secretos).
   No hace falta prender VMs para estos pasos. No crear manualmente otra SPA/API:
   las preparará este módulo después de revisar sus valores.

## Paso siguiente: configurar y revisar el aprovisionamiento

Este paso todavía no se ejecutó. Antes de continuar hay que confirmar el dominio,
la audience de desarrollo, el TTL de access token y las origins efectivas. El
ejemplo propone localhost:5173 y el hostname conocido de DEV, pero se comprueban
antes de aplicar. No cargar URLs de producción en la SPA de desarrollo. El tenant
es compartido, pero las SPA/API y sus audiences y URLs se separan por ambiente.
Este módulo prepara sólo los recursos dev; no crea un tenant ni configura prod.

1. Un responsable prepara la credencial administrativa para Terraform mediante
   el mecanismo oficial Auth0 (por ejemplo una aplicación M2M de bootstrap para
   Management API). No es el clientId de la SPA ni una credencial de usuario.
2. Autorizar inicialmente sólo estos ocho scopes para el módulo actual:
   `read:clients`, `create:clients`, `update:clients`, `read:resource_servers`,
   `create:resource_servers`, `update:resource_servers`, `read:connections`,
   `update:connections`. Permiten mantener SPA/API y habilitar la SPA en la
   conexión existente. No conceder borrado, usuarios, roles, client grants,
   options de conexiones ni lectura de client keys/credentials por anticipado.
   La configuración usa cliente público `none`, sin administrar claves privadas.
   El plan y la aplicación reales todavía deben confirmar los permisos efectivos:
   ante un 403 se revisa el endpoint concreto antes de ampliar permisos.
   Estos scopes administrativos no quedan limitados por nombre de recurso: la
   credencial puede operar sobre otros recursos de esas categorías del tenant.
   Es sólo para el operador Terraform, nunca para UI, Snippets o workers.
3. Inyectar `AUTH0_CLIENT_ID` y `AUTH0_CLIENT_SECRET` sólo en el proceso del
   responsable con el almacén de secretos acordado; alternativa: API token
   administrativo de corta duración. No pasarlos por argumentos, tfvars, chat o
   commits. No activar `TF_LOG`/`AUTH0_DEBUG` al operar con credenciales.
   No usar `AUTH0_AUDIENCE` como si fuese la audience de Snippets: esa variable
   del proveedor se refiere a Management API; Snippets usa `api_audience`.
4. Copiar `development.tfvars.example` a `development.tfvars` ignorado y completar
   parámetros públicos reales. El archivo no contiene campos para secretos.
5. Un solo operador conserva el estado de este módulo. No hacer que cada compañero
   aplique desde un estado vacío ni versionar/copiar el estado por canales públicos.
   Se usa estado local protegido en este corte; antes de distribuir la operación
   entre máquinas se acuerda backend con control de acceso, respaldo y locking.

### Ingreso local del secreto en Windows

Desde PowerShell en este equipo, ejecutar desde la raíz de infra:

```powershell
./auth0/Save-OperatorCredential.ps1 -ClientId <client-id-publico-de-Terraform>
```

El helper pide el secreto con entrada oculta y guarda un PSCredential en
`.sni71/auth0-operator.credential.xml`, ignorado por Git. En Windows, Export-Clixml
cifra el SecureString mediante DPAPI: sólo el mismo usuario en el mismo equipo
puede descifrarlo. No sincronizar ni compartir ese archivo. No ejecutar este helper
en Linux/macOS, donde Export-Clixml no protege credenciales de la misma manera.

El paso no solicita un token ni aplica recursos. Después, el operador cargará la
credencial sólo en el proceso que revise/ejecute Terraform y eliminará esas
variables al terminar. No imprimir la credencial, usar GetNetworkCredential para
mostrarla ni habilitar logs de depuración. Este detalle operativo permite el ingreso
local sin secretos en chat, argumentos, historial de comandos o tfvars.

Referencia: [Export-Clixml y credenciales](https://learn.microsoft.com/powershell/module/microsoft.powershell.utility/export-clixml).

## Estado verificado del proyecto — 07/11/2026

El usuario autorizó y se aplicó el plan DEV revisado: 4 recursos agregados,
0 modificados y 0 eliminados, usando únicamente los ocho scopes del runbook.
Verificados mediante lectura de Management API: SPA pública, código de autorización,
callbacks/logout/origins exactos, API RS256 con access token de 900 segundos y
asociación a `Username-Password-Authentication`. Clientes/APIs preexistentes
conservados en la comparación; plan posterior con refresh sin cambios.

[Parámetros públicos](development.public.json) para SNI-72/73. El clientId que usa
React es `BDuvRyQ6ryyye08Bs9ZEfRzw7AsskFs6`, no el de la aplicación administrativa.
Este JSON no reemplaza directamente app-config.json: la integración runtime de
backend/UI todavía debe implementarse. Cuenta compartida/usuarios, VM y PROD no
se configuran como efecto de activar estos recursos en Auth0.

El estado y los planes de Terraform pueden incluir atributos sensibles que devuelve
el proveedor incluso si ningún output los muestra. Guardarlos de forma protegida.
`.terraform/`, estado, tfvars y planes se ignoran; el lockfile sí se versiona.

Sólo después de revisar configuración, credenciales y estado:

```powershell
terraform -chdir=auth0 plan -var-file=development.tfvars -out=development.tfplan
# Revisar tenant, nombres dev, URLs y recursos. No publicar el plan ni terraform show -json.
# Aplicar únicamente el plan concreto revisado y autorizado:
terraform -chdir=auth0 apply development.tfplan
terraform -chdir=auth0 output -json public_integration
```

No repetir el bootstrap ni crear un estado vacío después del primer apply.
El plan inicial debe tener sólo los cuatro recursos previstos y no debe modificar
datos de usuarios o infraestructura Azure. El estado actual aplicado figura al
final de esta guía; los planes posteriores deben conservarlo. `prevent_destroy`
protege SPA y API contra eliminación/reemplazo accidental; no reemplaza la revisión.
Si ya existen estos recursos, detenerse e importar los IDs correctos antes de
planificar: no crear duplicados ni intentar un destroy para corregirlos.

El output solicitado contiene sólo datos públicos para SNI-72/73, pero no debe
confundirse con una integración activa: falta configurar y probar backend/UI.
El SDK hará PKCE; el módulo no garantiza el comportamiento de un cliente que
implemente otro flujo por su cuenta. Sin refresh grants, la renovación puede
requerir interacción; no hay promesa de renovación silenciosa permanente.

## Fuentes

- [Proveedor Auth0](https://registry.terraform.io/providers/auth0/auth0/1.56.0/docs).
- [Client](https://registry.terraform.io/providers/auth0/auth0/1.56.0/docs/resources/client).
- [Client credentials](https://registry.terraform.io/providers/auth0/auth0/1.56.0/docs/resources/client_credentials).
- [Asociación individual de conexión](https://registry.terraform.io/providers/auth0/auth0/1.56.0/docs/resources/connection_client).
- [API/resource server](https://registry.terraform.io/providers/auth0/auth0/1.56.0/docs/resources/resource_server).
- [SDK React](https://auth0.com/docs/libraries/auth0-react).
- [Miembros del tenant](https://support.auth0.com/center/s/article/How-to-add-new-tenant-members).
