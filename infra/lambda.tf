# --- Configuration in SSM Parameter Store (spec 002 FR-002, FR-003) --------------------------------

# Transcription model id. Terraform sets the initial value only; change it with scripts/set-model.sh.
resource "aws_ssm_parameter" "transcription_model" {
  name        = local.model_param_name
  description = "OpenRouter speech-to-text model used for new transcriptions"
  type        = "String"
  value       = var.transcription_model

  lifecycle {
    ignore_changes = [value]
  }
}

# OpenRouter API key. Placeholder only; the real value is written by scripts/set-openrouter-key.sh
# so it never enters Terraform state or source control (Constitution III/IV).
resource "aws_ssm_parameter" "openrouter_api_key" {
  name        = local.api_key_param_name
  description = "OpenRouter API key (set out-of-band)"
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}

# --- Package ---------------------------------------------------------------------------------------

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/src"
  output_path = "${path.module}/build/lambda.zip"
  excludes    = ["__pycache__"]
}

# --- IAM -------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${var.project}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "transcriber" {
  name               = "${var.project}-transcriber"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
  statement {
    sid       = "AudioWrite" # signs presigned POSTs and writes manifests
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/audio/*"]
  }
  statement {
    sid     = "Read"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/status/*",
      "${aws_s3_bucket.data.arn}/transcripts/*",
    ]
  }
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["audio/*", "status/*", "transcripts/", "transcripts/*"]
    }
  }
}

data "aws_iam_policy_document" "transcriber" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.transcriber.arn}:*"]
  }
  statement {
    sid     = "Read"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/audio/*",
      "${aws_s3_bucket.data.arn}/status/*",
      "${aws_s3_bucket.data.arn}/work/*",
      "${aws_s3_bucket.data.arn}/${local.vocabulary_key}",
    ]
  }
  statement {
    sid     = "Write"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/status/*",
      "${aws_s3_bucket.data.arn}/work/*",
      "${aws_s3_bucket.data.arn}/transcripts/*",
    ]
  }
  statement {
    sid       = "List" # so a missing status/work/vocabulary object reads as NoSuchKey, not AccessDenied
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["status/*", "work/*", local.vocabulary_key]
    }
  }
  statement {
    sid       = "Config"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.transcription_model.arn, aws_ssm_parameter.openrouter_api_key.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_iam_role_policy" "transcriber" {
  role   = aws_iam_role.transcriber.id
  policy = data.aws_iam_policy_document.transcriber.json
}

# --- Functions -------------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.project}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "transcriber" {
  name              = "/aws/lambda/${var.project}-transcriber"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "api.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      DATA_BUCKET = aws_s3_bucket.data.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

resource "aws_lambda_function" "transcriber" {
  function_name    = "${var.project}-transcriber"
  role             = aws_iam_role.transcriber.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "transcriber.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 1024
  timeout          = 900

  environment {
    variables = {
      DATA_BUCKET            = aws_s3_bucket.data.id
      MODEL_PARAM            = aws_ssm_parameter.transcription_model.name
      API_KEY_PARAM          = aws_ssm_parameter.openrouter_api_key.name
      VOCABULARY_KEY         = local.vocabulary_key
      DATA_COLLECTION        = var.openrouter_data_collection
      TRANSCRIBE_PARALLELISM = tostring(var.transcribe_parallelism)
      DIARIZE                = tostring(var.speaker_labels)
    }
  }

  depends_on = [aws_cloudwatch_log_group.transcriber, aws_iam_role_policy.transcriber]
}

# A failed run must not silently re-bill OpenRouter; the user retries explicitly (001 research R6).
resource "aws_lambda_function_event_invoke_config" "transcriber" {
  function_name          = aws_lambda_function.transcriber.function_name
  maximum_retry_attempts = 0
}

resource "aws_lambda_permission" "s3_invoke" {
  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.transcriber.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.data.arn
  source_account = local.account_id
}

resource "aws_s3_bucket_notification" "manifest" {
  bucket = aws_s3_bucket.data.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.transcriber.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "audio/"
    filter_suffix       = "manifest.json"
  }

  depends_on = [aws_lambda_permission.s3_invoke]
}
