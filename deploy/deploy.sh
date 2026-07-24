#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f .env ]; then
    echo "缺少 .env：请先执行 cp .env.example .env 并填写生产配置。" >&2
    exit 1
fi

if grep -Eq 'REPLACE_WITH_|owner-dev-only|app-dev-only|example\.com' .env; then
    echo ".env 仍包含示例值或开发密码，请修改后再部署。" >&2
    exit 1
fi

env_value() {
    sed -n "s/^$1=//p" .env | tail -n 1
}

if [ "$(env_value APP_ENV)" != "production" ]; then
    echo "APP_ENV 必须设置为 production。" >&2
    exit 1
fi

PUBLIC_HOST=$(env_value PUBLIC_HOST)
PUBLIC_APP_URL=$(env_value PUBLIC_APP_URL)
CORS_ALLOWED_ORIGINS=$(env_value CORS_ALLOWED_ORIGINS)
COOKIE_SECURE=$(env_value COOKIE_SECURE)
OWNER_PASSWORD=$(env_value POSTGRES_OWNER_PASSWORD)
APP_PASSWORD=$(env_value POSTGRES_APP_PASSWORD)
OPENALEX_API_KEY=$(env_value OPENALEX_API_KEY)

if [ -z "$PUBLIC_HOST" ] || [ -z "$PUBLIC_APP_URL" ]; then
    echo "PUBLIC_HOST 和 PUBLIC_APP_URL 不能为空。" >&2
    exit 1
fi

if printf '%s\n' "$PUBLIC_APP_URL" | grep -Eqi '^https?://(localhost|127\.|\[::1\])([:/]|$)'; then
    echo "PUBLIC_APP_URL 不能指向 localhost 或回环地址。" >&2
    exit 1
fi

if [ "$CORS_ALLOWED_ORIGINS" != "$PUBLIC_APP_URL" ]; then
    echo "单域部署时 CORS_ALLOWED_ORIGINS 必须与 PUBLIC_APP_URL 完全一致。" >&2
    exit 1
fi

for password in "$OWNER_PASSWORD" "$APP_PASSWORD"; do
    if [ "${#password}" -lt 20 ]; then
        echo "两个 PostgreSQL 密码都必须至少 20 个字符。" >&2
        exit 1
    fi
    case "$password" in
        *[!A-Za-z0-9_-]*)
            echo "PostgreSQL 密码只能包含字母、数字、下划线和短横线。" >&2
            exit 1
            ;;
    esac
done

if [ "$OWNER_PASSWORD" = "$APP_PASSWORD" ]; then
    echo "数据库所有者密码和应用密码不能相同。" >&2
    exit 1
fi

if [ -z "$OPENALEX_API_KEY" ]; then
    echo "OPENALEX_API_KEY 不能为空；请从 openalex.org/settings/api 获取免费 key。" >&2
    exit 1
fi

if [ "$PUBLIC_HOST" = ":80" ]; then
    case "$PUBLIC_APP_URL" in
        http://*) ;;
        *) echo "仅 IP 部署时 PUBLIC_APP_URL 必须以 http:// 开头。" >&2; exit 1 ;;
    esac
    if [ "$COOKIE_SECURE" != "false" ]; then
        echo "仅 IP/HTTP 部署必须设置 COOKIE_SECURE=false。" >&2
        exit 1
    fi
    echo "警告：当前使用 HTTP，登录 Cookie 不受 TLS 保护。建议绑定域名后启用 HTTPS。" >&2
else
    case "$PUBLIC_APP_URL" in
        https://*) ;;
        *) echo "域名部署时 PUBLIC_APP_URL 必须以 https:// 开头。" >&2; exit 1 ;;
    esac
    if [ "$COOKIE_SECURE" != "true" ]; then
        echo "HTTPS 部署必须设置 COOKIE_SECURE=true。" >&2
        exit 1
    fi
fi

docker compose config --quiet
docker compose up -d --build --remove-orphans --wait --wait-timeout 180
docker compose ps

echo "部署完成：$PUBLIC_APP_URL"
