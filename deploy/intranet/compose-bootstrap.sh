#!/bin/sh
# Offline deployment uses Docker/Compose and ordinary Linux utilities only.
set -eu
root=$1
shift
cd "$root"
fail() { printf '%s\n' "$*" >&2; exit 1; }
[ -f .env ] || fail '缺少根目录 .env，请使用已配置的私有部署包。'
chmod 600 .env
if docker compose version >/dev/null 2>&1; then
    compose_cli() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1 && ! [ "$(command -v docker-compose)" -ef "$root/docker-compose" ]; then
    compose_cli() { docker-compose "$@"; }
else
    fail '需要已安装的 Docker Compose V2（docker compose 或系统 docker-compose）。'
fi
compose() { compose_cli --project-directory "$root" --env-file "$root/.env" -f "$root/docker-compose.yaml" "$@"; }
version=$(compose version --short)
printf '%s\n' "${version#v}" | awk -F. '{exit !($1>2 || ($1==2 && ($2>24 || ($2==24 && $3>=4))))}' || fail '需要 Docker Compose >=2.24.4。'
hash_check() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum --check --quiet "$1"
    else shasum -a 256 -c "$1" >/dev/null
    fi
}
metadata=''
probe=''
stage=''
assets=''
cleanup() {
    [ -z "$metadata" ] || rm -f -- "$metadata"
    [ -z "$probe" ] || rm -f -- "$probe"
    if [ -n "$stage" ] && [ -n "$assets" ]; then
        case "$stage" in "$assets"/.model-import.*) rm -rf -- "$stage" ;; esac
    fi
}
trap cleanup EXIT HUP INT TERM
verify_small_files() {
    metadata=$(mktemp "$root/.compose-env.XXXXXX")
    chmod 600 "$metadata"
    awk '$2 != "images/runtime.tar"' SHA256SUMS > "$metadata"
    hash_check "$metadata" || fail '部署文件校验失败，请重新解压原始包。'
}
load_images() {
    missing=false
    while read -r expected reference; do
        actual=$(docker image inspect --format '{{.Id}}/{{.Architecture}}' "$reference" 2>/dev/null || true)
        [ "$actual" = "$expected/arm64" ] || missing=true
    done < IMAGES.txt
    if [ "$missing" = true ]; then
        printf '%s\n' '校验并导入离线镜像，请等待……'
        awk '$2 == "images/runtime.tar"' SHA256SUMS > "$metadata"
        [ -s "$metadata" ] || fail '镜像归档缺少校验记录。'
        hash_check "$metadata" || fail '离线镜像归档校验失败。'
        docker load -i images/runtime.tar
    fi
    while read -r expected reference; do
        actual=$(docker image inspect --format '{{.Id}}/{{.Architecture}}' "$reference")
        [ "$actual" = "$expected/arm64" ] || fail "镜像ID或架构不匹配：$reference"
    done < IMAGES.txt
}
read_environment() {
    # Compose 2.24.4 lacks config --environment; let Compose resolve dotenv without shell eval.
    image=$(awk '$2 ~ /^traffic-analyzer-platform:/ {print $2; exit}' IMAGES.txt)
    case "$image" in ''|*[!A-Za-z0-9_./:@-]*) fail '缺少有效的Platform离线镜像记录。' ;; esac
    probe=$(mktemp "$root/.compose-probe.XXXXXX")
    chmod 600 "$probe"
    printf 'services:\n  config-reader:\n    image: "%s"\n' "$image" > "$probe"
    cat >> "$probe" <<'YAML'
    pull_policy: never
    network_mode: none
    entrypoint: [python3, -c]
    command:
      - |
        import os
        for key in ('PUBLIC_HOST', 'CORS_ORIGINS', 'DB_HOST', 'CONSOLE_PORT', 'ASSET_ROOT', 'DATA_ROOT'):
            value = os.environ[key]
            if '\n' in value or '\r' in value:
                raise SystemExit('Deployment paths and origins must be single-line')
            print(key + '=' + value)
    environment:
      PUBLIC_HOST: "${PUBLIC_HOST:-auto}"
      CORS_ORIGINS: "${CORS_ORIGINS:-auto}"
      DB_HOST: "${DB_HOST:-}"
      CONSOLE_PORT: "${CONSOLE_PORT:-8009}"
      ASSET_ROOT: "${ASSET_ROOT:?ASSET_ROOT is required}"
      DATA_ROOT: "${DATA_ROOT:?DATA_ROOT is required}"
YAML
    compose_cli --project-directory "$root" --env-file "$root/.env" -f "$probe" \
        -p "ta_boot_config_$$" run --rm --no-deps -T config-reader > "$metadata"
}
value() { awk -v prefix="$1=" 'index($0,prefix)==1 {print substr($0,length(prefix)+1); exit}' "$metadata"; }
prepare_origins() {
    [ "$(value CORS_ORIGINS)" = auto ] || return 0
    host=$(value PUBLIC_HOST)
    if [ -z "$host" ] || [ "$host" = auto ]; then
        host=''
        if command -v ip >/dev/null 2>&1; then
            host=$(ip route get "$(value DB_HOST)" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}' || true)
        fi
        [ -n "$host" ] || host=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    fi
    case "$host" in ''|*[!A-Za-z0-9._-]*) fail '无法自动识别访问IP，请在.env设置PUBLIC_HOST为服务器IP或主机名。' ;; esac
    port=$(value CONSOLE_PORT)
    case "$port" in ''|*[!0-9]*) fail 'CONSOLE_PORT必须是端口数字。' ;; esac
    origins="[\"http://localhost:$port\",\"http://127.0.0.1:$port\",\"http://$host:$port\"]"
    temporary=$(mktemp "$root/.env.XXXXXX")
    chmod 600 "$temporary"
    awk -v origins="$origins" -v host="$host" 'BEGIN {q=sprintf("%c",39)} /^CORS_ORIGINS=/ {print "CORS_ORIGINS=" q origins q; next} /^PUBLIC_HOST=/ {print "PUBLIC_HOST=" q host q; next} {print}' .env > "$temporary"
    mv -f -- "$temporary" .env
    printf '访问地址：http://%s:%s\n' "$host" "$port"
}
prepare_resources() {
    assets=$(value ASSET_ROOT)
    data=$(value DATA_ROOT)
    [ -n "$assets" ] && [ -n "$data" ] || fail 'ASSET_ROOT和DATA_ROOT不能为空。'
    mkdir -p "$assets" "$data"
    assets=$(CDPATH= cd -- "$assets" && pwd -P)
    data=$(CDPATH= cd -- "$data" && pwd -P)
    [ "$assets" != / ] && [ "$data" != / ] || fail '资源和数据目录不能是根目录。'
    mkdir -p "$assets/videos"
    for directory in hls output spool calibration survey trajectory-archive logs; do mkdir -p "$data/$directory"; done
    if [ ! -f "$assets/weights/ascend/manifest.json" ]; then
        if [ -d "$assets/weights" ] && [ -n "$(ls -A "$assets/weights")" ]; then
            fail 'weights目录已有不完整资源，拒绝覆盖；请按手册核对模型文件。'
        fi
        [ -f MODEL_ARCHIVE_SHA256SUMS ] || fail '请另行拷贝完整weights模型目录。'
        read -r expected archive < MODEL_ARCHIVE_SHA256SUMS
        case "$archive" in ''|*/*|*..*) fail '模型资源包文件名无效。' ;; esac
        candidate="$root/$archive"
        [ -f "$candidate" ] || candidate="$root/../$archive"
        [ -f "$candidate" ] || fail "请将 $archive 拷贝到解压目录或其上一级。"
        printf '%s  %s\n' "$expected" "$candidate" > "$metadata"
        hash_check "$metadata" || fail '模型资源包校验失败。'
        stage=$(mktemp -d "$assets/.model-import.XXXXXX")
        tar -tzf "$candidate" > "$stage/entries"
        awk '/^\// || /(^|\/)\.\.(\/|$)/ {exit 1}' "$stage/entries" || fail '模型包包含越界路径。'
        tar -tvzf "$candidate" > "$stage/types"
        awk 'substr($0,1,1)!~/[-d]/ {exit 1}' "$stage/types" || fail '模型包不允许链接或特殊文件。'
        tar -xzf "$candidate" --strip-components=1 --no-same-owner --no-same-permissions -C "$stage"
        (cd "$stage" && hash_check SHA256SUMS) || fail '模型内容校验失败。'
        [ -d "$stage/weights" ] || fail '模型包缺少weights目录。'
        if [ -d "$assets/weights" ]; then rmdir "$assets/weights"; fi
        mv -- "$stage/weights" "$assets/weights"
        rm -rf -- "$stage"
        stage=''
        printf '%s\n' '独立模型资源已导入，视频与遥测放入ASSET_ROOT/videos。'
    fi
    (cd "$assets" && hash_check "$root/MODEL_SHA256SUMS") || fail '模型文件与发布清单不一致。'
}
check_host() {
    [ "$(uname -s)" = Linux ] || fail '生产启动仅支持Linux；macOS仍使用原生MPS启动命令。'
    case "$(uname -m)" in aarch64|arm64) ;; *) fail '生产主机必须为aarch64/arm64。' ;; esac
    for device in /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc; do [ -e "$device" ] || fail "缺少昇腾设备：$device"; done
    [ -d /usr/local/Ascend/driver ] && [ -f /etc/ascend_install.info ] || fail '缺少昇腾驱动目录或安装信息。'
    command -v npu-smi >/dev/null 2>&1 || fail '请安装配套昇腾驱动并使npu-smi可用。'
    npu-smi info
}
start_database() {
    if compose config --services | awk '$0=="road9" {found=1} END {exit !found}'; then
        compose up -d --no-build --pull never --wait --wait-timeout 180 road9
    fi
}
command=${1:-up}
[ "$#" -eq 0 ] || shift
case "$command" in
    pull|build) fail '隔离部署禁止拉取镜像或构建，请使用离线镜像包。' ;;
    verify) hash_check SHA256SUMS; exit ;;
    load) verify_small_files; load_images; exit ;;
    prepare) verify_small_files; read_environment; prepare_origins; prepare_resources; exit ;;
    up|check)
        for argument in "$@"; do case "$argument" in --build|--pull|--pull=*) fail '离线启动无需--build或--pull参数。' ;; esac; done
        verify_small_files
        check_host
        load_images
        read_environment
        prepare_origins
        prepare_resources
        start_database
        preflight=/app/deploy/runtime_check.py
        [ ! -f application/APP_RELEASE.json ] || preflight=/app/deploy/intranet/runtime_check.py
        compose run --rm --no-deps platform python3 "$preflight"
        [ "$command" != check ] || exit 0
        compose up --no-build --pull never --wait --wait-timeout 180 "$@"
        ;;
    *) compose "$command" "$@" ;;
esac
