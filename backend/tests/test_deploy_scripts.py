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
    assert "set_env CREDENTIAL_ENCRYPTION_KEY" in script
    assert "openssl rand -base64 32" in script


def test_compose_auth_uses_secure_server_side_session_defaults():
    compose = COMPOSE.read_text()

    assert "APP_ENV: ${APP_ENV:-production}" in compose
    assert "COOKIE_SECURE: ${COOKIE_SECURE:-true}" in compose
    assert "SESSION_COOKIE_NAME: ${SESSION_COOKIE_NAME:-scholar_session}" in compose
    assert "SMTP_HOST" not in compose
    assert "AUTH_DEV_RETURN_MAGIC_LINK" not in compose


def test_compose_supplies_server_openalex_key_to_web_and_worker():
    compose = COMPOSE.read_text()
    deploy = DEPLOY.read_text()

    assert compose.count("OPENALEX_API_KEY: ${OPENALEX_API_KEY:-}") == 2
    assert compose.count("CREDENTIAL_ENCRYPTION_KEY: ${CREDENTIAL_ENCRYPTION_KEY:-") == 2
    assert "OPENALEX_API_KEY 不能为空" in deploy
    assert "CREDENTIAL_ENCRYPTION_KEY 必须是 44 字符的 Fernet key" in deploy
    assert "CREDENTIAL_ENCRYPTION_KEY 不能使用开发默认值" in deploy


def test_production_deploy_rejects_loopback_public_url():
    script = DEPLOY.read_text()

    assert "PUBLIC_APP_URL 不能指向 localhost 或回环地址" in script


def test_compose_runs_daily_postgres_backups_without_manual_profile():
    compose = COMPOSE.read_text()

    backup_service = compose.split("  backup:\n", 1)[1].split("\nvolumes:", 1)[0]
    assert 'profiles: ["backup"]' not in backup_service
    assert "restart: unless-stopped" in backup_service
    assert "BACKUP_INTERVAL_SECONDS" in backup_service
    assert "backup-postgres" in backup_service
    assert "compose --profile backup" not in BOOTSTRAP.read_text()
