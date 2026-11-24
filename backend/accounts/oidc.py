"""The OpenID Connect provider: its endpoints, from OIDC_ISSUER's discovery document.

Any provider that publishes one works (django-oauth-toolkit, Keycloak, Authentik, Authelia,
Zitadel, GitLab, Google…). The document is fetched once an hour per process: the backend uses
its userinfo endpoint, and the frontend gets the endpoints it needs through /api/auth/config/.
"""
import hashlib

import requests
from django.conf import settings
from django.core.cache import cache

DISCOVERY_CACHE_SECONDS = 60 * 60
# The scopes the frontend asks for: `profile` carries preferred_username, `email` the address.
SCOPE = 'openid profile email'

REQUIRED_ENDPOINTS = ('authorization_endpoint', 'token_endpoint', 'userinfo_endpoint')
# Not part of OpenID Connect Discovery (RFC 8414 and RFC 7009 define it), so not every provider
# lists it. Without it, logging out only forgets the tokens in the browser.
OPTIONAL_ENDPOINTS = ('revocation_endpoint',)


class DiscoveryError(Exception):
    """The provider's endpoints can't be known: OIDC_ISSUER unset, unreachable or wrong."""


def issuer():
    """OIDC_ISSUER without a trailing slash: how identities are stored and issuers compared."""
    return settings.OIDC_ISSUER.rstrip('/')


def discovery_url(issuer_url):
    # OpenID Connect Discovery §4: any terminating / is removed before appending the path.
    return issuer_url.rstrip('/') + '/.well-known/openid-configuration'


def provider():
    """The provider's endpoints, as a dict ('' for an optional one it doesn't list)."""
    if not settings.OIDC_ISSUER:
        raise DiscoveryError('OIDC_ISSUER is not set.')
    cache_key = 'oidc-discovery:' + hashlib.sha256(settings.OIDC_ISSUER.encode()).hexdigest()
    endpoints = cache.get(cache_key)
    if endpoints is not None:
        return endpoints

    url = discovery_url(settings.OIDC_ISSUER)
    try:
        resp = requests.get(url, headers={'Accept': 'application/json'}, timeout=5)
        resp.raise_for_status()
        doc = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise DiscoveryError(f'No discovery document at {url}: {e}')
    if not isinstance(doc, dict):
        raise DiscoveryError(f'No discovery document at {url}.')
    # §4.3: the document must name the issuer it was fetched for. A mismatch means OIDC_ISSUER
    # is wrong (e.g. the server's address instead of its issuer), or the document isn't its own.
    if str(doc.get('issuer') or '').rstrip('/') != issuer():
        raise DiscoveryError(f'The discovery document at {url} is for issuer '
                             f'{doc.get("issuer")!r}, not OIDC_ISSUER.')

    endpoints = {}
    for name in REQUIRED_ENDPOINTS + OPTIONAL_ENDPOINTS:
        value = doc.get(name) or ''
        if not isinstance(value, str):
            value = ''
        if not value and name in REQUIRED_ENDPOINTS:
            raise DiscoveryError(f'The discovery document at {url} has no {name}.')
        endpoints[name] = value
    cache.set(cache_key, endpoints, DISCOVERY_CACHE_SECONDS)
    return endpoints
