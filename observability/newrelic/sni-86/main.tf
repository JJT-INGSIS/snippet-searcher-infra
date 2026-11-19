terraform {
  required_version = ">= 1.5.0"

  required_providers {
    newrelic = {
      source  = "newrelic/newrelic"
      version = "~> 3.75.3"
    }
  }
}

variable "newrelic_account_id" {
  description = "Cuenta US de New Relic del equipo."
  type        = number
}

variable "dev_critical_policy_id" {
  description = "Política de disponibilidad DEV existente (correo y push)."
  type        = number
}

variable "dev_warning_policy_id" {
  description = "Política de warnings DEV existente (correo)."
  type        = number
}

variable "dev_snippets_guid" {
  description = "GUID de la entidad APM snippets-service (dev), donde se publican los SLO."
  type        = string
}

provider "newrelic" {
  account_id = var.newrelic_account_id
  region     = "US"
}

locals {
  runbook_url = "https://github.com/JJT-INGSIS/snippet-searcher-infra/blob/dev/docs/observability/sni-86-alerts-dashboards.md"

  api_ingress  = "logtype = 'nginx-ingress' AND route IN ('api', 'executions') AND path != '/api/languages'"
  http_success = "status >= 200 AND status < 300"
  http_failure = "status >= 500 AND status < 600"
  api_valid    = "${local.api_ingress} AND ((${local.http_success}) OR (${local.http_failure}))"

  functional_identity = "environment = 'dev' AND checkName = 'snippet-searcher-dev-functional-listing'"
  functional_valid    = "result IN ('SUCCESS', 'FAILURE')"

  lag            = "filter(max(lag), WHERE aspect = 'stream' AND lagKnown = true AND samplerError = false)"
  eligible_age   = "filter(max(oldestEligibleSeconds), WHERE aspect = 'jobs' AND reaction = 'all' AND samplerError = false)"
  consumer_delay = "clamp_max(${local.lag}, 1) * ${local.eligible_age}"
}
