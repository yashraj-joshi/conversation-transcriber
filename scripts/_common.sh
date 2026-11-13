#!/usr/bin/env bash
# Shared helpers: read deployed values from Terraform outputs.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tf_out() { terraform -chdir="$ROOT/infra" output -raw "$1"; }
REGION="${AWS_REGION:-$(tf_out region)}"
export AWS_REGION="$REGION"
