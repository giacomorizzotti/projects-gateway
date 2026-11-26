#!/usr/bin/env python3
"""The host's local scan for the Projects Gateway: git repos, nginx sites, systemd services,
maldet's malware scans, security traces (failed sudo, SSH logins and keys, unnamed containers).

It runs on the host, not in a container: a container can't see systemd, and mounting
/home/projects into one would also expose every project's .env. A crontab (of a user who can
read the projects) runs it every 15 minutes, and it writes one JSON snapshot that the
gateway's worker reads:

    */15 * * * * /usr/bin/python3 /path/to/projects-gateway/deploy/scan_local.py

    python3 deploy/scan_local.py --out data/dev/scan.json    # for the dev copy

Read-only. git runs with GIT_OPTIONAL_LOCKS=0 (no index refresh written) and never fetches,
so "to push" is counted against the last fetch. Credentials in remote URLs are stripped.
Standard library only.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path('/home/projects')
NGINX_SITES = Path('/etc/nginx/sites-enabled')
DEFAULT_OUT = Path(__file__).resolve().parent.parent / 'data' / 'scan.json'
MAX_DEPTH = 6
SKIP_DIRS = {'.git', 'node_modules', 'venv', '.venv', 'vendor', '__pycache__', 'site-packages', '.cache'}
GIT_ENV = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C'}


def run(*cmd, timeout=20):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=GIT_ENV)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip().splitlines()[-1:] or [f'exit {result.returncode}'])
    return result.stdout


def git(path, *args):
    # safe.directory: some repos belong to other users (umami); reading them is all this does.
    return run('git', '-c', 'safe.directory=*', '-C', str(path), *args)


def find_repos(root):
    repos = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if '.git' in dirnames or '.git' in filenames:
            repos.append(Path(dirpath))
        dirnames[:] = [] if depth >= MAX_DEPTH else sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith('venv-'))
    return repos


def strip_credentials(url):
    return re.sub(r'(?<=//)[^/@\s]+@', '', url)


def scan_repo(path):
    repo = {'path': str(path)}
    try:
        status = git(path, 'status', '--porcelain=v2', '--branch')
        changes = untracked = 0
        for line in status.splitlines():
            if line.startswith('# branch.head '):
                head = line.split(' ', 2)[2]
                repo['branch'] = None if head == '(detached)' else head
            elif line.startswith('# branch.upstream '):
                repo['upstream'] = line.split(' ', 2)[2]
            elif line.startswith('# branch.ab '):
                ahead, behind = line.split()[2:4]
                repo['ahead'], repo['behind'] = int(ahead), abs(int(behind))
            elif line[:2] in ('1 ', '2 ', 'u '):
                changes += 1
            elif line.startswith('? '):
                untracked += 1
        repo['changes'], repo['untracked'] = changes, untracked
        remotes = {}
        for line in git(path, 'remote', '-v').splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == '(fetch)':
                remotes[parts[0]] = strip_credentials(parts[1])
        repo['remotes'] = remotes
        try:
            sha, date, subject = git(path, 'log', '-1', '--format=%h%x00%cI%x00%s').rstrip('\n').split('\x00', 2)
            repo.update(head=sha, date=date, subject=subject[:200])
        except RuntimeError:
            repo['head'] = None            # no commits yet
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
        repo['error'] = str(e)[:300]
    return repo


# A failed lookup is tried again before a name counts as not resolving: some home routers drop
# a few lookups in a hundred, and one dropped lookup would flag a site until the next scan.
# (The gateway's health checks retry the same way.) A name that really doesn't resolve costs
# LOOKUP_TRIES - 1 pauses.
LOOKUP_TRIES = 3
LOOKUP_PAUSE = 1        # seconds


def resolve(name, sleep=time.sleep):
    for attempt in range(1, LOOKUP_TRIES + 1):
        try:
            return sorted({i[4][0] for i in socket.getaddrinfo(name, None, type=socket.SOCK_STREAM)})
        except UnicodeError:
            return []                   # not a name a lookup could ever answer
        except OSError:
            if attempt < LOOKUP_TRIES:
                sleep(LOOKUP_PAUSE)
    return []


def directive(text, name):
    return [m.split() for m in re.findall(rf'(?:^|[;{{}}\s]){name}\s+([^;]+);', text)]


def scan_nginx(sites):
    out = []
    for entry in sorted(sites.iterdir()) if sites.is_dir() else []:
        site = {'file': entry.name}
        try:
            text = '\n'.join(line.split('#', 1)[0] for line in entry.read_text(errors='replace').splitlines())
        except OSError as e:
            site['error'] = e.strerror or str(e)
            out.append(site)
            continue
        names = sorted({n for args in directive(text, 'server_name') for n in args})
        site['names'] = [{'name': n, 'ips': resolve(n) if re.fullmatch(r'[A-Za-z0-9.-]+\.[A-Za-z]+', n) else []}
                         for n in names]
        site['ssl_certificates'] = sorted({args[0] for args in directive(text, 'ssl_certificate')})
        site['proxy_pass'] = sorted({args[0] for args in directive(text, 'proxy_pass')})
        site['roots'] = sorted({args[0] for args in directive(text, 'root')})
        out.append(site)
    return out


def scan_systemd():
    def units(state):
        try:
            text = run('systemctl', 'list-units', '--type=service', f'--state={state}', '--no-legend', '--plain')
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            return None
        rows = []
        for line in text.splitlines():
            parts = line.split(None, 4)
            if parts:
                rows.append({'unit': parts[0], 'description': parts[4] if len(parts) > 4 else ''})
        return rows

    running = units('running')
    return {'failed': units('failed'), 'running': len(running) if running is not None else None}


# Linux Malware Detect. Its event log can be read by anyone (its scan reports can't): one
# line per step, "Nov 14 2026 06:28:04 myhost maldet(2003735): {scan} scan completed on
# …: files 469, malware hits 0, cleaned hits 0, time 7s", and "{hit} malware hit SIG found
# for FILE" for each file it flags. The pid ties a scan's lines together.
MALDET = Path('/usr/local/maldetect')
MALDET_DAYS = 8                     # the scans kept: a week and a day
MALDET_TAIL = 4 * 1024 * 1024       # the log's end that is read (it grows about 2.5 KB a day)
MONTHS = {m: i for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}
_MALDET_LINE = re.compile(r'^(\w{3}) +(\d{1,2}) (\d{4}) (\d\d):(\d\d):(\d\d) \S+ maldet\((\d+)\): \{(\w+)\} (.*)$')
_MALDET_DONE = re.compile(r'scan completed on (.+): files (\d+), malware hits (\d+), cleaned hits (\d+), time (\d+)s')
_MALDET_REPORT = re.compile(r'scan report saved, to view run: maldet --report (\S+)')
_MALDET_HIT = re.compile(r'malware hit (\S+) found for (.+)$')
_MALDET_QUARANTINED = re.compile(r"malware quarantined from '(.+)' to ")


def _maldet_list(name):
    """One of maldet's ignore files (ignore_paths, ignore_sigs): its non-empty lines."""
    try:
        return [line.strip() for line in (MALDET / name).read_text().splitlines() if line.strip()]
    except OSError:
        return []


def scan_maldet(log=None, now=None):
    """maldet's scans of the last MALDET_DAYS days, and every file its log says it flagged:
    whether that file is still there, was quarantined, or is ignored now (ignore_paths /
    ignore_sigs, maldet's own way to dismiss a false positive). None without maldet."""
    log = log or MALDET / 'logs' / 'event_log'
    if not log.exists():
        return None
    try:
        with log.open('rb') as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - MALDET_TAIL))
            text = f.read().decode('utf-8', 'replace')
    except OSError as e:
        return {'log': str(log), 'error': e.strerror or e.__class__.__name__, 'scans': [], 'hits': []}
    cutoff = (now or datetime.now().astimezone()) - timedelta(days=MALDET_DAYS)
    scans, hits, reports, quarantined = [], [], {}, set()
    for line in text.splitlines():
        m = _MALDET_LINE.match(line)
        if not m or m[1] not in MONTHS:
            continue
        # maldet writes the host's local time.
        at = datetime(int(m[3]), MONTHS[m[1]], int(m[2]), int(m[4]), int(m[5]), int(m[6])).astimezone()
        pid, kind, message = m[7], m[8], m[9]
        if kind == 'scan':
            done, report = _MALDET_DONE.match(message), _MALDET_REPORT.match(message)
            if done and at >= cutoff:
                scans.append({'at': at.isoformat(timespec='seconds'), 'pid': pid, 'paths': done[1],
                              'files': int(done[2]), 'hits': int(done[3]), 'cleaned': int(done[4]),
                              'seconds': int(done[5])})
            elif report:
                reports[pid] = report[1]
        elif kind == 'hit' and (hit := _MALDET_HIT.match(message)):
            hits.append({'at': at.isoformat(timespec='seconds'), 'pid': pid, 'signature': hit[1], 'file': hit[2]})
        elif kind == 'quar' and (quar := _MALDET_QUARANTINED.match(message)):
            quarantined.add(quar[1])
    ignored_paths, ignored_sigs = _maldet_list('ignore_paths'), _maldet_list('ignore_sigs')
    for hit in hits:
        hit['report'] = reports.get(hit['pid'], '')
        hit['quarantined'] = hit['file'] in quarantined
        hit['ignored'] = (any(hit['file'] == p or hit['file'].startswith(p.rstrip('/') + '/') for p in ignored_paths)
                          or any(s and s in hit['signature'] for s in ignored_sigs))
        try:
            hit['exists'] = os.path.lexists(hit['file'])
        except (OSError, ValueError):
            hit['exists'] = None
    for scan in scans:
        scan['report'] = reports.get(scan['pid'], '')
    return {'log': str(log), 'scans': scans, 'hits': hits[-200:]}


# Security traces: what an attacker who got code running as a user would likely do next, so it
# shows up within a run. The scan's user reads them through the adm group: the auth log
# (failed sudo, SSH logins with the key used) and the docker daemon's journal (containers
# started without --name: a quick `docker run --rm` is how a docker group member becomes root).
# Root's and the other accounts' authorized_keys can only be read by root, so a root cron job
# (/etc/cron.d/projects-gateway-watch, see the README) writes their fingerprints into WATCH_KEYS.
AUTH_LOGS = (Path('/var/log/auth.log.1'), Path('/var/log/auth.log'))     # oldest first
WATCH_KEYS = Path('/var/lib/projects-gateway-watch/authorized_keys')
SECURITY_DAYS = 8
SECURITY_TAIL = 64 * 1024 * 1024    # an auth.log can reach ~25 MB a week, nearly all SSH password-guessing bots
_SUDO_FAILED = re.compile(r' sudo(?:\[\d+\])?: +(\S+) : (?:\d+ incorrect password attempts?|a password is required'
                          r'|user NOT in sudoers|command not allowed)\b.*?(?:COMMAND=(.*))?$')
_SSH_ACCEPTED = re.compile(r' sshd(?:-session)?\[\d+\]: Accepted (\S+) for (\S+) from (\S+) port \d+ \w+'
                           r'(?:: \S+ (SHA256:[A-Za-z0-9+/]+))?')
_DOCKER_OWN_NAME = re.compile(r'^[a-z]+_[a-z]+$')    # the names docker makes up (adjective_surname)
_SBJOIN = re.compile(r'sbJoin: .*\bep=(\S+)')
_WATCH_LINE = re.compile(r'^(\S+) \d+ (SHA256:[A-Za-z0-9+/]+) ?(.*?)(?: \([A-Z0-9-]+\))?$')   # path + ssh-keygen -l
_KEY_TYPES = ('ssh-', 'ecdsa-', 'sk-')


def _tail(path, limit, keep=None):
    """The file's last `limit` bytes as lines; with `keep`, only lines containing one of those
    byte strings (decoding a whole auth log line by line takes seconds, filtering first doesn't)."""
    with path.open('rb') as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - limit))
        lines = f.read().split(b'\n')
    if keep:
        lines = [line for line in lines if any(k in line for k in keep)]
    return [line.decode('utf-8', 'replace') for line in lines]


def key_fingerprint(line):
    """(SHA256 fingerprint, comment) of an authorized_keys line, as ssh-keygen -l shows it.
    Options may come before the key type. (None, '') for anything else."""
    parts = line.split()
    for i, part in enumerate(parts[:-1]):
        if part.startswith(_KEY_TYPES):
            try:
                blob = base64.b64decode(parts[i + 1], validate=True)
            except ValueError:
                return None, ''
            digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
            return f'SHA256:{digest}', ' '.join(parts[i + 2:])
    return None, ''


def _docker_journal():
    return run('journalctl', '-u', 'docker', '-o', 'json', '--no-pager', '--since', f'-{SECURITY_DAYS}d', timeout=40)


def scan_security(now=None, auth_logs=AUTH_LOGS, watch=WATCH_KEYS, key_files=None, journal=_docker_journal):
    """The last SECURITY_DAYS days of: sudo refused (wrong or no password, not allowed), SSH
    logins accepted (method, user, address, key), containers started under a name docker made
    up, and every authorized_keys key that can be seen (WATCH_KEYS plus the files this user can
    read). Only facts: deciding what's suspicious is the gateway's job."""
    now = now or datetime.now().astimezone()
    cutoff = now - timedelta(days=SECURITY_DAYS)
    stamp = lambda at: at.isoformat(timespec='seconds')     # noqa: E731
    sudo, logins, read, errors = [], [], [], []
    for path in auth_logs:
        try:
            lines = _tail(path, SECURITY_TAIL, keep=(b' sudo', b': Accepted '))
        except FileNotFoundError:
            continue
        except OSError as e:
            errors.append(f'{path}: {e.strerror or e.__class__.__name__}')
            continue
        read.append(str(path))
        for line in lines:
            try:
                at = datetime.fromisoformat(line.split(' ', 1)[0])
            except ValueError:
                continue
            at = at if at.tzinfo else at.astimezone()
            if at < cutoff:
                continue
            if m := _SUDO_FAILED.search(line):
                sudo.append({'at': stamp(at), 'user': m[1], 'command': (m[2] or '').strip()[:160]})
            elif m := _SSH_ACCEPTED.search(line):
                logins.append({'at': stamp(at), 'method': m[1], 'user': m[2], 'ip': m[3], 'key': m[4] or ''})
    if not read and not errors:
        errors.append('no auth log found')

    containers = []
    try:
        for line in journal().splitlines():
            try:
                entry = json.loads(line)
                m = _SBJOIN.search(str(entry.get('MESSAGE', '')))
                if m and _DOCKER_OWN_NAME.match(m[1]):
                    at = datetime.fromtimestamp(int(entry['__REALTIME_TIMESTAMP']) / 1e6, timezone.utc).astimezone()
                    containers.append({'at': stamp(at), 'name': m[1]})
            except (ValueError, KeyError):
                continue
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        errors.append(f'docker journal: {e}')

    keys, seen = [], set()
    watch_info = {'file': str(watch), 'at': None, 'error': ''}
    try:
        watch_info['at'] = stamp(datetime.fromtimestamp(watch.stat().st_mtime, timezone.utc).astimezone())
        for line in watch.read_text().splitlines():
            m = _WATCH_LINE.match(line.strip())
            if m and (m[1], m[2]) not in seen:
                seen.add((m[1], m[2]))
                keys.append({'file': m[1], 'key': m[2], 'comment': m[3]})
    except FileNotFoundError:
        watch_info['error'] = 'missing'
    except OSError as e:
        watch_info['error'] = e.strerror or e.__class__.__name__
    if key_files is None:
        try:
            key_files = [Path('/root/.ssh/authorized_keys'), *sorted(Path('/home').glob('*/.ssh/authorized_keys'))]
        except OSError:
            key_files = []
    for path in key_files:
        try:
            text = path.read_text()
        except OSError:             # not readable as the scan's user: WATCH_KEYS covers it
            continue
        for line in text.splitlines():
            fingerprint, comment = key_fingerprint(line) if not line.lstrip().startswith('#') else (None, '')
            if fingerprint and (str(path), fingerprint) not in seen:
                seen.add((str(path), fingerprint))
                keys.append({'file': str(path), 'key': fingerprint, 'comment': comment})

    return {'auth_logs': read, 'error': '; '.join(errors), 'sudo_failed': sudo[-100:], 'ssh_logins': logins[-300:],
            'containers': containers[-100:], 'authorized_keys': keys, 'keys_watch': watch_info}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    started = time.monotonic()
    snapshot = {
        'version': 1,
        'host': socket.gethostname(),
        'scanned_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'repos': [scan_repo(path) for path in find_repos(ROOT)],
        'nginx': scan_nginx(NGINX_SITES),
        'systemd': scan_systemd(),
        'maldet': scan_maldet(),
        'security': scan_security(),
    }
    snapshot['seconds'] = round(time.monotonic() - started, 1)
    # Written whole, then renamed: the worker never reads half a file.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix('.tmp')
    tmp.write_text(json.dumps(snapshot, indent=1))
    os.replace(tmp, args.out)


if __name__ == '__main__':
    main()
