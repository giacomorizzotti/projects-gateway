from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Environment, Project, Service
from monitoring import attention as monitoring_attention
from . import registry
from .attention import attention
from .models import Domain, matching_service

WHOIS_IT = """*********************************************************************
* Please note that the following result could be a subgroup of      *
*********************************************************************

Domain:             example.it
Status:             ok
Signed:             no
Created:            2024-05-08 11:57:04
Last Update:        2026-05-24 00:52:45
Expire Date:        2027-05-08

Registrant
  Organization:     Someone
  Address:          Somewhere

Admin Contact
  Name:             A Person
  Organization:     Someone

Registrar
  Organization:     Aruba s.p.a.
  Name:             ARUBA-REG
  Web:              http://www.aruba.it

Nameservers
  ns1.dns-parking.com
  ns2.dns-parking.com
"""

RDAP = {
    'events': [{'eventAction': 'registration', 'eventDate': '2024-05-13T20:04:21.000Z'},
               {'eventAction': 'expiration', 'eventDate': '2027-05-13T23:59:59.000Z'}],
    'status': ['client transfer prohibited'],
    'nameservers': [{'ldhName': 'NS2.DNS-PARKING.COM'}, {'ldhName': 'ns1.dns-parking.com'}],
    'entities': [{'roles': ['registrar'], 'vcardArray': ['vcard', [['version', {}, 'text', '4.0'],
                                                                  ['fn', {}, 'text', 'HOSTINGER operations, UAB']]]}],
}


class RegistryTests(TestCase):
    def test_registered_name(self):
        self.assertEqual(registry.registered_name('www.example.com'), 'example.com')
        self.assertEqual(registry.registered_name('test.shop.example.eu'), 'example.eu')

    def test_whois_it_keeps_only_dates_registrar_and_dns(self):
        sock = mock.MagicMock()
        sock.__enter__.return_value.recv.side_effect = [WHOIS_IT.encode(), b'']
        with mock.patch('socket.create_connection', return_value=sock):
            found = registry.lookup('example.it')
        self.assertEqual(found, {'expires_on': date(2027, 5, 8), 'registered_on': date(2024, 5, 8),
                                 'registrar': 'Aruba s.p.a.', 'nameservers': ['ns1.dns-parking.com', 'ns2.dns-parking.com'],
                                 'status': ['ok']})
        self.assertNotIn('A Person', str(found))

    def test_rdap(self):
        answer = mock.Mock(ok=True, status_code=200)
        answer.json.return_value = RDAP
        with mock.patch.object(registry, '_rdap_servers', return_value={'space': 'https://rdap.example/'}), \
             mock.patch('requests.get', return_value=answer) as get:
            found = registry.lookup('example.space')
        self.assertEqual(get.call_args.args[0], 'https://rdap.example/domain/example.space')
        self.assertEqual((found['expires_on'], found['registrar']), (date(2027, 5, 13), 'HOSTINGER operations, UAB'))
        self.assertEqual(found['nameservers'], ['ns1.dns-parking.com', 'ns2.dns-parking.com'])

    def test_refresh_fills_blanks_and_keeps_a_typed_date_the_registry_lacks(self):
        d = Domain.objects.create(name='example.space')
        with mock.patch.object(registry, 'lookup', return_value={
                'expires_on': date(2027, 5, 13), 'registered_on': None, 'registrar': 'HOSTINGER operations, UAB',
                'nameservers': ['ns1.dns-parking.com'], 'status': []}):
            self.assertTrue(registry.refresh(d))
        self.assertEqual((d.expires_on, d.registrar, d.dns_provider), (date(2027, 5, 13), 'HOSTINGER operations, UAB', 'Hostinger'))
        eu = Domain.objects.create(name='example.eu', expires_on=date(2027, 1, 1), expires_by_hand=True)
        with mock.patch.object(registry, '_rdap_servers', return_value={}):
            self.assertFalse(registry.refresh(eu))
        self.assertEqual(eu.expires_on, date(2027, 1, 1))
        self.assertIn('by hand', eu.lookup_error)

    def test_matching_service(self):
        aruba, hostinger, smtp, ov = (Service.objects.create(name=n, slug=s) for n, s in [
            ('Aruba', 'aruba'), ('Hostinger', 'hostinger'), ('Hostinger SMTP (no-reply@example.com)', 'smtp'), ('OV', 'ov')])
        services = [aruba, hostinger, smtp, ov]
        self.assertEqual(matching_service('Aruba s.p.a.', services), aruba)
        self.assertEqual(matching_service('HOSTINGER operations, UAB', services), hostinger)   # not the SMTP account
        self.assertIsNone(matching_service('OVH SAS', services))                                # under 3 letters
        self.assertIsNone(matching_service('', services))
        longer = Service.objects.create(name='Hostinger operations', slug='hostinger-ops')
        self.assertEqual(matching_service('HOSTINGER operations, UAB', services + [longer]), longer)

    def test_refresh_links_services_and_never_replaces_a_chosen_one(self):
        hostinger = Service.objects.create(name='Hostinger', slug='hostinger', account='me@example.com')
        aruba = Service.objects.create(name='Aruba', slug='aruba')
        found = {'expires_on': date(2027, 5, 13), 'registered_on': None, 'registrar': 'HOSTINGER operations, UAB',
                 'nameservers': ['ns1.dns-parking.com'], 'status': []}
        linked = Domain.objects.create(name='example.space', registrar='typed by hand once')
        chosen = Domain.objects.create(name='example.org', registrar_service=aruba)
        with mock.patch.object(registry, 'lookup', return_value=found):
            registry.refresh(linked)
            registry.refresh(chosen)
        linked.refresh_from_db()
        chosen.refresh_from_db()
        # The registry's words replace an old text; the links are filled where empty, only.
        self.assertEqual((linked.registrar, linked.registrar_service, linked.dns_service),
                         ('HOSTINGER operations, UAB', hostinger, hostinger))
        self.assertEqual((chosen.registrar, chosen.registrar_service, chosen.dns_service),
                         ('HOSTINGER operations, UAB', aruba, hostinger))


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = Project.objects.create(name='Shop', slug='shop', group='software')
        Environment.objects.create(project=cls.project, name='TEST', urls=['https://test.shop.example.eu/'])
        Environment.objects.create(project=cls.project, name='PROD', urls=['https://shop.example.eu/', 'http://localhost:5180/'])
        other = Project.objects.create(name='Site', slug='site', group='tools')
        Environment.objects.create(project=other, name='PROD', urls=['https://www.example.com/'])

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create(username='me'))

    def test_track_a_suggestion(self):
        names = [s['name'] for s in self.api.get('/api/domains/suggestions/').json()]
        self.assertEqual(names, ['example.com', 'example.eu'])
        with mock.patch.object(registry, 'refresh') as refresh:
            r = self.api.post('/api/domains/', {'name': 'WWW.EXAMPLE.EU', 'expires_on': '2027-01-01'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual((data['name'], data['expires_by_hand']), ('example.eu', True))
        self.assertEqual({s['host'] for s in data['sites']}, {'test.shop.example.eu', 'shop.example.eu'})
        self.assertEqual([p['slug'] for p in data['project_details']], ['shop'])
        refresh.assert_called_once()
        self.assertEqual([s['name'] for s in self.api.get('/api/domains/suggestions/').json()], ['example.com'])

    def test_not_a_domain(self):
        self.assertIn('name', self.api.post('/api/domains/', {'name': 'not a domain'}, format='json').json())

    def test_registrar_and_dns_are_services(self):
        aruba = Service.objects.create(name='Aruba', slug='aruba', url='https://www.aruba.it/', account='me')
        d = Domain.objects.create(name='example.it', registrar='Aruba s.p.a.')
        r = self.api.patch(f'/api/domains/{d.id}/', {'registrar_service': aruba.id, 'registrar': 'ignored'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data['registrar'], 'Aruba s.p.a.')                     # the registry's, read-only
        self.assertEqual(data['registrar_service_details'],
                         {'id': aruba.id, 'slug': 'aruba', 'name': 'Aruba', 'url': 'https://www.aruba.it/', 'account': 'me'})
        self.assertIsNone(data['dns_service_details'])
        r = self.api.patch(f'/api/domains/{d.id}/', {'registrar_service': None}, format='json')
        self.assertIsNone(r.json()['registrar_service'])
        aruba.delete()   # a deleted service just unlinks
        d.refresh_from_db()
        self.assertIsNone(d.registrar_service)


class AttentionTests(TestCase):
    def items(self, today):
        out = []
        attention(lambda key, kind, severity, title, *a, **k: out.append((key, severity)), today)
        return dict(out)

    def test_expiry_warnings(self):
        Domain.objects.create(name='soon.it', expires_on=date(2026, 12, 1))
        Domain.objects.create(name='renews.com', expires_on=date(2026, 11, 20), auto_renew=True)
        Domain.objects.create(name='typed.eu')
        found = self.items(date(2026, 11, 13))
        self.assertEqual(found, {'domain:soon.it': 'warning', 'domains:unknown': 'info'})
        found = self.items(date(2026, 11, 28))
        self.assertEqual(found['domain:soon.it'], 'danger')                    # 3 days left
        self.assertEqual(self.items(date(2026, 11, 21))['domain:renews.com'], 'danger')    # auto-renew didn't happen

    def test_part_of_needs_attention(self):
        Domain.objects.create(name='gone.com', expires_on=date(2020, 1, 1))
        self.assertIn('domain:gone.com', {i['key'] for i in monitoring_attention.items()})
