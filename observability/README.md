# Configuración de observabilidad

La [guía de observabilidad](../docs/observability/README.md) explica las señales
de DEV y PROD, el diagnóstico y la evidencia disponible.

- [Runtime](runtime/README.md) cubre el agente de infraestructura, el colector
  y el forwarder de logs. `config.example.json` y `config.prod-local.example.json`
  describen topologías de ejemplo. Contrastá cada una con el release efectivo.
- [New Relic](newrelic/README.md) cubre Terraform, Synthetics y los chequeos
  autenticados.
- `qa/` y `scripts/verify_observability.py` ejecutan verificaciones aisladas de
  colectores y storage. `drills/` contiene herramientas y consultas de ensayo
  para DEV. Los datos de aceptación de referencia están enlazados desde la guía.
