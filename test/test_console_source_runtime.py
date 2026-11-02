"""Exercise host-mounted, read-only Console files against the existing runtime image."""
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONSOLE_IMAGE_TEST") != "1",
    reason="requires an existing ARM64 Console image and Docker",
)


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def start_console(tmp_path, *, provider="amap", private_html=False, entrypoint=None):
    html, logs = tmp_path / "html", tmp_path / "logs"
    html.mkdir(mode=0o755)
    logs.mkdir()
    for name, data in {
        "index.html": "<html>host source release</html>",
        "runtime-config.template.js": "window.__RUNTIME_CONFIG__={provider:'${MAP_PROVIDER}'};",
    }.items():
        path = html / name
        path.write_text(data)
        path.chmod(0o644)
    (html / "assets").mkdir()
    (html / "assets/app-12345678.js").write_text("window.publicAsset = true;\n")
    if private_html:
        for path in html.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        html.chmod(0o700)
    startup = logs / "nginx" / "startup.log"
    startup.parent.mkdir()
    with startup.open("wb") as stream:
        stream.truncate(20971520)
    mounts = {
        html: "/fixture-html" if private_html else "/opt/traffic-console/html",
        ROOT / "console2/nginx.conf": "/opt/traffic-console/nginx.conf",
        ROOT / "console2/docker-entrypoint.d/40-amap-runtime-config.sh": "/opt/traffic-console/configure.sh",
        entrypoint or ROOT / "deploy/intranet/console-runtime/entrypoint.sh": "/opt/traffic-console/entrypoint.sh",
    }
    command = ["docker", "run", "-d", "--add-host", "platform:127.0.0.1",
               "-p", "127.0.0.1::8080", "-e", "MAP_PROVIDER=" + provider,
               "--entrypoint", "sh"]
    for source, destination in mounts.items():
        command += ["--mount", f"type=bind,source={source},target={destination},readonly"]
    # Docker Desktop can translate host modes; create restrictive Linux-owned files too.
    prepare = ("rm -rf /opt/traffic-console/html; cp -R /fixture-html /opt/traffic-console/html; "
               "find /opt/traffic-console/html -type d -exec chmod 700 {} +; "
               "find /opt/traffic-console/html -type f -exec chmod 600 {} +; ") if private_html else ""
    command += ["--mount", f"type=bind,source={logs},target=/var/log/traffic-analyzer",
                os.getenv("CONSOLE_IMAGE_UNDER_TEST", "traffic-analyzer-console:2026.10.18.5-arm64"),
                "-c", "umask 077; " + prepare + "exec sh /opt/traffic-console/entrypoint.sh"]
    return run(*command), html, logs


@pytest.mark.parametrize("private_html", [False, True])
def test_readonly_host_resources_runtime_config_and_query_free_persistent_logs(tmp_path, private_html):
    container, html, logs = start_console(tmp_path, private_html=private_html)
    try:
        port = run("docker", "port", container, "8080/tcp").split(":")[-1]
        base = "http://127.0.0.1:" + port
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(base + "/index.html?access_token=must-not-log", timeout=2) as response:
                    assert b"host source release" in response.read()
                break
            except (urllib.error.URLError, ConnectionResetError):
                if time.monotonic() > deadline:
                    pytest.fail(run("docker", "logs", container))
                time.sleep(0.1)
        with urllib.request.urlopen(base + "/runtime-config.js", timeout=2) as response:
            assert response.status == 200
            assert b"provider:'amap'" in response.read()
            assert response.headers["Cache-Control"] == "no-store"
        for path in ("/", "/login", "/assets/app-12345678.js"):
            with urllib.request.urlopen(base + path, timeout=2) as response:
                assert response.status == 200
        assert (html / "index.html").stat().st_mode & 0o777 == (0o600 if private_html else 0o644)
        assert not (html / "runtime-config.js").exists()
        assert run("docker", "exec", container, "stat", "-c", "%a",
                   "/var/run/traffic-console/runtime-config.js") == "644"
        text = (logs / "nginx/startup.log").read_text()
        assert "event=READY" in text
        assert (logs / "nginx/startup.log.1").stat().st_size == 20971520
        access = (logs / "nginx/access.log").read_text()
        assert 'uri="/index.html"' in access and "must-not-log" not in access
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/api/probe?access_token=must-not-log", timeout=2)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if (logs / "nginx/error.log").exists() and "upstream" in (logs / "nginx/error.log").read_text():
                break
            time.sleep(0.1)
        errors = (logs / "nginx/error.log").read_text()
        assert "upstream" in errors and "must-not-log" not in errors
        assert "must-not-log" not in run("docker", "logs", container)
        assert "event=READY" in run("docker", "logs", container)
    finally:
        run("docker", "rm", "-f", container)


def test_configuration_failure_is_kept_on_host_and_container_exits_nonzero(tmp_path):
    container, _, logs = start_console(tmp_path, provider="invalid")
    try:
        assert int(run("docker", "wait", container)) != 0
        text = (logs / "nginx/startup.log").read_text()
        assert "Unsupported MAP_PROVIDER" in text
        assert "stage=configure event=ERROR" in text
    finally:
        run("docker", "rm", "-f", container)
