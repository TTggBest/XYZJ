import io
import os
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal, get_current_principal
from zhiju.app import app, create_app
from zhiju.database import get_db
from zhiju.models import AppIconSetting, Base, Device, RuntimePackageBuild
from zhiju.services.settings import _included_files


PLATFORM_PRINCIPAL = Principal(
    user_id="platform-admin",
    tenant_id="tenant-a",
    membership_role="owner",
    platform_role="super_admin",
    device_id=None,
    device_trust_level="super_code_machine",
    permissions=frozenset(),
)


def test_settings_read_models_come_from_runtime_and_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'settings.db'}")
    Base.metadata.create_all(engine, tables=[
        Device.__table__, RuntimePackageBuild.__table__, AppIconSetting.__table__,
    ])
    with Session(engine) as session:
        session.add(AppIconSetting(
            id="current-app-icon", source_type="default",
            source_path=str(tmp_path / "fixture-icon.png"),
            applied_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        session.commit()

    def open_db():
        with Session(engine) as session:
            yield session

    test_app = create_app()
    test_app.dependency_overrides[get_db] = open_db
    test_app.dependency_overrides[get_current_principal] = lambda: PLATFORM_PRINCIPAL
    try:
        with TestClient(test_app) as client:
            runtime = client.get("/api/v3/settings/runtime")
            assert runtime.status_code == 200
            assert runtime.json()["system"] == "筱宇智矩"
            assert runtime.json()["port"] == 19732
            assert runtime.json()["database_ok"] is True

            assert client.get("/api/v3/devices").status_code == 200
            assert client.get("/api/v3/runtime-packages").status_code == 200
            icon = client.get("/api/v3/settings/app-icon")
            assert icon.status_code == 200
            assert icon.json()["source_type"] == "default"
            assert icon.json()["preview_url"].startswith("/assets/app-icon-1024.png?v=")
    finally:
        engine.dispose()


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
    assert 'set URL of browserTab to targetURL' in browser_opener


def test_browser_opener_falls_back_when_chrome_tab_lookup_fails(tmp_path: Path) -> None:
    opener = Path(__file__).resolve().parents[2] / "scripts" / "open_app_url.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    opened = tmp_path / "opened.txt"
    commands = {
        "pgrep": "#!/bin/sh\nexit 0\n",
        "osascript": "#!/bin/sh\ncat >/dev/null\nexit 1\n",
        "open": "#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$OPENED_FILE\"\n",
    }
    for name, body in commands.items():
        path = fake_bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(opener), "http://127.0.0.1:19732/?dev_commit=test"],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "OPENED_FILE": str(opened),
        },
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert opened.read_text(encoding="utf-8").strip() == "http://127.0.0.1:19732/?dev_commit=test"


def test_code_machine_launcher_allows_feature_branch_and_worktree_changes(tmp_path: Path) -> None:
    launcher = Path(__file__).resolve().parents[2] / "start-dev.command"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    commands = {
        "git": """#!/bin/sh
case "$1 $2" in
  "branch --show-current") echo feature/test-launch ;;
  "status --porcelain") echo ' M backend/example.py' ;;
  "rev-parse --short=12") echo abcdef123456 ;;
esac
""",
        "curl": "#!/bin/sh\nexit 1\n",
        "lsof": "#!/bin/sh\nexit 0\n",
    }
    for name, body in commands.items():
        path = fake_bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(launcher)],
        input="",
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        timeout=10,
        check=False,
    )

    assert "代码分支：feature/test-launch" in result.stdout
    assert "只能从 dev 分支启动" not in result.stdout
    assert "工作区存在未提交变更" not in result.stdout
    assert "端口 19732 已被其他程序占用" in result.stdout


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


def test_runtime_start_ensures_local_production_mysql_before_device_lookup() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "start_package.sh").read_text(
        encoding="utf-8"
    )

    assert '"$ROOT/scripts/ensure_local_production_mysql.sh"' in source
    assert source.index("ensure_local_production_mysql.sh") < source.index("configure_package_device.py")


def test_runtime_install_ensures_local_production_mysql_before_device_lookup() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "setup_package.sh").read_text(
        encoding="utf-8"
    )

    assert '"$ROOT/scripts/ensure_local_production_mysql.sh"' in source
    assert source.index("ensure_local_production_mysql.sh") < source.index("configure_package_device.py")


def test_local_production_mysql_start_refuses_to_initialize_an_empty_database() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "ensure_local_production_mysql.sh"
    ).read_text(encoding="utf-8")

    assert '[[ -d "$DATADIR/mysql" ]]' in source
    assert '[[ -f "$CNF_FILE" ]]' in source
    assert "--initialize" not in source


def test_only_current_runtime_package_has_download_endpoint(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime-packages.db'}")
    Base.metadata.create_all(engine, tables=[RuntimePackageBuild.__table__])
    with Session(engine) as session:
        session.add_all(
            [
                RuntimePackageBuild(
                    build_number=1,
                    version="3.0.0-build.1",
                    target_environment="production",
                    status="succeeded",
                    file_count=1,
                    size_bytes=1,
                    started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                RuntimePackageBuild(
                    build_number=2,
                    version="3.0.0-build.2",
                    target_environment="production",
                    status="succeeded",
                    file_count=1,
                    size_bytes=1,
                    started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

    def open_db():
        with Session(engine) as session:
            yield session

    test_app = create_app()
    test_app.dependency_overrides[get_db] = open_db
    test_app.dependency_overrides[get_current_principal] = lambda: PLATFORM_PRINCIPAL
    try:
        client = TestClient(test_app)
        packages = client.get("/api/v3/runtime-packages").json()
        current = packages[0]
        response = client.get(f"/api/v3/runtime-packages/{current['id']}/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/gzip"
        assert "attachment;" in response.headers["content-disposition"]
        assert response.content[:2] == b"\x1f\x8b"

        old_response = client.get(f"/api/v3/runtime-packages/{packages[1]['id']}/download")
        assert old_response.status_code == 409
    finally:
        engine.dispose()
