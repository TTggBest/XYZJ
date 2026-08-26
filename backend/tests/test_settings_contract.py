import io
import tarfile

from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.services.settings import _included_files


def test_settings_read_models_come_from_runtime_and_database() -> None:
    client = TestClient(app)

    runtime = client.get("/api/v3/settings/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["system"] == "筱宇智矩"
    assert runtime.json()["port"] == 19732
    assert runtime.json()["database_ok"] is True

    assert client.get("/api/v3/devices").status_code == 200
    assert client.get("/api/v3/runtime-packages").status_code == 200
    icon = client.get("/api/v3/settings/app-icon")
    assert icon.status_code == 200
    assert icon.json()["source_type"] in {"default", "custom"}
    assert icon.json()["preview_url"].startswith("/assets/app-icon-1024.png?v=")


def test_runtime_package_source_excludes_local_state() -> None:
    relative_paths = [str(path.relative_to(path.parents[0])) for path in _included_files()]
    files = _included_files()

    assert files
    assert all("/.venv/" not in f"/{path.as_posix()}" for path in files)
    assert all("/.runtime/" not in f"/{path.as_posix()}" for path in files)
    assert all("/data/" not in f"/{path.as_posix()}" for path in files)
    assert all(path.name != ".env" for path in files)
    assert all(path.name != "server.py" for path in files)
    assert all(path.name != "mysql_dev.sh" for path in files)
    assert all("/tests/" not in f"/{path.as_posix()}" for path in files)
    assert relative_paths


def test_runtime_package_contract_is_production_only() -> None:
    from zhiju.services.settings import _write_runtime_archive

    buffer = io.BytesIO()
    file_count, size_bytes = _write_runtime_archive(buffer, "3.0.0-build.999")
    buffer.seek(0)

    with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
        names = archive.getnames()
        version_name = next(name for name in names if name.endswith("/VERSION"))
        version = archive.extractfile(version_name).read().decode().strip()
        setup_info = next(member for member in archive.getmembers() if member.name.endswith("/scripts/setup_package.sh"))
        setup_body = archive.extractfile(setup_info).read().decode()
        install_name = next(name for name in names if name.endswith("/scripts/install_downloaded_package.sh"))
        install_body = archive.extractfile(install_name).read().decode()

    assert file_count > 0
    assert size_bytes > 0
    assert version == "3.0.0-build.999"
    assert any(name.endswith("/scripts/setup_package.sh") for name in names)
    assert any(name.endswith("/scripts/start_package.sh") for name in names)
    assert setup_info.mode & 0o111
    assert "builder|studio|worker" not in setup_body
    assert 'ROLE="${1:-}"' not in setup_body
    assert 'ROLE="${1:-}"' not in install_body
    assert any(name.endswith("/scripts/configure_package_device.py") for name in names)


def test_device_api_exposes_runtime_profile_fields() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()["components"]["schemas"]

    register_fields = schema["DeviceRegister"]["properties"]
    read_fields = schema["DeviceRead"]["properties"]
    expected = {
        "hostname",
        "device_role",
        "login_user",
        "thunderbolt_address",
        "lan_address",
        "ssh_key_path",
    }
    assert expected.issubset(register_fields)
    assert expected.issubset(read_fields)


def test_launchers_wait_for_process_exit_and_force_stuck_sse_shutdown() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    run_source = (root / "run_v3.py").read_text(encoding="utf-8")
    dev_launcher = (root / "start-dev.command").read_text(encoding="utf-8")
    package_launcher = (root / "scripts" / "start_package.sh").read_text(encoding="utf-8")
    browser_opener = (root / "scripts" / "open_app_url.sh").read_text(encoding="utf-8")

    assert "timeout_graceful_shutdown=3" in run_source
    for launcher in (dev_launcher, package_launcher):
        assert 'kill -0 "$OLD_PID"' in launcher
        assert 'kill -KILL "$OLD_PID"' in launcher
        assert 'open_app_url.sh' in launcher
        assert 'PID ${OLD_PID}' in launcher
    assert 'PID ${OLD_PID}' in (root / "scripts" / "install_downloaded_package.sh").read_text(encoding="utf-8")
    assert 'set active tab index' in browser_opener
    assert 'reload browserTab' in browser_opener


def test_system_timestamps_are_rendered_in_beijing_time() -> None:
    from pathlib import Path

    app_source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function fmtUtc" in app_source
    assert 'timeZone: "Asia/Shanghai"' in app_source
    assert "fmtUtc(item.completed_at || item.started_at)" in app_source


def test_runtime_package_install_is_non_interactive_and_uses_shared_config() -> None:
    from pathlib import Path

    setup_source = (Path(__file__).resolve().parents[2] / "scripts" / "setup_package.sh").read_text(encoding="utf-8")

    assert "read -r" not in setup_source
    assert '"$HOME/Documents/XYData/XYZJ/config/zhiju-runtime.env"' in setup_source
    assert '"/Volumes/XYData/XYZJ/config/zhiju-runtime.env"' in setup_source
    assert "未找到智矩生产配置" in setup_source
    assert "python3.12" in setup_source
    assert 'install --ignore-dependencies python@3.12' in setup_source
    assert '[[ -x "$PYTHON_BIN" ]]' in setup_source
    assert 'python3 -m venv' not in setup_source
    assert 'ZHJ_DEVICE_ROLE:-' in setup_source
    assert 'ZHJ_MIGRATION_DATABASE_URL:-' in setup_source
    assert '"$ROOT/.venv/bin/alembic" -c "$ROOT/alembic.ini" upgrade head' in setup_source
    assert setup_source.index('alembic.ini\" upgrade head') < setup_source.index('preflight_package.py')

    install_source = (Path(__file__).resolve().parents[2] / "scripts" / "install_downloaded_package.sh").read_text(encoding="utf-8")
    assert "zhiju-runtime-*.tar.gz" in install_source
    assert ".zhiju-runtime-new.*" in install_source


def test_runtime_desktop_app_launches_terminal_without_apple_events() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "create_package_app.sh").read_text(
        encoding="utf-8"
    )

    assert 'Contents/Resources/start-package.command' in source
    assert 'exec /usr/bin/open -a Terminal "$CONTENTS_DIR/Resources/start-package.command"' in source
    assert "osacompile" not in source
    assert 'tell application "Terminal"' not in source


def test_studio_mysql_bootstrap_uses_an_independent_instance() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_studio_mysql.sh").read_text(encoding="utf-8")

    assert 'PORT=33306' in source
    assert 'ROOT="$HOME/Documents/XYData/XYZJ"' in source
    assert 'DATADIR="$MYSQL_ROOT/data"' in source
    assert "zhiju_prod" in source
    assert "brew services stop" not in source
    assert "mysql.server stop" not in source


def test_only_current_runtime_package_has_download_endpoint() -> None:
    client = TestClient(app)
    packages = client.get("/api/v3/runtime-packages").json()

    if not packages:
        return

    current = packages[0]
    if current["status"] == "succeeded":
        response = client.get(f"/api/v3/runtime-packages/{current['id']}/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/gzip"
        assert "attachment;" in response.headers["content-disposition"]
        assert response.content[:2] == b"\x1f\x8b"

    if len(packages) > 1:
        old_response = client.get(f"/api/v3/runtime-packages/{packages[1]['id']}/download")
        assert old_response.status_code == 409
