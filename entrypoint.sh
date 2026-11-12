#!/usr/bin/env bash
set -euo pipefail

cd /app/brandtechsolution

# The image serves four roles (web, worker, beat, and one-off commands), so the
# entrypoint dispatches on its first argument instead of hardcoding gunicorn.
# Only the web role migrates and collects static: running migrate from three
# containers at once races, and the worker has no static files to serve.
ROLE="${1:-web}"

case "$ROLE" in
  web)
    echo "[entrypoint] Applying database migrations..."
    python manage.py migrate --noinput

    echo "[entrypoint] Collecting static files..."
    python manage.py collectstatic --noinput

    # Invites any seed team address that has no account yet. Deduplicated
    # against pending invitations, so redeploying does not resend; only the
    # web role runs it, so the worker and beat containers do not each send a
    # copy. Never fatal - a mail outage must not stop the site coming up.
    echo "[entrypoint] Seeding team invitations..."
    python manage.py seed_team_invitations || \
        echo "[entrypoint] WARNING: team invitation seeding failed; continuing."

    echo "[entrypoint] Starting gunicorn..."
    exec gunicorn brandtechsolution.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 3 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
    ;;

  worker)
    # Prefork, not gevent: the tasks are I/O-bound on the Gemini API, but the
    # stack underneath them (psycopg2, LangChain) does not monkey-patch
    # cleanly, and silent connection corruption is a far worse failure than
    # a couple of idle worker slots.
    echo "[entrypoint] Starting celery worker..."
    exec celery -A brandtechsolution worker \
        --loglevel=info \
        --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
    ;;

  library-worker)
    echo "[entrypoint] Starting isolated library processing worker..."
    exec celery -A brandtechsolution worker \
        --loglevel=info --queues=library_processing --concurrency=2 \
        --hostname="library@%h" --max-tasks-per-child=10 --max-memory-per-child=400000
    ;;

  beat)
    # --schedule under /tmp: the default writes celerybeat-schedule into the
    # working directory, which is read-only in some deployments and would
    # otherwise be shared between replicas.
    echo "[entrypoint] Starting celery beat..."
    exec celery -A brandtechsolution beat \
        --loglevel=info \
        --schedule=/tmp/celerybeat-schedule
    ;;

  *)
    # Anything else is a one-off: `docker compose run --rm web python manage.py shell`
    exec "$@"
    ;;
esac
