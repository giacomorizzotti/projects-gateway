# CLAUDE.md

Projects Gateway: a self-hosted catalog of web projects (environments, platforms, repositories, dependencies, technologies, services, domains), with health checks, a host scan, a backup planner and notifications on top. What it does and how to run it: [README.md](README.md).

This repository is public. A deployment's own notes (its server, host names, clients, plans) live in `private/`, which is gitignored; if `private/CLAUDE.md` exists it's loaded at the end of this file.

## Layout

```
backend/    Django 5.2 LTS + DRF, SQLite (data/gateway.sqlite3)
  gateway/    settings (everything from the repo-root .env), urls, the SPA fallback view
  accounts/   login: Bearer tokens checked against the auth server's userinfo; add_user command
  catalog/    models, API, import_inventory, seed_dev_data, refresh_dev_db, the worker command
  monitoring/ live status: health checks, the host scan, "needs attention" (/api/status/), notifications
  backups/    the backup planner: targets, jobs, runs, agents; the agents' own API (/api/agent/…)
  domains/    the domains owned or renewed: registry lookups (RDAP, WHOIS for .it), expiry in "needs attention"
frontend/   Vue 3 + Vite + mini (src/mini is a relative symlink to ../mini/website/src/mini: mini is checked out next to this repo)
seed/       demo.yaml: invented data for development and the tests
deploy/     scan_local.py and backup_agent.py (run on the host from a crontab, not in Docker), an nginx example
private/    (gitignored) this deployment's own notes and data
data/       SQLite DB, scan.json (gitignored)
```

## Commands

```bash
# Both dev servers in the background (Django reads .env): this machine only, never Vite's --host.
# Logs and pids in $XDG_RUNTIME_DIR/projects-gateway-dev-<uid>.
./dev.sh start | stop | status | logs

# Backend (dev ports: API 8010, Vite 5180)
cd backend
../venv/bin/python manage.py runserver 127.0.0.1:8010
../venv/bin/python manage.py test
DJANGO_DEBUG=True DATA_DIR=<scratch dir> ../venv/bin/python manage.py test   # as a user that can't read .env
../venv/bin/python manage.py seed_dev_data [--user <name>]   # the dev database ← the demo (seed/demo.yaml + made-up status); keeps the logins
../venv/bin/python manage.py refresh_dev_db            # the dev database ← a snapshot of the live one instead, then migrated
../venv/bin/python manage.py import_inventory [file]   # seed an EMPTY catalog from YAML (default: the demo; refuses otherwise)
../venv/bin/python manage.py add_user <auth-server username> --name "Full Name"
../venv/bin/python manage.py sync_github               # needs GITHUB_OWNER and GITHUB_TOKEN in .env
../venv/bin/python manage.py check_health              # the worker's run, now (checks, host scan), then what needs attention; --notify sends too
../venv/bin/python manage.py notify_test               # a test message on every channel set up in .env (and your Telegram chat ID)
../venv/bin/python manage.py agent_token <platform>    # a new agent token, printed once: pipe it into the agent's token file
python3 ../deploy/scan_local.py --out ../data/dev/scan.json   # the host scan, for the dev database

# Frontend (VITE_AUTH_SERVER_BASE and VITE_OAUTH_CLIENT_ID in frontend/.env.local)
cd frontend
npm run dev      # http://localhost:5180, proxies /api to 127.0.0.1:8010
npm run build    # dist/, served by Django (WhiteNoise + spa_index) in production

# Production (Docker Compose; GATEWAY_*, VITE_* and MINI_DIR come from .env)
docker compose up -d --build   # app on 127.0.0.1:GATEWAY_PORT (8040) behind a host reverse proxy; worker = background jobs
docker compose logs -f worker
docker compose exec -T app python manage.py shell -c "…"   # change the production catalog from the shell
```

## Data

- `./data/gateway.sqlite3` is the **production** catalog where the containers run (compose sets `DATA_DIR=/data`, i.e. `./data`). A dev server on the same machine uses `DATA_DIR` in `.env` (e.g. `data/dev`). Never point the dev server at the live file.
- **Dev runs on invented data**: `seed_dev_data` replaces the dev database with `seed/demo.yaml` (two made-up clients, three platforms on the documentation IP ranges, seven projects, `.example` domains) plus live status made up around it, so every page and every kind of "needs attention" item has something to show: a site down, one failing, a certificate and two domains near expiry, a failed backup, a failed unit, repos with changes or unpushed commits, an nginx site in no project. The demo's home server takes the slug `SCAN_PLATFORM` names. It keeps the users already there (the logins) and the default groups and categories, and refuses without DEBUG or when the settings point at the live file. No worker runs in dev, and `check_health` there would mark the `.example` sites down (they don't resolve).
- `refresh_dev_db` copies the real catalog instead, only to debug what only real data shows: it reads the live DB through SQLite's backup API (it's in WAL mode, so never `cp` it while the app runs), writes it into the dev database, then migrates it. It refuses when DATA_DIR points at the live file.
- **The tests run on `seed/demo.yaml` too** (import_inventory's default): keep the demo and the tests in step.

## Conventions

- **Public repository**: nothing that belongs to a deployment goes into tracked files: no real host names, domains, clients, server paths or addresses (examples use `.example` domains and the documentation IP ranges). Those belong in `.env` or `private/`.
- **Login**: an OAuth 2 auth server, Authorization Code + PKCE through mini's `stores/auth.js`; endpoints in `frontend/src/config/auth.js` (django-oauth-toolkit's layout under `VITE_AUTH_SERVER_BASE`), public client, no secret. The backend never creates users: only usernames added with `add_user` get in, even if anyone can sign up on the auth server. Keep it that way.
- **No secrets in the catalog**, only pointers to where they live. The GitHub token goes in `.env` only (never in git, never in chat), and never reaches the browser: the API only says whether there is one.
- **GitHub sync** (`catalog/github.py`) is read-only towards GitHub and takes only repos owned by `GITHUB_OWNER`. It refuses a token of another account (every repo would look deleted).
- **Health checks** (`monitoring/checks.py`) send real requests to every public URL. They skip environments with checks off, archived/discontinued projects and projects in a hidden group, retry a failure twice within a check, and throw away a run where nothing answered (the gateway offline). A URL that still fails is only *failing* (`failing_since`, amber, no event, no notification): the worker checks it again 5 minutes later (`CONFIRM_AFTER`, `checks.confirm`) with up to 3 sites that are up on other platforms as controls, and it goes down (dated from the first failure) only if it fails again while a control answers. If no control answers either, nothing is decided and it's tried again a minute later: name lookups and home connections drop out for a minute now and then. A confirmation run never moves `checks_ran_at`. A failed lookup ("DNS error") is told apart from a name that doesn't exist. Up = any answer below 500. The user agent is a plain `projects-gateway/1.0`: some hosts' firewalls drop the "Mozilla/5.0 (compatible; …)" bot form. A platform's `public_ips` may hold networks (some CDNs give each site its own addresses), and DNS is compared per address family. Without an IPv6 route the checks connect over IPv4 only (otherwise IPv6's "Network unreachable", as the last address tried, hides IPv4's real error). On platforms that renew their own certificates (`checks.renews_here`), the other names on each site's certificate are resolved too: one pointing elsewhere means the renewal will fail.
- **Host scan**: `deploy/scan_local.py` runs on the host from a crontab every 15 minutes (standard library only, read-only: `GIT_OPTIONAL_LOCKS=0`, no fetch, credentials stripped from remote URLs) and writes `data/scan.json`. The worker reads each new one within seconds (it checks the file's time every tick), then notifies; `monitoring/local.py` compares it with the catalog on each request. The container is never given the projects folder (every project's `.env` is in there). It also reads maldet's event log (world-readable; its reports aren't): the scans of the last 8 days and every file it flagged, with whether that file still exists or is quarantined or ignored (`ignore_paths` / `ignore_sigs`). A flagged file is a red item, one per scan, until it's dealt with, because maldet's daily scan only looks at files changed in the last day, so a clean next scan proves nothing. No completed scan in 50 hours is a warning.
- **Security alerts** (`monitoring/local.py`, `security_attention`): the host scan reads, through its user's `adm` group, the last 8 days of the auth log (sudo refused; SSH logins accepted, with method and key fingerprint) and of the docker daemon's journal (containers started under a name docker made up, i.e. `docker run` without `--name`), plus the fingerprints in every `authorized_keys` it can read. Root's and the other accounts' files are root-only, so a root cron job (README, "Security watch") writes their fingerprints into `/var/lib/projects-gateway-watch/authorized_keys`. Events are red for 24 hours after the latest one: sudo refused (per user), an unnamed container, an SSH login with a password or as root; the key holds the latest event's time, so each new one is announced, and ageing out isn't (`notify.QUIET_WHEN_CLEARED`). A key in an `authorized_keys` file, or used to log in, that isn't in `SSH_KNOWN_KEYS` is red until removed or listed. `SECURITY_SINCE` silences everything before it. No key list: a warning listing the keys seen. No watch file: info; older than an hour: warning.
- **Notifications** (`monitoring/notify.py`): red "needs attention" items only, each announced once when it appears and once when it clears (keyed by the item's `key`), by Telegram and/or email as set up in `.env`. Nothing is sent or recorded with no channel set up. The bot token is in the Telegram URL, so request errors are reported by class name only. `check_health` notifies only with `--notify`: a dev server and production may share `.env`.
- **Backup agent** (`deploy/backup_agent.py`, standard library only): runs from the platform's crontab every 15 minutes as an installed **copy** (by default next to its config, `/home/backups/agent.json`), so editing the repo never changes what runs; copy it again to update. Its config holds the roots it may read (`source_roots`) and write (`target_roots`) and its credentials folder: the gateway can't widen them, and every value the gateway sends is checked again there (no option-like names, no `..`). Kinds: MySQL dump through an option file, folder zip (`zip -r -y`: symlinks stored as links), SQLite backup API. Its token is stored hashed (`agent_token`), and its API (`Authorization: Agent …`) is separate from the users' login. Try it with `--dry-run`, or `--job SLUG` against the dev server with a scratch config.
- **Backup schedule**: daily / weekly (Sunday) / monthly (1st) / yearly (1 January) at an hour. Due when no run started since the last scheduled time; a new job waits for its first one; a failed run isn't retried by itself (it's notified; "Back up now" re-runs it, scheduled or not).
- **Settings** (page /settings): the catalog's lists. **Project groups** live in `catalog.ProjectGroup` (name, order, `hidden`; migration `0005` makes the defaults); a project keeps its group's slug (`Project.group`, validated in the model's `clean` and the serializer), so renaming or reordering never touches projects. A group with projects can't be deleted. `hidden` (Archive) keeps a group off the dashboard unless "Show archived" is on, and out of the health checks. **Technology categories** work the same way (`catalog.TechnologyCategory`, name + slug, alphabetical, no order or hiding; migration `0007` makes the defaults): a technology keeps its category's slug (`Technology.category`, validated in the serializer; '' = none), one with technologies can't be deleted, and a technology created with its name only (the project form's "create on the spot") goes in "other" while that exists. **Clients** and **technologies** are renamed and deleted there too, with what uses them (deleting a client leaves its projects and domains with none). Simple lists use `components/forms/ListItemForm.vue`.
- **Services** (`catalog.Service`, page /services): the web services projects use (payments, privacy, SMTP…), grouped by kind, with the projects using each. `account` says which login or team it's under: a pointer, never a password.
- **Domains** (`domains/`): only the ones you own or renew; the page suggests the registered names found in the catalog's URLs, to "+ Track" by hand. The registry is asked once a day per domain by the worker (RDAP from IANA's bootstrap list; `whois.nic.it` for .it, which has no RDAP; .eu and .es publish no expiry: typed, `expires_by_hand`). Only dates, registrar, nameservers and status are kept, never WHOIS contacts. Projects and sites using a domain are derived from the URLs (`Domain.covers`), plus `projects` for links no URL shows. Expiry: warning under 30 days, red under 7, unless auto-renew (then only once the date has passed). **Registrar and DNS are links to Services** (`registrar_service`, `dns_service`), so the account that renews a domain or edits its zone shows; `registrar` and `dns_provider` keep the registry's text and the nameservers' guess, refreshed at each lookup and read-only in the API. An empty link is filled (at each lookup) when a Service's whole name appears in that text (`matching_service`); a link already set is never changed. The Services page lists each service's domains; the domain form creates a service on the spot (kind "Domains").
- **"Check now"** sets `MonitorState.check_requested_at`; the worker (5-second tick) runs within seconds, and the page polls until `checks_ran_at` passes it. A run can take a minute with retries, too long for a request.
- **Dependencies** carry how they're included (`via`, `version`, `reference`, optional `environment`): keep them true when a project changes how it loads a library (CDN version, symlink, git clone). The dashboard's dependency tree and the "live / manual / pinned" badges come from them.
- **Project notes** are Markdown, edited with mini's `MarkdownEditor` (toolbar, Preview) and shown with `MarkdownText`, which sanitizes through mini's `useMarkdown` (marked + DOMPurify: no raw HTML, no images, links only http(s)). Its Plain switch is `Project.notes_markdown`. The one-line description stays plain: it's the dashboard card's text.
- **Forms** are modals in `frontend/src/components/forms/` built on `FormModal` + `Field` + `useForm` (DRF 400s go under their field). After a write, `catalog.refresh()` re-reads the whole (small) catalog.
- **Admin**: the Django admin exists only with `DJANGO_DEBUG=True`; production has no password login at all.
- **Installable (PWA)**: `frontend/public/manifest.webmanifest` + icons drawn from `favicon.svg`'s design (192, 512, maskable 512, Apple 180), served at the root by WhiteNoise (`WHITENOISE_MIMETYPES` gives the manifest its type). No service worker on purpose: nothing useful offline behind a login. Change the icon in `favicon.svg` and the PNGs together.
- **mini**: import mini_vue components file by file (`@/mini/components/X.vue`), not from the barrels: the barrels pull in packages this app doesn't install (vue-i18n among others). Anything generic belongs in mini_vue itself; follow its CLAUDE.md (additive changes only, invisible consumers exist).

@private/CLAUDE.md
