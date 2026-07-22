#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

PUBLIC_IP="${PUBLIC_IP:-}"
REGISTRY_MIRROR="${DOCKER_REGISTRY_MIRROR:-}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
BACKUP_DIR="${BACKUP_HOST_DIR:-$(dirname "$ROOT_DIR")/scholar-profile-backups}"

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
    printf '\n部署停止：%s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
用法：sudo ./deploy/bootstrap-aliyun.sh [选项]

为 Ubuntu 24.04 阿里云 ECS 安装 Docker、配置可选镜像加速、创建 Swap、
生成公网 IP 模式 .env，并启动学者画像系统。

选项：
  --public-ip IP          公网 IPv4；默认从阿里云 ECS 元数据自动获取
  --registry-mirror URL  阿里云 ACR 控制台提供的专属 Docker Hub 加速地址
  --backup-dir PATH      宿主机备份目录，默认项目同级 scholar-profile-backups
  --swap-gb N            无 Swap 时创建的容量，默认 2；设为 0 可禁用
  -h, --help             显示帮助

也可使用环境变量 PUBLIC_IP、DOCKER_REGISTRY_MIRROR、BACKUP_HOST_DIR、SWAP_SIZE_GB。
脚本不会覆盖已经配置完成的数据库密码或自定义域名设置。
EOF
}

while (($#)); do
    case "$1" in
        --public-ip)
            (($# >= 2)) || die "--public-ip 缺少参数"
            PUBLIC_IP="$2"
            shift 2
            ;;
        --registry-mirror)
            (($# >= 2)) || die "--registry-mirror 缺少参数"
            REGISTRY_MIRROR="${2%/}"
            shift 2
            ;;
        --backup-dir)
            (($# >= 2)) || die "--backup-dir 缺少参数"
            BACKUP_DIR="$2"
            shift 2
            ;;
        --swap-gb)
            (($# >= 2)) || die "--swap-gb 缺少参数"
            SWAP_SIZE_GB="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "未知参数：$1"
            ;;
    esac
done

[[ $EUID -eq 0 ]] || die "请使用 root 运行：sudo ./deploy/bootstrap-aliyun.sh"
[[ -f "$ROOT_DIR/docker-compose.yml" && -f "$ROOT_DIR/.env.example" ]] || \
    die "脚本必须从完整项目仓库中运行"
[[ -r /etc/os-release ]] || die "无法识别操作系统"

# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
    die "此脚本仅针对 Ubuntu 24.04；当前为 ${PRETTY_NAME:-unknown}"
[[ "$(uname -m)" == "x86_64" ]] || die "此脚本当前仅支持 x86_64"
[[ "$SWAP_SIZE_GB" =~ ^[0-9]+$ ]] || die "--swap-gb 必须是非负整数"

if [[ -z "$PUBLIC_IP" ]]; then
    metadata_token="$(curl -fsS --max-time 3 -X PUT \
        'http://100.100.100.200/latest/api/token' \
        -H 'X-aliyun-ecs-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
    if [[ -n "$metadata_token" ]]; then
        for metadata_key in eipv4 public-ipv4; do
            PUBLIC_IP="$(curl -fsS --max-time 3 \
                -H "X-aliyun-ecs-metadata-token: $metadata_token" \
                "http://100.100.100.200/latest/meta-data/$metadata_key" 2>/dev/null || true)"
            [[ -n "$PUBLIC_IP" ]] && break
        done
    fi
    unset metadata_token metadata_key
fi

[[ "$PUBLIC_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || \
    die "无法自动获取公网 IPv4，请通过 --public-ip 明确指定"

IFS=. read -r ip1 ip2 ip3 ip4 <<<"$PUBLIC_IP"
for octet in "$ip1" "$ip2" "$ip3" "$ip4"; do
    ((10#$octet <= 255)) || die "公网 IPv4 格式不正确"
done

if [[ -n "$REGISTRY_MIRROR" && ! "$REGISTRY_MIRROR" =~ ^https://[^/[:space:]]+(/.*)?$ ]]; then
    die "镜像加速地址必须是 https:// URL"
fi

case "$ROOT_DIR" in
    *[[:space:]]*) die "项目路径不能包含空格：$ROOT_DIR" ;;
esac
case "$BACKUP_DIR" in
    *[[:space:]]*) die "备份路径不能包含空格：$BACKUP_DIR" ;;
esac

available_kb="$(df -Pk "$ROOT_DIR" | awk 'NR == 2 {print $4}')"
((available_kb >= 12 * 1024 * 1024)) || die "项目磁盘可用空间不足 12 GiB"

install_docker() {
    log "安装 Docker Engine 与 Compose plugin"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg |
        gpg --dearmor --batch --yes -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    printf '%s\n' \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu ${VERSION_CODENAME} stable" \
        >/etc/apt/sources.list.d/docker.list

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    systemctl enable --now cron
}

log "安装引导脚本所需的基础工具"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates cron curl gnupg openssl git python3

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    install_docker
else
    log "Docker 与 Compose 已安装，跳过安装"
    systemctl enable --now docker
    systemctl enable --now cron
fi

configure_registry_mirror() {
    local mirror="$1"
    log "配置账号专属 Docker Hub 镜像加速地址"
    MIRROR_URL="$mirror" python3 <<'PY'
import json
import os
from pathlib import Path

path = Path("/etc/docker/daemon.json")
if path.exists() and path.stat().st_size:
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} 不是有效 JSON，请先人工修复：{exc}")
else:
    config = {}

config["registry-mirrors"] = [os.environ["MIRROR_URL"]]
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
temporary.chmod(0o644)
temporary.replace(path)
PY
    systemctl restart docker
    docker info >/dev/null
}

if [[ -n "$REGISTRY_MIRROR" ]]; then
    configure_registry_mirror "$REGISTRY_MIRROR"
fi

ensure_swap() {
    if swapon --noheadings --show=NAME 2>/dev/null | grep -q .; then
        log "系统已有 Swap，跳过创建"
        swapon --show
        return
    fi
    if ((SWAP_SIZE_GB == 0)); then
        log "已按参数跳过 Swap 创建"
        return
    fi

    log "创建 ${SWAP_SIZE_GB} GiB Swap，降低首次构建 OOM 风险"
    if [[ ! -e /swapfile ]]; then
        fallocate -l "${SWAP_SIZE_GB}G" /swapfile || \
            dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    grep -Eq '^/swapfile[[:space:]]' /etc/fstab || \
        printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
    printf 'vm.swappiness=20\n' >/etc/sysctl.d/99-scholar-profile.conf
    sysctl --system >/dev/null
    swapon --show
}

ensure_swap

log "顺序拉取基础镜像并检查 Docker Hub 可用性"
base_images=(
    "python:3.13-slim"
    "node:24-alpine"
    "nginx:1.29-alpine"
    "postgres:17-alpine"
    "caddy:2.11.4-alpine"
)
for image in "${base_images[@]}"; do
    if ! docker pull "$image"; then
        if [[ -z "$REGISTRY_MIRROR" ]]; then
            die "无法拉取 $image。请在阿里云容器镜像服务控制台取得专属加速地址，然后重新运行：DOCKER_REGISTRY_MIRROR=https://你的地址.mirror.aliyuncs.com ./deploy/bootstrap-aliyun.sh"
        fi
        die "通过配置的镜像加速仍无法拉取 $image，请检查加速地址和 ECS 出站规则"
    fi
done

env_value() {
    sed -n "s/^$1=//p" "$ROOT_DIR/.env" | tail -n 1
}

set_env() {
    local key="$1"
    local value="$2"
    [[ "$value" != *'|'* && "$value" != *$'\n'* ]] || die "$key 包含不支持的字符"
    if grep -q "^${key}=" "$ROOT_DIR/.env"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ROOT_DIR/.env"
    else
        printf '%s=%s\n' "$key" "$value" >>"$ROOT_DIR/.env"
    fi
}

log "生成或补全生产环境配置"
if [[ ! -f "$ROOT_DIR/.env" ]]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

current_host="$(env_value PUBLIC_HOST)"
current_url="$(env_value PUBLIC_APP_URL)"
if [[ -z "$current_host" || "$current_host" == *example.com* ]]; then
    set_env PUBLIC_HOST ":80"
    set_env PUBLIC_APP_URL "http://$PUBLIC_IP"
    set_env CORS_ALLOWED_ORIGINS "http://$PUBLIC_IP"
    set_env COOKIE_SECURE "false"
elif [[ "$current_host" == ":80" && ( -z "$current_url" || "$current_url" == *example.com* ) ]]; then
    set_env PUBLIC_APP_URL "http://$PUBLIC_IP"
    set_env CORS_ALLOWED_ORIGINS "http://$PUBLIC_IP"
    set_env COOKIE_SECURE "false"
fi

owner_password="$(env_value POSTGRES_OWNER_PASSWORD)"
app_password="$(env_value POSTGRES_APP_PASSWORD)"
if [[ -z "$owner_password" || "$owner_password" == REPLACE_WITH_* || "$owner_password" == "owner-dev-only" ]]; then
    set_env POSTGRES_OWNER_PASSWORD "$(openssl rand -hex 24)"
fi
if [[ -z "$app_password" || "$app_password" == REPLACE_WITH_* || "$app_password" == "app-dev-only" ]]; then
    set_env POSTGRES_APP_PASSWORD "$(openssl rand -hex 24)"
fi

set_env APP_ENV "production"
set_env DATABASE_POOL_SIZE "3"
set_env DATABASE_MAX_OVERFLOW "2"

current_backup="$(env_value BACKUP_HOST_DIR)"
if [[ -z "$current_backup" || "$current_backup" == "./backups" ]]; then
    set_env BACKUP_HOST_DIR "$BACKUP_DIR"
else
    BACKUP_DIR="$current_backup"
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
chmod 600 "$ROOT_DIR/.env"

if ss -ltnH '( sport = :80 )' 2>/dev/null | grep -q .; then
    if ! (cd "$ROOT_DIR" && docker compose ps --status running -q gateway | grep -q .); then
        die "80 端口已被其他进程占用，请先执行 ss -lntp 检查"
    fi
fi

log "构建并启动应用"
cd "$ROOT_DIR"
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"
./deploy/deploy.sh

log "验证本机健康接口"
curl -fsS http://127.0.0.1/api/health
printf '\n'
curl -fsS http://127.0.0.1/api/ready
printf '\n'

rm -f /etc/cron.d/scholar-profile-backup

cat <<EOF

部署成功。

访问地址：        http://$PUBLIC_IP
自动备份目录：    $BACKUP_DIR
项目配置：        $ROOT_DIR/.env（权限 600，请勿提交）
查看状态：        cd $ROOT_DIR && docker compose ps
查看日志：        cd $ROOT_DIR && docker compose logs --tail=200 web worker gateway

仍需在阿里云控制台确认安全组已开放 TCP 80；不要开放 5432、55432 或 8000。
当前是公网 IP + HTTP 测试模式，不要启用真实邮箱登录。绑定并备案域名后再切换 HTTPS。
EOF
