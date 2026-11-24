# Projects Gateway

A self-hosted catalog of every web project you run: where each environment lives, what it's built with, which repositories and outside services it uses. On top of it: health checks, domain expiry, a backup planner, a scan of the server itself, and one "needs attention" list that alerts you by Telegram or email.

It's made for one person or a small studio with dozens of sites spread over a home server, a VPS or two, shared hosting and clients' servers. At that size, "where does that site run, and what breaks if this server goes down?" needs a search, not memory.

## What it does

### The catalog

- **Projects**, in groups you define (the dashboard's sections). Each has a client, a status (active, in development, maintenance, discontinued, archived), a one-line description and Markdown notes.
- **Environments**: a project's PROD, TEST, DEV or local copies. Each has its URLs, the platform it runs on, the path there, its runtime, how it's deployed, and whether it's health-checked.
- **Platforms**: where things run. A home server, a VPS, shared hosting, a client's server, a LAN device or third-party hosting, each with its provider, IPv4 and IPv6 addresses (or a dynamic DNS name), hostnames, OS, admin links and cleanup notes. A platform's page shows every project on it: what breaks if it goes down.
- **Repositories** on GitHub, Bitbucket, a host's deploy remote, or local only, each linked to one or more projects.
- **Dependencies** between projects, such as a site using a UI library or an app logging in through an auth server. Each records *how* it's included: a CDN link at a version, a symlink, a build from source, a git clone, a copy or a package. That decides how a change reaches it: at once, at the next build, or only by hand. The dashboard draws them as a tree, with "live", "manual" and "pinned" badges.
- **Technologies** (in categories you define), **services** (the outside accounts projects use: payments, privacy, SMTP, registrars, DNS), **domains** and **clients**.

The dashboard shows a card per project: search by name, client, URL, technology or path, filter by platform, or switch to a tree by dependency, platform, group or client.

### Live status

- **Health checks**: every public URL, every 15 minutes. A failed request is retried twice. If it still fails, the URL is only marked *failing* and nothing is sent. Five minutes later it's checked again, together with up to three sites that are up on other platforms. It goes *down*, dated from the first failure, only if it fails again while one of those answers. If none answers, the trouble is the gateway's own connection, so nothing is decided. This keeps short DNS or network drops from turning into alerts.
- **Certificates and DNS**: each check also reads the certificate (its expiry and the names it covers), and compares the DNS answer with the platform's addresses, per address family. On a server that renews its own certificates, a name on the certificate that points elsewhere is flagged, because the next renewal would fail.
- **Domains**: the registry is asked once a day (RDAP, and WHOIS for `.it`). Expiry is a warning under 30 days and red under 7, unless the domain renews automatically. Only dates, registrar, nameservers and status are kept, never WHOIS contacts. The page suggests the registered domains it finds in your URLs, and links each domain's registrar and DNS host to their services.
- **GitHub sync**: read-only, every 6 hours, for the repositories of one owner (visibility, language, topics, last push). A repository no project uses, or one deleted on GitHub, needs attention.
- **Host scan** (optional): a script on the server, run from cron, writes a JSON snapshot that the worker reads. It covers:
  - git working copies with uncommitted or unpushed work;
  - nginx sites that no environment claims;
  - failed systemd units;
  - files maldet has flagged;
  - security traces: refused sudo, SSH logins and the keys they used, keys that aren't on your list, containers started without a name.
- **Needs attention**: one list of everything amber or red, from all of the above. A red item is announced once when it appears and once when it clears, by Telegram, email or both.

### Backups

A planner in the gateway, and an agent on each server.

- **In the gateway** you define targets (folders) and jobs: a MySQL dump, a folder zip or an SQLite copy, daily, weekly, monthly or yearly at a set hour.
- **The agent** is one Python file with no dependencies, run from cron every 15 minutes. It checks in, makes each due backup in the job's first target, verifies it, copies it to the other targets, keeps the newest N where a target says so, and reports every run and the free space left.
- **"Back up now"** runs a job at the agent's next check-in.
- **Limits:** the agent's own config file, on its server, sets which folders it may read and write. Nothing the gateway sends can widen them.

### Also

- **Settings**: project groups (order, hidden from the dashboard), technology categories, clients and technologies. Each can be renamed, and deleted once nothing uses it.
- **Installable as an app** (a PWA manifest). There's no service worker, because nothing is useful offline behind a login.

## Design choices

- **No secrets in the catalog.** It records where a secret lives ("the `.env` in `/srv/app` on the VPS"), never the secret itself. The GitHub, Telegram and SMTP credentials live in `.env` only and never reach the browser.
- **Read-only towards everything it watches.** The checks are plain HTTP requests, the GitHub token needs read access only, and the host scan never fetches or writes. It runs git without taking locks and strips credentials from remote URLs.
- **The containers never see the server's project folders.** What only the host can see (systemd, nginx, git working copies, logs) arrives as the host scan's JSON file. Mounting the projects folder would hand the app every project's `.env`.
- **Ports on 127.0.0.1 only**, behind a reverse proxy on the host that handles TLS. Docker's published ports bypass host firewalls such as UFW.
- **No sign-ups.** Login is OpenID Connect (Authorization Code with PKCE) through the provider you choose. Only the usernames you add with `add_user` get in, and each is tied to its provider account at its first login, so someone who later takes that username on the provider can't get in. Production has no password login and no Django admin.
- **Small on purpose**: SQLite, one app container and one worker container, with no message queue and no cron inside Docker.

## How it fits together

```
browser ── HTTPS ── reverse proxy (host) ── 127.0.0.1:8040 ── app: gunicorn, Django API + the built Vue app
                                                                │
                                                       data/    SQLite (WAL)
                                                                │
host cron ── deploy/scan_local.py ──> data/scan.json ───────── worker: checks and confirmations, domains,
                                                                        GitHub sync, scan import, notifications
host cron ── deploy/backup_agent.py <── HTTPS /api/agent/ ──>  app
```

The app and the worker run from the same image. The worker loops on a 5-second tick, and "Check now" in the app is picked up within seconds.

## Stack

- **Backend**: Python 3.12, Django 5.2, Django REST framework, django-filter, requests, WhiteNoise, gunicorn. The database is SQLite.
- **Frontend**: Vue 3, Vite, Pinia, Vue Router, [mini](https://github.com/giacomorizzotti/mini) (CSS) and [mini_vue](https://github.com/giacomorizzotti/mini_vue) (components), Iconoir icons, d3-hierarchy for the trees, marked and DOMPurify for the notes.
- **Deployment**: Docker Compose.

## Before you try it

It grew out of one person's setup, and a few things still assume one like it:

- **Login** needs an OpenID Connect provider that publishes a discovery document: Keycloak, Authentik, Authelia, Zitadel, GitLab, Google, django-oauth-toolkit and most others do. Register a public client (PKCE, no secret) with `…/callback` as its redirect URI, and let the app's origin call the provider's token endpoint (CORS). There's no local login, and GitHub can't be used: it isn't an OpenID Connect provider.
- **mini** must be checked out next to this repository (`../mini`) when you build: `frontend/src/mini` is a relative symlink into it, and `docker-compose.yml` passes it to the Docker build (`MINI_DIR` points elsewhere).
- **The host scan** looks for git repositories under `/home/projects` and nginx sites in `/etc/nginx/sites-enabled`. It's written for Ubuntu with systemd, nginx and certbot.

## Development

You need Python 3.12 and Node 22, and mini next to this repository.

```bash
git clone https://github.com/giacomorizzotti/mini ../mini

python3 -m venv venv
venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci)

cp .env.example .env
# In .env: DJANGO_DEBUG=True, DATA_DIR=/absolute/path/to/this/repo/data/dev, OIDC_ISSUER, OIDC_CLIENT_ID
mkdir -p data/dev

cd backend
../venv/bin/python manage.py migrate
../venv/bin/python manage.py seed_dev_data --user <your username on the provider>
cd ..

./dev.sh start      # Django on 127.0.0.1:8010, Vite on http://localhost:5180
```

- **Demo data:** `seed_dev_data` fills the development database with invented data from `seed/demo.yaml`. The domains end in `.example` and the addresses come from the documentation ranges. It also makes up live status around that data, so every page and every kind of "needs attention" item has something to show.
- **Safety:** it refuses to run without `DJANGO_DEBUG`, or when the settings point at the production database.
- **What stays still in dev:** no worker runs there, so the made-up status stays as it is.
- **Login:** it goes through your provider in development too. Register `http://localhost:5180/callback` as a redirect URI, and allow `http://localhost:5180` as an origin.
- **Your machine only:** both dev servers listen locally. Don't start Vite with `--host`: a dev server reachable from the internet runs whatever it's asked to.

Tests:

```bash
cd backend && ../venv/bin/python manage.py test
```

## Production

1. **Configure.** Check out mini next to this repository, and fill in `.env` (see [Configuration](#configuration)). Docker Compose reads it too, and won't start without these:
   - `DJANGO_SECRET_KEY`, `SITE_URL`, `OIDC_ISSUER` and `OIDC_CLIENT_ID`;
   - `GATEWAY_HOST`, your host name;
   - `GATEWAY_UID` and `GATEWAY_GID`, the user the containers run as, which should own `./data`.

   Nothing about your deployment is built into the image: the frontend reads its sign-in settings from the API when it starts.
2. **Start:** `docker compose up -d --build`. Migrations run when the app starts. The app listens on `127.0.0.1:8040` (`GATEWAY_PORT`), and `./data` holds the database.
3. **Proxy:** put a reverse proxy in front. There's an nginx example in `deploy/` for use with certbot.
4. **Let yourself in:** `docker compose exec app python manage.py add_user <username> --name "Your Name"`, with your username on the provider. Your first login ties the account to you.
5. **Fill the catalog** in the app, or seed an empty one from a YAML file in `seed/demo.yaml`'s format: `manage.py import_inventory <file>`.

Optional parts:

- **Host scan**: `*/15 * * * * /usr/bin/python3 /path/to/repo/deploy/scan_local.py` in the crontab of a user who can read the projects. It writes `data/scan.json`. Set `SCAN_PLATFORM` to the slug of the platform it describes. For the security traces, that user needs the `adm` group (the auth log and the docker journal).
- **Security watch**: root's and the other accounts' `authorized_keys` files are readable by root only. A root cron job writes their fingerprints where the scan can read them. Put it in `/etc/cron.d/projects-gateway-watch` (owned by root, mode 644), and create `/var/lib/projects-gateway-watch` first, readable by the scan's user:
  ```
  */15 * * * * root for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do [ -f "$f" ] && ssh-keygen -lf "$f" | sed "s#^#$f #"; done > /var/lib/projects-gateway-watch/authorized_keys.tmp 2>/dev/null; mv /var/lib/projects-gateway-watch/authorized_keys.tmp /var/lib/projects-gateway-watch/authorized_keys
  ```
  Then list the keys you expect in `SSH_KNOWN_KEYS`. Any other key is red.
- **Backup agent**:
  1. Copy `deploy/backup_agent.py` to the server. It runs as an installed copy, so editing the repository never changes what runs.
  2. Write its config file: `gateway`, `token_file`, `source_roots`, `target_roots`, `credentials_dir`, `log_file`.
  3. Create its token with `manage.py agent_token <platform-slug>`. It's printed once and stored hashed.
  4. Add the agent to cron every 15 minutes. `--dry-run` shows its plan without running anything.
- **GitHub**: `GITHUB_OWNER`, plus a fine-grained token with read-only metadata access.
- **Notifications**: a Telegram bot, SMTP, or both. `manage.py notify_test` sends a test message on every channel set up (and prints your Telegram chat ID).

## Configuration

Everything comes from `.env` at the repository root. `.env.example` explains each setting.

| Variable | What it's for |
|---|---|
| `DJANGO_DEBUG` | `True` in development only. When it's off, `DJANGO_SECRET_KEY` is required. |
| `DJANGO_SECRET_KEY` | Django's secret key. |
| `DJANGO_ALLOWED_HOSTS` | The host names the app answers to, comma-separated. |
| `DATA_DIR` | Where the database and `scan.json` live. The default is `data/`; the containers always use `/data`. |
| `SITE_URL` | The app's public address, for the links in notifications. |
| `OIDC_ISSUER` | The OpenID Connect provider's issuer, as its discovery document names it. The endpoints come from that document, which is read once an hour. |
| `OIDC_CLIENT_ID` | The app's public client on the provider (PKCE, no secret). |
| `OIDC_USERNAME_CLAIM` | The claim holding the username given to `add_user`. The default is `preferred_username`. |
| `GATEWAY_HOST`, `GATEWAY_UID`, `GATEWAY_GID`, `GATEWAY_PORT` | Docker Compose: the public host name, the user the containers run as, the port on 127.0.0.1 (default 8040). |
| `MINI_DIR` | Docker Compose: where mini is checked out. The default is `../mini`. |
| `GITHUB_OWNER`, `GITHUB_TOKEN`, `GITHUB_SYNC_HOURS` | The GitHub sync. It's off without a token; the default interval is 6 hours. |
| `HEALTH_CHECK_MINUTES` | How often the URLs are checked. The default is 15. |
| `SCAN_PLATFORM` | The platform the host scan describes. |
| `SSH_KNOWN_KEYS`, `SECURITY_SINCE` | The SSH key fingerprints allowed on the server, and the moment before which security traces are ignored. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Notifications by Telegram. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `NOTIFY_EMAIL_TO` | Notifications by email. Port 465 is SSL, 587 is STARTTLS. |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | HTTPS settings when `DJANGO_DEBUG` is off. |
| `MINI_CSS_DIR` | Where mini's SCSS is, at build time. |
| `LOG_LEVEL` | The logging level. The default is `INFO`. |

## Management commands

Run them from `backend/` with `../venv/bin/python manage.py …`, or in the container with `docker compose exec app python manage.py …`.

| Command | What it does |
|---|---|
| `add_user <username> --name "…" [--rebind]` | Lets a provider account in. Nobody gets in otherwise. `--rebind` forgets which provider account the user signs in as, so the next login with that username ties it again, e.g. after the account was replaced. |
| `import_inventory [file]` | Seeds an empty catalog from YAML (the demo by default). It refuses when the catalog isn't empty. |
| `seed_dev_data [--user …]` | Replaces the development database with the demo data and made-up status. |
| `refresh_dev_db` | Replaces the development database with a snapshot of the production one, read through SQLite's backup API, then migrates the copy. |
| `check_health [--notify]` | The worker's run now (the checks and the host scan), then prints what needs attention. |
| `notify_test` | Sends a test message on every channel set up. |
| `sync_github` | Runs the GitHub sync now. |
| `agent_token <platform>` | Creates a backup agent's token. |
| `worker` | The background loop the worker container runs. |

## Layout

```
backend/
  gateway/      settings (from .env), URLs, the single-page app's fallback view
  accounts/     login: the provider's discovery document, bearer tokens checked at its userinfo; add_user
  catalog/      the catalog's models and API, the GitHub sync, the worker
  monitoring/   health checks, the host scan's reader, "needs attention", notifications
  domains/      domains and registry lookups
  backups/      the backup planner and the agents' API
frontend/       the Vue app: views, forms, stores
deploy/         scan_local.py and backup_agent.py (run on the host), an nginx example
seed/           demo.yaml, invented data for development and the tests
dev.sh          both dev servers in the background
private/        (gitignored) your deployment's own notes, if you keep any
```

## License

MIT, see [LICENSE](LICENSE).
