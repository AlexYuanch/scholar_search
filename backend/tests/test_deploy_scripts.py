from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "deploy" / "bootstrap-aliyun.sh"


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
