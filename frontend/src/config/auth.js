// The contract mini's stores/auth.js and views/LoginView.vue expect (see mini_vue's CLAUDE.md).
// The values come from the gateway's own API when the app starts (main.js waits for
// loadAuthConfig): the backend reads them from the OpenID Connect provider's discovery document
// (OIDC_ISSUER and OIDC_CLIENT_ID in .env), so nothing about the provider is built in.
// They're `let` exports: mini's modules import them by name, and an ES module import is a live
// binding, so they see the values once loaded.
// A public client with PKCE: there's no secret.
export let OAUTH_AUTHORIZE_ENDPOINT = ''
export let OAUTH_TOKEN_ENDPOINT = ''
export let OAUTH_REVOKE_ENDPOINT = ''      // '' when the provider doesn't list one
export let OAUTH_USERINFO_ENDPOINT = ''
export let OAUTH_CLIENT_ID = ''
export const OAUTH_CLIENT_SECRET = ''
export let OAUTH_SCOPE = 'openid profile email'

export async function loadAuthConfig() {
  const response = await fetch('/api/auth/config/', { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`Sign-in settings unavailable (${response.status})`)
  const config = await response.json()
  OAUTH_AUTHORIZE_ENDPOINT = config.authorization_endpoint
  OAUTH_TOKEN_ENDPOINT = config.token_endpoint
  OAUTH_REVOKE_ENDPOINT = config.revocation_endpoint || ''
  OAUTH_USERINFO_ENDPOINT = config.userinfo_endpoint
  OAUTH_CLIENT_ID = config.client_id
  OAUTH_SCOPE = config.scope || OAUTH_SCOPE
}
