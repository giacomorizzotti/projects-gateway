"""Bearer tokens from the OpenID Connect provider (OIDC_ISSUER).

The token is checked at the provider's userinfo endpoint (from its discovery document, see
oidc.py). Users are never auto-created: only the accounts added with `add_user` get in, even if
anyone can sign up on the provider.

A local user is matched once by username (the OIDC_USERNAME_CLAIM claim), at their first login,
which binds them to that provider account's `sub` (accounts.Identity). After that the `sub`
decides, so another account taking the username later on the provider can't get in as them.
"""
import hashlib
import logging

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from . import oidc
from .models import Identity

logger = logging.getLogger(__name__)

# A token revoked upstream stays usable here for up to this long, in exchange for one
# provider round trip per user per minute instead of one per API request.
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

        info = userinfo(token)
        subject = info.get('sub')
        if not isinstance(subject, str) or not subject:
            raise AuthenticationFailed('Malformed auth server response.')
        user = user_for(oidc.issuer(), subject, info)
        if user is None or not user.is_active:
            raise AuthenticationFailed('No matching local account.')
        return (user, token)

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when no token is sent, so the frontend
        # knows to refresh its token or log in again.
        return 'Bearer'


def userinfo(token):
    """The provider's userinfo for this token, cached by a hash of it (never the token)."""
    cache_key = 'userinfo:' + hashlib.sha256(token.encode()).hexdigest()
    info = cache.get(cache_key)
    if info is not None:
        return info
    try:
        endpoint = oidc.provider()['userinfo_endpoint']
    except oidc.DiscoveryError as e:
        logger.error('Login: %s', e)
        raise AuthenticationFailed('Auth server unreachable.')
    try:
        resp = requests.get(endpoint, headers={'Authorization': f'Bearer {token}'}, timeout=5)
    except requests.RequestException:
        raise AuthenticationFailed('Auth server unreachable.')
    if resp.status_code != 200:
        raise AuthenticationFailed('Invalid or expired token.')
    try:
        info = resp.json()
    except ValueError:
        raise AuthenticationFailed('Malformed auth server response.')
    if not isinstance(info, dict):
        raise AuthenticationFailed('Malformed auth server response.')
    cache.set(cache_key, info, USERINFO_CACHE_SECONDS)
    return info


def user_for(issuer, subject, info):
    """The local user this provider account signs in as, or None."""
    identity = Identity.objects.select_related('user').filter(issuer=issuer, subject=subject).first()
    if identity:
        return identity.user

    # First login: the username claim names a user added with add_user, not yet bound here.
    claim = settings.OIDC_USERNAME_CLAIM
    username = info.get(claim)
    if not isinstance(username, str) or not username:
        logger.warning('Login refused: the userinfo has no %r claim (OIDC_USERNAME_CLAIM).', claim)
        return None
    user = User.objects.filter(username=username, is_active=True).first()
    if user is None:
        return None
    if user.identities.filter(issuer=issuer).exists():
        # Another account of this provider got in as this user first. If the provider account
        # was replaced on purpose, `add_user <username> --rebind` lets the new one bind.
        logger.warning('Login refused: %r is bound to another account of the provider '
                       '(the refused one has sub %r).', username, subject)
        return None
    try:
        with transaction.atomic():
            Identity.objects.create(user=user, issuer=issuer, subject=subject)
    except IntegrityError:
        # A parallel first request bound it a moment ago: fine if it bound the same pair.
        if not Identity.objects.filter(user=user, issuer=issuer, subject=subject).exists():
            return None
    else:
        logger.info('Login: %r is now bound to sub %r at %s.', username, subject, issuer)
    return user
