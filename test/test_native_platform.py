"""New full native release: test actual lifecycle ordering and site translation."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/host-platform"))
spec = importlib.util.spec_from_file_location(
    "native_platform", ROOT / "deploy/native-platform/native_platform.py"
)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


@pytest.fixture
def site(monkeypatch, tmp_path):
    package = tmp_path / "新原生 包"
    deployment = tmp_path / "现有 部署"
    package.mkdir()
    deployment.mkdir()
    (package / "state").mkdir()
    (package / "app").mkdir()
    for name in ("weights", "test_videos", "logs"):
        (package / "app" / name).mkdir()
    (deployment / ".env").write_text("PRIVATE=true\n")
    (deployment / ".env").chmod(0o600)
    mounts = {}
    for i, target in enumerate(native.ASSETS):
        path = deployment / f"资源 {i}"
        path.mkdir()
        mounts[target] = str(path)
    env = [
        "DB_HOST=road9",
        "DB_NAME=ycx_prod",
        "DB_SCHEMA=drone",
        "DB_PASSWORD=p$a${s} /app/secret",
        "KAFKA_BOOTSTRAP=kafka:9092",
        "PIPELINE_DEVICE=ascend",
        "PIPELINE_ASCEND_MANIFEST=/app/weights/ascend/manifest.json",
        'SURVEY_ASSET_ROOTS=["/app/test_videos"]',
        "LD_LIBRARY_PATH=/container/libs",
    ]
    platform = {
        "Id": "platform",
        "Image": "sha256:different-on-purpose",
        "Config": {"Labels": {"com.docker.compose.project": "production"}, "Env": env},
        "Mounts": [
            {"Type": "bind", "Destination": t, "Source": s} for t, s in mounts.items()
        ],
        "NetworkSettings": {"Networks": {"bridge": {}}},
        "State": {"Running": True},
    }
    console = {
        "Id": "console",
        "Config": {"Labels": {}},
        "NetworkSettings": {"Networks": {"bridge": {}}},
    }
    services = {
        "platform": platform,
        "console2": console,
        "road9": {
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.28.0.3"}}}
        },
        "kafka": {
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.28.0.4"}}}
        },
    }
    config = {
        "services": {
            "platform": {"image": "old-platform"},
            "console2": {
                "image": "old-console",
                "volumes": [],
                "extra_hosts": {"unrelated": "192.0.2.1"},
                "environment": {"PRIVATE": "a$literal${text}"},
                "depends_on": {"platform": {}},
            },
        }
    }
    monkeypatch.setattr(native, "ROOT", package)
    monkeypatch.setattr(native, "STATE", package / "state")
    monkeypatch.setattr(native.common, "discover", lambda root: platform)
    monkeypatch.setattr(
        native, "service", lambda state, name, running=False: services[name]
    )
    monkeypatch.setattr(
        native, "config_for", lambda item, root: json.loads(json.dumps(config))
    )
    monkeypatch.setattr(
        native,
        "capture",
        lambda *a: json.dumps(
            [{"Driver": "bridge", "IPAM": {"Config": [{"Gateway": "172.28.0.1"}]}}]
        ),
    )
    monkeypatch.setattr(
        native,
        "container_text",
        lambda *a: "server { proxy_pass http://platform:8000; }",
    )
    monkeypatch.setattr(native, "previous_alias", lambda root: None)
    return package, deployment, services, mounts


def test_full_import_accepts_image_layout_and_maps_paths_without_changing_password(
    site,
):
    package, deployment, services, mounts = site
    state = native.install(deployment)
    env = state["environment"]
    assert env["DB_PASSWORD"] == "p$a${s} /app/secret"
    assert env["DB_HOST"] == "172.28.0.3"
    assert env["KAFKA_BOOTSTRAP"] == "172.28.0.4:9092"
    assert (
        env["ASCEND_MODEL_MANIFEST"] == mounts["/app/weights"] + "/ascend/manifest.json"
    )
    assert env["ASCEND_MODEL_MANIFEST"] == env["PIPELINE_ASCEND_MANIFEST"]
    assert json.loads(env["SURVEY_ASSET_ROOTS"]) == [mounts["/app/test_videos"]]
    assert all(env[name] == "1" for name in native.THREAD_VARS)
    assert "LD_LIBRARY_PATH" not in env
    assert (package / "app/test_videos").resolve() == Path(mounts["/app/test_videos"])
    saved = package / "state/site.json"
    assert saved.stat().st_mode & 0o777 == 0o600
    console = json.loads((package / "state/docker-host.json").read_text())["services"][
        "console2"
    ]
    assert console["extra_hosts"]["unrelated"] == "192.0.2.1"
    assert console["extra_hosts"]["host.traffic.internal"] == "172.28.0.1"
    assert console["environment"]["PRIVATE"] == "a$$literal$${text}"
    assert console["depends_on"] == {}
    assert "platform:8000" not in (package / "state/nginx.conf").read_text()


def test_database_recreation_refreshes_address(site):
    _, deployment, services, _ = site
    state = native.install(deployment)
    services["road9"]["NetworkSettings"]["Networks"]["bridge"]["IPAddress"] = (
        "172.28.0.9"
    )
    native.refresh(state)
    assert state["environment"]["DB_HOST"] == "172.28.0.9"
    assert state["environment"]["DB_NAME"] == "ycx_prod"
    assert state["environment"]["DB_SCHEMA"] == "drone"


def test_conflicting_manifest_rejected_before_links_or_state(site):
    package, deployment, services, _ = site
    services["platform"]["Config"]["Env"].append(
        "ASCEND_MODEL_MANIFEST=/different/model.json"
    )
    with pytest.raises(ValueError, match="MODEL_PATH_CONFIG"):
        native.install(deployment)
    assert not (package / "state/site.json").exists()
    assert not (package / "app/weights").is_symlink()


def test_missing_resource_rejected(site):
    _, deployment, services, _ = site
    services["platform"]["Mounts"].pop()
    with pytest.raises(ValueError, match="RESOURCE_DIRECTORY"):
        native.install(deployment)


def test_source_mounted_console_supported(site, monkeypatch):
    package, deployment, services, _ = site
    config = package / "console-nginx.conf"
    config.write_text("proxy_pass http://platform:8000;")
    monkeypatch.setattr(
        native,
        "config_for",
        lambda *a: {
            "services": {
                "platform": {"image": "old"},
                "console2": {
                    "volumes": [
                        {
                            "target": "/opt/traffic-console/nginx.conf",
                            "source": str(config),
                        }
                    ]
                },
            }
        },
    )
    monkeypatch.setattr(
        native,
        "container_text",
        lambda *a: pytest.fail("must read existing source bind"),
    )
    native.install(deployment)
    assert (
        package / "state/nginx.conf"
    ).read_text() == "proxy_pass http://host.traffic.internal:8000;"


def lifecycle(monkeypatch, state):
    events = []
    monkeypatch.setattr(native, "owned_pid", lambda: None)
    monkeypatch.setattr(native, "prepare", lambda s: events.append("prepare"))
    monkeypatch.setattr(
        native, "save", lambda *a: events.append(("save", a[1].get("phase")))
    )
    monkeypatch.setattr(native, "execute", lambda cmd, **kw: events.append(tuple(cmd)))
    monkeypatch.setattr(native, "compose", lambda s, f, *args: [f, *args])
    monkeypatch.setattr(
        native, "old_native", lambda s, cmd: events.append("old-" + cmd)
    )
    monkeypatch.setattr(native, "check_port", lambda s: events.append("port-check"))
    monkeypatch.setattr(native, "alias_set", lambda s: events.append("alias-set"))
    monkeypatch.setattr(
        native, "alias_restore", lambda s: events.append("alias-restore")
    )
    monkeypatch.setattr(native, "logged", lambda *a: events.append("preflight"))
    monkeypatch.setattr(native, "launch", lambda s: events.append("launch"))
    monkeypatch.setattr(
        native, "console_ready", lambda s: events.append("console-ready")
    )
    monkeypatch.setattr(native, "stop", lambda: events.append("stop-native"))
    state.update(
        phase="prepared",
        platform_running=True,
        bind_address="127.0.0.1",
        environment={},
    )
    return events


def test_start_failure_restores_platform_before_console(monkeypatch):
    state = {}
    events = lifecycle(monkeypatch, state)
    monkeypatch.setattr(
        native, "launch", lambda s: (_ for _ in ()).throw(RuntimeError("launch failed"))
    )
    with pytest.raises(RuntimeError, match="launch failed"):
        native.start(state)
    platform = (
        "docker-original.json",
        "up",
        "-d",
        "--no-deps",
        "--pull",
        "never",
        "platform",
    )
    console = (
        "docker-original.json",
        "up",
        "-d",
        "--no-deps",
        "--pull",
        "never",
        "console2",
    )
    assert events.index("stop-native") < events.index(platform) < events.index(console)
    assert state["phase"] == "rolled_back"
    assert not any("init-db" in str(e) for e in events)


def test_start_when_original_platform_stopped_does_not_start_it_on_failure(monkeypatch):
    state = {}
    events = lifecycle(monkeypatch, state)
    state["platform_running"] = False
    monkeypatch.setattr(
        native, "launch", lambda s: (_ for _ in ()).throw(RuntimeError("failed"))
    )
    with pytest.raises(RuntimeError):
        native.start(state)
    assert not any(
        isinstance(e, tuple) and "up" in e and e[-1] == "platform" for e in events
    )


def test_start_success_and_interrupted_switch_rejected(monkeypatch):
    state = {}
    events = lifecycle(monkeypatch, state)
    native.start(state)
    assert state["phase"] == "native"
    assert (
        events.index("prepare")
        < events.index("preflight")
        < events.index("launch")
        < events.index("console-ready")
    )
    state["phase"] = "switching"
    with pytest.raises(ValueError, match="INTERRUPTED_SWITCH"):
        native.start(state)


def test_repeated_start_does_not_launch_or_stop(monkeypatch):
    state = {}
    events = lifecycle(monkeypatch, state)
    monkeypatch.setattr(native, "owned_pid", lambda: 123)
    monkeypatch.setattr(native, "service", lambda *a: {"State": {"Running": False}})
    monkeypatch.setattr(native, "ready", lambda s: True)
    native.start(state)
    assert events == ["console-ready"]


def test_pid_reuse_does_not_signal_unrelated_process(monkeypatch):
    monkeypatch.setattr(
        native,
        "process_record",
        lambda pid: {"pid": pid, "start_ticks": "new", "status": "S"},
    )
    monkeypatch.setattr(native.os, "kill", lambda *a: pytest.fail("PID was reused"))
    native.terminate([{"pid": 123, "start_ticks": "old"}], 15)


def test_restore_old_native_before_console(monkeypatch):
    state = {}
    events = lifecycle(monkeypatch, state)
    state.update(previous_native_running=True, previous_platform_running=False)
    native.restore(state)
    assert events.index("alias-restore") < events.index("old-start")
    assert events.index("old-start") < next(
        i for i, e in enumerate(events) if isinstance(e, tuple) and e[-1] == "console2"
    )


def test_dependency_baseline_tamper_refused(site):
    package, _, _, _ = site
    (package / "HOST_RELEASE.json").write_text(
        json.dumps({"runtime_baseline": {"main_optimized.py": "bad"}})
    )
    (package / "app/main_optimized.py").write_text("bad")
    with pytest.raises(ValueError, match="DEPENDENCY_BASELINE"):
        native.check_baseline()


def test_occupied_port_detected(monkeypatch):
    import socket

    real_socket = socket.socket
    with real_socket() as server:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]

        class Probe:
            def __enter__(self):
                self.socket = real_socket()
                return self

            def __exit__(self, *args):
                self.socket.close()

            def setsockopt(self, *args):
                self.socket.setsockopt(*args)

            def bind(self, address):
                assert address == ("127.0.0.1", 8000)
                self.socket.bind(("127.0.0.1", port))

        monkeypatch.setattr(native.socket, "socket", Probe)
        with pytest.raises(OSError):
            native.check_port({"bind_address": "127.0.0.1"})


def test_restart_keeps_original_rollback_state(monkeypatch):
    state = {}
    lifecycle(monkeypatch, state)
    native.start(state)
    assert state["previous_platform_running"] is True
    state["platform_running"] = False
    native.start(state)
    assert state["previous_platform_running"] is True


def test_previous_native_alias_requires_matching_deployment(monkeypatch, tmp_path):
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    old = tmp_path / "previous"
    (old / "app").mkdir(parents=True)
    (old / "state").mkdir()
    (old / "HOST_RELEASE.json").write_text(json.dumps({"kind": "native-host-platform"}))
    (old / "state/site.json").write_text(
        json.dumps({"deployment_root": str(deployment)})
    )
    alias = tmp_path / "alias"
    alias.symlink_to(old / "app")
    real_path = Path
    monkeypatch.setattr(
        native, "Path", lambda value: alias if value == "/app" else real_path(value)
    )
    assert native.previous_alias(deployment) == str(old)
    (old / "state/site.json").write_text(
        json.dumps({"deployment_root": str(tmp_path / "other")})
    )
    with pytest.raises(ValueError, match="APP_PATH_OCCUPIED"):
        native.previous_alias(deployment)


def test_unrelated_app_directory_is_never_replaced(monkeypatch, tmp_path):
    alias = tmp_path / "app"
    alias.mkdir()
    (alias / "keep").write_text("unrelated")
    real_path = Path
    monkeypatch.setattr(
        native, "Path", lambda value: alias if value == "/app" else real_path(value)
    )
    with pytest.raises(ValueError, match="APP_PATH_OCCUPIED"):
        native.previous_alias(tmp_path)
    assert (alias / "keep").read_text() == "unrelated"


def test_native_production_device_is_explicit_ascend_even_with_stale_container_setting(
    site,
):
    _, deployment, services, _ = site
    services["platform"]["Config"]["Env"] = [
        value
        for value in services["platform"]["Config"]["Env"]
        if not value.startswith("PIPELINE_DEVICE=")
    ]
    services["platform"]["Config"]["Env"].append("PIPELINE_DEVICE=cpu")
    state = native.install(deployment)
    assert state["environment"]["PIPELINE_DEVICE"] == "ascend"


def test_foreign_owned_writable_log_rejected_before_logging(monkeypatch, tmp_path):
    log = tmp_path / "platform.log"
    log.touch()
    log.chmod(0o666)
    uid = log.stat().st_uid + 1
    monkeypatch.setattr(native.os, "geteuid", lambda: uid)
    with pytest.raises(PermissionError, match="sudo ./traffic"):
        native.check_owned_writable_path(log, owner_required=True)


def test_owned_writable_log_is_accepted(tmp_path):
    log = tmp_path / "platform.log"
    log.touch()
    log.chmod(0o600)
    native.check_owned_writable_path(log, owner_required=True)


def test_permission_check_precedes_source_check_and_state_write(monkeypatch):
    events = []

    def deny(state):
        events.append("permissions")
        raise PermissionError("RUNTIME_PERMISSION")

    monkeypatch.setattr(native, "check_runtime_permissions", deny)
    monkeypatch.setattr(native, "check_baseline", lambda: events.append("baseline"))
    monkeypatch.setattr(native, "save", lambda *a: events.append("write-state"))
    monkeypatch.setattr(native, "logged", lambda *a: events.append("logged"))
    with pytest.raises(PermissionError):
        native.prepare({})
    assert events == ["permissions"]


def test_native_environment_disables_runtime_binding_without_expanding_cpu_mask(
    monkeypatch,
):
    monkeypatch.setenv("OMP_PROC_BIND", "true")
    state = {"environment": {"OMP_PROC_BIND": "true", "OMP_NUM_THREADS": "1"}}
    result = native.environment(state)
    assert result["OMP_PROC_BIND"] == "false"
    assert result["OMP_NUM_THREADS"] == "1"
    assert state["environment"]["OMP_PROC_BIND"] == "true"


def test_diagnose_retains_a_complete_stage_cycle_instead_of_only_last_24kb(
    site, monkeypatch
):
    package, deployment, _, _ = site
    state = native.install(deployment)
    (package / "HOST_RELEASE.json").write_text(json.dumps({"version": "fixture"}))
    log_root = Path(state["environment"]["TRAFFIC_LOG_DIR"])
    directory = log_root / "pipelines"
    directory.mkdir()
    # The missing heavy stage precedes a dense burst of per-stage logs in real captures.
    content = "STAGE_END stage=tracker.image_motion elapsed_ms=500.0\n" + (
        "following-stage\n" * 5000
    )
    (directory / "pipe-current.log").write_text(content)
    monkeypatch.setattr(native, "owned_pid", lambda: None)
    monkeypatch.setattr(native, "owned_children", lambda: [])
    monkeypatch.setattr(native, "cpu_snapshot", lambda pids: {})
    native.diagnose(state)
    result = json.loads((package / "state/diagnosis.json").read_text())
    assert "stage=tracker.image_motion" in result["logs"]["pipe-current.log"]
    assert len(result["logs"]["pipe-current.log"].encode()) <= 256 * 1024


def test_bundled_console_replaces_resources_and_preserves_restore_snapshot(site):
    package, deployment, _, _ = site
    bundle = package / "console"
    (bundle / "html").mkdir(parents=True)
    (bundle / "html/index.html").write_text("new-console")
    (bundle / "nginx.conf").write_text("proxy_pass http://platform:8000;")
    native.install(deployment)
    deployed = json.loads((package / "state/docker-host.json").read_text())["services"][
        "console2"
    ]
    assert deployed["entrypoint"] == ["/bin/sh", "/opt/traffic-console/entrypoint.sh"]
    assert any(
        m["source"] == str(bundle)
        and m["target"] == "/opt/traffic-console"
        and m["read_only"]
        for m in deployed["volumes"]
    )
    previous = json.loads((package / "state/docker-original.json").read_text())[
        "services"
    ]["console2"]
    assert "entrypoint" not in previous
    assert str(bundle) not in json.dumps(previous)
    assert "host.traffic.internal:8000" in (package / "state/nginx.conf").read_text()


@pytest.mark.parametrize('exit_code',[0,7])
def test_logged_init_kafka_reaches_real_wrapper_and_preserves_arguments_and_exit(monkeypatch,tmp_path,exit_code):
    import os
    import shutil
    package=tmp_path/'package';tools=package/'app/deploy/intranet';tools.mkdir(parents=True)
    (package/'bin').mkdir();(package/'bin/python3').symlink_to(sys.executable)
    shutil.copy2(ROOT/'deploy/intranet/run_logged.py',tools/'run_logged.py')
    probe=tmp_path/'child-arguments.json'
    (tools/'init_kafka.py').write_text('import json,sys\nfrom pathlib import Path\nPath('+repr(str(probe))+').write_text(json.dumps(sys.argv[1:]))\nprint("INIT_KAFKA_CHILD_REACHED")\nraise SystemExit('+str(exit_code)+')\n')
    monkeypatch.setattr(native,'ROOT',package)
    monkeypatch.setattr(native,'environment',lambda state:{**os.environ,'PYTHONPATH':str(ROOT),'TRAFFIC_LOG_DIR':str(tmp_path/'logs')})
    state={'environment':{'TRAFFIC_LOG_DIR':str(tmp_path/'logs')}}
    if exit_code:
        with pytest.raises(RuntimeError,match='CHECK_FAILED: init-kafka'):
            native.logged(state,'init-kafka','init_kafka.py','--partitions','3','--replication-factor','1')
    else:
        native.logged(state,'init-kafka','init_kafka.py','--partitions','3','--replication-factor','1')
    assert json.loads(probe.read_text())==['--partitions','3','--replication-factor','1']
    log=(tmp_path/'logs/containers/init-kafka.log').read_text()
    assert 'INIT_KAFKA_CHILD_REACHED' in log and f'exit_code={exit_code}' in log
