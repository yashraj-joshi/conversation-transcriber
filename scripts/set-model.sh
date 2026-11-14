#!/usr/bin/env bash
# Change a model setting (takes effect for the next transcript; no redeploy).
# Usage: ./scripts/set-model.sh                                  show both models + available STT models
#        ./scripts/set-model.sh microsoft/mai-transcribe-2       set the transcription model
#        ./scripts/set-model.sh --summary anthropic/claude-haiku-5.5   set the title/summary model ("none" = off)
source "$(dirname "$0")/_common.sh"
PARAM="$(tf_out model_parameter)"
KIND="Transcription"
if [[ "${1:-}" == "--summary" ]]; then
  shift
  PARAM="$(tf_out summary_model_parameter)"
  KIND="Title/summary"
fi
if [[ $# -eq 0 ]]; then
  echo "Transcription model: $(aws ssm get-parameter --name "$(tf_out model_parameter)" --query Parameter.Value --output text)"
  echo "Title/summary model: $(aws ssm get-parameter --name "$(tf_out summary_model_parameter)" --query Parameter.Value --output text)"
  echo "Speech-to-text models on OpenRouter:"
  curl -fsS "https://openrouter.ai/api/v1/models?output_modalities=transcription" \
    | python3 -c 'import json,sys; [print("  " + m["id"]) for m in json.load(sys.stdin).get("data", [])]' \
    || echo "  (could not list models)"
  exit 0
fi
aws ssm put-parameter --name "$PARAM" --type String --overwrite --value "$1" >/dev/null
echo "$KIND model set to '$1' ($PARAM). The next transcript will use it."
