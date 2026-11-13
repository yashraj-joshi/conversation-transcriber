// Terraform generates config.js from the deployed resources. For local development copy this file to
// frontend/config.js and fill it in from `terraform -chdir=infra output` (config.js is git-ignored).
window.APP_CONFIG = {
  region: 'us-east-1',
  userPoolClientId: 'REPLACE_WITH_user_pool_client_id',
  apiUrl: 'https://REPLACE.execute-api.us-east-1.amazonaws.com',
};
