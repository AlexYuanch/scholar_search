from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "deploy" / "bootstrap-aliyun.sh"
DEPLOY = ROOT / "deploy" / "deploy.sh"
COMPOSE = ROOT / "docker-compose.yml"


def test_aliyun_bootstrap_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", str(BOOTSTRAP)], check=True)


def test_aliyun_bootstrap_help_is_available_without_server_changes():
    result = subprocess.run(
        [str(BOOTSTRAP), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--registry-mirror" in result.stdout
    assert "--public-ip" in result.stdout
    assert "--swap-gb" in result.stdout


def test_aliyun_bootstrap_does_not_commit_host_specific_or_untrusted_registry_values():
    script = BOOTSTRAP.read_text()
    assert 'PUBLIC_IP="${PUBLIC_IP:-}"' in script
    assert "docker.1ms.run" not in script
    assert "dockerproxy" not in script
    assert 'openssl rand -hex 24' in script


def test_compose_auth_defaults_fail_closed_outside_local_development():
    compose = COMPOSE.read_text()

    assert "APP_ENV: ${APP_ENV:-production}" in compose
    assert "PUBLIC_APP_URL: ${PUBLIC_APP_URL:-}" in compose
    assert "AUTH_DEV_RETURN_MAGIC_LINK: ${AUTH_DEV_RETURN_MAGIC_LINK:-false}" in compose
    assert "PUBLIC_APP_URL: ${PUBLIC_APP_URL:-http://localhost}" not in compose


def test_production_deploy_rejects_loopback_public_url():
    script = DEPLOY.read_text()

    assert "PUBLIC_APP_URL 不能指向 localhost 或回环地址" in script
