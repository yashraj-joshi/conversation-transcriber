#!/usr/bin/env bash
# Upload config/vocabulary.txt to S3 without a full `terraform apply`.
# (A later `terraform apply` uploads the same file, so keep the repo file as the source of truth.)
source "$(dirname "$0")/_common.sh"
python3 - "$ROOT/config/vocabulary.txt" <<'PY'
import sys
sys.path.insert(0, sys.argv[1].rsplit("/config/", 1)[0] + "/backend/src")
import core
terms, skipped = core.parse_vocabulary(open(sys.argv[1], encoding="utf-8").read())
print(f"{len(terms)} terms; {len(skipped)} skipped")
for term, reason in skipped:
    print(f"  skipped ({reason}): {term}")
PY
aws s3 cp "$ROOT/config/vocabulary.txt" "$(tf_out vocabulary_s3_uri)" \
  --content-type "text/plain; charset=utf-8" --cache-control no-cache
echo "Vocabulary uploaded. The next recording will use it."
