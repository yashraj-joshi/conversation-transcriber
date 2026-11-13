#!/usr/bin/env bash
# Create (or reset) a user with a permanent password. Self sign-up is disabled (001 FR-002).
# Usage: ./scripts/create-user.sh you@example.com
source "$(dirname "$0")/_common.sh"
EMAIL="${1:?usage: create-user.sh <email>}"
POOL="$(tf_out user_pool_id)"
read -r -s -p "Password for $EMAIL (min 12 chars, upper+lower+digit): " PASSWORD
echo
if ! aws cognito-idp admin-get-user --user-pool-id "$POOL" --username "$EMAIL" >/dev/null 2>&1; then
  aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$EMAIL" \
    --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
    --message-action SUPPRESS >/dev/null
fi
TMP="$(mktemp)"
chmod 600 "$TMP"
trap 'rm -f "$TMP"' EXIT
python3 -c 'import json,sys; json.dump({"UserPoolId": sys.argv[1], "Username": sys.argv[2], "Password": sys.argv[3], "Permanent": True}, open(sys.argv[4], "w"))' "$POOL" "$EMAIL" "$PASSWORD" "$TMP"
aws cognito-idp admin-set-user-password --cli-input-json "file://$TMP"
echo "User $EMAIL is ready. Sign in at $(tf_out app_url)"
