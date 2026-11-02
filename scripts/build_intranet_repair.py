#!/usr/bin/env python3
"""Build the private cumulative repair; never download dependencies on the deployment host."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import io
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output, wheel, doris_config):
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != "e6b1d89711dd51f8f74b1631fe08f039e7d76cf67a42a323d3178f0f25762ed9":
        raise ValueError("Expected verified PyMySQL 1.1.2 universal wheel")
    spec = importlib.util.spec_from_file_location("repair_installer", ROOT / "deploy/intranet/hotfix-highgo-version.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    source_by_target = {
        "/app/deploy/runtime_check.py": ROOT / "deploy/intranet/runtime_check.py",
        "/app/deploy/init_db.py": ROOT / "deploy/intranet/init_db.py",
    }
    values = {}
    for name, target in installer.OVERLAY_FILES.items():
        if name == "pymysql.zip":
            values[name + ".b64"] = base64.b64encode(wheel.read_bytes()).decode()
        else:
            path = source_by_target.get(target, ROOT / target.removeprefix("/app/"))
            values[name] = path.read_text()
    values.update({name: (ROOT / relative).read_text() for name, relative in {
        "console-entrypoint.sh": "console2/docker-entrypoint.d/40-amap-runtime-config.sh",
        "compose-apply.sh": "deploy/intranet/hotfix-compose-environment.sh",
        "compose-bootstrap.sh": "deploy/intranet/compose-bootstrap.sh",
        "apply.sh": "deploy/intranet/hotfix-highgo-version.sh",
        "apply.py": "deploy/intranet/hotfix-highgo-version.py",
    }.items()})
    static = ROOT / "console2/dist"
    if not (static / "index.html").is_file() or "roadFeaturesEnabled" not in (static / "runtime-config.template.js").read_text():
        raise ValueError("Build current Console assets before packaging the repair")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        for file in sorted(static.rglob("*")):
            if file.is_file() and file.name != "runtime-config.js":
                stream.write(file, file.relative_to(static).as_posix())
    values["console-static.zip.b64"] = base64.b64encode(archive.getvalue()).decode()
    # Read only the authorised connection fields; do not embed the reference app.
    config = json.loads(doris_config.read_text())
    mysql = config["mysql"]
    defaults = {
        "ROAD_FEATURES_ENABLED": "false", "DB_TIMESCALE_REQUIRED": "false", "YCX_METRICS_BACKEND": "doris", "YCX_ROAD_VERSION": "",
        "DORIS_MYSQL_HOST": str(mysql["host"]), "DORIS_MYSQL_PORT": str(mysql.get("port", 9030)),
        "DORIS_MYSQL_USER": mysql.get("user", ""), "DORIS_MYSQL_PASSWORD": mysql.get("password", ""),
        "DORIS_DATABASE": config.get("database", "ycx_xc"),
    }
    def quote(value):
        if any(character in value for character in ("\n", "\r", "\0")):
            raise ValueError("Unsupported newline in private deployment value")
        return "'" + value.replace("'", "\\'") + "'"
    values["site-defaults.env"] = "".join(f"{key}={quote(value)}\n" for key, value in defaults.items())
    values["SHA256SUMS"] = "".join(f"{hashlib.sha256(content.encode()).hexdigest()}  {name}\n" for name, content in sorted(values.items()))
    raw = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    encoded = base64.b64encode(raw).decode()
    script = (ROOT / "deploy/intranet/repair-highgo.sh.in").read_text().replace(
        "__PAYLOAD_SHA256__", hashlib.sha256(raw).hexdigest()).replace(
        "__PAYLOAD_BASE64__", "\n".join(encoded[index:index + 100] for index in range(0, len(encoded), 100)))
    with output.open("x") as stream:
        output.chmod(0o600)
        stream.write(script)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(f"{checksum}  {output.name}\n")
    print(output.name, output.stat().st_size, "bytes", checksum)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--doris-config", type=Path, required=True)
    args = parser.parse_args()
    build(args.output, args.wheel, args.doris_config)
