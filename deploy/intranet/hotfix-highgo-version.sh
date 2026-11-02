#!/bin/sh
set -eu
patch=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
root=$(CDPATH= cd -- "${1:-.}" && pwd -P)
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$patch" && sha256sum --check --quiet SHA256SUMS)
else
    (cd "$patch" && shasum -a 256 -c SHA256SUMS >/dev/null)
fi
image=sha256:d1286fcc6a40335fbe70a75e72780b68c4de3a394fcee8cad91b560b4fa9dbb8
docker image inspect "$image" >/dev/null
docker run --rm --pull never --network none --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$root,target=/release" \
    --mount "type=bind,source=$patch,target=/patch,readonly" \
    --entrypoint python3 "$image" /patch/apply.py
