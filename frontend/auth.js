// Cognito USER_PASSWORD_AUTH + refresh, using the Cognito JSON API directly (no SDK; 001 research R7).
const cfg = () => window.APP_CONFIG || {};
const REFRESH_KEY = 'ct.refreshToken';
const EMAIL_KEY = 'ct.email';
const ID_KEY = 'ct.idToken';

export class AuthError extends Error {}

async function cognito(target, body) {
  const resp = await fetch(`https://cognito-idp.${cfg().region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const type = String(data.__type || '').split('#').pop();
    const messages = {
      NotAuthorizedException: 'Incorrect email or password.',
      UserNotFoundException: 'Incorrect email or password.',
      PasswordResetRequiredException: 'A password reset is required. Ask the administrator.',
      UserNotConfirmedException: 'This account is not confirmed yet.',
      TooManyRequestsException: 'Too many attempts. Wait a minute and try again.',
    };
    throw new AuthError(messages[type] || data.message || `Sign-in failed (${resp.status}).`);
  }
  return data;
}

function decodeExp(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(payload)).exp * 1000;
  } catch {
    return 0;
  }
}

function safeGet(storage, key) {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(storage, key, value) {
  try {
    if (value == null) storage.removeItem(key);
    else storage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

let idToken = safeGet(sessionStorage, ID_KEY);

export function isSignedIn() {
  return !!safeGet(localStorage, REFRESH_KEY);
}

export function email() {
  return safeGet(localStorage, EMAIL_KEY) || '';
}

export async function signIn(user, password) {
  const data = await cognito('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: cfg().userPoolClientId,
    AuthParameters: { USERNAME: user, PASSWORD: password },
  });
  if (data.ChallengeName) {
    throw new AuthError(`Additional sign-in step required (${data.ChallengeName}). Ask the administrator to set a permanent password.`);
  }
  const result = data.AuthenticationResult;
  idToken = result.IdToken;
  safeSet(sessionStorage, ID_KEY, idToken);
  safeSet(localStorage, REFRESH_KEY, result.RefreshToken);
  safeSet(localStorage, EMAIL_KEY, user);
}

export function signOut() {
  idToken = null;
  safeSet(sessionStorage, ID_KEY, null);
  safeSet(localStorage, REFRESH_KEY, null);
}

/** A valid ID token, refreshing it if it expires within a minute. Throws AuthError when signed out. */
export async function getIdToken({ force = false } = {}) {
  if (!force && idToken && decodeExp(idToken) - Date.now() > 60_000) return idToken;
  const refresh = safeGet(localStorage, REFRESH_KEY);
  if (!refresh) throw new AuthError('Please sign in.');
  try {
    const data = await cognito('InitiateAuth', {
      AuthFlow: 'REFRESH_TOKEN_AUTH',
      ClientId: cfg().userPoolClientId,
      AuthParameters: { REFRESH_TOKEN: refresh },
    });
    idToken = data.AuthenticationResult.IdToken;
    safeSet(sessionStorage, ID_KEY, idToken);
    return idToken;
  } catch (err) {
    if (err instanceof AuthError) {
      signOut();
      throw new AuthError('Your session expired. Please sign in again.');
    }
    throw err; // network error: keep the refresh token
  }
}
