# Infra — Descripciones de PR y contexto de diseño

Textos preparados para SNI-20, SNI-21 y SNI-24. Cada bloque puede copiarse como descripción de su PR hacia `dev`. SNI-20 corresponde a la PR #8 ya integrada; SNI-21 y SNI-24 mantienen cambios locales en sus ramas. Este documento no publica ni integra nada.

La separación es deliberada: SNI-20 entrega acceso e identidad de los hosts; SNI-21 verifica el motor y los managers; SNI-24 despliega y comprueba el sistema; SNI-25 implementará CD usando esos contratos. Azure/PIM, GitHub Environments y el usuario Linux son mecanismos diferentes.

## SNI-20 — Verificar las VMs y documentar acceso SSH

### Descripción para la PR

Las VMs existentes necesitaban un inventario verificable y un procedimiento de acceso que el equipo pudiera usar sin depender del chat. Esta PR agrega una guía enlazada desde README y las entradas ED25519 de `known_hosts`, obtenidas por Azure Run Command y comprobadas mediante SSH estricto.

Se documentan Ubuntu 24.04.4 x86_64, tamaño B4als v2, discos y recursos independientes, IPs públicas estáticas, `azureuser`, puerto 22, huellas SHA256, alta y revocación de claves, arranque/desasignación y los valores de SSH entregados a SNI-25.

### Decisiones y alternativas descartadas

| Decisión | Motivo | Alternativa descartada / costo aceptado |
| --- | --- | --- |
| Conservar las dos VMs, sus discos e IPs estáticas | Ya estaban creadas y permiten destinos estables de SSH | Recrearlas o agregar un aprovisionador genérico: excede el ticket y podría alterar datos/identidades existentes |
| Mantener `azureuser` y usar claves individuales | Respeta el acceso existente y permite revocar cada clave por separado | Compartir la privada de Thiago: impediría revocar de forma independiente. No se crearon usuarios Linux separados; la cuenta continúa compartida |
| Agregar públicas sin reemplazar `authorized_keys` | Evita perder los accesos que ya funcionan | Restablecer la clave desde Azure o sobrescribir el archivo: puede desplazar claves existentes |
| Obtener ED25519 por Azure y exigir verificación estricta | Establece la confianza antes de conectarse por la red pública | Confiar sólo en `ssh-keyscan` o aceptar cualquier host automáticamente: no verifica la identidad contra un canal independiente |
| Conservar SSH y probar HTTP mediante túneles | Permite acceso del equipo sin agregar exposición HTTP al alcance | Abrir 8080–8082, bases o Swarm/Docker a Internet: no era necesario y se coordina aparte |
| Separar permisos Azure de acceso Linux | Un rol de Azure no incorpora una clave a la cuenta Linux | Presentar IAM/PIM como evidencia de SSH: verifica otro mecanismo de acceso |
| Desasignar después de las pruebas | Conserva discos e inventario y libera el cómputo asignado | Apagar únicamente desde Linux: puede mantener recursos asignados. Los discos/IP siguen existiendo y pueden generar cargos |

### Validación

Thiago ejecutó `hostname` y `uname -m` por SSH estricto en ambas VMs, con las claves de host obtenidas por Azure. Se revisaron las reglas efectivas y DNS/HTTPS hacia GHCR y Docker Hub. Los códigos 401 del registro prueban conectividad, no autorización para descargar imágenes privadas. Ambas VMs quedaron desasignadas.

### Fuera de alcance y pendientes

- No se recrean recursos ni se modifican Docker, Swarm, stack o workflows.
- No se configuran PIM/IAM ni los secrets de Actions; SNI-25 recibe los valores verificados.
- No se distribuyen privadas, tokens ni contraseñas. La documentación sólo contiene identidad pública e inventario.
- Juan Francisco y Juan Rudolph deben entregar sus públicas y probar personalmente ambas VMs. La prueba de Thiago no completa ese criterio.
- Se conserva la regla SSH existente; no se implementó restricción por IP de origen, VPN ni usuarios Linux individuales. Esas serían decisiones de hardening adicionales.

**Documento del cambio:** `docs/sni-20-acceso-vms.md` y `docs/ssh_known_hosts`.

## SNI-21 — Verificar Docker y Swarms independientes

### Descripción para la PR

Las VMs ya tenían Docker y Swarm, pero faltaba comprobar su operación y entregar una guía reproducible. Esta PR conserva la instalación existente, documenta los managers y agrega una prueba temporal de creación, actualización y eliminación de un servicio con un secreto montado.

Cada VM tiene un cluster de un nodo distinto, con manager Ready/Active/Leader. Se registra Docker 29.1.3, la operación por SSH con `sudo -n docker`, recuperación básica, límites de un solo nodo y el contrato entregado al bootstrap de SNI-24.

### Decisiones y alternativas descartadas

| Decisión | Motivo | Alternativa descartada / costo aceptado |
| --- | --- | --- |
| Verificar y conservar Docker/Swarm | El motor y los clusters ya funcionaban | Reinstalar o repetir `swarm init`: cambia infraestructura sin resolver una necesidad comprobada |
| Un Swarm por ambiente | Aísla managers, secretos, servicios y datos | Cluster compartido dev/prod: amplía el impacto de errores y exige aislamiento adicional |
| Un nodo manager/worker por VM | Mantiene una operación pequeña adecuada al alcance actual | Multinodo/HA/Kubernetes: requiere más recursos, red y diseño de almacenamiento. Se acepta indisponibilidad al caer o apagar la VM |
| Usar el sudo existente | Permite operaciones remotas sin modificar grupos o privilegios | Agregar `azureuser` al grupo Docker sólo para omitir sudo: no aporta una necesidad funcional. Ambas opciones conceden administración del host; no se implementa un rol Docker limitado |
| Probar con imagen pública y secreto descartable | Aísla el funcionamiento de Swarm de la autenticación y configuración de las aplicaciones | Usar imágenes privadas o contraseñas reales como prueba del motor: mezcla dependencias de SNI-24 |
| Servicio único, sin puertos ni volúmenes, con limpieza dirigida | Reduce interferencias y permite comparar inventarios antes/después | Un stack de prueba completo o limpieza con `prune`: agrega recursos innecesarios o puede afectar recursos ajenos |
| Conservar los puertos de cluster fuera de Internet | Un nodo no requiere comunicación pública entre managers/workers | Abrir 2377/7946/4789 o el daemon Docker: no se justifica para este diseño |

### Validación

En ambas VMs se comprobó Docker activo/habilitado, un manager Ready/Active/Leader y IDs de cluster diferentes. La prueba descargó Alpine pública, comprobó el secreto en la revisión 1, actualizó a revisión 2 y verificó la nueva tarea. Se eliminaron el servicio/secreto temporales y se compararon inventarios originales. Las VMs quedaron desasignadas.

### Fuera de alcance y pendientes

- No se despliegan aplicaciones, bases o secretos definitivos del proyecto: corresponde a SNI-24.
- No se implementa CD, promoción de imágenes, acceso de runners ni publicación de paquetes: corresponde a SNI-23/SNI-25.
- No se agrega disponibilidad ante pérdida de VM, replicación de datos ni recuperación automática de un manager perdido.
- El montaje de un secreto de prueba no demuestra todavía que PostgreSQL/Spring consuman sus credenciales; eso se verifica en SNI-24.
- El cierre conserva la dependencia de SNI-20 y la integración de la documentación. La verificación del motor no sustituye el acceso personal de los compañeros.

**Documento del cambio:** `docs/sni-21-docker-swarm.md` y `scripts/verify_swarm_vm.sh`.

## SNI-24 — Stack y bootstrap manual dev/prod

### Descripción para la PR

El entorno local no proporcionaba un despliegue verificable en las VMs ni una fuente de referencias vigentes que permitiera actualizar una aplicación sin revertir otras. Esta PR agrega un stack de cinco servicios por digest, un bootstrap manual por ambiente y un registro confirmado compartido con el futuro CD.

Snippets, Permissions y PrintScript consumen imágenes públicas verificadas y configuración externa; cada ambiente tiene dos PostgreSQL, sus secretos y tres volúmenes propios. Se conserva Compose local. El bootstrap hace preflight, espera convergencia, comprueba SQL/HTTP y sólo entonces confirma las referencias. Prod exige las mismas cuatro imágenes comprobadas en dev.

### Decisiones y alternativas descartadas

| Decisión | Motivo | Alternativa descartada / costo aceptado |
| --- | --- | --- |
| Un stack por ambiente con cinco servicios | Centraliza redes, configuración y nombres de entrega a CD | Stack separado por aplicación: no hace falta para actualizar un servicio de forma independiente; aumenta ensamblado repetido |
| Imágenes por digest; configuración externa | Define exactamente el artefacto ejecutado y permite promocionarlo sin reconstruir | `latest`, tags mutables como referencia operativa o builds en la VM: dificultan reproducibilidad y correspondencia entre ambientes |
| Paquetes públicos actuales de GHCR | Fue la decisión confirmada por el usuario para este bootstrap; habilita pull sin login | Mantener autenticación privada en SNI-24: agrega credenciales que ya no requiere la visibilidad actual. Se acepta acceso público a los artefactos; los secretos de runtime siguen separados |
| Secretos Swarm distintos por VM | PostgreSQL y Spring consumen archivos de secretos sin poner contraseñas en manifiestos o registros | Contraseñas en YAML/ENV del stack, Git o documentación; o reutilizar tokens de build como runtime: mezcla responsabilidades y expone credenciales |
| Volúmenes persistentes para ambas bases y contenido | Conserva datos al recrear tareas; el contenido es escribible por uid 10001 | Filesystem efímero de contenedor, bind mounts de código o ejecutar Snippets como root: no cumplen persistencia/contrato de storage |
| Un nodo por ambiente; bases fijadas a `database=true` | Corresponde a las VMs verificadas y a volúmenes locales | Replicar bases/storage o agregar nodos sin diseñar sus datos: los volúmenes no se replican automáticamente. Ampliar el cluster requiere revisar también la ubicación de Snippets |
| Reinicios y comprobación final, sin `depends_on` | Swarm no ofrece la garantía de disponibilidad que se usa en Compose local | Suponer arranque ordenado de aplicaciones y bases: puede fallar en el primer bootstrap; se observaron arranques recuperados por la política de reinicio |
| Start-first/rollback para aplicaciones; stop-first para bases | Reduce interrupciones de aplicaciones y evita dos tareas de base usando el mismo volumen | Start-first de PostgreSQL: puede iniciar dos procesos sobre el mismo almacenamiento. El solapamiento breve de aplicaciones se acepta; no garantiza cero interrupciones |
| Límites de memoria 768 MiB/app y 512 MiB/base | Mantiene el conjunto dentro de una VM de 8 GiB | JVMs sin límites y sobredimensionamiento sin medir: pueden competir por recursos. Estos valores fueron suficientes para las pruebas; no son un estudio de capacidad de producción |
| Healthcheck más verificación SQL/funcional | Distingue escucha HTTP, salud de datasource y funcionamiento real | Dar por bueno un `docker stack deploy` exitoso, 1/1 réplicas o HTTP 404: no prueban consultas ni contratos. Snippets/PrintScript tienen check de escucha; Permissions incluye datasource |
| Servicio Swarm temporal para probar HTTP interno | Usa la red del stack sin secretos ni puertos y se elimina al terminar | Hacer la overlay `attachable` sólo para adjuntar un contenedor de prueba: amplía acceso a la red sin una necesidad del sistema |
| HTTP por túneles; bases sin puertos publicados | Respeta la red acordada y habilita pruebas desde la computadora | Abrir HTTP/SQL/Docker/Swarm públicamente para facilitar verificación: cambia exposición fuera de este bootstrap |
| Un registro JSON confirmado por ambiente | Mantiene una instantánea coherente de referencias con una implementación pequeña | Referencias antiguas fijas en YAML como autoridad, registros dispersos por servicio o un control plane externo: pueden restaurar versiones viejas, fragmentar estado o exceder el alcance |
| Selección pura y catálogo de servicios centralizado | Permite comprobar preservación de referencias y evita decisiones duplicadas entre verificadores | Mutar el manifiesto recibido o repetir el inventario en cada consumidor: aumenta acoplamiento y riesgo de diferencias. El conjunto de servicios es cerrado por el alcance acordado |
| `flock` y reemplazo atómico del registro | Serializa lectura/modificación/verificación/escritura y evita archivos parcialmente escritos | Read-modify-write fuera del lock o confirmar antes de verificar: puede perder actualizaciones o registrar un despliegue fallido. El bloqueo es cooperativo: SNI-25 debe respetarlo |
| Dev primero; prod con registro confirmado e igualdad de digests | Promueve artefactos que ya funcionaron y prueba separación de datos | Reconstruir para prod o promover sólo porque hubo CI/publicación: no verifica ese artefacto en la VM |
| Pruebas que escriben sólo en dev | Permite recorrer creación, storage y ownership sin datos ficticios en prod | Repetir la suite de creación/ownership en prod: introduce datos de prueba innecesarios. En prod se comprueban SQL, migraciones, salud y consultas de lectura |

### Validación

29 tests locales exitosos, renderizado del stack para dev/prod, validación de Compose local, sintaxis Bash/Python y enlaces Markdown. El CI existente incorpora la validación del stack; el check remoto queda pendiente de publicación de la rama.

En ambas VMs se desplegaron los mismos digests y se comprobaron cinco servicios saludables, SQL autenticado, migraciones y HTTP interno. Dev comprobó creación de Snippets y ownership, una actualización aislada de PrintScript que preservó las otras cuatro tareas y reaplicación de un manifiesto anterior sin revertir referencias ni recrear tareas. Se recrearon las tareas de ambas bases por ambiente y se compararon datos/huellas, conservando también el contenido. Prod mantuvo cero filas funcionales de prueba. Ambas VMs quedaron desasignadas.

### Fuera de alcance, pendientes y límites

- CD automático, runners, triggers, promoción desde Actions y sus secrets: SNI-25 consumirá el contrato de SNI-24. No se activaron los borradores de workflows de despliegue.
- Apertura HTTP pública, dominio, HTTPS de aplicación, proxy/balanceador y autenticación real de usuarios: necesitan coordinación y no fueron necesarios para el bootstrap por túneles.
- Swarm multinodo, HA, replicación de PostgreSQL/storage y almacenamiento remoto: requieren otro diseño. Apagar/perder la VM deja indisponible el ambiente.
- No se implementó respaldo/restauración integral. La prueba de recrear tareas no prueba recuperación de un disco perdido ni de un fallo durante escritura.
- Una validación posterior fallida conserva el último registro confirmado, pero no garantiza rollback de todo el stack. Swarm puede revertir una actualización de servicio; SQL/HTTP fallidos requieren inspección y recuperación explícita.
- El registro guardado en la VM y su copia de promoción se confían mediante el procedimiento SSH verificado. No se implementó firma de releases ni un registro externo replicado.
- El perfil `prod` no habilita la identidad de desarrollo de Snippets. El bootstrap de prod no acredita creación/autenticación de usuarios finales ni todo el negocio de actualizaciones de snippets.
- Contrato local de storage compatible con SNI-8/SNI-17; adaptación a una interfaz futura y otras funcionalidades del dominio pertenecen a sus tickets.
- Publicación, PR, integración y CI remoto son acciones pendientes del usuario. SNI-20 mantiene pendientes los accesos personales de los compañeros y SNI-21 su documentación local.

**Documentos del cambio:** [operación](./sni-24-bootstrap.md), [evidencia](./sni-24-evidencia.md) y [comandos de entrega](./sni-24-entrega.md).

## Lectura del contexto histórico

La guía de SNI-20 registra el supuesto original de imágenes privadas y conectividad al 11/10. Para SNI-24, el usuario confirmó el 12/10 usar los paquetes públicos actuales. El diseño final de SNI-24 usa pull público; no atribuir a SNI-20 una decisión de cambiar visibilidad ni afirmar que su HTTP 401 acredita un pull privado.

SNI-21 describe recursos temporales vacíos al terminar su prueba del motor. Posteriormente SNI-24 creó las aplicaciones, secretos definitivos y volúmenes persistentes. No interpretar el inventario histórico vacío de SNI-21 como el inventario actual del stack.
