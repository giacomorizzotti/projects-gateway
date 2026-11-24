"""GitHub sync: the owner's profile and repos, read into the catalog.

Read-only towards GitHub: a couple of GET requests per sync, with the fine-grained token
from `.env` (Metadata: read). Only repos owned by GITHUB_OWNER are taken.

Each GitHub repo is matched to a Repository record by its GitHub id (after the first sync)
or by its remote URL (git@github.com:owner/name.git ↔ github.com/owner/name). A repo with
no record gets one, linked to no project, so it shows up as "needs a project".
"""
import re
from datetime import datetime, timezone as dt_timezone

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import GitHubProfile, Repository
from .utils import unique_slug

API = 'https://api.github.com'
TIMEOUT = 15
MAX_PAGES = 20

_REMOTE = re.compile(r'github\.com[:/]+(?P<owner>[^/\s]+)/(?P<name>[^/\s]+?)(?:\.git)?/?$', re.I)


class GitHubError(Exception):
    pass


def parse_remote(url):
    """('owner', 'name'), lowercased, from any GitHub remote or web URL; None otherwise."""
    m = _REMOTE.search((url or '').strip())
    return (m['owner'].lower(), m['name'].lower()) if m else None


def _parse_expiry(value):
    # e.g. "2027-02-08 12:00:00 +0100" or "2027-02-08 12:00:00 UTC"
    if not value:
        return None
    value = value.strip().replace(' UTC', ' +0000')
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S %z').astimezone(dt_timezone.utc)
    except ValueError:
        return None


class _Client:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'projects-gateway',
        })
        self.token_expires_at = None

    def get(self, url, params=None):
        try:
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            # The exception's text can include the URL but never the headers (the token).
            raise GitHubError(f'GitHub is unreachable ({e.__class__.__name__}).') from None
        expiry = _parse_expiry(resp.headers.get('github-authentication-token-expiration'))
        if expiry:
            self.token_expires_at = expiry
        if resp.status_code == 401:
            raise GitHubError('GitHub rejected the token: expired or revoked? Create a new one and update .env.')
        if resp.status_code in (403, 429) and resp.headers.get('x-ratelimit-remaining') == '0':
            raise GitHubError('GitHub rate limit reached: try again later.')
        if not resp.ok:
            raise GitHubError(f'GitHub answered {resp.status_code} for {url.removeprefix(API)}.')
        return resp

    def get_all(self, url, params):
        items = []
        for _ in range(MAX_PAGES):
            resp = self.get(url, params)
            items.extend(resp.json())
            url, params = resp.links.get('next', {}).get('url'), None
            if not url:
                return items
        raise GitHubError('Too many pages of repositories.')


def _profile():
    profile = GitHubProfile.objects.first()
    return profile or GitHubProfile(login=settings.GITHUB_OWNER)


def sync():
    """Runs one sync. Returns a summary; raises GitHubError (also recorded on the profile)."""
    profile = _profile()
    profile.attempted_at = timezone.now()
    try:
        summary = _sync(profile)
    except GitHubError as e:
        profile.last_error = str(e)
        profile.save()
        raise
    profile.last_error = ''
    profile.synced_at = timezone.now()
    profile.save()
    return summary


def _sync(profile):
    owner = settings.GITHUB_OWNER
    if not settings.GITHUB_TOKEN:
        raise GitHubError('No GITHUB_TOKEN in .env yet.')
    if not owner:
        raise GitHubError('No GITHUB_OWNER in .env yet.')
    client = _Client(settings.GITHUB_TOKEN)

    user = client.get(f'{API}/user').json()
    # The repo list below is "repos of the token's account": refuse a token of another
    # account, which would make every one of the owner's repos look deleted.
    if user.get('login', '').lower() != owner.lower():
        raise GitHubError(f'The token belongs to "{user.get("login")}", not to "{owner}".')
    repos = client.get_all(f'{API}/user/repos', {'affiliation': 'owner', 'per_page': 100})
    repos = [r for r in repos if r['owner']['login'].lower() == owner.lower()]

    profile.token_expires_at = client.token_expires_at
    for field in ['login', 'name', 'bio', 'avatar_url', 'html_url', 'blog', 'location', 'company']:
        setattr(profile, field, (user.get(field) or '')[:profile._meta.get_field(field).max_length])
    profile.followers = user.get('followers') or 0

    with transaction.atomic():
        return _apply_repos(repos, owner.lower())


def _apply_repos(repos, owner):
    now = timezone.now()
    records = list(Repository.objects.all())
    by_id = {r.github_id: r for r in records if r.github_id}
    by_remote = {}
    for r in records:
        key = parse_remote(r.remote_url)
        if key:
            by_remote.setdefault(key, r)

    seen, created = set(), 0
    for gh in repos:
        repo = by_id.get(gh['id']) or by_remote.get((owner, gh['name'].lower()))
        if repo is None:
            repo = Repository(name=gh['name'], slug=unique_slug(Repository, gh['name']),
                              remote_url=gh.get('ssh_url') or '')
            created += 1
        repo.hosting = Repository.Hosting.GITHUB
        repo.github_id = gh['id']
        repo.github_url = gh.get('html_url') or ''
        repo.github_description = (gh.get('description') or '')[:500]
        repo.default_branch = gh.get('default_branch') or ''
        repo.language = gh.get('language') or ''
        repo.topics = gh.get('topics') or []
        repo.private = bool(gh.get('private'))
        repo.archived = bool(gh.get('archived'))
        repo.fork = bool(gh.get('fork'))
        repo.pushed_at = parse_datetime(gh['pushed_at']) if gh.get('pushed_at') else None
        repo.open_issues = gh.get('open_issues_count')
        repo.github_missing = False
        repo.synced_at = now
        repo.save()
        seen.add(repo.pk)

    # The owner's repos GitHub didn't list. Other owners' repos (upstream clones) aren't judged.
    missing = 0
    for repo in Repository.objects.filter(hosting=Repository.Hosting.GITHUB).exclude(pk__in=seen):
        key = parse_remote(repo.remote_url)
        is_owners = bool(repo.github_id) or bool(key and key[0] == owner)
        if repo.github_missing != is_owners:
            repo.github_missing = is_owners
            repo.save(update_fields=['github_missing'])
        missing += is_owners

    return {'repos': len(repos), 'created': created, 'missing': missing}


def status():
    """What the gateway knows about the GitHub side, for the frontend."""
    profile = GitHubProfile.objects.first()
    synced = Repository.objects.exclude(github_id=None)
    return {
        'owner': settings.GITHUB_OWNER,
        'configured': bool(settings.GITHUB_TOKEN),
        'profile': None if not (profile and profile.html_url) else {
            field: getattr(profile, field)
            for field in ['login', 'name', 'bio', 'avatar_url', 'html_url', 'blog', 'location',
                          'company', 'followers']
        },
        'synced_at': profile.synced_at if profile else None,
        'attempted_at': profile.attempted_at if profile else None,
        'last_error': profile.last_error if profile else '',
        'token_expires_at': profile.token_expires_at if profile else None,
        'counts': {
            'repos': synced.count(),
            'public': synced.filter(private=False).count(),
            'private': synced.filter(private=True).count(),
            'archived': synced.filter(archived=True).count(),
            'unlinked': synced.filter(projects__isnull=True, archived=False).count(),
            'missing': Repository.objects.filter(github_missing=True).count(),
        },
    }
