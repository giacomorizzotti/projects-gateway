from io import StringIO
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Identity

ISSUER = 'https://auth.example.com/realms/main'


def discovery(**changes):
    doc = {
        'issuer': ISSUER,
        'authorization_endpoint': f'{ISSUER}/protocol/openid-connect/auth',
        'token_endpoint': f'{ISSUER}/protocol/openid-connect/token',
        'userinfo_endpoint': f'{ISSUER}/protocol/openid-connect/userinfo',
        'jwks_uri': f'{ISSUER}/protocol/openid-connect/certs',
    }
    doc.update(changes)
    return {k: v for k, v in doc.items() if v is not None}


def response(status=200, payload=None):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = payload if payload is not None else {}
    resp.raise_for_status.side_effect = requests.HTTPError(status) if status >= 400 else None
    return resp


class FakeProvider:
    """Stands in for requests.get: the discovery document, and userinfo per token."""

    def __init__(self, doc=None, users=None):
        self.doc = doc if doc is not None else discovery()
        self.users = users or {}          # token -> userinfo claims
        self.calls = []

    def __call__(self, url, headers=None, **kwargs):
        self.calls.append(url)
        if url == f'{ISSUER}/.well-known/openid-configuration':
            if isinstance(self.doc, Exception):
                raise self.doc
            return response(payload=self.doc)
        if url == self.doc.get('userinfo_endpoint'):
            token = (headers or {}).get('Authorization', '').removeprefix('Bearer ')
            if token not in self.users:
                return response(status=401)
            if isinstance(self.users[token], Exception):
                raise self.users[token]
            return response(payload=self.users[token])
        return response(status=404)

    def count(self, suffix):
        return sum(1 for url in self.calls if url.endswith(suffix))


@override_settings(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID='gateway-client',
                   OIDC_USERNAME_CLAIM='preferred_username')
class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create(username='alice', first_name='Ada', last_name='Lovelace')
        self.provider = FakeProvider(users={
            'alice-token': {'sub': 'a-1', 'preferred_username': 'alice'},
        })
        patcher = mock.patch('requests.get', self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def me(self, token):
        return self.client.get('/api/me/', HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_no_token_is_401(self):
        self.assertEqual(self.client.get('/api/me/').status_code, 401)

    def test_valid_token_for_known_user(self):
        resp = self.me('alice-token')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'alice')
        self.assertEqual(resp.json()['name'], 'Ada Lovelace')

    def test_first_login_binds_the_provider_account(self):
        with self.assertLogs('accounts.authentication', 'INFO'):
            self.me('alice-token')
        identity = Identity.objects.get()
        self.assertEqual((identity.user, identity.issuer, identity.subject), (self.user, ISSUER, 'a-1'))

    def test_unknown_user_is_rejected_not_created(self):
        # Anyone can sign up on the provider: only pre-existing local users get in.
        self.provider.users['stranger-token'] = {'sub': 's-1', 'preferred_username': 'stranger'}
        self.assertEqual(self.me('stranger-token').status_code, 401)
        self.assertFalse(User.objects.filter(username='stranger').exists())
        self.assertFalse(Identity.objects.exists())

    def test_inactive_user_is_rejected(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.me('alice-token').status_code, 401)
        self.assertFalse(Identity.objects.exists())

    def test_bound_inactive_user_is_rejected(self):
        Identity.objects.create(user=self.user, issuer=ISSUER, subject='a-1')
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.me('alice-token').status_code, 401)

    def test_renamed_on_the_provider_still_gets_in(self):
        Identity.objects.create(user=self.user, issuer=ISSUER, subject='a-1')
        self.provider.users['alice-token']['preferred_username'] = 'ada'
        self.assertEqual(self.me('alice-token').json()['username'], 'alice')

    def test_another_account_taking_the_username_is_rejected(self):
        self.me('alice-token')
        # Alice renamed herself on the provider, and someone else took "alice".
        self.provider.users['mallory-token'] = {'sub': 'm-1', 'preferred_username': 'alice'}
        with self.assertLogs('accounts.authentication', 'WARNING'):
            self.assertEqual(self.me('mallory-token').status_code, 401)
        self.assertEqual(list(Identity.objects.values_list('subject', flat=True)), ['a-1'])

    def test_rebind_lets_a_new_account_bind(self):
        self.me('alice-token')
        self.provider.users['new-alice-token'] = {'sub': 'a-2', 'preferred_username': 'alice'}
        call_command('add_user', 'alice', '--rebind', stdout=StringIO())
        self.assertEqual(self.me('new-alice-token').status_code, 200)
        self.assertEqual(Identity.objects.get().subject, 'a-2')
        # The old account is no longer the one bound.
        cache.clear()
        self.assertEqual(self.me('alice-token').status_code, 401)

    def test_a_new_issuer_binds_again(self):
        Identity.objects.create(user=self.user, issuer='https://old.example.com', subject='a-1')
        self.assertEqual(self.me('alice-token').status_code, 200)
        self.assertEqual(Identity.objects.filter(user=self.user).count(), 2)

    @override_settings(OIDC_USERNAME_CLAIM='username')
    def test_the_username_claim_is_configurable(self):
        self.provider.users['alice-token'] = {'sub': 'a-1', 'username': 'alice'}
        self.assertEqual(self.me('alice-token').status_code, 200)

    def test_missing_username_claim_is_rejected(self):
        self.provider.users['alice-token'] = {'sub': 'a-1', 'username': 'alice'}
        with self.assertLogs('accounts.authentication', 'WARNING') as logs:
            self.assertEqual(self.me('alice-token').status_code, 401)
        self.assertIn('preferred_username', logs.output[0])

    def test_missing_sub_is_rejected(self):
        self.provider.users['alice-token'] = {'preferred_username': 'alice'}
        self.assertEqual(self.me('alice-token').status_code, 401)

    def test_expired_token_is_401(self):
        self.assertEqual(self.me('old-token').status_code, 401)

    def test_provider_down_is_401(self):
        self.provider.users['alice-token'] = requests.ConnectionError()
        self.assertEqual(self.me('alice-token').status_code, 401)

    def test_no_discovery_document_is_401(self):
        self.provider.doc = requests.ConnectionError()
        with self.assertLogs('accounts.authentication', 'ERROR'):
            self.assertEqual(self.me('alice-token').status_code, 401)

    def test_userinfo_is_cached_per_token(self):
        for _ in range(3):
            self.me('alice-token')
        self.assertEqual(self.provider.count('/userinfo'), 1)

    def test_discovery_is_cached(self):
        self.provider.users['alice-token-2'] = {'sub': 'a-1', 'preferred_username': 'alice'}
        self.me('alice-token')
        self.me('alice-token-2')
        self.assertEqual(self.provider.count('/userinfo'), 2)
        self.assertEqual(self.provider.count('/openid-configuration'), 1)

    @override_settings(OIDC_ISSUER=ISSUER + '/')
    def test_issuer_with_a_trailing_slash(self):
        # Some providers' issuers end in "/": the document is still found, the issuers compared
        # without it, and the identity stored without it.
        self.provider.doc['issuer'] = ISSUER + '/'
        self.assertEqual(self.me('alice-token').status_code, 200)
        self.assertEqual(Identity.objects.get().issuer, ISSUER)

    def test_health_needs_no_login(self):
        self.assertEqual(self.client.get('/api/health/').status_code, 200)


@override_settings(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID='gateway-client')
class AuthConfigTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.provider = FakeProvider()
        patcher = mock.patch('requests.get', self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, **headers):
        return self.client.get('/api/auth/config/', **headers)

    def test_gives_the_endpoints_and_the_public_client(self):
        resp = self.config()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            'authorization_endpoint': f'{ISSUER}/protocol/openid-connect/auth',
            'token_endpoint': f'{ISSUER}/protocol/openid-connect/token',
            'userinfo_endpoint': f'{ISSUER}/protocol/openid-connect/userinfo',
            'revocation_endpoint': '',
            'client_id': 'gateway-client',
            'scope': 'openid profile email',
        })

    def test_gives_the_revocation_endpoint_when_listed(self):
        self.provider.doc['revocation_endpoint'] = f'{ISSUER}/revoke'
        self.assertEqual(self.config().json()['revocation_endpoint'], f'{ISSUER}/revoke')

    def test_ignores_a_stale_token(self):
        self.assertEqual(self.config(HTTP_AUTHORIZATION='Bearer expired').status_code, 200)

    def test_issuer_mismatch_is_503(self):
        self.provider.doc['issuer'] = 'https://elsewhere.example.com'
        with self.assertLogs('accounts.views', 'ERROR') as logs:
            self.assertEqual(self.config().status_code, 503)
        self.assertIn('not OIDC_ISSUER', logs.output[0])

    def test_missing_endpoint_is_503(self):
        self.provider.doc = discovery(token_endpoint=None)
        with self.assertLogs('accounts.views', 'ERROR'):
            self.assertEqual(self.config().status_code, 503)

    def test_unreachable_provider_is_503(self):
        self.provider.doc = requests.ConnectionError()
        with self.assertLogs('accounts.views', 'ERROR'):
            self.assertEqual(self.config().status_code, 503)

    @override_settings(OIDC_ISSUER='')
    def test_no_issuer_is_503(self):
        with self.assertLogs('accounts.views', 'ERROR') as logs:
            self.assertEqual(self.config().status_code, 503)
        self.assertIn('OIDC_ISSUER', logs.output[0])

    @override_settings(OIDC_CLIENT_ID='')
    def test_no_client_is_503(self):
        with self.assertLogs('accounts.views', 'ERROR'):
            self.assertEqual(self.config().status_code, 503)
