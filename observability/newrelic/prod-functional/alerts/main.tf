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

provider "newrelic" {
  account_id = var.newrelic_account_id
  region     = "US"
}

variable "prod_snippets_guid" {
  description = "GUID APM verificado de snippets-service (prod)."
  type        = string
}

locals {
  api_ingress         = "logtype = 'nginx-ingress' AND route IN ('api', 'executions') AND path != '/api/languages'"
  http_success        = "status >= 200 AND status < 300"
  http_failure        = "status >= 500 AND status < 600"
  api_valid           = "${local.api_ingress} AND ((${local.http_success}) OR (${local.http_failure}))"
  functional_identity = "environment = 'prod' AND checkName = 'snippet-searcher-prod-functional-listing'"
  functional_valid    = "result IN ('SUCCESS', 'FAILURE')"
}
