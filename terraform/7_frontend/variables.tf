variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

# Clerk validation happens in Lambda, not at API Gateway level
variable "clerk_jwks_url" {
  description = "Clerk JWKS URL for JWT validation in Lambda"
  type        = string
}

variable "clerk_issuer" {
  description = "Clerk issuer URL (kept for Lambda environment)"
  type        = string
  default     = "" # Not actually used but kept for backwards compatibility
}

variable "polygon_api_key" {
  description = "Polygon.io API key for market data (used by /api/market/timeseries)"
  type        = string
  default     = ""
}
