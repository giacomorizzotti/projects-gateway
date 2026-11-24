# Projects Gateway: one image, Django serving the API and the built Vue app.
# Built by docker-compose.yml, which passes a checkout of mini (MINI_DIR, by default ../mini)
# as the extra build context "mini". Nothing about the deployment is built in: the frontend reads
# its sign-in settings from the API at startup.

FROM node:22-alpine AS frontend
# frontend/src/mini is a relative symlink to ../mini/website/src/mini next to the repo, and
# Sass loads mini's SCSS from ../mini/css (vite.config.js). With the app in /app, mini goes
# to /mini: the same place relative to it, so both resolve unchanged.
COPY --from=mini css /mini/css
COPY --from=mini website/src/mini /mini/website/src/mini
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# --chmod: the containers run as uid 1001, so the code must be readable by anyone,
# whatever the modes on the host (a 700 catalog/migrations once hid every catalog
# migration from Django).
COPY --chmod=a+rX backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

EXPOSE 8000
# Config comes from the environment (docker-compose.yml + .env), data from the /data volume.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn gateway.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile -"]
