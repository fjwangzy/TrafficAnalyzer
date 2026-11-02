#!/bin/sh
set -eu
package=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
root=$(CDPATH= cd -- "${1:-.}" && pwd -P)
docker load -i "$package/console-image.tar"
cd "$root"
docker compose -f docker-compose.yaml -f "$package/console-image.yaml" up -d --wait --wait-timeout 60 --no-deps --force-recreate --pull never console2
