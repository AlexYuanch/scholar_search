# 学者画像系统 Scholar Profile

基于 OpenAlex 发现、Crossref DOI 核验的学者检索与画像应用。当前版本使用标准 PostgreSQL 17 自托管数据层，不依赖 Supabase、Firebase 或其他 BaaS。

## 当前能力

- 中文姓名同时检索原名、姓在前拼音和姓在后拼音；候选使用姓名、ORCID、机构、共同论文、共同合作者和研究主题进行保守身份聚类，不同 ORCID 或证据不足的同名者保持分开。
- 被判定为同一学者的拆分 OpenAlex 档案联合获取论文并归到主身份；研究方向由 OpenAlex 细粒度 topics、keywords 与标题高频短语交叉提取，宽泛学科标签降权。
- 联合论文会执行保守的身份一致性审查；只有同时与核心机构、合作者和主题断开的微小论文簇才自动排除，较大冲突簇保留并提示人工确认。
- LangGraph 分页获取 OpenAlex 论文，以 DOI 查询 Crossref 出版元数据，裁决后再生成引用统计、研究方向、兴趣演化、代表论文和合作网络。
- 概览展示本次收录、DOI 数、跨来源核验数、待核实数、来源差异和分页完整性；待核实只表示缺少 DOI 或 Crossref 暂无记录。
- 最终总结经过证据审查，论文依据必须能回溯到裁决后的统一论文集；不通过审查的新画像不会发布。
- 每次用户发起画像查询都会重新获取 OpenAlex 当前数据，并通过 NDJSON 持续展示进度。
- PostgreSQL 规范化保存学者、机构、论文和署名关系，并保留一份最近成功画像用于质量对比和自动更新。
- 收藏学者每天更新，近 30 天访问学者每 7 天更新；失败不会覆盖最近一次成功画像。
- 研究追踪记录用户上次看过的论文数、引用数和画像版本；后台发现增量后在追踪面板提示，查看最新版后自动清除。
- 用户自助注册本地账号并使用密码登录；HttpOnly Cookie 会话保护查询、私有历史和收藏。
- 搜索与画像生成按账号和来源 IP 限速，避免公开注册用户短时间重复触发外部数据抓取。
- PostgreSQL `LISTEN/NOTIFY` 经 FastAPI SSE 推送版本变化，前端自动加载新版画像。
- Compose 常驻备份服务每天生成 PostgreSQL 自定义格式备份，默认保留 7 天。
- 全量论文游标分页；文章详情、查询历史和收藏在桌面端使用自适应双栏，在窄屏端使用可滚动抽屉。
- 导航、搜索区、画像卡片和合作图随浏览器宽高重排；从候选、合作者、历史或收藏跳转时同步当前搜索姓名。
- 支持选择第二位学者进行并列对比，展示成果规模、近五年活跃度、研究方向和代表论文；对比过程重新获取当前数据。
- 画像总览按最近发表年份比较连续两个三年阶段，展示论文数量变化、近期开始活跃及研究比重升降，并用六年矩阵呈现方向演化。

## 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | Vite、React 19、TypeScript、Tailwind CSS v4 |
| UI / 图谱 | Radix primitives、lucide-react、vis-network |
| API | FastAPI、Uvicorn、SQLAlchemy 2、psycopg |
| 工作流 | LangGraph |
| 数据源 | OpenAlex、Crossref；可选 OpenAI 兼容 LLM |
| 数据库 | PostgreSQL 17、Alembic |
| 身份认证 | 本地账号密码、scrypt 密码摘要、服务端会话 Cookie |
| 实时更新 | PostgreSQL `LISTEN/NOTIFY`、Server-Sent Events |
| 后台更新 | 独立 worker、`FOR UPDATE SKIP LOCKED` |

## 阿里云 ECS 从 Gitee 部署

仓库已经包含 PostgreSQL、数据库迁移、FastAPI、worker、前端 Nginx 和 Caddy HTTPS 网关。服务器拉取后不需要改源码，只需创建未提交的 `.env`。

### 已检查 ECS 的快速入口

针对已检查的上海 ECS（Ubuntu 24.04 x86_64、2 核、1.6 GiB 内存、40 GiB 系统盘、无 Docker/Swap/域名），可以使用 [`deploy/bootstrap-aliyun.sh`](deploy/bootstrap-aliyun.sh)：

1. 在阿里云安全组新增入方向 `TCP:80`，来源暂设 `0.0.0.0/0`；SSH 22 仅允许管理 IP。不要开放 5432、55432 或 8000。
2. 服务器实测无法访问 Docker Hub。进入阿里云“容器镜像服务 ACR → 镜像工具 → 镜像加速器”，复制当前账号的专属 `https://...mirror.aliyuncs.com` 地址。
3. 拉取公开 Gitee 仓库并执行：

```bash
git clone <你的-Gitee-仓库地址> /opt/scholar-profile
cd /opt/scholar-profile
DOCKER_REGISTRY_MIRROR='https://你的专属地址.mirror.aliyuncs.com' \
  ./deploy/bootstrap-aliyun.sh
```

脚本会从 ECS 元数据自动读取公网 EIP，并执行以下操作：

- 从阿里云 Docker CE 软件源安装 Docker Engine、Buildx 和 Compose plugin。
- 在系统没有 Swap 时创建 2 GiB `/swapfile`，降低 1.6 GiB 内存首次构建 OOM 风险。
- 合并写入 Docker `registry-mirrors`，顺序预拉取所有基础镜像；任一镜像不可用时在数据库创建前停止。
- 自动生成两个随机 PostgreSQL 密码，配置公网 IP + HTTP、生产安全开关和较小连接池。
- 把备份放在项目同级的 `/opt/scholar-profile-backups`，由 Compose 常驻服务按日备份。
- 构建、迁移、启动全部服务并验证本机健康接口。

脚本幂等可重复执行；已有有效 `.env` 密码和自定义域名不会被覆盖。首次跑通后访问 `http://公网IP`。阿里云说明个人镜像加速不保证所有新镜像均可用，所以脚本会预拉取项目使用的全部基础镜像标签进行验证；若仍失败，应改用 ACR 制品订阅或把构建好的镜像推送到自己的 ACR 仓库。

### 1. 准备服务器

- 建议至少 2 核 4 GB、40 GB 云盘；安装 Docker Engine 和 Docker Compose plugin。
- 阿里云安全组开放 `80/tcp`、`443/tcp`；`22/tcp` 只允许你的管理 IP。
- 不要开放 `5432`、`55432` 或 `8000`。Compose 只把 PostgreSQL 测试端口绑定到服务器回环地址。
- 有域名时，先把域名的 A/AAAA 记录解析到 ECS 公网 IP。Caddy 会自动申请和续期 HTTPS 证书。

确认安装：

```bash
docker --version
docker compose version
git --version
```

Docker 的安装方式以 [Docker Engine for Ubuntu 官方文档](https://docs.docker.com/engine/install/ubuntu/) 为准，不建议使用来路不明的一键安装脚本。

### 2. 拉取代码并创建配置

```bash
git clone <你的-Gitee-仓库-HTTPS-或-SSH-地址> scholar-profile
cd scholar-profile
cp .env.example .env
nano .env
```

`.env` 至少要修改这些值：

| 配置 | 有域名的正式部署 | 暂时只有公网 IP |
|------|------------------|----------------|
| `PUBLIC_HOST` | `scholar.your-domain.com` | `:80` |
| `PUBLIC_APP_URL` | `https://scholar.your-domain.com` | `http://你的公网IP` |
| `CORS_ALLOWED_ORIGINS` | 与 `PUBLIC_APP_URL` 完全一致 | 与 `PUBLIC_APP_URL` 完全一致 |
| `COOKIE_SECURE` | `true` | `false` |
| `POSTGRES_OWNER_PASSWORD` | 新的强密码 | 新的强密码 |
| `POSTGRES_APP_PASSWORD` | 与上面不同的强密码 | 与上面不同的强密码 |

密码会被拼入数据库连接 URL，当前模板要求使用足够长的字母、数字、下划线和短横线组合。不要在密码中放 `@`、`:`、`/`、`#`、`%` 等未编码 URL 字符。

保持以下生产安全项不变：

```dotenv
APP_ENV=production
```

本地账号不依赖邮箱、短信或第三方平台。`LLM_*` 可留空，系统会使用确定性规则分析。

### 3. 启动并验收

只通过生产检查脚本启动，它会拒绝示例密码、错误的生产开关和不安全的 Cookie 组合：

```bash
./deploy/deploy.sh
curl -fsS "https://你的域名/api/health"
curl -fsS "https://你的域名/api/ready"
docker compose ps
```

正常结果应为 `health -> {"status":"ok"}`、`ready -> {"status":"ready"}`，且 `postgres`、`web`、`worker`、`frontend`、`gateway` 均为运行/健康状态。只有公网 IP 时，把验收 URL 换成 `http://你的公网IP`。排查日志：

```bash
docker compose logs --tail=200 web worker gateway
```

部署完成后，用户可直接在登录弹窗切换到“注册账号”。用户名为 3–64 位，只允许字母、数字、点、下划线和短横线；密码至少 12 位。注册按来源 IP 限制为每小时最多 10 次，并在成功后自动登录。

服务器管理员仍可使用以下运维命令创建账号、查看账号或重置密码：

```bash
docker compose exec -it web python manage_users.py create admin
docker compose exec web python manage_users.py list
docker compose exec -it web python manage_users.py reset-password admin
```

### 4. 后续更新

```bash
cd scholar-profile
git pull --ff-only
./deploy/deploy.sh
```

需要重新构建：后端、前端和依赖都封装在镜像内，`deploy.sh` 已执行 `docker compose up -d --build`，并会在启动 Web 前自动运行 Alembic 迁移。不要运行 `docker compose down -v`，`-v` 会删除 PostgreSQL、备份和 Caddy 证书数据卷。普通停机使用：

```bash
docker compose down
```

仅 IP 的 HTTP 模式适合短期验收，账号密码和 Cookie 会以明文 HTTP 传输。正式使用前应绑定域名，把三项 URL/Host 配置切到域名、设 `COOKIE_SECURE=true`，再重新执行部署脚本。

## 一键本地运行

需要 Docker Desktop 和 Docker Compose。本地无 `.env` 启动时显式传入开发参数：

```bash
APP_ENV=development \
PUBLIC_APP_URL=http://localhost \
CORS_ALLOWED_ORIGINS=http://localhost \
COOKIE_SECURE=false \
docker compose up -d --build --wait
```

打开 <http://localhost>，在登录弹窗中注册账号。

## 从源码开发

```bash
npm install
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cd ..

npm run db:up
npm run db:migrate
```

后端 Web 环境至少需要：

```bash
export DATABASE_URL='postgresql://scholar_app:app-dev-only@127.0.0.1:55432/scholar_profile'
export COOKIE_SECURE=false
```

分别启动三个进程：

```bash
cd backend && .venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 5800
cd backend && .venv/bin/python worker.py
npm run dev -- --port 5173
```

Vite 会把 `/api` 代理到 `127.0.0.1:5800`。

## 数据库与迁移

[`backend/migrations`](backend/migrations) 是数据库结构的唯一来源。迁移必须使用数据库所有者连接，应用和 worker 使用权限受限的固定角色 `scholar_app`：

```bash
cd backend
MIGRATION_DATABASE_URL='postgresql://scholar_owner:...@db:5432/scholar_profile' \
  .venv/bin/alembic -c alembic.ini upgrade head
```

主要表：

- 学术事实：`scholars`、`scholar_aliases`、`institutions`、`scholar_institutions`、`works`、`authorships`
- 画像与任务：`scholar_profiles`、`profile_status`、`refresh_jobs`
- 用户与会话：`app_users`、`auth_login_attempts`、`auth_registration_attempts`、`api_rate_limit_events`、`user_sessions`、`user_history`、`favorites`

数据库不暴露给浏览器，授权边界由 FastAPI 强制执行。迁移撤销 `PUBLIC` 默认权限，并只向 `scholar_app` 授予所需数据操作权限。

## API

| 接口 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/health`、`GET /api/ready` | 公开 | 进程与数据库健康检查 |
| `GET /api/search?name=...` | 必须登录、限速 | 搜索候选学者 |
| `POST /api/profile` | 必须登录 | 返回最新画像并记录当前用户历史 |
| `POST /api/profile/stream` | 必须登录、限速 | 重新获取当前数据并输出 NDJSON 进度流 |
| `GET /api/authors/{author_id}/works` | 必须登录 | 全量论文游标分页 |
| `POST /api/auth/register` | 公开、限速 | 创建本地账号并自动登录 |
| `POST /api/auth/login` | 公开、限速 | 用户名密码登录并设置会话 Cookie |
| `GET /api/auth/me` | 可匿名 | 查询当前会话 |
| `POST /api/auth/logout` | 可匿名 | 注销当前会话 |
| `GET /api/history` | 必须登录 | 当前用户历史 |
| `GET/POST/DELETE /api/favorites...` | 必须登录 | 当前用户收藏 |
| `GET /api/profiles/{scholar_id}/events` | 必须登录 | 画像状态 SSE |

## 测试

```bash
npm test
npm run lint
npm run build
npm run test:db
```

`npm test` 使用 fake/in-memory repository。`npm run test:db` 启动标准 PostgreSQL，应用 Alembic 迁移，并验证结构、权限、事务发布、分页、队列和会话。

## 备份

`backup` 服务随 Compose 常驻运行，启动时立即备份，之后默认每 86400 秒备份一次，并删除超过 `BACKUP_RETENTION_DAYS` 的旧文件。手工额外生成一次备份：

```bash
docker compose exec backup backup-postgres
```

备份默认写入服务器项目目录的 `backups/`，也可通过 `.env` 的 `BACKUP_HOST_DIR` 指向挂载的数据盘；周期由 `BACKUP_INTERVAL_SECONDS` 配置。

生产环境还应把备份同步到对象存储或另一台机器，并定期验证 `pg_restore`；同一台 ECS 上的备份无法防御整机或云盘故障。

## 单机容量增长后的拆分

当前版本针对单台 ECS 直接启动优化。数据量或并发增长后，可把 PostgreSQL 迁到同 VPC 的 RDS PostgreSQL，把数据库 URL 改为 RDS 私网地址，并继续让 Web/worker 使用受限账号；迁移账号只在发布阶段使用。旧 SQLite 缓存不迁移，自托管 PostgreSQL 从空库开始。

## 目录结构

```text
backend/
  main.py          # FastAPI、NDJSON、Auth 与 SSE
  repository.py    # PostgreSQL Repository
  auth.py          # 密码摘要与 Cookie 会话依赖
  manage_users.py  # 服务器端本地账号管理命令
  events.py        # LISTEN/NOTIFY 到 SSE
  worker.py        # 刷新与维护 worker
  migrations/      # Alembic 迁移
src/
  App.tsx          # 搜索、画像、登录、收藏与自动换版
  api.ts           # Cookie API、NDJSON 与 SSE 地址
  auth.tsx         # 后端会话上下文
deploy/
  Caddyfile        # 公网 HTTP/HTTPS 入口
  bootstrap-aliyun.sh # Ubuntu 24.04 ECS 初始化与一键部署
  deploy.sh        # 生产配置检查与启动
  nginx.conf       # 静态前端与 /api 代理
  postgres/001-create-app-user.sh
  backup-postgres.sh
docker-compose.yml
```
