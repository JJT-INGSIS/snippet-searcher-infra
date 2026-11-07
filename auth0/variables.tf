variable "tenant_domain" {
  description = "Development tenant hostname from Auth0, without scheme or slash."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9-]+(\\.[a-z0-9-]+)?\\.auth0\\.com$", var.tenant_domain))
    error_message = "Use the exact Auth0 tenant hostname, not a URL or an invented placeholder."
  }
}

variable "api_audience" {
  description = "Reviewed identifier for the Snippets development API; not the Management API."
  type        = string
  validation {
    condition     = can(regex("^https://[^/?#\\s]+(/[^?#\\s]*)?$", var.api_audience)) && !endswith(var.api_audience, "/api/v2/")
    error_message = "Use an HTTPS API identifier without query or fragment, different from the Management API audience."
  }
}

variable "ui_origins" {
  description = "Exact development origins. HTTPS, or HTTP only on localhost/127.0.0.1 with an explicit port."
  type        = set(string)
  validation {
    condition = length(var.ui_origins) > 0 && alltrue([
      for origin in var.ui_origins : can(regex("^(https://[a-z0-9.-]+(:[0-9]+)?|http://(localhost|127\\.0\\.0\\.1):[0-9]+)$", origin)) && !strcontains(origin, "*")
    ])
    error_message = "Origins must be exact HTTPS origins or HTTP loopback origins with port; no paths, trailing slash, wildcard, query or fragment."
  }
}

variable "database_connection_id" {
  description = "Existing Auth0 database connection selected by the team. Only this SPA's association is managed."
  type        = string
  validation {
    condition     = can(regex("^con_[A-Za-z0-9]+$", var.database_connection_id))
    error_message = "Supply the actual con_ identifier of the selected Auth0 database connection."
  }
}

variable "access_token_lifetime_seconds" {
  description = "Positive whole-second access token lifetime, to be agreed before applying. No default policy is invented."
  type        = number
  validation {
    condition     = var.access_token_lifetime_seconds > 0 && floor(var.access_token_lifetime_seconds) == var.access_token_lifetime_seconds
    error_message = "Token lifetime must be a positive integer."
  }
}
