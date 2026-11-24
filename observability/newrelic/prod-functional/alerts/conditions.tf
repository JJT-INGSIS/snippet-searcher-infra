variable "prod_alert_policy_id" {
  description = "ID de la política PROD que recibe el workflow de correo y push de SNI-89."
  type        = number
}

locals {
  prod_functional_signal = "FROM SnippetFunctionalCheck WHERE environment = 'prod' AND checkName = 'snippet-searcher-prod-functional-listing'"
}

resource "newrelic_nrql_alert_condition" "prod_functional_failure" {
  account_id                   = var.newrelic_account_id
  policy_id                    = var.prod_alert_policy_id
  type                         = "static"
  name                         = "PROD - Chequeo funcional de listado falló"
  description                  = "Responsable: Thiago. Revisar failureCategory y el servicio correspondiente. Se recupera con un chequeo exitoso."
  aggregation_method           = "event_timer"
  aggregation_window           = 60
  aggregation_timer            = 60
  violation_time_limit_seconds = 86400

  nrql {
    query = "SELECT filter(count(*), WHERE result = 'FAILURE') ${local.prod_functional_signal}"
  }

  critical {
    operator              = "above"
    threshold             = 0
    threshold_duration    = 60
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "prod_functional_missing" {
  account_id                   = var.newrelic_account_id
  policy_id                    = var.prod_alert_policy_id
  type                         = "static"
  name                         = "PROD - Chequeo funcional sin resultados"
  description                  = "Responsable: Thiago. Revisar timer de PROD y último estado de Event API. Se recupera al recibir un resultado."
  aggregation_method           = "event_timer"
  aggregation_window           = 60
  aggregation_timer            = 60
  expiration_duration          = 46800
  open_violation_on_expiration = true
  violation_time_limit_seconds = 86400

  nrql {
    query = "SELECT count(*) ${local.prod_functional_signal}"
  }
}
