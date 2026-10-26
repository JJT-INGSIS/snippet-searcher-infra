# SNI-39 — DuckDNS y acceso de red por ambiente

## Alcance y estado

Hostnames públicos y reglas de red de las VMs existentes, configurados y verificados
el **25 de octubre de 2026** por Juan Rudolph. No se crearon VMs, Swarms ni stacks;
no se cambiaron SSH, CD ni `ssh_known_hosts`. Este ticket entrega nombres, resolución
y reglas: **no declara HTTPS funcionando**. Nada escucha todavía en 80/443; NGINX,
el certificado y la renovación se prueban en SNI-40 y SNI-44.

## Hostnames

| Ambiente | Hostname | Registro A | AAAA | VM | Recurso de IP |
| --- | --- | --- | --- | --- | --- |
| dev | `jjt-snippets-dev.duckdns.org` | `57.156.69.174` | no se publica | `vm-snippet-dev` | `vm-snippet-dev-ip` |
| prod | `jjt-snippets-prod.duckdns.org` | `20.80.18.207` | no se publica | `vm-snippet-prod` | `vm-snippet-prod-ip` |

Cada nombre apunta a la IP del grupo de recursos de su ambiente, tomada del inventario
de [SNI-20](sni-20-acceso-vms.md). NGINX acepta sólo el hostname configurado en su
ambiente y responde 404 a cualquier otro Host, así que usar el nombre de un ambiente
contra la VM del otro no sirve datos cruzados. El hostname se entrega a SNI-43 como
`--nginx-host`; no se escribe en código ni en configuraciones de este repositorio.

Las VMs no tienen IPv6 público (NIC: «Dirección IPv6 pública: -», y
`ip -6 addr show scope global` no devuelve direcciones). Por eso el campo ipv6 de
DuckDNS queda vacío: anunciar un AAAA sin un host que lo atienda haría fallar a los
clientes que prefieren IPv6.

## Administración de DuckDNS

| Dato | Valor |
| --- | --- |
| Cuenta dueña de los dos subdominios | Juan Rudolph |
| Quién puede cambiarlos | Sólo quien inicia sesión en esa cuenta |
| Token | No se copió a Git, Linear, chats, VMs ni GitHub Secrets; sigue sólo en la cuenta |
| Cupo | DuckDNS admite 5 subdominios por cuenta; se usan 2 |

Para cambiar un registro, el dueño inicia sesión en duckdns.org, edita el campo
*current ip* de la fila correspondiente y presiona **update ip**. Al crear un dominio,
DuckDNS completa la IP del navegador; siempre reemplazarla por la de la VM antes de
dar el registro por bueno. Si el dueño no está disponible, nadie más puede cambiar
los registros; con IP estática es un caso excepcional y se acepta ese costo.

## Estabilidad de la IP

Las dos IPs públicas son SKU **Standard**, y en Azure una IP Standard siempre es de
asignación **estática**: se conserva al detener, desasignar, reiniciar o encender la
VM. Sólo se pierde si se elimina el recurso de IP pública. Se comprobó un ciclo real
**Detener → Detenido (desasignado) → Iniciar** en cada ambiente: la IP del portal no
cambió y el hostname siguió resolviendo a la misma dirección.

Por eso **no hay actualizador DNS** en las VMs. Si algún día se recrea el recurso de
IP pública, el procedimiento es:

1. El dueño de DuckDNS actualiza el registro A del ambiente.
2. Revisar con CD (SNI-25) `SSH_HOST` y `SSH_KNOWN_HOSTS` del GitHub Environment y
   [`ssh_known_hosts`](ssh_known_hosts): hoy usan la IP, no el hostname.
3. Repetir las comprobaciones de [después de arrancar](#comprobación-después-de-arrancar-una-vm)
   y actualizar este documento y SNI-20.

## Reglas de red

En las dos VMs `ufw` está `inactive`: el NSG de la NIC es el único filtro de entrada.
Cada NSG está asociado a una interfaz de red y a ninguna subred; la configuración de
red de dev muestra sólo `vm-snippet-dev-nsg` aplicado a `vm-snippet-dev628`.

| Prioridad | Regla | Puertos | dev | prod |
| --- | --- | --- | --- | --- |
| 300 | `SSH` | TCP 22 | Cualquier origen, sin cambios | Cualquier origen, sin cambios |
| 305 | `AllowPublicHttp` (sólo dev, desde SNI-40) | TCP 80 | Cualquier origen: sólo ACME y redirect 308 | — |
| 310 | `AllowTeamWeb` (dev) / `AllowPublicWeb` (prod) | dev: TCP 443; prod: TCP 80, 443 | **Sólo IPs del equipo** | Cualquier origen |
| 65000 | `AllowVnetInBound` | todos | Predeterminada | Predeterminada |
| 65001 | `AllowAzureLoadBalancerInBound` | todos | Predeterminada | Predeterminada |
| 65500 | `DenyAllInBound` | todos | Denegar | Denegar |

No hay reglas para Docker API (2375/2376), Swarm (2377, 7946, 4789), PostgreSQL
(5432/5433), los puertos de aplicaciones (8080–8082), management, Azurite ni Redis:
todos caen en `DenyAllInBound`. Docker publica 8080–8082 y Swarm escucha 2377/7946
en todas las interfaces de la VM; esa escucha no equivale a permiso de entrada.

## Acceso del equipo a dev

Mientras dev acepte `X-Dev-Actor-Id` y la UI de dev use una identidad fija,
`AllowTeamWeb` admite sólo las IPs públicas IPv4 de los integrantes. **Las IPs no se
escriben en este repositorio**, que es público: viven sólo en la regla del NSG.

Para agregar o actualizar una IP (por ejemplo, porque cambió la de tu casa):

1. Obtener la IP pública IPv4 actual de quien necesita acceso y pasarla por privado.
2. Portal → `rg-snippet-dev` → `vm-snippet-dev-nsg` → **Reglas de seguridad de entrada** → `AllowTeamWeb`.
3. En **Direcciones IP de origen**, agregar la IP separada por coma o reemplazar la vieja. Guardar.
4. Comprobar desde esa red que `nc` a 80 da *refused* (llega) con la VM encendida.

Quitar una IP sigue el mismo camino. Al 25/10 la regla contiene sólo la IP de Juan
Rudolph; faltan las de Juan Francisco y Thiago, que se agregan cuando necesiten
probar dev por navegador. SSH no depende de esta regla.

## Decisiones aprobadas

Juan aprobó el 25/10/2026, con «dale empecemos», las seis recomendaciones del plan:

| Elección | Motivo y ventaja | Alternativa descartada y costo aceptado |
| --- | --- | --- |
| Nombres `jjt-snippets-dev` / `jjt-snippets-prod` | Los dos nombran su ambiente; no se confunden | Prod sin sufijo es más corto pero ambiguo. Cambiar un nombre exige actualizar SNI-40/43. |
| Cuenta DuckDNS de Juan | No se comparte un login | Una cuenta compartida obliga a distribuir credenciales. Si Juan no está, nadie cambia los registros. |
| Registro manual, sin actualizador | La IP es estática; el token nunca llega a las VMs | Un cron con el token en la VM agrega un secreto sin necesidad. Recrear la IP exige el procedimiento manual. |
| Dev restringido por IP en el NSG | HTTPS real con el hostname desde el navegador | Sólo túnel SSH rompe hostname/CORS; auth en NGINX es código de otro ticket. Cada cambio de IP residencial exige editar la regla. |
| Dev 80 sólo para el equipo por ahora | Si se despliega NGINX antes del server de redirección, falla cerrado | Abrirlo ya a Internet expondría UI y `/api` de dev por HTTP. SNI-40 debe ampliar la regla para emitir el certificado. |
| IPs del equipo sólo en el NSG | El repositorio es público | Escribirlas en el doc publicaría direcciones residenciales. La lista se consulta en Azure. |

SSH y CD se conservan con la IP como destino, como exige el ticket.

## Comprobación después de arrancar una VM

Con la VM en **En ejecución**, desde una computadora fuera de Azure (macOS usa `-G`;
en Linux reemplazar `-G 5` por `-w 5`):

```bash
dig +short A jjt-snippets-dev.duckdns.org @1.1.1.1
dig +short AAAA jjt-snippets-dev.duckdns.org @1.1.1.1
for p in 80 443 8080 8081 8082 2375 2376 2377 5432 5433 7946; do nc -vz -G 5 jjt-snippets-dev.duckdns.org $p; done
```

Para prod, reemplazar `dev` por `prod` en el hostname.

| Resultado | Significado |
| --- | --- |
| A = IP de la tabla, AAAA vacío | DNS correcto |
| 80/443 `Connection refused` | El NSG deja pasar y la VM responde, sin nada escuchando todavía |
| 80/443 conectado | NGINX ya escucha (después de SNI-40/43) |
| Otros puertos `Operation timed out` | El NSG los bloquea |
| 80/443 de dev con timeout desde una IP del equipo | Su IP cambió o falta en `AllowTeamWeb` |

Al terminar, **Detener** y esperar **Detenido (desasignado)**, como indica SNI-20.

## Evidencia

Todas las comprobaciones son del 25/10/2026, hechas por Juan Rudolph.

| Comprobación | Desde | dev | prod |
| --- | --- | --- | --- |
| A con `1.1.1.1` y `8.8.8.8` | Mac, red residencial | `57.156.69.174` | `20.80.18.207` |
| AAAA con `1.1.1.1` y `8.8.8.8` | Mac | Vacío | Vacío |
| `ufw`, listeners e IPv6 (Run Command) | Azure | 22:49:08 UTC: `inactive`; nada en 80/443; sin IPv6 global | 23:17:22 UTC: `inactive`; nada en 80/443; sin IPv6 global |
| 80, 443 | Mac, IP del equipo | `Connection refused` | `Connection refused` |
| 8080–8082, 2375–2377, 5432–5433, 7946 | Mac | `Operation timed out` | `Operation timed out` |
| 80, 443 desde IP ajena al equipo | Azure Cloud Shell sin VNet | Código 124: timeout, bloqueado | Código 1: refused, llega a la VM |
| Ciclo desasignar → iniciar | Portal + Mac | IP igual; A igual; 80 `refused` | IP igual; A igual; 80 `refused` |
| Estado final | Portal | Detenido (desasignado) | Detenido (desasignado) |

Cloud Shell corre en Azure pero sale por una IP pública ajena al equipo y fuera de la
VNet de las VMs; para el NSG es un origen de Internet cualquiera. La prueba de Cloud
Shell usó `timeout 6 bash -c "</dev/tcp/HOST/PUERTO"`: 124 indica timeout y 1 indica
conexión rechazada. Las capturas de reglas no se versionan porque contienen IPs del
equipo; la prueba reproducible es la tabla de comandos.

## Coordinación

* **SNI-40:** prod ya tiene 80/443 abiertos a Internet para HTTP-01. En dev, cambiar
  el origen de 80 a cualquier origen **sólo** cuando el server del puerto 80 responda
  únicamente el desafío ACME y la redirección a HTTPS; el template de SNI-38 todavía
  sirve UI y `/api` por 80. 443 de dev sigue restringido al equipo.
  Hecho el 26/10/2026: el 80 de dev se abrió con `AllowPublicHttp`.
* **SNI-43:** usar los hostnames de la tabla como `--nginx-host` de cada ambiente.
* **SNI-44:** repetir la comprobación externa con NGINX y TLS activos.
* **SNI-20/25:** sin cambios de destino SSH ni de `known_hosts`.

Fuentes: [DuckDNS: actualización y registros](https://www.duckdns.org/spec.jsp),
[HTTP-01 y puerto 80](https://letsencrypt.org/docs/challenge-types/),
[IPs públicas de Azure](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/public-ip-addresses),
[reglas de NSG](https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview).
