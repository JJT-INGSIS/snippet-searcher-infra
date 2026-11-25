# Terraform de alertas, tableros y SLO de DEV

Este directorio es una raíz independiente. Las políticas y workflows existentes se referencian por ID. Los monitores y el chequeo funcional de DEV conservan el
estado de [la raíz padre](../README.md).

## Ejecutar en la cuenta del equipo

Proveer la User API key al proceso por `NEW_RELIC_API_KEY`. Usar las políticas
DEV de disponibilidad y warnings, y el GUID de `snippets-service (dev)`.
Los valores de cuenta, políticas y GUID son identificadores, no secretos.

```powershell
$env:TF_VAR_newrelic_account_id = '8718557'
$env:TF_VAR_dev_critical_policy_id = '8318071'
$env:TF_VAR_dev_warning_policy_id = '8318260'
$env:TF_VAR_dev_snippets_guid = 'ODcxODU1N3xBUE18QVBQTElDQVRJT058MTAxMDM1ODM2Ng'
terraform init
terraform fmt -check
terraform validate
terraform plan -out sni86.tfplan
terraform apply sni86.tfplan
terraform output dashboard_links
```

Revisar cuenta, filtros DEV y acciones antes de aplicar. Conservar el estado
local en un almacenamiento privado del equipo. Si se pierde el estado,
importar las condiciones, tableros y SLO existentes antes de planificar.
`newrelic_nrql_alert_condition` importa con
`POLICY_ID:CONDITION_ID:static`, `newrelic_one_dashboard_json` con el GUID,
y `newrelic_service_level` con `ACCOUNT_ID:SLI_ID:GUID`. Confirmar los
identificadores con la API. Los archivos de estado y los planes están
excluidos por Git. La clave de usuario se puede revocar después de aplicar.
Ver el [runbook](../../../docs/observability/README.md).
