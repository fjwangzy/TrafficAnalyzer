#!/bin/sh
set -eu

envsubst '${AMAP_JS_API_KEY} ${AMAP_SECURITY_JS_CODE}' \
  < /usr/share/nginx/html/runtime-config.template.js \
  > /usr/share/nginx/html/runtime-config.js
