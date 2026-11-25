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
  description = "Cuenta de New Relic del equipo."
  type        = number
}

variable "newrelic_api_key" {
  description = "User API key de New Relic; proveer mediante variable de entorno."
  type        = string
  sensitive   = true
}

variable "dev_base_url" {
  description = "URL HTTPS pública de DEV, sin barra final."
  type        = string
}

provider "newrelic" {
  account_id = var.newrelic_account_id
  api_key    = var.newrelic_api_key
  region     = "US"
}

resource "newrelic_synthetics_monitor" "dev_ui" {
  name                = "snippet-searcher-dev-ui-disponibilidad"
  type                = "SIMPLE"
  status              = "ENABLED"
  period              = "EVERY_15_MINUTES"
  locations_public    = ["SA_EAST_1"]
  uri                 = "${var.dev_base_url}/"
  verify_ssl          = true
  bypass_head_request = true

  tag {
    key    = "environment"
    values = ["dev"]
  }
}

resource "newrelic_synthetics_monitor" "dev_api" {
  name                      = "snippet-searcher-dev-api-disponibilidad"
  type                      = "SIMPLE"
  status                    = "ENABLED"
  period                    = "EVERY_15_MINUTES"
  locations_public          = ["SA_EAST_1"]
  uri                       = "${var.dev_base_url}/api/languages"
  verify_ssl                = true
  bypass_head_request       = true
  treat_redirect_as_failure = true
  validation_string         = "printscript"

  tag {
    key    = "environment"
    values = ["dev"]
  }
}
