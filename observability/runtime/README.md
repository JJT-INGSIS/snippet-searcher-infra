# DEV: agente fuera de Swarm y colector privado

Thiago eligió esta alternativa el 10/11/2026, reemplazando la propuesta anterior
de agente nativo. El agente oficial corre como contenedor independiente, con red,
PID y cgroups del host y acceso privilegiado/socket Docker. El colector de Swarm
no tiene socket, licencia de New Relic ni capacidades Linux: sólo las redes privadas,
credenciales dedicadas y volúmenes de medición. No se publican puertos de las bases.

Se acepta el acceso amplio del agente al host y mantener otro contenedor fuera del
orquestador a cambio de un paquete fijado por digest. Se descartó el agente nativo
por la elección de empaquetado de Thiago; ambos requieren colectores privados para
resolver DNS de Swarm. El agente completo no se instala como servicio Swarm porque
sus privilegios/namespaces no se reproducen con un stack estándar. Marco de análisis:
capítulos 2/21 del [índice de Fundamentals of Software Architecture, 2e](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/);
la elección concreta es del proyecto, no una recomendación atribuida al libro.

Referencias técnicas: [agente en contenedor](https://docs.newrelic.com/docs/infrastructure/infrastructure-agent/linux-installation/infra-agent-as-container/),
[exec de integraciones](https://docs.newrelic.com/docs/infrastructure/host-integrations/infrastructure-integrations-sdk/specifications/host-integrations-standard-configuration-format/),
[métricas Docker con API](https://docs.newrelic.com/docs/infrastructure/infrastructure-agent/linux-installation/instrument-container/).

## Frontera y configuración

Este candidato es **sólo DEV**, con los nombres/UID/volúmenes efectivamente revisados.
La configuración no se promueve a PROD cambiando un flag: primero inventariar su
release, recursos y proveedores. No modifica CD ni versiones de aplicaciones.
Se reutilizan el renderer, los binarios oficiales y el probe de SNI-82: no se duplica
el mapeo de opciones PostgreSQL/Redis. Las llamadas salen del agente, pasan por un
Docker CLI oficial fijado por digest y ejecutan una operación acotada dentro del
único colector activo. Si falta o hay varias tareas, falla explícitamente. No hay
spool de resultados antiguos ni reemplazo de ausencia por métricas saludables.

El colector tiene raíz de sólo lectura, UID/GID **10001:10001**, capacidades vacías
y `/tmp` de 32 MiB para el cache que requieren los colectores oficiales. La identidad
coincide con el volumen de contenido observado; no se cambian propietarios ni modos
de datos de aplicación. Los secretos del colector conservan el montaje de sólo
lectura de Swarm. PostgreSQL/Redis sólo se montan en lectura para `statvfs`; el probe
escribe exclusivamente dentro de `.sni82-probe` en contenido.

El agente dispone de límites 384 MiB/0,5 CPU; colector 256 MiB/0,5 CPU. Son topes,
no consumo medido. Intervalos de 60 segundos, métricas de procesos e inventario
general desactivados. Licencia sólo en `agent.json` root:root 0600, dentro de un
directorio 0700, montada como archivo; no se incluye en imagen, argumentos, Compose,
repo o environment de servicio. Se usa Docker API 1.44, compatible con el mínimo
del Engine 29 observado. Las imágenes y versiones de colectores están fijadas.

## Operación inicial explícita

1. Confirmar SSH con `docs/ssh_known_hosts`, VM `vm-snippet-dev`, x86-64, manager
   activo, ocho tareas saludables y ausencia de otro agente/roles/secretos de monitor.
   Registrar versiones de servicios antes de tocar configuración.
2. Copiar `scripts`, `observability` y `redis` de la revisión aprobada a una carpeta
   de trabajo de infraestructura de la VM. No son código de aplicación ni builds.
3. `sudo python3 scripts/prepare_observability_dev.py` crea un directorio nuevo
   `/opt/snippet-observability/dev/runtime-v1`, valida la VM/UID y descarga/verifica
   paquetes oficiales. Rechaza sobrescribir un runtime existente. No inicia nada.
4. Revisar los archivos generados y ejecutar explícitamente
   `sudo python3 scripts/provision_observability_dev.py`. Primero comprueba salud
   y colisiones; crea credenciales de monitor separadas, aplica el perfil SQL aprobado,
   agrega alias DEV a las redes existentes y actualiza sólo la configuración ACL de
   Redis. Las actualizaciones son stop-first: hay un reinicio breve de cada base y
   Redis. Espera salud entre cambios. Luego levanta el colector, sin puertos públicos.
   Si falla, inspeccionar estado parcial y archivos protegidos: **no borrar carpetas
   ni repetir a ciegas** para rotar secretos existentes.
5. `sudo python3 scripts/verify_observability_dev.py` exige métricas PostgreSQL/Redis
   presentes, fixture local write/read/delete correcto y capacidad de cada volumen;
   prueba el dispatch real desde la imagen del agente sin licencia ni envío externo.
6. Sólo con una licencia de ingesta autorizada, entregar su valor por **stdin** a
   `sudo python3 scripts/start_observability_dev.py`. No usar un literal en shell,
   argumento o historial. Rechaza configuración/licencia preexistentes. Levanta el
   Compose de observabilidad independiente con restart `unless-stopped`.
7. Verificar recepción en la cuenta **8718557**, tipos de muestra, frescura, identidad,
   atributos efectivos y gasto/CPU/RAM. Comprobar las claves de atributos con `keyset()`
   antes de fijar queries por labels. No dar por hecho que se llaman `labels.*`.

Consultas iniciales sin inventar nombres de atributo:

```sql
SHOW EVENT TYPES SINCE 15 minutes ago
SELECT keyset() FROM PostgresqlInstanceSample, PostgresqlDatabaseSample,
  PgCustomQuerySample, RedisSample, SnippetStorageSample, SnippetSwarmSample
  SINCE 15 minutes ago
```

`SnippetSwarmSample` informa nombre, imagen publicada y réplicas disponibles/deseadas
de cada servicio de la aplicación. No vuelca environment, secretos ni especificación
completa. El host/contendedores los recolecta el agente. El contenedor oficial no
incluye el forwarder de logs: **logs de host/NGINX, OOM/reinicios, alertas/pérdida de
señal y correlación completa de SNI-80 siguen pendientes**. Este bundle no cierra ese
ticket ni reemplaza JDBC/pool de SNI-81. No se ejecutan fallos destructivos ni llamadas.

## Reversión

Detener sólo el agente con `docker compose -f /opt/snippet-observability/dev/runtime-v1/agent.compose.yaml stop`
y quitar únicamente el stack `snippet-observability-dev` si se revierte el colector.
Sus redes/volúmenes de aplicación son externos. No usar `down -v`, podas globales ni
borrar volúmenes de aplicación. Conservar la evidencia de la revisión retirada.

Redis conserva su config anterior en el archivo protegido `redis-previous-config`.
Para retirar el monitor, revisar la especificación vigente, restaurar ese config en
`/etc/redis/entrypoint.sh` y quitar sólo el secreto `obs_redis_password`. Esperar salud.
No usar rollback genérico si hubo cambios posteriores de otro operador. Los alias
aditivos pueden permanecer; quitarlos implica otro reinicio que no aporta recuperación.

Deshabilitar LOGIN del rol `nri_monitor` de cada base si se retira definitivamente;
ninguna tabla de aplicación se modifica. Borrar credenciales/Swarm secrets sólo tras
confirmar que ningún consumidor sigue montándolos. Revocar la clave dedicada de
New Relic desde un administrador. Al terminar una sesión, **detener y desasignar las
VMs en Azure**, no sólo ejecutar shutdown dentro de Ubuntu.

## Evidencia del 10/11/2026

Staging y provisión ejecutados en DEV, ocho servicios de aplicación recuperados 1/1.
Se probó el rechazo de raíz readonly de los binarios oficiales sin `/tmp`; se agregó
tmpfs acotado. El montaje debe ser de tipo `tmpfs` dentro de `volumes` para Swarm,
no asumir que `tmpfs:` abreviado termina aplicado. UID de contenido medido 10001.

New Relic permite consultas, pero crear la clave dedicada fue rechazado explícitamente
con `You do not have permission to create this key.`. No se creó ni obtuvo una licencia
válida, por lo tanto **el agente no se inició y la ingesta no está acreditada**.
La cuenta necesita que su administrador cree/entregue la clave por un canal privado.
Auth0 queda pospuesto por indicación del usuario; no se cambian sus recursos/permisos.

## Recepción comprobada el 16/11/2026

La falta de ingesta documentada arriba es histórica: el agente se inició con una
licencia entregada por Thiago y la cuenta **8718557** recibió muestras reales de
ambos PostgreSQL, Redis, los cuatro probes de storage/volumen y Swarm. El storage
activo observado es **local**; esta ejecución no acredita Asset/Azurite en DEV.
La evidencia y las consultas reproducibles están en
[`docs/evidence/sni82-ingestion-2026-11-16.json`](../../docs/evidence/sni82-ingestion-2026-11-16.json).

Las integraciones nativas usan `label.environment`, `label.service` y
`label.version`; los probes Flex usan `environment`, `service` y `version`.
Para consultar salud de storage filtrar `WHERE up IS NOT NULL`: una muestra de
metadatos del agente sin `up` no significa salud ni caída de un proveedor.
No sustituir la ausencia de muestras por cero. Los probes filesystem no verifican
contenido: sólo `storage-local` aporta `contentOk`, además de lectura/escritura/borrado.

SSH rechazó las claves locales, por lo que se utilizó Run Command de Azure. La
licencia viajó cifrada para una clave temporal root-only de la VM; se descifró
exclusivamente allí y entró por stdin al script revisado. Se comprobó modo 0600
de `agent.json` y eliminación del material temporal. No se puso la licencia en
el script de Azure, environment, argumentos, repo ni evidencia. Como el usuario
la compartió en el chat, corresponde coordinar su rotación con el administrador;
no se revocó ni reemplazó automáticamente la licencia operativa.

La aceptación local volvió a pasar, con ocho servicios de aplicación 1/1.
La muestra puntual del agente fue 136 MiB y 0,03% CPU; no representa un pico ni
una medición sostenida. El helper local conserva `newRelicIngestionVerified: false`
por diseño: la prueba externa de recepción se registra por separado, sin cambiar
retroactivamente su resultado.

Esto no completa JDBC/pool/APM de SNI-81 ni los logs/alertas de SNI-80. No se
provocaron caídas en las dependencias compartidas de DEV: las fallas aisladas
anteriores conservan su alcance de QA; observar fallo/recuperación en DEV y
coordinar la conservación de alias/configuración con CD siguen pendientes.
SNI-82 permanece In Progress hasta resolver esos puntos. PROD no fue modificado.
DEV ya estaba encendida al iniciar esta sesión y se verificó al finalizar como
**Detenido (desasignado)**. Al volver a iniciarla, el agente conserva su configuración
y política `unless-stopped`; comprobar muestras nuevas, no sólo las de esta evidencia.

### Entrega de consultas y ensayos aislados

[`dependencies-dev.nrql`](dependencies-dev.nrql) contiene las consultas ejecutadas
en la cuenta 8718557: identidad/frescura de las integraciones, salud del storage e
inventario de recepción. Ejecutar cada SELECT por separado. Son resultados para
diagnóstico y preparación de SNI-86, no condiciones ni umbrales de alerta elegidos.

Se repitió `verify_observability.py --architecture amd64` con los colectores reales
en un proyecto Docker local exclusivo. Resultado **PASS**: bloqueo PostgreSQL
1→0, caída/recuperación de base y Redis, volumen readonly, caída/recuperación del
backend Azurite, AOF sin espacio en tmpfs exclusivo y credencial de monitor inválida
sin perder disponibilidad de aplicación. Contenedores propios detenidos, sin
eliminar volúmenes ni interrumpir DEV. Registro:
[`sni82-faults-2026-11-16.json`](../../docs/evidence/sni82-faults-2026-11-16.json).

La prueba aislada acredita detección/restauración por los colectores; la evidencia
de ingesta acredita recepción sana en DEV. No se combinan para afirmar que New
Relic observó esos fallos, abrió incidentes o envió avisos al teléfono.

| Pendiente de integración | Evidencia que falta / coordinación |
| --- | --- |
| JDBC/pool (SNI-81) | Señales efectivas de la aplicación y consulta de diagnóstico; sesiones SQL no equivalen a conexiones ocupadas del pool |
| Siguientes despliegues | Conservar alias privados y configuración ACL/secret de Redis de observabilidad en el CD vigente |
| Falla/recuperación en DEV | Ventana y restauración revisadas; observar pérdida/recuperación de muestras por dependencia |
| Alertas y aviso (SNI-86/87) | Condiciones/canal entregados por SNI-86 antes de ejecutar la aceptación de SNI-87 |

La aceptación de ensayos **aislados** del ticket tiene evidencia actual; la
integración operativa pendiente mantiene SNI-82 In Progress. SNI-86 ya dispone
de las consultas y muestras de dependencias para preparar sus dashboards, sin
atribuirle métricas JDBC todavía no entregadas ni cerrar tickets de compañeros.
