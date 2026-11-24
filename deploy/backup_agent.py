#!/usr/bin/env python3
"""The Projects Gateway backup agent: runs the backups the gateway plans for this server.

From the crontab, every 15 minutes (installed as a copy, so editing the repo never changes
what runs):

    */15 * * * * /usr/bin/python3 /home/backups/backup_agent.py

Each run: check in with the gateway (its token), get this server's jobs and which are due,
make each due backup ONCE in the job's first target, check it, copy it to the other
targets, keep only the newest N where a target says so, report every run, then report
free space and what each job keeps where.

What the gateway can't make it do: it runs only these kinds (a MySQL dump through an
option file, a folder zip, a SQLite copy), and only on paths under the roots allowed in
its own config file on this server. Every value from the gateway is checked here again.
Standard library only.

    backup_agent.py --dry-run        # check in and show the plan, run nothing
    backup_agent.py --job SLUG       # run that job now, due or not
"""
import argparse
import fcntl
import fnmatch
import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = '1.0'
DEFAULT_CONFIG = Path('/home/backups/agent.json')
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DATABASE = re.compile(r'^[A-Za-z0-9_$][A-Za-z0-9_$-]*$')
SUFFIX = {'mysql': '_DB_BK_{}.sql.gz', 'files': '_BK_{}.zip', 'sqlite': '_DB_BK_{}.sqlite3.gz'}
RETRIES, RETRY_WAIT = 3, 10      # talking to the gateway: a home resolver drops lookups now and then


class JobError(Exception):
    pass


# ---- Config and the gateway ----

def load_config(path):
    cfg = json.loads(Path(path).read_text())
    for key in ('gateway', 'token_file', 'source_roots', 'target_roots', 'credentials_dir', 'log_file'):
        if key not in cfg:
            raise SystemExit(f'{path}: "{key}" is missing')
    token_file = Path(cfg['token_file'])
    if token_file.stat().st_mode & 0o077:
        raise SystemExit(f'{token_file} is readable by others: chmod 600 it')
    cfg['token'] = token_file.read_text().strip()
    cfg['source_roots'] = [Path(r).resolve() for r in cfg['source_roots']]
    cfg['target_roots'] = [Path(r).resolve() for r in cfg['target_roots']]
    return cfg


def api(cfg, path, body):
    headers = {'Authorization': f'Agent {cfg["token"]}', 'Content-Type': 'application/json',
               'User-Agent': f'projects-gateway-agent/{VERSION}'}
    if cfg.get('host'):
        # The gateway's local port: say which site, and that the outside leg is HTTPS.
        headers.update({'Host': cfg['host'], 'X-Forwarded-Proto': 'https'})
    request = urllib.request.Request(cfg['gateway'].rstrip('/') + path, data=json.dumps(body).encode(),
                                     headers=headers, method='POST')
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                text = resp.read().decode()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == RETRIES:
                raise SystemExit(f'Gateway answered {e.code} to {path}: {e.read().decode()[:300]}')
        except (urllib.error.URLError, OSError) as e:
            if attempt == RETRIES:
                raise SystemExit(f'Gateway unreachable ({path}): {getattr(e, "reason", e)}')
        time.sleep(RETRY_WAIT)


class Log:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, message):
        line = f'{datetime.now().astimezone().isoformat(timespec="seconds")} agent: {message}'
        with self.path.open('a') as f:
            f.write(line + '\n')
        if sys.stdout.isatty():
            print(line)


# ---- Checks on what the gateway sends ----

def under(path, roots):
    """`path`, resolved (symlinks too), if it's inside one of `roots`; otherwise None."""
    resolved = Path(path).resolve()
    return resolved if any(resolved == r or r in resolved.parents for r in roots) else None


def checked_targets(job, targets, cfg):
    out = []
    for target_id in job['targets']:
        t = targets.get(target_id)
        if t is None:
            raise JobError(f'unknown target {target_id}')
        folder = job['folder']
        if not folder or folder.startswith('/') or not all(NAME.match(p) for p in folder.split('/')):
            raise JobError(f'folder "{folder}" is not allowed')
        base = under(t['path'], cfg['target_roots'])
        if base is None:
            raise JobError(f'target {t["path"]} is outside this agent\'s target_roots')
        out.append({**t, 'dir': base / folder})
    if not out:
        raise JobError('no target')
    return out


def check_job(job, cfg):
    if job['kind'] not in SUFFIX:
        raise JobError(f'unknown kind "{job["kind"]}"')
    if not NAME.match(job['prefix'] or ''):
        raise JobError(f'prefix "{job["prefix"]}" is not allowed')
    if job['kind'] == 'mysql':
        if not DATABASE.match(job['source']):
            raise JobError(f'database name "{job["source"]}" is not allowed')
        if not NAME.match(job['credentials'] or ''):
            raise JobError(f'credentials "{job["credentials"]}" is not allowed')
        cnf = Path(cfg['credentials_dir']) / job['credentials']
        if not cnf.is_file():
            raise JobError(f'no option file {cnf}')
        return cnf
    source = under(job['source'], cfg['source_roots'])
    if source is None:
        raise JobError(f'{job["source"]} is outside this agent\'s source_roots')
    if job['kind'] == 'files' and not source.is_dir():
        raise JobError(f'source folder {source} does not exist')
    if job['kind'] == 'sqlite' and not source.is_file():
        raise JobError(f'database file {source} does not exist')
    if any(not isinstance(e, str) or not e or e.startswith('-') for e in job.get('excludes') or []):
        raise JobError('an exclude pattern is not allowed')
    return source


def mounted(target):
    return not target.get('mount') or os.path.ismount(target['mount'])


# ---- Making a backup ----

def stderr_tail(stream):
    stream.seek(0)
    lines = stream.read().decode(errors='replace').strip().splitlines()
    return lines[-1][:300] if lines else ''


def make_mysql(cnf, database, tmp):
    """mysqldump | gzip, checked: the dump must end with "-- Dump completed"."""
    with tempfile.TemporaryFile() as err, gzip.open(tmp, 'wb') as out:
        proc = subprocess.Popen(['mysqldump', f'--defaults-extra-file={cnf}', '--single-transaction', database],
                                stdout=subprocess.PIPE, stderr=err)
        tail = b''
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b''):
            out.write(chunk)
            tail = (tail + chunk)[-4096:]
        if proc.wait() != 0:
            raise JobError(f'mysqldump failed: {stderr_tail(err) or f"exit {proc.returncode}"}')
    last = tail.decode(errors='replace').rstrip().splitlines()[-1:] or ['']
    if not last[0].startswith('-- Dump completed'):
        raise JobError('the dump is incomplete (no "-- Dump completed" at its end)')


def make_zip(source, excludes, tmp):
    """zip -r, symlinks stored as links (-y): what they point to has its own backup."""
    with tempfile.TemporaryFile() as err:
        args = ['zip', '-q', '-r', '-y', str(tmp), str(source) + '/']
        if excludes:
            args += ['-x', *excludes]
        code = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=err).returncode
        if code != 0:
            raise JobError(f'zip failed (exit {code}): {stderr_tail(err)}')


def make_sqlite(source, tmp):
    """SQLite's backup API (consistent while the app writes), checked, then gzipped."""
    with tempfile.TemporaryDirectory() as work:
        copy = Path(work) / 'copy.sqlite3'
        src = sqlite3.connect(source, timeout=30)
        dst = sqlite3.connect(copy)
        try:
            src.backup(dst)
            result = dst.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            src.close()
            dst.close()
        if result != 'ok':
            raise JobError(f'the copy fails its integrity check: {result}')
        with copy.open('rb') as f, gzip.open(tmp, 'wb') as out:
            shutil.copyfileobj(f, out)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def human(n):
    for unit in ('B', 'K', 'M', 'G'):
        if n < 1024:
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}T'


def run_job(job, targets, cfg, log):
    """Make, check, copy, prune. Returns the run report."""
    started = datetime.now(timezone.utc)
    report = {'job': job['id'], 'started_at': started.isoformat(), 'requested': job.get('requested', False),
              'files': [], 'error': ''}
    try:
        source = check_job(job, cfg)
        places = checked_targets(job, targets, cfg)
        first = places[0]
        if not mounted(first):
            raise JobError(f'{first["mount"]} is not mounted')
        first['dir'].mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d%H%M%S')
        name = job['prefix'] + SUFFIX[job['kind']].format(stamp)
        dest = first['dir'] / name
        # zip adds ".zip" to a name without it: the part file keeps the extension.
        tmp = dest.with_name(name.replace('.zip', '.part.zip') if job['kind'] == 'files' else name + '.part')
        tmp.unlink(missing_ok=True)
        try:
            if job['kind'] == 'mysql':
                make_mysql(source, job['source'], tmp)
            elif job['kind'] == 'files':
                make_zip(source, job.get('excludes') or [], tmp)
            else:
                make_sqlite(source, tmp)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        size = dest.stat().st_size
        report.update(size=size, sha256=sha256(dest))
        report['files'].append({'target': first['id'], 'path': str(dest), 'ok': True})
        log(f'OK   {first["name"]}: {dest} ({human(size)})')
        for place in places[1:]:
            copy = place['dir'] / name
            try:
                if not mounted(place):
                    raise JobError(f'{place["mount"]} is not mounted')
                place['dir'].mkdir(parents=True, exist_ok=True)
                part = copy.with_name(name + '.part')
                shutil.copyfile(dest, part)
                try:
                    # The timestamps only (like cp --preserve=timestamps): a CIFS share like
                    # a NAS may refuse permission bits.
                    st = dest.stat()
                    os.utime(part, (st.st_atime, st.st_mtime))
                except OSError:
                    pass
                if part.stat().st_size != size:
                    part.unlink(missing_ok=True)
                    raise JobError('the copy has a different size')
                os.replace(part, copy)
                report['files'].append({'target': place['id'], 'path': str(copy), 'ok': True})
                log(f'OK   {place["name"]}: {copy}')
            except (JobError, OSError) as e:
                report['files'].append({'target': place['id'], 'path': str(copy), 'ok': False, 'error': str(e)})
                log(f'FAIL {place["name"]}: {copy}: {e}')
        for place in places:
            prune(job, place, log)
        report['status'] = 'ok' if all(f['ok'] for f in report['files']) else 'partial'
    except (JobError, OSError, sqlite3.Error, subprocess.SubprocessError) as e:
        report.update(status='failed', error=str(e)[:2000])
        log(f'FAIL {job["slug"]}: {e}')
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    return report


def job_files(job, directory):
    pattern = job['prefix'] + SUFFIX[job['kind']].format('*')
    try:
        return sorted(p for p in directory.iterdir() if p.is_file() and fnmatch.fnmatchcase(p.name, pattern))
    except OSError:
        return []


def prune(job, place, log):
    """Keep the target's newest N of this job's backups (the stamp in the name sorts them)."""
    keep = place.get('keep') or 0
    if keep <= 0 or not mounted(place):
        return
    for old in job_files(job, place['dir'])[:-keep]:
        old.unlink(missing_ok=True)
        log(f'DEL  {place["name"]}: {old} (keeping the newest {keep})')


# ---- Reports ----

def disk_and_usage(plan, cfg):
    targets = {t['id']: t for t in plan['targets']}
    disk = {}
    for t in targets.values():
        if not mounted(t):
            disk[t['id']] = {'error': f'{t["mount"]} is not mounted'}
            continue
        try:
            u = shutil.disk_usage(t['path'])
            disk[t['id']] = {'free': u.free, 'total': u.total}
        except OSError as e:
            disk[t['id']] = {'error': e.strerror or str(e)}
    usage = {}
    for job in plan['jobs']:
        per = {}
        for target_id in job['targets']:
            t = targets.get(target_id)
            if not t or 'error' in disk.get(target_id, {}) or job['kind'] not in SUFFIX or not NAME.match(job['prefix']):
                continue
            base = under(t['path'], cfg['target_roots'])
            if base is None:
                continue
            files = job_files(job, base / job['folder'])
            per[target_id] = {'count': len(files), 'bytes': sum(f.stat().st_size for f in files)}
        usage[job['id']] = per
    return disk, usage


def main():
    parser = argparse.ArgumentParser(description='The Projects Gateway backup agent.')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--dry-run', action='store_true', help='check in and show the plan, run nothing')
    parser.add_argument('--job', help='run this job now (its slug), due or not')
    args = parser.parse_args()
    cfg = load_config(args.config)
    log = Log(cfg['log_file'])

    # One agent at a time: a long weekly zip can outlast the 15 minutes.
    lock = open(cfg.get('lock_file', '/tmp/backup_agent.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0

    plan = api(cfg, '/api/agent/checkin/', {'version': VERSION, 'hostname': socket.gethostname()})
    targets = {t['id']: t for t in plan['targets']}
    if args.job:
        jobs = [j for j in plan['jobs'] if j['slug'] == args.job]
        if not jobs:
            raise SystemExit(f'No job "{args.job}" on {plan["platform"]}.')
    else:
        jobs = [j for j in plan['jobs'] if j['due']]
    if args.dry_run:
        for job in plan['jobs']:
            mark = 'DUE' if job in jobs else '   '
            try:
                check_job(job, cfg)
                checked_targets(job, targets, cfg)
                problem = ''
            except (JobError, OSError) as e:
                problem = f'  ← {e}'
            print(f'{mark} {job["slug"]:24} {job["kind"]:6} {job["source"]}{problem}')
        return 0

    failed = 0
    if jobs:
        log(f'START {len(jobs)} job(s): {", ".join(j["slug"] for j in jobs)}')
    for job in jobs:
        report = run_job(job, targets, cfg, log)
        failed += report['status'] == 'failed'
        api(cfg, '/api/agent/runs/', report)
    if jobs:
        log(f'END  {len(jobs) - failed} made, {failed} failed')
    disk, usage = disk_and_usage(plan, cfg)
    api(cfg, '/api/agent/report/', {'disk': disk, 'usage': usage})
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
