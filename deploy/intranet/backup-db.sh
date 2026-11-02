#!/bin/sh
# Back up the temporary database; never stop services or alter the source database.
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
destination=${1:-$root/backups}
mkdir -p "$destination"
temporary=$(mktemp "$destination/.postgres-backup.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM
"$root/docker-compose" exec -T road9 sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' > "$temporary"
"$root/docker-compose" exec -T road9 pg_restore --list < "$temporary" > /dev/null
final="$temporary.dump"
mv -- "$temporary" "$final"
trap - EXIT HUP INT TERM
if command -v sha256sum >/dev/null 2>&1; then sha256sum "$final" > "$final.sha256"
else shasum -a 256 "$final" > "$final.sha256"
fi
printf 'Backup verified: %s\n' "$final"
