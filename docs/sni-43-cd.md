# SNI-43 — CD e inventario ampliado

## Estado y alcance

Implementación local en `feat/sni-43-expanded-stack`, desde infra/dev `f576d18`.
No ejecuta cambios en Azure, no activa Asset, no migra contenido y no implementa
la UI ni TLS. SNI-33/38 entregaron los componentes; SNI-42 aporta imagen/CI/caller
de UI; SNI-40 incorpora TLS/Certbot; SNI-44 acredita la regresión remota integrada.

El CD sigue usando publish/select/deploy, evidencia histórica, árbol Git exacto,
digest, autorización de main, SSH estricto y el mismo `deploy.lock` por ambiente.
Este ticket no instala un orquestador ni cambia el protocolo HTTP de aplicaciones.

## Inventario explícito

| Tipo | Nombres autorizados | Operación |
| --- | --- | --- |
| Aplicaciones base | snippets-service, permissions-service, printscript-service | CD por servicio/digest |
| Aplicación opcional | ui, repo JJT-INGSIS/snippet-searcher-ui | CD propio, CI frontend en SNI-42 |
| Bases | snippets-db, permissions-db | Referencia existente, preservada al reaplicar |
| Infra permanente opcional | nginx, asset-service, azurite | Cambio explícito de infraestructura |
| Tarea puntual | certbot | SNI-40; no se exige una réplica running en CD |

La presencia de un componente en el registro significa instalado. No se agregan
entradas ficticias para componentes pendientes. Un servicio desconocido en el stack
es drift, no se ignora. Certbot no es una aplicación autorizada para publicación/CD.

`stack.yaml` conserva la base compatible; `stack.ingress.yaml` ahora sólo contiene
NGINX/configs/webroot, eliminando la copia de las tres apps y bases. El renderer
operativo combina los archivos y quita explícitamente los puertos de aplicaciones
antes de validar/enviar JSON a Swarm. **No aplicar los overlays directamente**:
`ports: []` no es una garantía de eliminación de puertos en un merge de Swarm.

`stack.asset.yaml` aporta el runtime cuando se solicita. `stack.ui.yaml` prepara
el contrato ui:8080, sin imagen por defecto ni bundle ficticio: el digest real y la
configuración runtime deben entregarse en SNI-42. El probe de UI requiere HTML y
app-config.json JSON del ambiente; identidad dev no es válida en prod.
`ui.dev_actor` registra el actor opcional de dev (ASCII, 1–128 caracteres, inicial
alfanumérica y resto alfanumérico o `._:@|/-`). Omitirlo deshabilita identidad;
prod lo rechaza si no está vacío. El registro, render y probes comparten ese contrato.

## Registro v1 → v2 y protección frente a herramientas antiguas

Los lectores nuevos aceptan ambos formatos. El modo normal preserva el formato
actual hasta el corte explícito; no migra registros al desplegar una aplicación.

La versión 2 conserva `environment`, `images`, evidencias, recibos y metadatos,
y agrega referencias mínimas de los componentes efectivos. Ejemplo conceptual:

```json
{
  "schema_version": 2,
  "environment": "dev",
  "images": {"snippets-service": "paquete@digest", "permissions-service": "paquete@digest", "printscript-service": "paquete@digest"},
  "database": {"image": "postgres:18.6-bookworm@digest"},
  "infrastructure": {},
  "storage_provider": "local"
}
```

Los ejemplos abreviados no son manifiestos desplegables. NGINX registra imagen,
hostname, estado `tls` y nombre/SHA-256 de sus configs inmutables: tres en HTTP y
cinco con TLS, según [SNI-40](sni-40-tls.md), que reemplazó el antiguo `port`. Asset/Azurite
registran imágenes. La configuración del proveedor, si existe, vive en `asset`:
container, timeouts, límite y probe controlado. No se guardan secretos ni código
de snippets. No se convierte el archivo en una definición completa del sistema.

**Se sustituye deliberadamente `database_image` por `database.image`.** Los scripts
de v0.5.1 ignoran un campo nuevo de versión; por eso ese campo por sí solo no los
detendría. Su validador exige database_image antes de actualizar: el formato v2 lo
rechaza. Se comprueba con una copia byte por byte del validador real de infra
`c2180b28abc1b44b9aecfdf855ff7af544339523`, pin de v0.5.1, en tests/legacy.

El corte escribe el fence v2 bajo lock **antes** de ampliar Swarm. Una recuperación
mantiene v2: nunca se vuelve a habilitar accidentalmente un runner histórico.
Una reejecución antigua puede fallar, pero no debe modificar el stack ampliado.
No borrar el registro, restaurar su forma v1 ni usar Docker directamente para eludir
esta protección. Un operador con root puede saltarse los scripts: esto protege de
uso accidental de herramientas antiguas, no de un administrador malicioso.

## Precondiciones de la VM

No hace falta encender VMs para las pruebas locales. Antes del rollout real:

```bash
docker compose version
docker info --format '{{.Name}} {{.Swarm.ControlAvailable}}'
```

El render operativo requiere el plugin Docker Compose además del Docker CLI,
Python 3 y flock existentes. Verificarlo/prepararlo antes de la ventana; no se
instala nada automáticamente. La VM debe ser el manager independiente correcto.
Azurite requiere un único nodo con el volumen original y `asset_storage=true`;
el script no etiqueta nodos ni cambia ubicación automáticamente.

## Orden de integración y corte por ambiente

Primero completar la [integración central y callers v0.6.0](https://github.com/JJT-INGSIS/github-workflows/blob/main/docs/sni-43-integration.md),
con el stack todavía anterior. Para cada ambiente, continuar así:

1. Confirmar callers nuevos en dev o main para producción, conservando protección
   de ramas. No publicar ni adoptar la versión central mientras conserve su marcador.
2. Encender el ambiente y actualizar también el checkout/manual de bootstrap y
   recuperación a la misma revisión nueva. No usar copias antiguas de scripts.
3. Esperar que terminen los runs push/manual en ese ambiente. Reconciliar operaciones
   pendientes y comprobar estado real antes de incorporar componentes.
4. Generar/revisar el candidato desde el registro vigente, no desde digests históricos.
5. Ejecutar el cambio explícito bajo lock; verificar y registrar sólo lo confirmado.
6. Registrar prueba remota en SNI-44. La transición funcional de storage sigue SNI-36.

La puerta de corte consulta en GitHub los workflows de los tres repos de backend,
exige v0.6.0 y rechaza referencias centrales antiguas y runs activos del ambiente.
Si se incorpora UI, exige además su caller cd.yml@v0.6.0. Los errores de consulta
bloquean el corte. GH_TOKEN es opcional para repos públicos, necesario si la API
requiere autenticación; transmitir por entorno, nunca por argumentos/archivos/logs.

## Preparar un candidato sin desplegar

Dentro del checkout **fijo y revisado** de infra en la VM, usando el registro real:

```bash
python3 -B scripts/bootstrap_swarm.py plan \
  /home/azureuser/.local/state/snippet-searcher/dev/release.json \
  --nginx-host HOSTNAME_DEV_ACORDADO --install-assets > candidate-dev.json
python3 -B scripts/bootstrap_swarm.py check candidate-dev.json
```

HOSTNAME_DEV_ACORDADO debe reemplazarse por el hostname real validado de SNI-39.
Ese plan instala el estado HTTP; `--tls` agrega el 443 una vez emitido el
certificado, siguiendo el procedimiento de [SNI-40](sni-40-tls.md).
El modo plan no modifica recursos ni exige permisos Docker de escritura. Calcula
hashes sobre los archivos exactos del checkout; generar en Linux desde la revisión
que se ejecutará, evitando hashes de otros finales de línea de Windows.

Plan conserva digests actuales y proveedor. Instalar Asset/Azurite no cambia local
a asset. Revisar el JSON y respaldar el registro antes del corte. No editar imágenes
para promover aplicaciones mediante infra. UI nueva en prod exige evidencia dev
del digest exacto; posteriores actualizaciones se realizan mediante su CD.

Para incorporar UI por primera vez, agregar al modo plan `--ui-image` con su
paquete GHCR/digest real y, sólo en dev, `--ui-dev-actor dev-juanfran` si corresponde.
No se permite cambiar por este camino la imagen de una UI ya instalada. Prod
exige además igualdad con el Git tree aprobado en main protegido mediante PR
dev→main; no alcanza con que cualquier imagen haya pasado por dev.

Tras aprobación operativa del cambio y cumplir precondiciones:

```bash
sudo -n --preserve-env=GH_TOKEN python3 -B scripts/bootstrap_swarm.py deploy \
  candidate-dev.json --infrastructure
```

Sin token, omitir preserve-env. Repetir el procedimiento separado para prod, con su
registro y hostname reales y main actualizada. No reutilizar datos/configs de dev.
No dar este comando por ejecutado durante la implementación local.

## Configuración y recuperación

Las configs existentes se inspeccionan y su contenido debe coincidir con el hash
registrado. Las nuevas se crean con nombre versionado y contenido del checkout
revisado. No se sobrescriben configs distribuidas ni se eliminan las anteriores.
En plan, `--config-version 2` permite nombrar nuevas revisiones cuando cambió su
contenido; las que no cambiaron conservan su referencia previa.

Cada operación infra tiene un journal `operations/infra-<uuid>.json`, y el mismo
pending.json/lock compartido con CD. Los logs persistentes evitan que cortar SSH
rompa un probe sano por escribir a una tubería cerrada. Bootstrap infra ignora
SIGHUP; no cancelar/provocar fallos manualmente en prod para probarlo.

Reintentar el comando con herramientas nuevas primero consulta Swarm y reconcilia:

* Candidato efectivo, configuración y salud correctas: confirmar sin reaplicar.
* Estado anterior ya sano: registrar recuperación sin repetir la actualización.
* Candidato defectuoso: restaurar referencias/configs de infraestructura previas.
* Componentes añadidos por esta operación: retirar sus servicios si hace falta,
  conservando volúmenes y configs. Nunca retirar bases o apps backend.
* Imagen/config ajena a ambos estados: detenerse; no sobrescribir cambios externos.
* Recuperación fallida: mantener pending y checks fallidos; no declarar salud.

El comando devuelve fallo aunque recupere correctamente el estado anterior. No
retrocede imágenes de aplicaciones por una configuración NGINX defectuosa.
Un corte de storage no se revierte cambiando una variable: el selector rechaza
cambios de proveedor/configuración en este procedimiento. SNI-19/36 define copia,
verificación y aprobación de la transición; SNI-43 sólo opera sobre el proveedor
ya seleccionado. No elimina contenidos, volúmenes ni backups.

Validación y aplicación comparten el manifiesto enviado por stdin al Docker CLI,
sin archivos temporales. El JSON de `docker compose config` ya conserva `$$` para
la interpolación de Swarm: se envía sin volver a escapar esos dólares. Escaparlos
dos veces deja `$$line` en el contenedor, que el shell interpreta como su PID y no
como la variable leída por el healthcheck. La regresión de SNI-42 comprobó el valor
almacenado en servicios Swarm aislados con cero réplicas y retirados al finalizar.

## Verificación y evidencia

Un deploy de backend comprueba aplicaciones/dependencias internas, SQL y storage
seleccionado; no usa DNS/TLS externos para decidir rollback. UI comprueba su propia
salud/configuración HTTP; su recibo no afirma haber probado SQL. Un cambio de infra
comprueba todo el inventario permanente y, si hay NGINX, su salud y rutas internas.
No confundir estos checks con disponibilidad pública acreditada.

Evidencia de UI: frontend-ci.yml y cd.yml centrales deben resolver a la misma
revisión inmutable. El job Frontend CI del intento que construyó/desplegó la imagen
debe figurar completed/success; skipped, failure y cancelled no son evidencia.
La consulta de jobs es paginada y se conserva la selección histórica existente.

Asset activo en dev reutiliza probes con objetos sintéticos aislados. En prod,
el probe es lectura de un manifiesto controlado previamente preparado y validado;
si falta ese manifiesto o falla la lectura, falla la verificación. No se prueba
TCP como sustituto ni se escriben/borran snippets productivos para aprobar un deploy.

Comandos locales reproducibles (suite completa requiere Linux, incluyendo flock):

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
python3 -B scripts/validate_stack.py
python3 -B scripts/validate_asset_config.py
python3 -B scripts/validate_nginx_config.py
python3 -B scripts/validate_expanded_stack.py
python3 -B scripts/verify_asset_persistence.py
python3 -B scripts/verify_nginx.py
```

Los probes reales sólo aceptan Docker local: socket Unix o el pipe local específico
de Docker Desktop Linux en Windows, comprobando motor Linux. No admiten un contexto
SSH/TCP remoto. Los proyectos tienen nombres aleatorios y no usan el .env real.
Los contenedores/redes propios se retiran; los volúmenes Asset se conservan.

La validación de render cubre dev/prod y stacks de 5/6/8/9 servicios. Los digests
de UI usados en esos fixtures no son imágenes reales ni prueba de SNI-42.
El adaptador de render preserva variables shell tras la doble interpolación
Compose/Swarm, tipos de puertos, secretos, nombres de volúmenes por ambiente y
refs externas de configs; no aplica un merge de ports vacío como si los quitara.

UI real con NGINX real y API de contrato: construir su imagen local y ejecutar
`python3 -B scripts/verify_ui_ingress.py snippet-searcher-ui:sni42-local`.
Reutiliza el fixture/probes de SNI-38; no acredita el backend funcional completo.
