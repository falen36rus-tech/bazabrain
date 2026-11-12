#!/usr/bin/env bash
# Run from cron on the Ubuntu host after the first production release.
set -Eeuo pipefail
umask 077

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ "$(git branch --show-current)" != "production" ]]; then
    echo "Expected the production branch." >&2
    exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "Tracked files were changed on this server; refusing to overwrite them." >&2
    exit 1
fi
if [[ ! -f .env ]]; then
    echo "Create .env from .env.example before deploying." >&2
    exit 1
fi

lock_file="$(git rev-parse --git-path kb-update.lock)"
exec 9>"$lock_file"
flock -n 9 || exit 0

git fetch --no-tags origin production
target="$(git rev-parse FETCH_HEAD)"
current="$(git rev-parse HEAD)"
deployed_file="$(git rev-parse --git-path kb-deployed-sha)"
last_deployed="$(cat "$deployed_file" 2>/dev/null || true)"
if [[ "$last_deployed" == "$target" ]]; then
    exit 0
fi
if ! git merge-base --is-ancestor "$current" "$target"; then
    echo "Release history diverged; manual review required." >&2
    exit 1
fi

backup_dir="${KB_BACKUP_DIR:-$(pwd)/../bazabrain-backups}"
mkdir -p "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

# Back up the live database and uploads before changing the running version.
db_container="$(docker compose ps --all -q db)"
db_running="$(docker compose ps --status running -q db)"
if [[ -n "$db_container" && -z "$db_running" ]]; then
    echo "The existing database container is stopped; repair it before deploying." >&2
    exit 1
fi
if [[ -n "$db_running" ]]; then
    database_backup="$backup_dir/${stamp}-${current:0:12}.sql"
    uploads_backup="$backup_dir/${stamp}-${current:0:12}-uploads.tar.gz"
    docker compose exec -T db sh -c \
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" "$POSTGRES_DB"' \
        >"${database_backup}.tmp"
    mv "${database_backup}.tmp" "$database_backup"
    docker compose exec -T web tar -C /app -czf - private_media \
        >"${uploads_backup}.tmp"
    mv "${uploads_backup}.tmp" "$uploads_backup"
fi

if [[ "$current" != "$target" ]]; then
    git merge --ff-only "$target"
fi
docker compose up -d --build

ready=0
for _ in {1..30}; do
    if curl --silent --fail --max-time 3 \
        --header 'X-Forwarded-Proto: https' \
        --output /dev/null http://127.0.0.1:8000/accounts/login/; then
        ready=1
        break
    fi
    sleep 2
done
if [[ "$ready" != 1 ]]; then
    echo "The new site did not become ready. Review docker compose logs web." >&2
    exit 1
fi

# Gives imported pages a recoverable baseline; subsequent runs skip existing revisions.
docker compose exec -T web python manage.py createinitialrevisions
printf '%s\n' "$target" >"${deployed_file}.tmp"
mv "${deployed_file}.tmp" "$deployed_file"
echo "Deployed ${target:0:12}."
