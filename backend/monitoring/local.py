"""The host's local scan: git repos, nginx sites and systemd services, compared with the catalog,
maldet's malware scans, and security traces (failed sudo, SSH logins and keys, unnamed containers).

`deploy/scan_local.py` runs on the host from a crontab every 15 minutes and
writes a JSON snapshot into the data folder (the container can't see systemd, and isn't
given /home/projects). The worker reads it with `read()`, marking which nginx names point
at the scanned platform (that needs DNS). `analyse()` compares it with the catalog on every
request, so a catalog edit shows at once.
"""
import ipaddress
import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from catalog.models import Environment, Platform, Repository
from .models import LocalScan

STALE_AFTER = timedelta(hours=1)      # four missed runs
MALDET_STALE = timedelta(hours=50)    # maldet scans daily (cron.daily): two missed scans
SECURITY_WINDOW = timedelta(hours=24)  # how long a security event (failed sudo, …) stays red
KEYS_WATCH_STALE = timedelta(hours=1)  # the root cron job writes the key watch every 15 minutes
ROOT = '/home/projects/'
LIST_MAX = 8


def _platform():
    return Platform.objects.filter(slug=settings.SCAN_PLATFORM).first()


def read(path=None, now=None):
    """Read the snapshot into the LocalScan row. Returns True when there was one to read."""
    from .checks import dns_match, platform_networks     # (checks imports the catalog models too)
    path = path or settings.SCAN_FILE
    now = now or timezone.now()
    scan = LocalScan.get()
    try:
        data = json.loads(path.read_text())
        scanned_at = datetime.fromisoformat(data['scanned_at'])
    except FileNotFoundError:
        scan.read_at, scan.error = now, f'No scan at {path} yet: is deploy/scan_local.py in the crontab?'
        scan.save(update_fields=['read_at', 'error'])
        return False
    except (OSError, ValueError, KeyError) as e:
        scan.read_at, scan.error = now, f'Cannot read {path}: {e.__class__.__name__}'
        scan.save(update_fields=['read_at', 'error'])
        return False
    nets = platform_networks(_platform())
    for site in data.get('nginx', []):
        for name in site.get('names', []):
            name['here'] = dns_match(name.get('ips', []), nets) if name.get('ips') else None
    scan.data, scan.scanned_at, scan.read_at, scan.error = data, scanned_at, now, ''
    scan.save()
    return True


def _is_hostname(host):
    if not host or host in ('_', 'localhost') or host.startswith(('~', '*')):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


def _brief(project):
    return {'slug': project.slug, 'name': project.name}


def analyse(scan=None):
    """The snapshot, each repo and nginx name matched with the catalog, plus what's missing."""
    scan = scan or LocalScan.objects.first()
    if not scan or not scan.data:
        return None
    data = scan.data
    platform = _platform()

    # Repos: by their local path.
    records = {r.local_path.rstrip('/'): r for r in Repository.objects.exclude(local_path='')}
    repos = []
    for repo in data.get('repos', []):
        record = records.get(repo['path'])
        repos.append({**repo, 'catalog': {'slug': record.slug, 'name': record.name} if record else None})
    scanned = {repo['path'] for repo in data.get('repos', [])}
    missing_repos = [{'slug': r.slug, 'name': r.name, 'path': path} for path, r in sorted(records.items())
                     if path.startswith(ROOT) and path not in scanned]

    # nginx: every URL host in the catalog, and the platforms' own names.
    by_host = {}
    envs = Environment.objects.select_related('project', 'platform')
    for env in envs:
        for url in env.urls:
            by_host.setdefault(urlsplit(url).hostname, []).append(env)
    platform_names = {n for p in Platform.objects.all() for n in [*p.hostnames, p.dynamic_dns] if n}
    sites, served = [], set()
    for site in data.get('nginx', []):
        names = []
        for name in site.get('names', []):
            host = name['name']
            served.add(host)
            in_catalog = [{'project': _brief(e.project), 'environment': e.name,
                           'platform': e.platform.slug if e.platform else None} for e in by_host.get(host, [])]
            names.append({**name, 'catalog': in_catalog,
                          'known': bool(in_catalog) or host in platform_names or not _is_hostname(host)})
        sites.append({**site, 'names': names})
    missing_sites = []
    if platform:
        for env in envs:
            if env.platform_id != platform.id:
                continue
            for url in env.urls:
                parts = urlsplit(url)
                if _is_hostname(parts.hostname) and parts.port is None and parts.hostname not in served:
                    missing_sites.append({'host': parts.hostname, 'project': _brief(env.project), 'environment': env.name})

    return {
        'host': data.get('host'),
        'platform': {'slug': platform.slug, 'name': platform.name} if platform else None,
        'scanned_at': scan.scanned_at,
        'seconds': data.get('seconds'),
        'repos': repos,
        'missing_repos': missing_repos,
        'nginx': sites,
        'missing_sites': missing_sites,
        'failed_units': (data.get('systemd') or {}).get('failed') or [],
        'running_units': (data.get('systemd') or {}).get('running'),
        'maldet': _maldet(data.get('maldet')),
        'security': data.get('security'),
    }


def _maldet(data):
    """maldet's latest scan of each set of folders, and the flagged files still to deal with:
    still on disk, not quarantined, not ignored. A later clean scan doesn't clear a file:
    the daily scan only looks at files changed in the last day. None without maldet."""
    if data is None:
        return None
    latest = {}
    for scan in data.get('scans', []):          # oldest first: the last one of each set wins
        latest[scan['paths']] = scan
    open_hits = [h for h in data.get('hits', []) if h.get('exists') is not False
                 and not h.get('quarantined') and not h.get('ignored')]
    return {
        'log': data.get('log', ''),
        'error': data.get('error', ''),
        'latest': sorted(latest.values(), key=lambda s: s['paths']),
        'last_at': max((s['at'] for s in data.get('scans', [])), default=None),
        'open_hits': open_hits,
        'hits': len(data.get('hits', [])),
    }


def _listing(names):
    names = list(names)
    more = f' and {len(names) - LIST_MAX} more' if len(names) > LIST_MAX else ''
    return ', '.join(names[:LIST_MAX]) + more


def _short(path):
    return path.removeprefix(ROOT)


def attention(add, now):
    """Add the local scan's findings to "Needs attention" (see attention.items)."""
    scan = LocalScan.objects.first()
    platform = _platform()
    if not scan or (not scan.scanned_at and not scan.error):
        add('scan:never', 'scan', 'warning', 'The local scan has not run yet',
            'deploy/scan_local.py runs from the host’s crontab every 15 minutes (see the README).', platform=platform)
        return
    if scan.error:
        add('scan:error', 'scan', 'warning', 'The local scan cannot be read', scan.error, platform=platform)
        if not scan.data:
            return
    elif now - scan.scanned_at > STALE_AFTER:
        add('scan:stale', 'scan', 'warning', 'The local scan has stopped',
            f'Last scan {timezone.localtime(scan.scanned_at):%d %b %H:%M}: is its line still in '
            'the host’s crontab?', platform=platform)
    result = analyse(scan)
    where = platform.name if platform else result['host']

    maldet_attention(add, now, result['maldet'], where, platform)
    security_attention(add, now, result['security'], where, platform)

    for unit in result['failed_units']:
        add(f'unit:{unit["unit"]}', 'service', 'warning', f'Failed service: {unit["unit"]}',
            f'On {where}: {unit["description"]}. See: sudo systemctl status {unit["unit"]}', platform=platform)

    # nginx: sites for names that now point elsewhere are leftovers (and their certificates
    # can't renew); names that don't resolve at all, or that the catalog doesn't know.
    elsewhere, unresolved, unknown = [], [], []
    for site in result['nginx']:
        hosts = [n for n in site.get('names', []) if _is_hostname(n['name'])]
        away = [n['name'] for n in hosts if n.get('here') is False]
        if away:
            elsewhere.append((site['file'], away))
        unresolved += [n['name'] for n in hosts if not n.get('ips')]
        unknown += [n['name'] for n in hosts if not n['known'] and n.get('ips') and n.get('here') is not False]
    for file, names in elsewhere:
        add(f'nginx-elsewhere:{file}', 'nginx', 'warning', f'nginx site for a name that points elsewhere: {", ".join(names)}',
            f'/etc/nginx/sites-enabled/{file} on {where}, but the name points to another server: a leftover? '
            'Its certificate can’t renew here either.', platform=platform)
    if unresolved:
        add('nginx:unresolved', 'nginx', 'info', 'nginx sites for names that don’t resolve',
            f'On {where}: {_listing(unresolved)}. Leftovers?', platform=platform)
    if unknown:
        add('nginx:unknown', 'nginx', 'info', 'nginx sites not in the catalog',
            f'On {where}: {_listing(unknown)}', platform=platform)
    if result['missing_sites']:
        hosts = sorted({m['host'] for m in result['missing_sites']})
        add('nginx:missing', 'nginx', 'warning', f'In the catalog on {where}, but no nginx site',
            _listing(hosts), platform=platform)

    # git.
    repos = result['repos']
    errors = [r for r in repos if r.get('error')]
    unpushed = [r for r in repos if r.get('ahead')]
    changed = [r for r in repos if r.get('changes') or r.get('untracked')]
    no_remote = [r for r in repos if not r.get('error') and not r.get('remotes')]
    outside = [r for r in repos if not r['catalog']]
    if errors:
        add('git:error', 'git', 'warning', 'Repos the scan couldn’t read',
            _listing(f'{_short(r["path"])} ({r["error"]})' for r in errors), platform=platform)
    if result['missing_repos']:
        add('git:missing', 'git', 'warning', f'In the catalog, but not on {where}',
            _listing(f'{r["name"]} ({r["path"]})' for r in result['missing_repos']), page='repositories')
    if unpushed:
        add('git:unpushed', 'git', 'info', 'Commits not pushed',
            _listing(f'{_short(r["path"])} ({r["ahead"]})' for r in unpushed), page='status')
    if changed:
        add('git:changes', 'git', 'info', f'Uncommitted changes in {len(changed)} repos',
            _listing(_short(r['path']) for r in changed), page='status')
    if no_remote:
        add('git:no-remote', 'git', 'info', f'{len(no_remote)} repos only on {where} (no remote)',
            _listing(_short(r['path']) for r in no_remote), page='status')
    if outside:
        add('git:unknown', 'git', 'info', 'Repos not in the catalog',
            _listing(_short(r['path']) for r in outside), page='repositories')


def maldet_attention(add, now, maldet, where, platform):
    """Flagged files are red (and notified), one item per scan that found them: a new scan
    flagging new files announces itself. Each clears once its files are deleted,
    quarantined or ignored (maldet's ignore_paths / ignore_sigs)."""
    if maldet is None:
        return
    if maldet['error']:
        add('maldet:error', 'malware', 'warning', 'maldet’s log can’t be read',
            f'{maldet["log"]} on {where}: {maldet["error"]}', platform=platform)
        return
    if not maldet['last_at'] or now - datetime.fromisoformat(maldet['last_at']) > MALDET_STALE:
        when = (f'since {timezone.localtime(datetime.fromisoformat(maldet["last_at"])):%d %b %H:%M}'
                if maldet['last_at'] else 'in the last 8 days')
        add('maldet:stale', 'malware', 'warning', f'maldet hasn’t scanned {when}',
            f'Its daily scan runs from /etc/cron.daily/maldet on {where}.', platform=platform)
    by_scan = {}
    for hit in maldet['open_hits']:
        by_scan.setdefault(hit.get('report') or hit['pid'], []).append(hit)
    for scan_id, hits in by_scan.items():
        files = _listing(f'{h["file"]} ({h["signature"]})' for h in hits)
        first = timezone.localtime(datetime.fromisoformat(hits[0]['at']))
        report = f' Report: sudo maldet --report {hits[0]["report"]}.' if hits[0].get('report') else ''
        add(f'maldet:hits:{scan_id}', 'malware', 'danger',
            f'Malware on {where}: {len(hits)} file{"s" if len(hits) != 1 else ""} flagged by maldet',
            f'Scan of {first:%d %b %H:%M}: {files}. Check them, then delete or clean them; a false '
            f'positive goes in /usr/local/maldetect/ignore_paths.{report}', platform=platform)


def _when(at):
    return f'{timezone.localtime(datetime.fromisoformat(at)):%d %b %H:%M}'


def _times(n):
    return f'{n} time{"s" if n != 1 else ""}'


def security_attention(add, now, security, where, platform):
    """What the 2026-11 intrusion did, should it happen again (deploy/scan_local.py,
    scan_security). Events are red for SECURITY_WINDOW after the latest one: a refused sudo, a
    container started under a name docker made up (`docker run` without --name), an SSH login
    with a password or as root. Their key holds the latest event's time, so each new one is
    announced; ageing out isn't (notify.QUIET_WHEN_CLEARED). An SSH key that isn't in
    SSH_KNOWN_KEYS, in an authorized_keys file or used to log in, stays red until it's removed
    or listed. Events before SECURITY_SINCE are ignored."""
    if security is None:
        return
    since = now - SECURITY_WINDOW
    if settings.SECURITY_SINCE and settings.SECURITY_SINCE > since:
        since = settings.SECURITY_SINCE

    def recent(events):
        return [e for e in events if datetime.fromisoformat(e['at']) >= since]

    if security.get('error'):
        add('security:error', 'security', 'warning', 'Some security traces can’t be read',
            f'On {where}: {security["error"]}', platform=platform)

    by_user = {}
    for event in recent(security.get('sudo_failed', [])):
        by_user.setdefault(event['user'], []).append(event)
    for user, events in sorted(by_user.items()):
        commands = _listing(dict.fromkeys(e['command'][:80] or '(no command)' for e in events))
        add(f'security:sudo:{user}:{events[-1]["at"]}', 'security', 'danger',
            f'sudo refused on {where}: {user}, {_times(len(events))}',
            f'Last at {_when(events[-1]["at"])}: {commands}. If it wasn’t you, something is running '
            f'commands as {user}: see sudo journalctl _COMM=sudo.', platform=platform)

    containers = recent(security.get('containers', []))
    if containers:
        names = _listing(f'{c["name"]} ({_when(c["at"])})' for c in containers)
        add(f'security:container:{containers[-1]["at"]}', 'security', 'danger',
            f'Docker container without a name started on {where}, {_times(len(containers))}',
            f'{names}: `docker run` without --name, which is how the 2026-11 attacker became root. '
            'If it wasn’t you, see sudo journalctl -u docker and sudo docker ps -a.', platform=platform)

    logins = recent(security.get('ssh_logins', []))
    passwords = [e for e in logins if e['method'] != 'publickey']
    if passwords:
        who = _listing(f'{e["user"]} from {e["ip"]} ({_when(e["at"])})' for e in passwords)
        add(f'security:ssh-password:{passwords[-1]["at"]}', 'security', 'danger',
            f'SSH login with a password on {where}',
            f'{who}. Logins should need a key: PasswordAuthentication no.', platform=platform)
    as_root = [e for e in logins if e['user'] == 'root']
    if as_root:
        who = _listing(f'from {e["ip"]} ({_when(e["at"])})' for e in as_root)
        add(f'security:ssh-root:{as_root[-1]["at"]}', 'security', 'danger', f'SSH login as root on {where}',
            f'{who}. Root login should be off: PermitRootLogin no.', platform=platform)

    found = {}          # fingerprint → where it was seen
    for k in security.get('authorized_keys', []):
        found.setdefault(k['key'], []).append(f'{k["file"]} ({k["comment"]})' if k.get('comment') else k['file'])
    for e in logins:
        if e.get('key'):
            found.setdefault(e['key'], []).append(f'login as {e["user"]} from {e["ip"]} ({_when(e["at"])})')
    known = set(settings.SSH_KNOWN_KEYS)
    if not known:
        if found:
            add('security:ssh-keys-unlisted', 'security', 'warning', f'The SSH keys on {where} aren’t checked',
                f'List the keys allowed to log in as SSH_KNOWN_KEYS in .env. Seen now: {", ".join(sorted(found))}',
                platform=platform)
    else:
        for fingerprint, places in sorted(found.items()):
            if fingerprint not in known:
                add(f'security:ssh-key:{fingerprint}', 'security', 'danger', f'Unknown SSH key on {where}',
                    f'{fingerprint}: {_listing(dict.fromkeys(places))}. Remove it, or add it to SSH_KNOWN_KEYS '
                    'in .env if it’s yours.', platform=platform)

    watch = security.get('keys_watch') or {}
    if watch.get('error') == 'missing':
        add('security:keys-watch', 'security', 'info', f'Root’s SSH keys on {where} aren’t watched',
            'Only the authorized_keys files the scan’s user can read are checked: install the '
            'root cron job in the README ("Security watch").', platform=platform)
    elif watch.get('error'):
        add('security:keys-watch', 'security', 'warning', 'The SSH key watch can’t be read',
            f'{watch["file"]} on {where}: {watch["error"]}', platform=platform)
    elif watch.get('at') and now - datetime.fromisoformat(watch['at']) > KEYS_WATCH_STALE:
        add('security:keys-watch', 'security', 'warning', 'The SSH key watch has stopped',
            f'{watch["file"]} on {where} was last written {_when(watch["at"])}: is '
            'its root cron job still there?', platform=platform)
