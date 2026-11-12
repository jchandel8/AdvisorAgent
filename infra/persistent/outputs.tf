# Copy these into .env (locally) or the ECS task settings (step 5).
output "COGNITO_REGION" {
  value = var.region
}
output "COGNITO_USER_POOL_ID" {
  value = aws_cognito_user_pool.main.id
}
output "COGNITO_CLIENT_ID" {
  value = aws_cognito_user_pool_client.web.id
}
output "COGNITO_DOMAIN" {
  value = "${aws_cognito_user_pool_domain.hosted.domain}.auth.${var.region}.amazoncognito.com"
}
