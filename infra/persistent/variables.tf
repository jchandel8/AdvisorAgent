variable "region" {
  type    = string
  default = "us-west-1"
}

variable "app_urls" {
  description = "Origins where the web app runs. Sign-in returns to <url>/auth/callback; sign-out to <url>/login."
  type        = list(string)
  # Only used when the Cognito client is first created. After that the Deploy workflow adds the current AWS
  # URL itself (cognito.tf ignores later changes to the lists), because that URL changes after a teardown.
  default = ["http://localhost:4200"]
}
