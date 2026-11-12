variable "region" {
  type    = string
  default = "us-west-1"
}

variable "app_urls" {
  description = "Origins where the web app runs. Sign-in returns to <url>/auth/callback; sign-out to <url>/login."
  type        = list(string)
  default     = ["http://localhost:4200"] # step 5 adds the AWS URL
}
