#!/usr/bin/env bash
# Store the OpenRouter API key in SSM Parameter Store (SecureString). The key never touches
# Terraform state, the shell history, or the process list.
# Usage: ./scripts/set-openrouter-key.sh            (prompts)
#        OPENROUTER_API_KEY=sk-or-... ./scripts/set-openrouter-key.sh
source "$(dirname "$0")/_common.sh"
PARAM="$(tf_out api_key_parameter)"
KEY="${OPENROUTER_API_KEY:-}"
if [[ -z "$KEY" ]]; then
  read -r -s -p "OpenRouter API key (input hidden): " KEY
  echo
fi
[[ "$KEY" == sk-or-* ]] || echo "warning: OpenRouter keys usually start with 'sk-or-'" >&2
TMP="$(mktemp)"
chmod 600 "$TMP"
trap 'rm -f "$TMP"' EXIT
python3 -c 'import json,sys; json.dump({"Name": sys.argv[1], "Value": sys.argv[2], "Type": "SecureString", "Overwrite": True}, open(sys.argv[3], "w"))' "$PARAM" "$KEY" "$TMP"
aws ssm put-parameter --cli-input-json "file://$TMP" >/dev/null
echo "Stored OpenRouter key in $PARAM ($REGION)."
echo "The transcriber re-reads the key at least every 10 minutes (immediately after a rejected key)."
