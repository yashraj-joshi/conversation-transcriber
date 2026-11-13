#!/usr/bin/env bash
# Change the transcription model (takes effect for the next recording; no redeploy).
# Usage: ./scripts/set-model.sh microsoft/mai-transcribe-2
#        ./scripts/set-model.sh            (shows the current model and the available STT models)
source "$(dirname "$0")/_common.sh"
PARAM="$(tf_out model_parameter)"
if [[ $# -eq 0 ]]; then
  echo "Current model: $(aws ssm get-parameter --name "$PARAM" --query Parameter.Value --output text)"
  echo "Speech-to-text models on OpenRouter:"
  curl -fsS "https://openrouter.ai/api/v1/models?output_modalities=transcription" \
    | python3 -c 'import json,sys; [print("  " + m["id"]) for m in json.load(sys.stdin).get("data", [])]' \
    || echo "  (could not list models)"
  exit 0
fi
aws ssm put-parameter --name "$PARAM" --type String --overwrite --value "$1" >/dev/null
echo "Transcription model set to '$1' ($PARAM). The next recording will use it."
