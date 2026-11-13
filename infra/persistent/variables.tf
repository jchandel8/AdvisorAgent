variable "region" {
  type    = string
  default = "us-west-1"
}

variable "app_urls" {
  description = "Origins where the web app runs. Sign-in returns to <url>/auth/callback; sign-out to <url>/login."
  type        = list(string)
  default = [
    "http://localhost:4200",
    "https://ad-4e693211c8514b9389b0a39a34b07394.ecs.us-west-1.on.aws", # AWS demo (ECS Express); changes if the service is re-created
  ]
}
