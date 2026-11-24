from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient


def userinfo_response(status=200, payload=None):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = payload or {}
    return resp


class RemoteOAuth2AuthenticationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create(username='alice', first_name='Ada', last_name='Lovelace')

    def test_no_token_is_401(self):
        self.assertEqual(self.client.get('/api/me/').status_code, 401)

    @mock.patch('accounts.authentication.requests.get')
    def test_valid_token_for_known_user(self, get):
        get.return_value = userinfo_response(payload={'username': 'alice'})
        resp = self.client.get('/api/me/', HTTP_AUTHORIZATION='Bearer good-token')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], 'alice')
        self.assertEqual(resp.json()['name'], 'Ada Lovelace')

    @mock.patch('accounts.authentication.requests.get')
    def test_unknown_user_is_rejected_not_created(self, get):
        # Anyone can sign up on the auth server: only pre-existing local users get in.
        get.return_value = userinfo_response(payload={'username': 'stranger'})
        resp = self.client.get('/api/me/', HTTP_AUTHORIZATION='Bearer their-token')
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(User.objects.filter(username='stranger').exists())

    @mock.patch('accounts.authentication.requests.get')
    def test_inactive_user_is_rejected(self, get):
        self.user.is_active = False
        self.user.save()
        get.return_value = userinfo_response(payload={'username': 'alice'})
        self.assertEqual(self.client.get('/api/me/', HTTP_AUTHORIZATION='Bearer t').status_code, 401)

    @mock.patch('accounts.authentication.requests.get')
    def test_expired_token_is_401(self, get):
        get.return_value = userinfo_response(status=401)
        self.assertEqual(self.client.get('/api/me/', HTTP_AUTHORIZATION='Bearer old').status_code, 401)

    @mock.patch('accounts.authentication.requests.get')
    def test_auth_server_down_is_401(self, get):
        get.side_effect = requests.ConnectionError()
        self.assertEqual(self.client.get('/api/me/', HTTP_AUTHORIZATION='Bearer t').status_code, 401)

    @mock.patch('accounts.authentication.requests.get')
    def test_userinfo_is_cached_per_token(self, get):
        get.return_value = userinfo_response(payload={'username': 'alice'})
        for _ in range(3):
            self.client.get('/api/me/', HTTP_AUTHORIZATION='Bearer same-token')
        self.assertEqual(get.call_count, 1)

    def test_health_needs_no_login(self):
        self.assertEqual(self.client.get('/api/health/').status_code, 200)
