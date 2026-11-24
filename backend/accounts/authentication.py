"""Bearer tokens from an OAuth 2 auth server (OAUTH2_USERINFO_ENDPOINT).

The token is checked against the auth server's userinfo endpoint, and the username it
returns must match a PRE-EXISTING local user. Users are never auto-created, so only the
accounts added with `add_user` get in, even if anyone can sign up on the auth server.
"""
import hashlib

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

# A token revoked upstream stays usable here for up to this long, in exchange for one
# auth-server round trip per user per minute instead of one per API request.
USERINFO_CACHE_SECONDS = 60


class RemoteOAuth2Authentication(BaseAuthentication):
    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != b'bearer':
            return None
        if len(auth) != 2:
            raise AuthenticationFailed('Invalid token header.')
        try:
            token = auth[1].decode()
        except UnicodeError:
            raise AuthenticationFailed('Invalid token header.')

        # Cache only a hash of the token, never the token itself.
        cache_key = 'userinfo:' + hashlib.sha256(token.encode()).hexdigest()
        info = cache.get(cache_key)
        if info is None:
            if not settings.OAUTH2_USERINFO_ENDPOINT:
                raise AuthenticationFailed('No OAUTH2_USERINFO_ENDPOINT set.')
            try:
                resp = requests.get(
                    settings.OAUTH2_USERINFO_ENDPOINT,
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=5,
                )
            except requests.RequestException:
                raise AuthenticationFailed('Auth server unreachable.')
            if resp.status_code != 200:
                raise AuthenticationFailed('Invalid or expired token.')
            try:
                info = resp.json()
            except ValueError:
                raise AuthenticationFailed('Malformed auth server response.')
            cache.set(cache_key, info, USERINFO_CACHE_SECONDS)

        username = info.get('username') or ''
        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            raise AuthenticationFailed('No matching local account.')
        return (user, token)

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when no token is sent, so the frontend
        # knows to refresh its token or log in again.
        return 'Bearer'
