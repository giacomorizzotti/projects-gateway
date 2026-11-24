// The contract mini's stores/auth.js expects (see mini_vue's CLAUDE.md).
// The app is a public OAuth 2 client with PKCE on your auth server, so there's no secret.
// Both values come from the environment at build time: frontend/.env.local in development,
// build arguments from the repo-root .env in Docker (docker-compose.yml).
const AUTH_SERVER_BASE = (import.meta.env.VITE_AUTH_SERVER_BASE || '').replace(/\/$/, '')

export const OAUTH_AUTHORIZE_ENDPOINT = `${AUTH_SERVER_BASE}/o/authorize/`
export const OAUTH_TOKEN_ENDPOINT = `${AUTH_SERVER_BASE}/o/token/`
export const OAUTH_REVOKE_ENDPOINT = `${AUTH_SERVER_BASE}/o/revoke_token/`
export const OAUTH_USERINFO_ENDPOINT = `${AUTH_SERVER_BASE}/o/userinfo/`

export const OAUTH_CLIENT_ID = import.meta.env.VITE_OAUTH_CLIENT_ID || ''
export const OAUTH_CLIENT_SECRET = ''
export const OAUTH_SCOPE = 'openid profile email'
