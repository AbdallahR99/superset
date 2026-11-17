#!/bin/bash
# Fast frontend build loop for development (runs inside the fe-build container).
#
#   docker compose -f nxtbi/docker-compose.yml -f nxtbi/docker-compose.dev.yml run --rm fe-build [dev|prod|translations|test <jest args>|type]
#
# The container keeps its own Linux copy of superset-frontend (named volume, including
# node_modules and the webpack cache). Each run first copies the files that changed on
# the host, then builds into the volume that the web container serves as
# /app/superset/static/assets. The production image build (Dockerfile) is unaffected.
set -euo pipefail

MODE="${1:-dev}"
shift || true
SRC=/host/superset-frontend
DST=/app/superset-frontend
STAMP=/app/superset-frontend/.nxtbi-last-sync

sync_sources() {
  local started=$SECONDS newer=()
  [ -f "$STAMP" ] && newer=(-newer "$STAMP")
  touch /tmp/sync-start
  ( cd "$SRC" && find . \( -name node_modules -o -name .git -o -name coverage -o -name esm -o -name lib -o -name dist \) -prune \
      -o -type f "${newer[@]}" -print0 | tar --null -T - -cf - ) | tar -xf - -C "$DST"
  # translation catalogues live outside superset-frontend
  mkdir -p /app/superset/translations
  ( cd /host/superset/translations && find . -type f \( -name '*.po' -o -name '*.pot' -o -name '*.py' -o -name '*.txt' -o -name '*.cfg' \) -print0 \
      | tar --null -T - -cf - ) | tar -xf - -C /app/superset/translations
  mv /tmp/sync-start "$STAMP"
  echo "[fe-build] sources synced in $((SECONDS - started))s"
}

deps_if_needed() {
  local want have
  want=$(sha256sum "$DST/package-lock.json" | cut -d' ' -f1)
  have=$(cat "$DST/node_modules/.nxtbi-lock-hash" 2>/dev/null || true)
  if [ "$want" != "$have" ]; then
    if [ -z "$have" ] && [ -d "$DST/node_modules/webpack" ]; then
      echo "[fe-build] node_modules come from the image; recording lock hash"
    else
      echo "[fe-build] package-lock.json changed: npm ci"
      ( cd "$DST" && npm ci --no-audit --no-fund )
    fi
    echo "$want" > "$DST/node_modules/.nxtbi-lock-hash"
  fi
}

cd "$DST"
sync_sources
case "$MODE" in
  dev|prod)
    deps_if_needed
    started=$SECONDS
    # --no-devtool: the default development source maps use eval(), which the
    # production Content-Security-Policy of the running stack blocks.
    if [ "$MODE" = prod ]; then npm run build; else npm run build-dev -- --no-devtool; fi
    echo "[fe-build] webpack ($MODE) finished in $((SECONDS - started))s -> /app/superset/static/assets"
    ;;
  translations)
    deps_if_needed
    npm run build-translation
    mkdir -p /out/translations
    for lang in ar en; do
      if [ -f "/app/superset/translations/$lang/LC_MESSAGES/messages.json" ]; then
        mkdir -p "/out/translations/$lang"
        cp "/app/superset/translations/$lang/LC_MESSAGES/messages.json" "/out/translations/$lang/messages.json"
      fi
    done
    echo "[fe-build] language packs written to nxtbi/out/dev/translations"
    ;;
  test)
    deps_if_needed
    npm run test -- "$@"
    ;;
  type)
    deps_if_needed
    # Build mode: the packages are TypeScript project references, so their
    # declarations must exist before the application is checked.
    NODE_OPTIONS=--max-old-space-size=8192 npx tsc --build
    ;;
  *)
    echo "usage: fe-build.sh [dev|prod|translations|test <jest args>|type]" >&2
    exit 2
    ;;
esac
