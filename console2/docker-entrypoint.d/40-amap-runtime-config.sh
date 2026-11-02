#!/bin/sh
set -eu
runtime_config_path=${CONSOLE_RUNTIME_CONFIG_PATH:-/opt/traffic-console/html/runtime-config.js}
export ROAD_FEATURES_ENABLED="${ROAD_FEATURES_ENABLED:-true}"

export MAP_DISABLED="${MAP_DISABLED:-false}"
export MAP_PROVIDER="${MAP_PROVIDER:-amap}"
export MINEMAP_DOMAIN="${MINEMAP_DOMAIN:-}"
export MINEMAP_KEY="${MINEMAP_KEY:-}"
export MINEMAP_SOLUTION="${MINEMAP_SOLUTION:-17000}"
export MINEMAP_SDK_BASE_URL="${MINEMAP_SDK_BASE_URL:-}"
export MINEMAP_SERVICE_URL="${MINEMAP_SERVICE_URL:-}"
export MINEMAP_SERVER_DOMAIN="${MINEMAP_SERVER_DOMAIN:-}"
export MINEMAP_STYLE_URL="${MINEMAP_STYLE_URL:-}"
case "$MAP_PROVIDER" in amap|minemap) ;; *) echo 'Unsupported MAP_PROVIDER' >&2; exit 1 ;; esac
if [ "$MAP_PROVIDER" = minemap ]; then
  : "${MINEMAP_DOMAIN:?MineMap domain is required}" "${MINEMAP_KEY:?MineMap key is required}"
  case "$MINEMAP_DOMAIN" in *[!A-Za-z0-9.:/-]*) echo 'Invalid MineMap domain' >&2; exit 1 ;; esac
  case "$MINEMAP_DOMAIN" in http://*|https://*) ;; *) echo 'MineMap domain must be an HTTP(S) origin' >&2; exit 1 ;; esac
  case "${MINEMAP_DOMAIN#*://}" in ''|*/*) echo 'MineMap domain must not contain a path' >&2; exit 1 ;; esac
  case "$MINEMAP_KEY" in *[!A-Za-z0-9._~+/=%:@-]*) echo 'Invalid MineMap key' >&2; exit 1 ;; esac
  case "$MINEMAP_SOLUTION" in ''|*[!0-9]*) echo 'Invalid MineMap solution' >&2; exit 1 ;; esac
  minemap_origins="$MINEMAP_DOMAIN"
  for minemap_url in "$MINEMAP_SDK_BASE_URL" "$MINEMAP_SERVICE_URL" "$MINEMAP_SERVER_DOMAIN" "$MINEMAP_STYLE_URL"; do
    [ -n "$minemap_url" ] || continue
    case "$minemap_url" in *[!A-Za-z0-9.:/_-]*) echo 'Invalid MineMap service URL' >&2; exit 1 ;; esac
    case "$minemap_url" in http://*|https://*) ;; *) echo 'MineMap services must use HTTP(S)' >&2; exit 1 ;; esac
    minemap_authority=${minemap_url#*://}
    minemap_authority=${minemap_authority%%/*}
    [ -n "$minemap_authority" ] || { echo 'MineMap service has no host' >&2; exit 1; }
    minemap_origins="$minemap_origins ${minemap_url%%://*}://$minemap_authority"
  done
  # Scope the production CSP to the configured internal map service.
  minemap_csp="default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' $minemap_origins; style-src 'self' 'unsafe-inline' $minemap_origins; img-src 'self' blob: data: $minemap_origins; connect-src 'self' ws: wss: $minemap_origins; font-src 'self' data: $minemap_origins; worker-src 'self' blob:"
  awk -v csp="$minemap_csp" '$1 == "set" && $2 == "$console_csp" { print "    set $console_csp \"" csp "\";"; next } { print }' \
    /etc/nginx/conf.d/default.conf > /etc/nginx/conf.d/default.conf.tmp
  mv /etc/nginx/conf.d/default.conf.tmp /etc/nginx/conf.d/default.conf
fi
envsubst '${AMAP_JS_API_KEY} ${AMAP_SECURITY_JS_CODE} ${MAP_DISABLED} ${MAP_PROVIDER} ${MINEMAP_DOMAIN} ${MINEMAP_KEY} ${MINEMAP_SOLUTION} ${ROAD_FEATURES_ENABLED} ${MINEMAP_SDK_BASE_URL} ${MINEMAP_SERVICE_URL} ${MINEMAP_SERVER_DOMAIN} ${MINEMAP_STYLE_URL}' \
  < /opt/traffic-console/html/runtime-config.template.js \
  > "$runtime_config_path"

chmod 644 "$runtime_config_path"
