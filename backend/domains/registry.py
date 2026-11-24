"""Asking a domain's registry for its expiry, registrar, nameservers and status.

RDAP (JSON over HTTPS) where IANA's bootstrap list names a server for the ending: .com,
.net, .xyz, .space, .agency, .engineering, .cloud… For .it, which has no RDAP, the
registry's WHOIS (whois.nic.it, port 43). .eu and .es publish no expiry: typed by hand.

Only those fields are kept: WHOIS answers also carry contact names and addresses, which
are never stored.
"""
import re
import socket
import time
from datetime import datetime

import requests
from django.utils import timezone

BOOTSTRAP = 'https://data.iana.org/rdap/dns.json'
WHOIS = {'it': 'whois.nic.it'}
TIMEOUT = 20
USER_AGENT = 'projects-gateway/1.0'
_bootstrap = {'at': 0, 'table': {}}

# Who runs the DNS, from the nameservers' names: a hint, kept current. The account that edits
# the zone is the domain's dns_service.
DNS_PROVIDERS = [
    ('dns-parking.com', 'Hostinger'), ('hostinger', 'Hostinger'), ('cloudflare.com', 'Cloudflare'),
    ('aruba', 'Aruba'), ('cloud.it', 'Aruba'), ('forpsicloud', 'Aruba'), ('siteground', 'SiteGround'),
    ('register.it', 'Register.it'), ('ovh.', 'OVH'), ('domaincontrol.com', 'GoDaddy'),
]


class RegistryError(Exception):
    pass


def registered_name(host):
    """The registered domain of a host: its last two labels (enough for the endings in use;
    a name under co.uk and the like would need the public suffix list)."""
    labels = (host or '').lower().rstrip('.').split('.')
    return '.'.join(labels[-2:]) if len(labels) >= 2 else ''


def dns_provider(nameservers):
    for ns in nameservers:
        for needle, provider in DNS_PROVIDERS:
            if needle in ns:
                return provider
    return ''


def _rdap_servers():
    if time.time() - _bootstrap['at'] > 86400 or not _bootstrap['table']:
        try:
            data = requests.get(BOOTSTRAP, timeout=TIMEOUT, headers={'User-Agent': USER_AGENT}).json()
        except (requests.RequestException, ValueError) as e:
            if not _bootstrap['table']:
                raise RegistryError(f'IANA’s RDAP list is unreachable ({e.__class__.__name__})') from None
        else:
            _bootstrap['table'] = {tld: urls[0] for tlds, urls in data['services'] for tld in tlds}
            _bootstrap['at'] = time.time()
    return _bootstrap['table']


def _day(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except (AttributeError, ValueError):
        return None


def rdap(name, base):
    try:
        resp = requests.get(f'{base.rstrip("/")}/domain/{name}', timeout=TIMEOUT,
                            headers={'Accept': 'application/rdap+json', 'User-Agent': USER_AGENT})
    except requests.RequestException as e:
        raise RegistryError(f'The registry is unreachable ({e.__class__.__name__})') from None
    if resp.status_code == 404:
        raise RegistryError('The registry doesn’t know this name')
    if not resp.ok:
        raise RegistryError(f'The registry answered {resp.status_code}')
    data = resp.json()
    events = {e.get('eventAction'): e.get('eventDate') for e in data.get('events', [])}
    registrar = ''
    for entity in data.get('entities', []):
        if 'registrar' in entity.get('roles', []):
            for field in (entity.get('vcardArray') or [None, []])[1]:
                if field[0] == 'fn':
                    registrar = field[3]
    return {
        'expires_on': _day(events.get('expiration')),
        'registered_on': _day(events.get('registration')),
        'registrar': registrar,
        'nameservers': sorted(n['ldhName'].lower() for n in data.get('nameservers', []) if n.get('ldhName')),
        'status': data.get('status', []),
    }


def whois_it(name):
    """whois.nic.it: the top block (dates, status), the Registrar block's organisation and
    the Nameservers block. Contacts are skipped."""
    try:
        with socket.create_connection((WHOIS['it'], 43), timeout=TIMEOUT) as sock:
            sock.sendall(f'{name}\r\n'.encode())
            chunks = []
            while chunk := sock.recv(4096):
                chunks.append(chunk)
    except OSError as e:
        raise RegistryError(f'The registry is unreachable ({e.__class__.__name__})') from None
    text = b''.join(chunks).decode(errors='replace')
    if re.search(r'^Status:\s+AVAILABLE', text, re.M):
        raise RegistryError('The registry says this name isn’t registered')
    section, top, registrar, nameservers = None, {}, '', []
    for line in text.splitlines():
        if not line.strip() or line.startswith('*'):
            continue
        if not line.startswith(' ') and ':' not in line:
            section = line.strip()            # Registrant, Admin Contact, Registrar, Nameservers…
            continue
        if section is None and ':' in line:
            key, _, value = line.partition(':')
            top[key.strip()] = value.strip()
        elif section == 'Registrar' and line.strip().startswith('Organization:'):
            registrar = line.split(':', 1)[1].strip()
        elif section == 'Nameservers':
            nameservers.append(line.strip().lower())
    parse = lambda key: (datetime.strptime(top[key][:10], '%Y-%m-%d').date() if top.get(key) else None)
    return {
        'expires_on': parse('Expire Date'),
        'registered_on': parse('Created'),
        'registrar': registrar,
        'nameservers': sorted(nameservers),
        'status': [s for s in [top.get('Status', '')] if s],
    }


def lookup(name):
    tld = name.rsplit('.', 1)[-1]
    if tld in WHOIS:
        return whois_it(name)
    base = _rdap_servers().get(tld)
    if not base:
        raise RegistryError(f'.{tld} publishes no expiry date: enter it by hand')
    return rdap(name, base)


def refresh(domain, now=None):
    """Update one Domain from its registry. Returns True when the registry answered."""
    now = now or timezone.now()
    domain.looked_up_at = now
    try:
        found = lookup(domain.name)
    except RegistryError as e:
        domain.lookup_error = str(e)[:300]
        domain.link_services()
        domain.save()
        return False
    domain.lookup_error = ''
    if found['expires_on']:
        domain.expires_on, domain.expires_by_hand = found['expires_on'], False
    domain.registered_on = found['registered_on'] or domain.registered_on
    domain.nameservers = found['nameservers']
    domain.registry_status = found['status']
    # The registry's own words, kept current: which account renews it is registrar_service.
    if found['registrar']:
        domain.registrar = found['registrar'][:100]
    domain.dns_provider = dns_provider(found['nameservers'])
    domain.link_services()
    domain.save()
    return True


def days_left(expires_on, today=None):
    return (expires_on - (today or timezone.localdate())).days if expires_on else None

