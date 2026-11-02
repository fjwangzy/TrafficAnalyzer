#!/bin/sh
set -eu
umask 077
payload=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
root=$(CDPATH= cd -- "${1:-.}" && pwd -P)
(cd "$payload" && sha256sum -c SHA256SUMS)
image=$(awk '$2 ~ /^traffic-analyzer-platform:/ {print $2; exit}' "$root/IMAGES.txt")
case "$image" in ''|*[!A-Za-z0-9_./:@-]*) echo 'Missing valid offline Platform image' >&2; exit 1 ;; esac
docker run --rm --pull never --network none --entrypoint python3 \
  --mount "type=bind,source=$root,target=/release" \
  --mount "type=bind,source=$payload,target=/patch,readonly" \
  "$image" /patch/apply.py /release /patch
cd "$root"
if docker compose version >/dev/null 2>&1; then
  docker compose --env-file .env -f docker-compose.yaml up -d --no-deps --force-recreate --pull never console2
else
  docker-compose --env-file .env -f docker-compose.yaml up -d --no-deps --force-recreate --pull never console2
fi
printf '%s\n' 'Console fix applied. Refresh the browser; use deploy/intranet/diagnose_live.py to inspect missing statistics.'
