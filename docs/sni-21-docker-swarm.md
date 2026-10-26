# SNI-21 — Docker y Swarms independientes

## Estado y alcance

Verificación del 12/10/2026. Las VMs ya tenían Docker Engine y Swarm: se conserva esa instalación, sin reinstalar Docker ni ejecutar nuevamente `swarm init`. No se despliega el stack de aplicaciones ni se configura CD en SNI-21.

Esta guía y [`verify_swarm_vm.sh`](../scripts/verify_swarm_vm.sh) quedan como cambios locales sin commit, push o merge. El cierre de SNI-21 depende también de completar el acceso del equipo en [SNI-20](./sni-20-acceso-vms.md).

| Dato comprobado | dev | prod |
| --- | --- | --- |
| VM | `vm-snippet-dev` | `vm-snippet-prod` |
| Docker Engine / CLI | 29.1.3 / 29.1.3 | 29.1.3 / 29.1.3 |
| Servicio systemd Docker | active / enabled | active / enabled |
| Arquitectura | x86_64 | x86_64 |
| Cluster ID | `wl1naiqll2ieqk6gs349lsbas` | `mm4y9rv6c6cdxrcjp62dfzgqj` |
| Node ID | `zej7253bmw9kj0ndqzxi2e5dk` | `s65v3vdf9q4utw1qj2qt7bvt1` |
| Manager | Ready / Active / Leader, 1 nodo y 1 manager | Ready / Active / Leader, 1 nodo y 1 manager |
| Usuario operativo | `azureuser`, `sudo -n docker` | `azureuser`, `sudo -n docker` |
| Imagen pública en servicio de prueba sin puertos | Creación y actualización verificadas | Creación y actualización verificadas |
| Secreto temporal | Montado en ambas revisiones; eliminado | Montado en ambas revisiones; eliminado |
| Limpieza | Listas de servicios/secretos iguales antes y después | Listas de servicios/secretos iguales antes y después |
| Estado final de VM | Detenido (desasignado) | Detenido (desasignado) |

Dev se comprobó por SSH estricto a partir de las 13:54:12 UTC del 12/10 y prod a partir de las 13:57:42 UTC. En ambas, el servicio de prueba resolvió `alpine:3.23` a `alpine:3.23@sha256:85fe1e81d6758c208f3e1eed4338a1997e19d4be002d4dd32d3100c9a8c010a0`. El contenedor cambió de revisión 1 a 2 y comprobó que `/run/secrets/sni21_probe` existía y tenía contenido, sin imprimirlo. Los servicios, secretos y volúmenes de ambas VMs estaban vacíos al concluir; no se prepararon los secretos definitivos de SNI-24.

Se confirmó dev desasignada antes de iniciar prod. Ambas VMs quedaron `Detenido (desasignado)` después de las pruebas.

## Operación por SSH

Usar las identidades y reglas de [SNI-20](./sni-20-acceso-vms.md). Encender una VM a la vez y desasignarla al terminar. `azureuser` no pertenece al grupo `docker` en ninguna VM: tiene acceso administrativo mediante `sudo -n docker`. Los comandos remotos deben incluir ese prefijo. No agregar el grupo para resolver un comando escrito sin sudo; el grupo Docker también concede privilegios de administración del host.

```sh
sudo -n docker version
sudo -n docker info --format 'State={{.Swarm.LocalNodeState}} Manager={{.Swarm.ControlAvailable}} Cluster={{.Swarm.Cluster.ID}}'
sudo -n docker node ls
sudo -n docker service ls
sudo -n docker secret ls
sudo -n docker volume ls
```

## Prueba reproducible

Desde la raíz de infra, definir una ruta a **la propia clave privada**, sin copiarla a Git ni a Linear:

```sh
SSH_KEY=~/.ssh/snippet_searcher
ssh -i "$SSH_KEY" -p 22 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=docs/ssh_known_hosts -o GlobalKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-ed25519 azureuser@57.156.69.174 'bash -s -- vm-snippet-dev' < scripts/verify_swarm_vm.sh
```

Para prod, sustituir IP por `20.80.18.207` y hostname esperado por `vm-snippet-prod`. El script exige el hostname correcto y un Swarm de un nodo con manager Ready/Active/Leader; si no los encuentra, falla antes de crear recursos.

La prueba crea nombres únicos `sni21-check-<epoch>-<pid>` para un servicio y un secreto **de prueba descartable**, con label `ticket=SNI-21`. Descarga una imagen pública, monta el secreto y ejecuta `sleep`; no publica puertos, no crea volúmenes ni toca servicios del proyecto. Cambia `SNI21_REVISION` de 1 a 2 y comprueba la nueva tarea, además de la presencia del secreto. El resultado esperado incluye:

```text
PASS running revision=1 secret mounted
PASS running revision=2 secret mounted
PASS service create/update and runtime secret; cleanup follows
Cleanup status=0; original services/secrets compared
```

El trap elimina solamente el servicio/secreto que creó esa ejecución y compara sus inventarios con los anteriores. Una desconexión abrupta o apagado puede impedir la limpieza: revisar los nombres exactos informados y su label antes de quitar cualquier recurso. No usar `prune`, `stack rm`, `swarm leave --force` ni borrar volúmenes para limpiar esta prueba. El pull deja la imagen pública en caché; esa caché no es un dato de aplicación ni una credencial.

## Instalación e inicialización: recuperación básica

Para un host nuevo o una instalación ausente, usar el repositorio oficial y la [instalación de Docker Engine en Ubuntu](https://docs.docker.com/engine/install/ubuntu/). No aplicar reinstalación a estas VMs sin diagnosticar primero el estado actual. Para revisar un fallo:

```sh
systemctl status docker --no-pager
sudo journalctl -u docker --since '-15 min' --no-pager
sudo -n docker info
sudo -n docker node ls
```

Si Docker estuviese detenido y el diagnóstico habilita su arranque, `sudo systemctl start docker` recupera el daemon sin volver a inicializar el cluster. Antes de reiniciar Docker, revisar tareas y coordinar la interrupción.

`docker swarm init` sólo corresponde cuando `LocalNodeState` es `inactive` y no hay un Swarm previo que recuperar. En cada VM, por separado, confirmar hostname y usar su IP privada real para `sudo docker swarm init --advertise-addr <ip-privada>`. Nunca usar un join token de dev en prod. No imprimir ni guardar join tokens en Git/Linear.

Un único manager no tolera la caída de su VM. Desasignar y volver a iniciar conserva el estado alojado en disco, pero no ofrece disponibilidad durante la detención. Ante pérdida del disco/estado, recuperar mediante un respaldo coordinado del manager y de los datos; `--force-new-cluster` no es una reparación rutinaria ni recupera discos perdidos.

## Secretos, red y entrega a SNI-24

Cada Swarm conserva su propio estado y secretos. La prueba sólo valida el mecanismo de montaje, usando contenido descartable; las contraseñas de PostgreSQL y los secretos reales se crean por separado en SNI-24 y no se muestran ni se guardan en la documentación. No reutilizar credenciales de build como secretos de runtime. La existencia de un secreto no prueba que una aplicación lo consuma: SNI-24 debe verificar PostgreSQL y Spring con sus montajes/configuración.

La conectividad DNS/HTTPS a GHCR y Docker Hub y las reglas efectivas se registraron en SNI-20. Se conservan: sin exposición pública de TCP 2375/2376/2377, TCP/UDP 7946, UDP 4789 ni bases. No se necesitan puertos de Swarm públicos para un único nodo. La prueba no crea reglas ni publica HTTP. Si después se agregan nodos, diseñar comunicación por una red de confianza, manteniendo dev/prod separados.

SNI-24 recibe los managers/IDs de la tabla, `azureuser` con `sudo -n docker`, identidades SSH de SNI-20 y el mecanismo de secretos verificado. El pull de las imágenes del proyecto, los secretos definitivos, storage, stack y verificación funcional corresponden a SNI-24; los workflows y credenciales de Actions a SNI-25.

Referencias: [servicios Swarm](https://docs.docker.com/engine/swarm/services/), [secretos Docker](https://docs.docker.com/engine/swarm/secrets/), [actualización de servicios](https://docs.docker.com/reference/cli/docker/service/update/).
