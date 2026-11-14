variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for resources and SSM parameters (lowercase letters, digits, hyphens)."
  type        = string
  default     = "conversation-transcriber"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.project))
    error_message = "project must be 3-31 chars: lowercase letters, digits, hyphens."
  }
}

variable "transcription_model" {
  description = "INITIAL value of the SSM model parameter. Later changes are made with scripts/set-model.sh; Terraform ignores drift on this value."
  type        = string
  default     = "microsoft/mai-transcribe-2"
}

variable "summary_model" {
  description = "INITIAL value of the SSM summary-model parameter (AI titles/summaries). Change later with scripts/set-model.sh --summary; set the parameter to \"none\" to turn titles off."
  type        = string
  default     = "anthropic/claude-haiku-5.5"
}

variable "openrouter_data_collection" {
  description = "OpenRouter provider.data_collection: \"deny\" routes only to providers that do not store/train on audio; \"allow\" relaxes it."
  type        = string
  default     = "deny"

  validation {
    condition     = contains(["deny", "allow"], var.openrouter_data_collection)
    error_message = "openrouter_data_collection must be \"deny\" or \"allow\"."
  }
}

variable "speaker_labels" {
  description = "Ask the model for speaker labels (diarization). Labels are per 5-minute part. Off by default."
  type        = bool
  default     = false
}

variable "transcribe_parallelism" {
  description = "How many audio parts are sent to OpenRouter at the same time."
  type        = number
  default     = 4
}

variable "audio_retention_days" {
  description = "Days to keep raw audio (and per-part results) before automatic deletion."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the Lambda functions."
  type        = number
  default     = 30
}

variable "protect_user_pool" {
  description = "Cognito deletion protection. Set false (and apply) before `terraform destroy`."
  type        = bool
  default     = true
}

variable "extra_allowed_origins" {
  description = "Extra browser origins allowed by CORS, e.g. [\"http://localhost:8000\"] for local frontend development."
  type        = list(string)
  default     = []
}
