import logging

from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import oidc

logger = logging.getLogger(__name__)


@api_view(['GET'])
def me(request):
    user = request.user
    return Response({
        'id': user.id,
        'username': user.username,
        'name': user.get_full_name() or user.username,
    })


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_config(request):
    """What the frontend needs to sign in: the provider's endpoints and the app's public client.

    Read at every page load, before anything else (frontend/src/config/auth.js). Nothing here is
    secret: a public client with PKCE has no secret.
    """
    if not settings.OIDC_CLIENT_ID:
        logger.error('Login: OIDC_CLIENT_ID is not set.')
        return Response({'detail': 'Sign-in isn’t set up.'}, status=503)
    try:
        endpoints = oidc.provider()
    except oidc.DiscoveryError as e:
        logger.error('Login: %s', e)
        return Response({'detail': 'The auth server can’t be reached.'}, status=503)
    return Response({
        **endpoints,
        'client_id': settings.OIDC_CLIENT_ID,
        'scope': oidc.SCOPE,
    })
