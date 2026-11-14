#!/usr/bin/env bash
# Add AI titles/summaries to existing transcripts of a month (spec 004 FR-009).
# Usage: ./scripts/retitle.sh 2026-11 [--force]     (--force regenerates titles that already exist)
source "$(dirname "$0")/_common.sh"
MONTH="${1:?usage: retitle.sh YYYY-MM [--force]}"
FORCE=false; [[ "${2:-}" == "--force" ]] && FORCE=true
OUT="$(mktemp)"; trap 'rm -f "$OUT"' EXIT
aws lambda invoke --function-name "$(tf_out project_name)-transcriber" --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 900 --payload "{\"action\":\"retitle\",\"month\":\"$MONTH\",\"force\":$FORCE}" "$OUT" >/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
print("updated:", len(d.get("updated", [])), "| skipped (already titled):", len(d.get("skipped", [])), "| failed:", len(d.get("failed", [])))
[print("  failed:", k) for k in d.get("failed", [])]
"errorMessage" in d and print("error:", d["errorMessage"])' "$OUT"
