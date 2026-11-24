"""Health checks: is every public URL in the catalog up, is its certificate far from expiry,
and does its name still point at the platform the catalog says it runs on.

A run checks every URL of every environment with checks on, a few at a time, except for
archived and discontinued projects (the dashboard hides those too). A run in which nothing
answered at all is thrown away: that's the gateway offline, not every site down at once.

A site is down only when the failure holds up. Within a check, a failure is retried twice,
10 seconds apart. Then a URL that still fails is only "failing" (`failing_since`): no event,
nothing notified. `confirm` checks it again CONFIRM_AFTER later, together with a few sites
that are up (on other platforms when there are). It's down if it fails again while one of
those answers. If none answers, the trouble is the gateway's own connection: nothing is
decided, and it's tried again later. Name lookups and a home connection drop for a minute now
and then: without this, about ten false "down" a day, each fine 15 minutes later.
"""
import ipaddress
import logging
import re
import socket
import ssl
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlsplit

import requests
import urllib3.util.connection
from django.db import transaction
from django.utils import timezone

from catalog.models import Environment, PlatformKind, Project, ProjectGroup
from .models import CheckEvent, MonitorState, UrlCheck

log = logging.getLogger('gateway.checks')

TIMEOUT = (5, 15)            # seconds: to connect, then to get an answer
RETRIES = 2                  # more attempts after a failure, within one check
RETRY_WAIT = 10              # seconds between attempts
CONFIRM_AFTER = timedelta(minutes=5)    # a failure counts once it still fails this much later
CONTROLS = 3                 # sites that are up, checked with a confirmation: is it us?
WORKERS = 8                  # URLs checked at the same time
MAX_REDIRECTS = 10
HISTORY_DAYS = 30
# Plain on purpose: some hosts' firewalls (some shared hosts') drop the connection for the
# usual bot form "Mozilla/5.0 (compatible; …)" and for "health check" in it.
USER_AGENT = 'projects-gateway/1.0'
SKIPPED_STATUSES = [Project.Status.ARCHIVED, Project.Status.DISCONTINUED]


def _has_ipv6_route():
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
            probe.connect(('2001:4860:4860::8888', 53))     # UDP: nothing is sent
        return True
    except OSError:
        return False


# A host (and its containers) may have no IPv6 route. Connecting to a site's IPv6 address then
# fails at once with "Network unreachable", and as the last address tried, that error hid
# the real one from IPv4. Without a route, connect over IPv4 only (urllib3's own switch).
IPV6 = _has_ipv6_route()
if not IPV6:
    urllib3.util.connection.HAS_IPV6 = False


@dataclass
class Outcome:
    ok: bool
    status_code: int | None = None
    response_ms: int | None = None
    final_url: str = ''
    error: str = ''
    attempts: int = 1
    ips: list = field(default_factory=list)
    tls_expires_at: datetime | None = None
    tls_error: str = ''
    tls_names: list = field(default_factory=list)          # the names the certificate covers
    tls_name_ips: dict = field(default_factory=dict)       # the other names → their addresses


NO_NAME = 'The name does not resolve'
DNS_FAILED = 'The name lookup failed (DNS error, not an answer)'
# The DNS answered that the name doesn't exist, or has no address. Anything else (a timeout,
# a server failure) is the lookup failing, not an answer about the name.
_NO_NAME_ERRNOS = {getattr(socket, n) for n in ('EAI_NONAME', 'EAI_NODATA') if hasattr(socket, n)}


def lookup(host):
    """(the addresses `host` resolves to, IPv4 first; why there are none, or '')."""
    if not host:
        return [], NO_NAME
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return [], NO_NAME if e.errno in _NO_NAME_ERRNOS else DNS_FAILED
    except (OSError, UnicodeError):
        return [], NO_NAME
    return sorted({info[4][0] for info in infos}, key=lambda ip: (':' in ip, ip)), ''


def resolve(host):
    """The addresses `host` resolves to, IPv4 first; [] when it doesn't resolve."""
    return lookup(host)[0]


_REASONS = [
    ('NameResolutionError', 'The name does not resolve'),
    ('Name or service not known', 'The name does not resolve'),
    ('Temporary failure in name resolution', 'The name did not resolve (DNS failure)'),
    ('Connection refused', 'Connection refused'),
    ('Connection reset', 'Connection reset'),
    ('No route to host', 'No route to host'),
    ('Network is unreachable', 'Network unreachable'),
    ('RemoteDisconnected', 'Closed the connection without answering'),
]


CERT_INVALID = 'Certificate not valid'


def describe(exc):
    """A short, readable reason for a failed request (urllib3's own text is a paragraph)."""
    text = str(exc)
    if 'Hostname mismatch' in text:
        return f'{CERT_INVALID}: it is for another name'
    m = re.search(r'certificate verify failed: ([^(]+?)\s*\(', text)
    if m:
        return f'{CERT_INVALID}: {m[1]}'
    for needle, reason in _REASONS:
        if needle in text:
            return reason
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return 'Timed out connecting'
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return 'Timed out waiting for an answer'
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return 'Too many redirects'
    if isinstance(exc, requests.exceptions.SSLError):
        return 'TLS handshake failed'
    return exc.__class__.__name__


def fetch(url, verify=True):
    """GET `url` (following redirects). Up: the server answers, with anything below 500.

    A 404 counts as up: an API's root often answers 404 by design, and
    what matters here is that the server and the app behind it respond. The code is kept,
    for the status page.

    A certificate that isn't valid isn't an outage: the page is asked for again without
    checking it, and if the server answers, the site is up and the certificate is the
    problem (`tls_error`, red in "needs attention": browsers show visitors a warning)."""
    start = time.monotonic()
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', urllib3.exceptions.InsecureRequestWarning)
            with session.get(url, timeout=TIMEOUT, stream=True, verify=verify,
                             headers={'User-Agent': USER_AGENT}) as resp:
                # The first bytes of the page too: headers alone, then a stall, isn't up.
                next(resp.iter_content(16 * 1024), b'')
                ms = round((time.monotonic() - start) * 1000)
                ok = resp.status_code < 500
                return Outcome(ok=ok, status_code=resp.status_code, response_ms=ms, final_url=resp.url,
                               error='' if ok else f'HTTP {resp.status_code} {resp.reason or ""}'.strip())
    except requests.RequestException as e:
        reason = describe(e)[:500]
        if verify and reason.startswith(CERT_INVALID):
            answer = fetch(url, verify=False)
            answer.tls_error = reason[:300]
            return answer if answer.ok else Outcome(ok=False, error=reason)
        return Outcome(ok=False, error=reason)
    finally:
        session.close()


def _connect(host, port):
    """A TCP connection to `host`, over IPv4 only when there's no IPv6 route (see IPV6)."""
    family = socket.AF_UNSPEC if IPV6 else socket.AF_INET
    error = OSError('The name does not resolve')
    for af, kind, proto, _, address in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
        sock = socket.socket(af, kind, proto)
        sock.settimeout(TIMEOUT[0])
        try:
            sock.connect(address)
            return sock
        except OSError as e:
            sock.close()
            error = e
    raise error


def certificate(host, port=443):
    """(expiry, '', the names it covers) of the certificate `host` serves, or
    (None, why it couldn't be read, [])."""
    context = ssl.create_default_context()
    try:
        with _connect(host, port) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except ssl.SSLCertVerificationError as e:
        return None, f'Certificate not valid: {e.verify_message or e.reason or "verification failed"}', []
    except (OSError, ssl.SSLError) as e:
        return None, describe(e), []
    names = [value for kind, value in cert.get('subjectAltName', ()) if kind == 'DNS']
    not_after = cert.get('notAfter')
    if not not_after:
        return None, 'The certificate has no expiry date', names
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), dt_timezone.utc), '', names


MAX_CERT_NAMES = 20      # a shared host's certificate can list many: only the first ones are looked up


def check_url(url, sleep=time.sleep, cert_names=False):
    """Check one URL, retrying a failure (no answer, or a server error) up to RETRIES times.

    With `cert_names`, also resolve the other names on its certificate: on a server that
    renews its own certificates, one pointing elsewhere means certbot can't renew it there."""
    parts = urlsplit(url)
    host = parts.hostname or ''
    attempts = 0
    while True:
        attempts += 1
        ips, no_ips = lookup(host)
        outcome = fetch(url) if ips else Outcome(ok=False, error=no_ips)
        if outcome.ok or attempts > RETRIES:
            break
        sleep(RETRY_WAIT)
    outcome.attempts = attempts
    outcome.ips = ips
    if parts.scheme == 'https' and ips:
        expires, cert_error, outcome.tls_names = certificate(host, parts.port or 443)
        outcome.tls_expires_at, outcome.tls_error = expires, cert_error or outcome.tls_error
        if cert_names:
            # Wildcards are renewed through DNS, wherever the names point: nothing to check.
            others = [n for n in outcome.tls_names if n != host and not n.startswith('*.')]
            outcome.tls_name_ips = {name: resolve(name) for name in others[:MAX_CERT_NAMES]}
    return outcome


def networks(entries):
    """The addresses and networks in `entries` ("1.2.3.4", "198.51.100.0/24"…); others skipped."""
    out = []
    for entry in entries:
        try:
            out.append(ipaddress.ip_network(str(entry).strip(), strict=False))
        except ValueError:
            pass
    return out


def platform_networks(platform):
    """Where the platform answers: its public IPs (or networks, for a CDN), plus what its
    dynamic DNS name and its hostnames resolve to right now."""
    if platform is None:
        return []
    names = ([platform.dynamic_dns] if platform.dynamic_dns else []) + list(platform.hostnames)
    return networks(list(platform.public_ips) + [ip for name in names for ip in resolve(name)])


def dns_match(ips, nets):
    """Does a name that resolves to `ips` point at the platform? None: nothing to compare.

    IPv4 is compared with the platform's IPv4 entries and IPv6 with its IPv6 ones. A lookup
    sometimes loses one family's answer, and a platform recorded with IPv4 only says nothing
    about IPv6: neither should look like the site has moved."""
    result = None
    for version in (4, 6):
        family = [n for n in nets if n.version == version]
        addresses = []
        for ip in ips:
            try:
                address = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if address.version == version:
                addresses.append(address)
        if not family or not addresses:
            continue
        if any(address in net for address in addresses for net in family):
            return True
        result = False
    return result


def targets():
    """(environment, url) for every URL due a check."""
    envs = (Environment.objects.filter(checks_enabled=True)
            .exclude(project__status__in=SKIPPED_STATUSES)
            .exclude(project__group__in=ProjectGroup.objects.filter(hidden=True).values('slug'))
            .select_related('project', 'platform'))
    return [(env, url) for env in envs for url in env.urls]


def self_renewed_kinds():
    """The platform kinds whose servers renew their certificates themselves (certbot over HTTP),
    so every name on one must point there; Settings page, `PlatformKind.renews_certificates`.
    Elsewhere the provider renews them, by its own means."""
    return set(PlatformKind.objects.filter(renews_certificates=True).values_list('slug', flat=True))


def run(now=None, check=check_url, only=None, controls=frozenset()):
    """Check every URL, save the results, and return a short summary.

    With `only` ((environment id, url) pairs), check just those: a confirmation (see
    `confirm`). It isn't the regular run: it leaves the other URLs and `checks_ran_at` alone
    (the schedule and "Check now" go by that). `controls` are the pairs among them that were
    up: when none of them answers, the gateway is the one offline."""
    started = time.monotonic()
    partial = only is not None
    pairs = targets()
    if partial:
        pairs = [(env, url) for env, url in pairs if (env.id, url) in only]
    renewed = self_renewed_kinds()      # read here: the pool's threads don't query the database

    def renews_here(env):
        return env.platform is not None and env.platform.kind in renewed

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        outcomes = list(pool.map(lambda pair: check(pair[1], cert_names=renews_here(pair[0])), pairs))
    now = now or timezone.now()
    state = MonitorState.get()

    # Nothing answered (not even with an error page), or in a confirmation none of the
    # controls: the gateway is offline. Keep the last real results rather than mark sites down.
    answered = [(env.id, url) for (env, url), o in zip(pairs, outcomes) if o.ok or o.status_code]
    present = {(env.id, url) for env, url in pairs} & set(controls)
    if present:
        offline = not present & set(answered)
    else:
        offline = len(pairs) >= 3 and not answered
    if offline:
        if not partial:
            state.checks_ran_at, state.checks_offline = now, True
            state.checks_seconds = round(time.monotonic() - started, 1)
            state.save(update_fields=['checks_ran_at', 'checks_offline', 'checks_seconds'])
        return {'checked': len(pairs), 'up': 0, 'down': 0, 'failing': 0, 'offline': True}

    platform_nets = {}
    for env, _ in pairs:
        if env.platform_id not in platform_nets:
            platform_nets[env.platform_id] = platform_networks(env.platform)

    UP, DOWN = UrlCheck.State.UP, UrlCheck.State.DOWN
    with transaction.atomic():
        existing = {(c.environment_id, c.url): c for c in UrlCheck.objects.all()}
        seen, saved = set(), []
        for (env, url), o in zip(pairs, outcomes):
            key = (env.id, url)
            if key in seen:          # the same URL twice in one environment
                continue
            seen.add(key)
            # A new URL starts as up: down, like any other, only once its failure is confirmed.
            check_row = existing.get(key) or UrlCheck(environment=env, url=url, since=now, state=UP)
            if o.ok:
                if check_row.state == DOWN:
                    CheckEvent.objects.create(environment=env, url=url, at=now, state=UP)
                    check_row.since = now
                elif check_row.failing_since:
                    log.info('%s answers again: its failure at %s (%s) did not hold up.',
                             url, check_row.failing_since.isoformat(timespec='seconds'), check_row.error)
                check_row.state, check_row.failing_since = UP, None
            elif check_row.state != DOWN:
                check_row.failing_since = check_row.failing_since or now
                if now - check_row.failing_since >= CONFIRM_AFTER:
                    # Down since the first failure: that's when it stopped answering.
                    check_row.state, check_row.since = DOWN, check_row.failing_since
                    CheckEvent.objects.create(environment=env, url=url, at=check_row.since, state=DOWN,
                                              detail=o.error[:500])
                    check_row.failing_since = None
                    log.warning('%s is down: still failing since %s (%s).',
                                url, check_row.since.isoformat(timespec='seconds'), o.error)
                else:
                    log.info('%s failed (%s): to be confirmed.', url, o.error)
            check_row.checked_at = now
            check_row.status_code = o.status_code
            check_row.response_ms = o.response_ms
            check_row.final_url = (o.final_url or '')[:500]
            check_row.error = o.error[:500]
            check_row.attempts = o.attempts
            check_row.ips = o.ips
            nets = platform_nets.get(env.platform_id) or []
            check_row.dns_match = dns_match(o.ips, nets)
            check_row.tls_expires_at = o.tls_expires_at
            check_row.tls_error = o.tls_error[:300]
            check_row.tls_names = o.tls_names
            check_row.tls_elsewhere = sorted(name for name, ips in o.tls_name_ips.items()
                                             if dns_match(ips, nets) is False)
            check_row.save()
            saved.append(check_row)
        if not partial:
            # URLs removed from the catalog, or whose checks were turned off.
            for key, check_row in existing.items():
                if key not in seen:
                    check_row.delete()
            CheckEvent.objects.filter(at__lt=now - timedelta(days=HISTORY_DAYS)).delete()
            state.checks_ran_at, state.checks_offline = now, False
            state.checks_seconds = round(time.monotonic() - started, 1)
            state.checks_count = len(seen)
            state.save(update_fields=['checks_ran_at', 'checks_offline', 'checks_seconds', 'checks_count'])

    return {'checked': len(seen), 'up': sum(1 for o in outcomes if o.ok),
            'down': sum(1 for r in saved if r.state == DOWN),
            'failing': sum(1 for r in saved if r.failing_since), 'offline': False}


def confirmation_due(now=None):
    """The failures to look at again: unconfirmed for CONFIRM_AFTER or longer."""
    return UrlCheck.objects.filter(failing_since__lte=(now or timezone.now()) - CONFIRM_AFTER)


def confirm(now=None, check=check_url):
    """Check again the failures due a second look, with up to CONTROLS sites that are up,
    one per platform, other platforms than theirs first (a platform that is down can't vouch
    for the gateway's line). None when there's nothing to confirm."""
    suspects = list(confirmation_due(now).select_related('environment'))
    if not suspects:
        return None
    theirs = {c.environment.platform_id for c in suspects}
    candidates = (UrlCheck.objects.filter(state=UrlCheck.State.UP, failing_since__isnull=True)
                  .select_related('environment').order_by('?'))
    controls, platforms = set(), set()
    for c in sorted(candidates, key=lambda c: c.environment.platform_id in theirs):
        if c.environment.platform_id in platforms:
            continue
        platforms.add(c.environment.platform_id)
        controls.add((c.environment_id, c.url))
        if len(controls) == CONTROLS:
            break
    return run(now=now, check=check, only={(c.environment_id, c.url) for c in suspects} | controls,
               controls=controls)
