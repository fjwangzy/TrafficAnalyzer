#!/bin/sh
# Host application files stay read-only; generated configuration lives in the container.
set -eu
umask 027
runtime=/var/run/traffic-console
logs=${TRAFFIC_LOG_DIR:-/var/log/traffic-analyzer}/nginx
mkdir -p "$runtime" "$logs"
chmod 755 "$runtime"

rotate_file() {
    file=$1
    [ -f "$file" ] || return 1
    [ "$(wc -c < "$file")" -ge 20971520 ] || return 1
    rm -f "$file.5"
    number=4
    while [ "$number" -gt 0 ]; do
        [ ! -f "$file.$number" ] || mv "$file.$number" "$file.$((number + 1))"
        number=$((number - 1))
    done
    mv "$file" "$file.1"
}

startup_log() {
    printf '%s level=INFO component=console-startup pid=%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$$" "$*" | tee -a "$logs/startup.log"
}

run_step() {
    startup_log "stage=$1 event=BEGIN"
    name=$1
    shift
    if "$@" > "$runtime/step.log" 2>&1; then
        cat "$runtime/step.log" | tee -a "$logs/startup.log"
        startup_log "stage=$name event=END"
    else
        status=$?
        cat "$runtime/step.log" | tee -a "$logs/startup.log" >&2
        startup_log "stage=$name event=ERROR exit_code=$status"
        return "$status"
    fi
}

# Nginx errors can include the original URI; filter query credentials before either sink.
rm -f "$runtime/error.pipe"
mkfifo "$runtime/error.pipe"
exec 3<> "$runtime/error.pipe"
(
    while IFS= read -r line; do
        printf '%s\n' "$line" | sed -E \
            -e 's/([?\&](access_token|token|password|secret|api_key)=)[^\&[:space:]"]*/\1[redacted]/g' \
            -e 's#([a-z]+://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[redacted]@#g' \
            | tee -a "$logs/error.log" >&2
    done <&3
) &

rotate_file "$logs/startup.log" || true
startup_log 'event=START readonly_host_resources=true'
for required in index.html runtime-config.template.js; do
    if [ ! -r "/opt/traffic-console/html/$required" ]; then
        startup_log "event=ERROR unreadable_resource=$required"
        exit 1
    fi
done

# Extraction can leave read-only host files at 700/600; Nginx workers need public copies.
prepare_html() {
    rm -rf "$runtime/html"
    cp -R /opt/traffic-console/html "$runtime/html"
    find "$runtime/html" -type d -exec chmod 755 {} +
    find "$runtime/html" -type f -exec chmod 644 {} +
}
run_step prepare-html prepare_html

# Log the URI without its query string so WebSocket tokens stay out of access logs.
cat > /etc/nginx/conf.d/default.conf <<'NGINX'
log_format traffic_source '$time_iso8601 level=INFO component=nginx pid=$pid method=$request_method uri="$uri" status=$status bytes=$body_bytes_sent duration=$request_time upstream=$upstream_response_time';
NGINX
awk -v directory="$logs" -v html="$runtime/html" '
    /access_log off;/ {next}
    {gsub(/\/opt\/traffic-console\/html/, html); print}
    /^server \{/ {
        print "    access_log /dev/stdout traffic_source;"
        print "    access_log \"" directory "/access.log\" traffic_source;"
        print "    error_log /var/run/traffic-console/error.pipe warn;"
        print "    location = /runtime-config.js {"
        print "        alias /var/run/traffic-console/runtime-config.js;"
        print "        add_header Cache-Control \"no-store\" always;"
        print "        add_header Content-Security-Policy $console_csp always;"
        print "        add_header X-Content-Type-Options \"nosniff\" always;"
        print "    }"
    }
' /opt/traffic-console/nginx.conf >> /etc/nginx/conf.d/default.conf
export CONSOLE_RUNTIME_CONFIG_PATH="$runtime/runtime-config.js"
run_step configure sh /opt/traffic-console/configure.sh
run_step nginx-check nginx -t
(
    while sleep 30; do
        reopen=false
        for target in access error; do
            if rotate_file "$logs/$target.log"; then reopen=true; fi
        done
        rotate_file "$logs/startup.log" || true
        if [ "$reopen" = true ]; then nginx -s reopen >/dev/null 2>&1 || true; fi
    done
) &
startup_log 'event=READY listen=8080'
exec nginx -g 'daemon off;'
