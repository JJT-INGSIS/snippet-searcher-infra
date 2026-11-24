# Agente, colector y logs

El agente oficial de infraestructura corre en cada host mediante un Compose
independiente. Necesita acceso a Docker y al host. El colector de Swarm se
ejecuta en redes privadas con secretos de monitoreo, sin socket Docker ni
licencia de New Relic. Lee PostgreSQL y, donde esté habilitado, Redis. El
probe de storage local usa un fixture sintético. Las imágenes y paquetes se
fijan en [el lock del runtime](images.lock.json) y
[el lock de integraciones](../integrations.lock.json).

| Componente | Configuración |
| --- | --- |
| Agente y despacho al colector | [agent.compose.yaml](agent.compose.yaml), [dispatch.sh](dispatch.sh) |
| Colector privado | [collector.stack.yaml](collector.stack.yaml), [collect.py](collect.py) |
| Muestras de servicios | [swarm_sample.py](swarm_sample.py) |
| Logs de host e ingreso | [Fluent Bit](../logs/fluent-bit.conf) |
| APM Java | [Overlay de Swarm](../../swarm/stack.apm.yaml) |

## Operación

1. Confirmá el host, release y topología. Comprobá salud, mounts, puertos y
   espacio antes de preparar cambios. Los defaults de DEV y PROD responden
   a topologías distintas.
2. Para una instalación DEV, los scripts
   [prepare](../../scripts/prepare_observability_dev.py),
   [provision](../../scripts/provision_observability_dev.py),
   [verify](../../scripts/verify_observability_dev.py) y
   [start](../../scripts/start_observability_dev.py) separan preparación,
   cambios al runtime, comprobación e ingesta. Provisionar puede reiniciar
   dependencias. Para una instalación DEV existente, revisá el
   [upgrade versionado](../../scripts/upgrade_observability_runtime_dev.py)
   antes de intervenir. [Forwarder DEV](../../scripts/start_log_forwarder_dev.py).
3. Para PROD, [production_observability_runtime.py](../../scripts/production_observability_runtime.py)
   expone `stage`, `provision`, `verify` y `start` para la topología PROD con
   storage local. Provision exige el SHA-256 del release confirmado revisado.
   Conservá el estado parcial protegido si
   falla una etapa y conciliá antes de repetir. Las claves de ingesta se entregan
   por stdin y se guardan fuera del repositorio.
4. Comprobá muestras nuevas y consumo del ambiente en New Relic. Si se retira
   instrumentación, actuá sobre su contenedor y stack exclusivos. Conservá
   datos, redes externas y secretos todavía montados. [Diagnóstico](../../docs/observability/README.md#diagnóstico-de-alertas).

Las métricas de infraestructura, los logs y APM son señales distintas. La
frescura de una de ellas no acredita salud del resto del pipeline de ingesta.
