from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELAY = ROOT / "deploy" / "google-egress-relay"


def _read(name: str) -> str:
    return (RELAY / name).read_text(encoding="utf-8")


def test_relay_is_loopback_only_and_filters_destinations() -> None:
    config = _read("tinyproxy.conf")
    destinations = _read("google-domains.filter")

    assert "Listen 127.0.0.1" in config
    assert "Port 17888" in config
    assert "FilterDefaultDeny Yes" in config
    assert "ConnectPort 443" in config
    assert "oauth2\\.googleapis\\.com" in destinations
    assert "youtubeanalytics\\.googleapis\\.com" in destinations


def test_container_is_isolated_and_uses_exact_name() -> None:
    script = _read("install-relay.sh")

    assert "--name zhiju-google-egress" in script
    assert "--network host" in script
    assert "--read-only" in script
    assert "--cap-drop ALL" in script
    assert "--security-opt no-new-privileges" in script
    assert "ufw" not in script
    assert "iptables" not in script


def test_install_uses_restricted_dedicated_authorized_key() -> None:
    script = _read("install-relay.sh")

    assert "useradd --system" in script
    assert "zhiju-egress" in script
    assert 'restrict,port-forwarding,permitopen="127.0.0.1:17888"' in script
    assert "/root/.ssh" not in script


def test_uninstall_has_only_exact_targets() -> None:
    script = _read("uninstall-relay.sh")

    assert "docker rm -f zhiju-google-egress" in script
    assert "docker image rm zhiju-google-egress:1" in script
    assert "userdel zhiju-egress" in script
    assert 'rm -rf -- "/opt/zhiju-google-egress"' in script
    assert "docker system prune" not in script
    assert "ufw" not in script
    assert "iptables" not in script
