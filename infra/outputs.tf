output "app_url" {
  description = "Open this on the iPhone and on the computer (same URL)."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "data_bucket" {
  value = aws_s3_bucket.data.id
}

output "region" {
  value = var.region
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "user_pool_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "model_parameter" {
  description = "SSM parameter holding the transcription model id."
  value       = aws_ssm_parameter.transcription_model.name
}

output "summary_model_parameter" {
  description = "SSM parameter holding the title/summary model id."
  value       = aws_ssm_parameter.summary_model.name
}

output "api_key_parameter" {
  description = "SSM SecureString holding the OpenRouter API key."
  value       = aws_ssm_parameter.openrouter_api_key.name
}

output "vocabulary_s3_uri" {
  value = "s3://${aws_s3_bucket.data.id}/${local.vocabulary_key}"
}

output "project_name" {
  value = var.project
}
