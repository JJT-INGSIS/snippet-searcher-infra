# SNI-20 — Acceso SSH e inventario de las VMs

## Alcance y estado

Preparación de las VMs existentes, revisada el **11 de octubre de 2026**. No recrear recursos ni modificar Docker, Swarm, stack o workflows para completar este ticket. Azure IAM/PIM autoriza operaciones del plano de control; el acceso Linux requiere una clave pública en `azureuser` y una prueba SSH independiente.

**SNI-20 sigue pendiente:** Juan Francisco debe entregar su clave pública y ejecutar las pruebas en ambos ambientes. Juan Rudolph completó las suyas el 25/10/2026. La documentación y la prueba de Thiago no sustituyen esas comprobaciones. El pull autenticado de las imágenes privadas de GHCR pertenece a SNI-24; Juan Francisco carga la configuración de Actions en SNI-25.

## Inventario verificado

Suscripción: `Azure for Students`, `591652c4-6bda-4f2a-968d-dc5139557ed5`.

| Recurso | dev | prod |
| --- | --- | --- |
| VM / hostname | `vm-snippet-dev` | `vm-snippet-prod` |
| Grupo de recursos | `rg-snippet-dev` | `rg-snippet-prod` |
| Región | Chile Central | North Central US |
| Sistema operativo | Ubuntu 24.04.4 LTS | Ubuntu 24.04.4 LTS |
| Arquitectura | `x86_64` (Azure: x64, generación V2) | `x86_64` (Azure: x64, generación V2) |
| Tamaño | `Standard_B4als_v2`: 4 vCPU, 8 GiB RAM | `Standard_B4als_v2`: 4 vCPU, 8 GiB RAM |
| Disco de SO | `vm-snippet-dev_OsDisk_1_3d783a02a2334f799132da2e60e3d386` | `vm-snippet-prod_OsDisk_1_7a76ca32f0eb42c4a149af84cfbc9846` |
| Almacenamiento | SSD estándar LRS, 30 GiB, SSE con PMK | SSD estándar LRS, 30 GiB, SSE con PMK |
| Discos de datos adicionales | 0 | 0 |
| NIC | `vm-snippet-dev628` | `vm-snippet-prod618` |
| VNet / subred | `vnet-chilecentral-1` / `snet-chilecentral-1` | `vnet-northcentralus-1` / `snet-northcentralus-1` |
| IP privada | `172.16.0.4` | `172.16.0.4` |
| Recurso de IP pública | `vm-snippet-dev-ip` | `vm-snippet-prod-ip` |
| IP pública | `57.156.69.174`, asignación Static | `20.80.18.207`, asignación Static |
| NSG | `vm-snippet-dev-nsg` | `vm-snippet-prod-nsg` |
| Estado al terminar las pruebas | Detenido (desasignado) | Detenido (desasignado) |

Los discos, NIC, VNet, NSG e IP pública pertenecen al grupo de cada ambiente. La misma dirección privada en VNet distintas no identifica un recurso compartido. Los datos locales persisten en discos de SO diferentes; no se adjuntan discos de un ambiente al otro. Las pruebas de SNI-20 no despliegan bases ni validan los datos funcionales del futuro stack.

## Identidad de los servidores y entrega a SNI-25

Las claves ED25519 se obtienen por **Azure → VM → Operaciones → Ejecutar comando → RunShellScript**, antes de confiar en SSH:

```sh
hostname
uname -m
cat /etc/ssh/ssh_host_ed25519_key.pub
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

| Ambiente | Huella SHA256 ED25519 | Fuente |
| --- | --- | --- |
| dev | `SHA256:Owg9yX8O6B3QC25mlQOg1Z/WTa6Vp62VWLUryAPTNxo` | Azure Run Command, 2026-10-11 16:25:05 UTC |
| prod | `SHA256:Y39MuXak0yJi65ApF9mMgUyOgP0MuFfDgUjsIN22hLw` | Azure Run Command, 2026-10-11 16:30:57 UTC |

El archivo público [`ssh_known_hosts`](./ssh_known_hosts) contiene las entradas verificadas. Para el puerto estándar `22`, el nombre es la IP sin corchetes ni sufijo de puerto. No usar `ssh-keyscan` como fuente de confianza ni aceptar una clave distinta sin compararla nuevamente por Azure.

Valores a entregar a Juan Francisco, separados por GitHub Environment:

| Configuración | dev | prod |
| --- | --- | --- |
| `SSH_HOST` | `57.156.69.174` | `20.80.18.207` |
| `SSH_USER` | `azureuser` | `azureuser` |
| `SSH_PORT` | `22` | `22` |

Contenido exacto de `SSH_KNOWN_HOSTS` para **dev**:

```text
57.156.69.174 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGRxe0sr75KjMn1QEyu/KowUzNZv2u7vzYBfW45MM5gP
```

Contenido exacto de `SSH_KNOWN_HOSTS` para **prod**:

```text
20.80.18.207 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK9PxZp+ASk6Ps6f/Zi1+dR7Hi4bfWggK1tkGRADnNMI
```

Las claves de host son públicas y autentican al servidor; no son las claves de acceso del equipo. SNI-25 prepara su propia clave de CD y sus secrets. No copiar la clave privada actual de Thiago, tokens GHCR ni credenciales de bases a Git, Linear o esta guía.

## Acceso de cada integrante

Conservar `azureuser`, puerto `22` y autenticación mediante clave. En ambas VMs se comprobó `pubkeyauthentication yes`, `passwordauthentication no` y `kbdinteractiveauthentication no`.

Cada integrante genera o selecciona su propio par de claves, conserva la privada en su computadora y entrega **sólo el archivo `.pub`**, identificando dueño y huella. Por ejemplo, con OpenSSH instalado (macOS/Linux o PowerShell):

```sh
ssh-keygen -t ed25519 -f ~/.ssh/snippet_searcher -C 'nombre-apellido-snippet-searcher'
ssh-keygen -lf ~/.ssh/snippet_searcher.pub -E sha256
```

Elegir una ruta nueva si ya existe; no sobrescribir claves personales. Usar passphrase. El operador confirma la identidad del dueño y valida el archivo con `ssh-keygen -lf` antes de autorizarlo en **cada VM**, una por vez.

Desde una sesión SSH administrativa verificada, copiar el `.pub` a un archivo temporal, por ejemplo `/home/azureuser/sni-20-member.pub`. Inspeccionar que contiene una sola clave pública del integrante esperado. Para agregarla sin reemplazar el archivo existente, como `azureuser`:

```sh
set -eu
ssh-keygen -lf ~/sni-20-member.pub -E sha256
umask 077
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
cp -p ~/.ssh/authorized_keys ~/.ssh/authorized_keys.sni-20-backup
MEMBER_PUBLIC_KEY=$(cat ~/sni-20-member.pub)
if ! grep -qxF "$MEMBER_PUBLIC_KEY" ~/.ssh/authorized_keys; then
  printf '\n%s\n' "$MEMBER_PUBLIC_KEY" >> ~/.ssh/authorized_keys
fi
rm ~/sni-20-member.pub
```

No usar el restablecimiento de claves de Azure ni redirigir con `>` a `authorized_keys`: podrían reemplazar accesos existentes. La copia de respaldo contiene claves públicas; conservarla en la VM para recuperación. Registrar dueño, huella de la clave de usuario y fecha de alta en la evidencia del ticket. El comentario de una clave ayuda a identificarla, pero su huella es la identificación verificable.

Desde la raíz de infra, **cada integrante** ejecuta con su propia clave privada:

```sh
ssh -i ~/.ssh/snippet_searcher -p 22 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=docs/ssh_known_hosts -o GlobalKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-ed25519 azureuser@57.156.69.174 'hostname; uname -m'
ssh -i ~/.ssh/snippet_searcher -p 22 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=docs/ssh_known_hosts -o GlobalKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-ed25519 azureuser@20.80.18.207 'hostname; uname -m'
```

La ruta `-i` pertenece a cada persona; Thiago usó su clave existente sin distribuirla, identificada por la huella pública RSA `SHA256:m9Bmu5jK5uw47O9ekxnI3i74WdO5Z8SrV82fPXDXr1c`. Esperado: `vm-snippet-dev` o `vm-snippet-prod`, seguido de `x86_64`. Una prueba usando la clave privada de otro integrante no cuenta. En Windows ejecutar desde infra, usando la ruta local equivalente para `-i`.

| Integrante | Clave propia autorizada | dev: hostname / arquitectura | prod: hostname / arquitectura |
| --- | --- | --- | --- |
| Thiago | Clave existente conservada | `vm-snippet-dev` / `x86_64`, SSH estricto, 2026-10-11 16:25:18 UTC | `vm-snippet-prod` / `x86_64`, SSH estricto, 2026-10-11 16:31:29 UTC |
| Juan Francisco | Pendiente de entrega de `.pub` y alta | Pendiente | Pendiente |
| Juan Rudolph | ED25519 `SHA256:oaUNKepRwnyNaqRMTqOFbM4qeJncdshJE6dsgLmPYks`, agregada por Azure Run Command conservando las existentes, 2026-10-25 | `vm-snippet-dev` / `x86_64`, SSH estricto, 2026-10-25 | `vm-snippet-prod` / `x86_64`, SSH estricto, 2026-10-25 |

Para revocar: identificar la huella con `ssh-keygen -lf ~/.ssh/authorized_keys -E sha256`, respaldar el archivo y quitar **sólo la línea correspondiente a esa clave** en ambas VMs. Mantener una sesión administrativa abierta y probar que otro acceso autorizado sigue funcionando. Probar una conexión nueva con la clave revocada: debe fallar. Quitar también las copias autorizadas de la misma clave en `authorized_keys2`, si existiesen; no restaurar después un respaldo que la vuelva a habilitar. La revocación no cierra sesiones activas ni elimina permisos Azure/PIM: coordinar esos controles aparte.

## Red y túneles HTTP

En ambas VMs se consultaron las **reglas de seguridad vigentes de la NIC**. El NSG de cada ambiente contiene las reglas de la tabla. En dev también se revisaron las reglas administrativas de Azure Network Manager; en prod sólo se mostró el NSG de la NIC.

| Dirección | Regla efectiva | Prioridad | Resultado |
| --- | --- | --- | --- |
| Entrada | `SSH`, TCP 22 desde cualquier origen | 300 | Permitir |
| Entrada | `AllowVnetInBound` | 65000 | Permitir tráfico de VNet |
| Entrada | `AllowAzureLoadBalancerInBound` | 65001 | Permitir desde Azure Load Balancer |
| Entrada | `DenyAllInBound` | 65500 | Denegar el resto |
| Salida | `AllowVnetOutBound` | 65000 | Permitir |
| Salida | `AllowInternetOutBound` | 65001 | Permitir |
| Salida | `DenyAllOutBound` | 65500 | Denegar el resto |

En dev, el administrador de red no agregó reglas de entrada; se observó una regla de salida `DefaultIPv6OutboundDeny` de prioridad 0 para una lista de destinos IPv6. No impidió las pruebas HTTPS realizadas. No se cambiaron reglas en SNI-20.

Para tráfico entrante desde Internet, sólo hay autorización TCP 22. Los puertos HTTP `8080–8082`, PostgreSQL `5432/5433`, Docker TCP `2375/2376`, Swarm TCP `2377`, TCP/UDP `7946` y UDP `4789` no tienen permiso público. `ss` puede mostrar puertos de Swarm escuchando en todas las interfaces: esa escucha no equivale a permiso de entrada en Azure. El 11/10 no se observaron listeners de base, daemon Docker TCP ni aplicaciones HTTP en ninguna VM.

Para probar HTTP cuando SNI-24 haya desplegado las aplicaciones, mantener una terminal abierta con un túnel, vinculado sólo a loopback de la computadora:

```sh
ssh -i ~/.ssh/snippet_searcher -p 22 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=docs/ssh_known_hosts -o GlobalKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-ed25519 -o ExitOnForwardFailure=yes -N -L 127.0.0.1:8080:127.0.0.1:8080 -L 127.0.0.1:8081:127.0.0.1:8081 -L 127.0.0.1:8082:127.0.0.1:8082 azureuser@57.156.69.174
```

Para prod sustituir el destino por `azureuser@20.80.18.207`. Usar una VM a la vez o puertos locales distintos; `Ctrl+C` cierra el túnel. Probar en `http://127.0.0.1:8080–8082` según el contrato de cada servicio. El túnel no despliega servicios ni prueba su salud por sí solo. La apertura HTTP pública y el acceso de runners quedan para la coordinación SNI-24/SNI-25.

## Salida DNS y HTTPS

Ejecutado mediante Azure Run Command desde cada VM, sin credenciales ni descarga de imágenes:

```sh
date -u +%Y-%m-%dT%H:%M:%SZ
hostname
for host in ghcr.io registry-1.docker.io auth.docker.io; do
  getent ahostsv4 "$host" | head -n 1
done
curl --max-time 20 -sS -o /dev/null -w 'GHCR HTTPS=%{http_code}\n' https://ghcr.io/v2/
curl --max-time 20 -sS -o /dev/null -w 'DockerHub HTTPS=%{http_code}\n' https://registry-1.docker.io/v2/
curl --max-time 20 -sS -o /dev/null -w 'DockerAuth HTTPS=%{http_code}\n' 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/postgres:pull'
```

| Ambiente | Fecha UTC | DNS de los tres dominios | GHCR `/v2/` | Docker Hub `/v2/` | Docker Hub auth |
| --- | --- | --- | --- | --- | --- |
| dev | 2026-10-11 16:25:05 | Resuelto | 401 | 401 | 200 |
| prod | 2026-10-11 16:30:57 | Resuelto | 401 | 401 | 200 |

Los códigos HTTP prueban DNS, conexión HTTPS y una respuesta del registro con validación TLS normal. **GHCR 401 no prueba autorización para descargar imágenes privadas.** Docker Hub también exige el flujo de token para su API de registro. El pull autenticado y sus permisos se verifican en SNI-24.

## Arranque, reinicio y detención

Desde Azure Portal, seleccionar la VM del ambiente y usar **Iniciar**. Esperar `En ejecución` antes de SSH o Run Command. Encender una sola VM a la vez para estas comprobaciones: terminar y desasignar dev antes de iniciar prod. **Reiniciar** sirve para un reinicio necesario, pero no reduce asignación ni reemplaza la detención final.

Al finalizar, usar **Detener**, confirmar y esperar **Detenido (desasignado)**. Un `shutdown` dentro de Linux puede dejar recursos asignados; no alcanza para este criterio. Conservar discos, IP pública y el resto de los recursos; no eliminar VM, grupo de recursos ni volúmenes. Los discos y recursos de IP pública siguen existiendo y pueden generar cargos.

Alternativa para una computadora con Azure CLI ya instalada y autenticada, o Azure Cloud Shell, con permisos Azure vigentes:

```sh
az account set --subscription 591652c4-6bda-4f2a-968d-dc5139557ed5
az vm start -g rg-snippet-dev -n vm-snippet-dev
az vm get-instance-view -g rg-snippet-dev -n vm-snippet-dev --query 'instanceView.statuses[].displayStatus' -o tsv
# Al terminar dev:
az vm deallocate -g rg-snippet-dev -n vm-snippet-dev
az vm get-instance-view -g rg-snippet-dev -n vm-snippet-dev --query 'instanceView.statuses[].displayStatus' -o tsv
# Sólo después de confirmar dev desasignada:
az vm start -g rg-snippet-prod -n vm-snippet-prod
# Al terminar prod:
az vm deallocate -g rg-snippet-prod -n vm-snippet-prod
az vm get-instance-view -g rg-snippet-prod -n vm-snippet-prod --query 'instanceView.statuses[].displayStatus' -o tsv
```

Para repetir el inventario, consultar Información general y Discos de cada VM; Configuración de cada IP pública; y NIC → Ayuda → Reglas de seguridad vigentes. Si cambia una identidad, obtener nuevamente la clave pública por Run Command y actualizar la evidencia y el archivo de hosts después de resolver la discrepancia.

## Evidencia y cierre

Registrar en SNI-20: fecha/ambiente, identidad de la persona que probó, huella de su clave pública, salida `hostname; uname -m`, resultado de verificación estricta, fuente Azure de la clave de host, resultados DNS/HTTPS, reglas efectivas y estado final desasignado. No adjuntar privadas, tokens ni salida de archivos de credenciales.

- [x] Inventario Azure de ambas VMs y discos separados.
- [x] Ambas IP públicas confirmadas estáticas.
- [x] Identidades ED25519 obtenidas por Azure y verificadas por SSH en ambos ambientes.
- [x] DNS/HTTPS y reglas efectivas comprobados en ambos ambientes.
- [ ] Claves públicas de Juan Francisco y Juan Rudolph agregadas sin reemplazar las existentes.
- [ ] Los tres integrantes probaron ambas VMs con sus claves propias.
- [ ] Documentación integrada mediante PR a `dev` y entrega de valores a SNI-25.
- [x] Ambas VMs confirmadas `Detenido (desasignado)` al terminar.

Se encendió dev para las pruebas y se confirmó desasignada antes de iniciar prod. Azure confirmó también prod desasignada al terminar, el 11/10/2026.

Marcar Done únicamente cuando todos los criterios estén completos. Se conserva una cuenta compartida porque es el alcance acordado; las claves individuales permiten revocación por persona, aunque Linux registra el mismo usuario. Se descarta compartir una privada porque impediría revocar de forma independiente y atribuir las pruebas a cada integrante.

Referencias: [SSH y huella mediante Run Command](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/mac-create-ssh-keys), [diagnóstico de reglas efectivas NSG](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-network/virtual-network-troubleshoot-ssh-nsg-problem), [red e IP estática de VMs Linux](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/tutorial-virtual-network).
