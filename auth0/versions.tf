terraform {
  required_version = "~> 1.13.0"

  required_providers {
    auth0 = {
      source  = "auth0/auth0"
      version = "1.56.0"
    }
  }
}

# Credentials come from the operator environment, never from tfvars or outputs.
# The explicit domain must agree with the reviewed tenant before any real plan.
provider "auth0" {
  domain = var.tenant_domain
}
