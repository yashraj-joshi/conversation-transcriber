data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  data_bucket = "${var.project}-data-${local.account_id}"
  web_bucket  = "${var.project}-web-${local.account_id}"
  app_origin  = "https://${aws_cloudfront_distribution.web.domain_name}"
  origins     = concat([local.app_origin], var.extra_allowed_origins)

  model_param_name   = "/${var.project}/transcription-model"
  api_key_param_name = "/${var.project}/openrouter-api-key"
  summary_param_name = "/${var.project}/summary-model"
  vocabulary_key     = "config/vocabulary.txt"
}
