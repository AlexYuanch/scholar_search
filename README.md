# ScholarSearch 学者情报产品

基于 OpenAlex 发现、Crossref DOI 核验的学者身份确认、画像、比较与持续追踪应用。当前版本使用标准 PostgreSQL 17 自托管数据层，不依赖 Supabase、Firebase 或其他 BaaS。

## 当前能力

- 中文姓名同时检索原名、姓在前拼音和姓在后拼音；候选使用姓名、ORCID、机构、共同论文、共同合作者和研究主题进行保守身份聚类，不同 ORCID 或证据不足的同名者保持分开。
- 被判定为同一学者的拆分 OpenAlex 档案联合获取论文并归到主身份；研究方向由 OpenAlex 细粒度 topics、keywords 与标题高频短语交叉提取，宽泛学科标签降权。
- 联合论文会执行保守的身份一致性审查；只有同时与核心机构、合作者和主题断开的微小论文簇才自动排除，较大冲突簇保留并提示人工确认。
- LangGraph 分页获取 OpenAlex 论文，以 DOI 查询 Crossref 出版元数据，裁决后再生成引用统计、研究方向、兴趣演化、代表论文和合作网络。
- 概览展示本次收录、DOI 数、跨来源核验数、待核实数、来源差异和分页完整性；待核实只表示缺少 DOI 或 Crossref 暂无记录。
- 最终总结经过证据审查，论文依据必须能回溯到裁决后的统一论文集；不通过审查的新画像不会发布。
- 已有画像立即从 PostgreSQL 返回；超过刷新阈值时只向 `refresh_jobs` 幂等排队，由 worker 异步获取 OpenAlex/Crossref 新数据，Web 请求不再同步重复运行完整工作流。
- PostgreSQL 规范化保存学者、机构、论文和署名关系，并保留一份最近成功画像用于质量对比和自动更新。
- 学者搜索使用 PostgreSQL 持久缓存：相同规范化姓名共享结果，冷请求由 `openalex_search_jobs` 合并为一个上游任务，身份指纹单独缓存 30 天；平台 OpenAlex 免费额度不足或上游限流时，可返回旧缓存或已发布真实学者的本地索引结果。
- 研究追踪学者每天更新，近 30 天访问学者每 7 天更新；失败不会覆盖最近一次成功画像。
- 研究追踪记录用户上次看过的论文数、引用数和画像版本；后台发现新增论文、引用或可检测的方向变化后提示，查看最新版后自动清除。
- 追踪面板展示排队、更新中、成功和失败状态，支持立即检查、重试、查看画像和停止追踪；立即检查只排队，不在 Web 请求中同步运行工作流。
- 用户自助注册本地账号并使用密码登录；HttpOnly Cookie 会话保护查询、私有历史和研究追踪。
- OpenAlex API key 由平台管理员写入服务器 `.env`，普通用户注册登录后即可查询，无需理解或配置数据源密钥。搜索、首次画像和后台追踪统一使用服务端 key；个人 key 接口仅作为未来 HTTPS 能力保留，当前界面不展示。
- 搜索与画像生成按账号和来源 IP 限速，避免公开注册用户短时间重复触发外部数据抓取。
- PostgreSQL `LISTEN/NOTIFY` 经 FastAPI SSE 推送版本变化，前端自动加载新版画像。
- Compose 常驻备份服务每天生成 PostgreSQL 自定义格式备份，默认保留 7 天。
- 全量论文游标分页；文章详情、查询历史和研究追踪在桌面端使用自适应双栏，在窄屏端使用可滚动抽屉。
- 导航、搜索区、画像卡片和合作图随浏览器宽高重排；从候选、合作者、历史或研究追踪跳转时同步当前搜索姓名。
- 候选卡明确展示身份置信度、主要/其他关联机构、ORCID（缺失时明确标为未公开）、合并档案数（包括单一档案）和同名区分依据；主搜索与对比搜索都要求用户确认正确身份后才生成画像。主要关联机构按 OpenAlex 最近六年内覆盖的不同发表年份数确定，最近年份和全职业覆盖数只用于同分排序，避免一篇新论文改变顶部身份锚点，也避免旧的长期单位永久压过持续多年的近期单位。
- 学者简介和依据由结构化画像事实按当前界面语言生成，不再复用后端固定语言文本。OpenAlex `affiliations` 和论文 `raw_affiliation_strings` 只作为论文关联证据；它们不会生成任职机构、学院、实验室、职称或培养阶段。任职与教育字段只有在独立任职/教育来源明确支持时才展示，否则整项省略并说明未作推断。
- 画像严格按“学者简介 → 当前主要研究方向 → 研究方向时间线 → 近期研究变化 → 论文/引用/h-index → 代表论文 → 全部论文 → 合作者与网络 → 数据来源/更新时间/置信度/局限”展示。
- 研究方向时间线标签可点击；点击后跳到全部论文，并按该年份和方向筛选数据库中的关联论文，支持一键清除筛选。
- 画像标题链接到当前学者的 OpenAlex 主页；合作网络上方姓名和图节点使用 OpenAlex author ID 直接切换到对应学者画像，合作连线仍用于查看共同论文。
- 支持选择第二位学者进行证据化对比，覆盖研究方向、时间线、代表作、论文与引用、影响力、合作者和近期变化；每项均展示统计依据。
- 画像总览按最近发表年份比较连续两个三年阶段，展示论文数量变化、近期开始活跃及研究比重升降，并用六年矩阵呈现方向演化。
- 流式画像只展示“核验身份、聚合学术成果、分析研究轨迹、核验分析依据”四个用户阶段；前端区分无结果、网络、超时、限流、登录失效和任务失败，并支持重试。OpenAlex 搜索限流会保留 `Retry-After` 并返回 HTTP 429，不会误报为内部 500。切换学者时会取消旧搜索、画像、论文分页和实时换版请求，避免旧响应覆盖新学者。

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
- 自动生成两个随机 PostgreSQL 密码和独立 Fernet 凭据加密 key，配置公网 IP + HTTP、生产安全开关和较小连接池。
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
| `OPENALEX_API_KEY` | OpenAlex 免费账号 key | OpenAlex 免费账号 key |
| `CREDENTIAL_ENCRYPTION_KEY` | 启用个人 key 时填写 | 启用个人 key 时填写 |

密码会被拼入数据库连接 URL，当前模板要求使用足够长的字母、数字、下划线和短横线组合。不要在密码中放 `@`、`:`、`/`、`#`、`%` 等未编码 URL 字符。

保持以下生产安全项不变：

```dotenv
APP_ENV=production
```

本地账号不依赖邮箱、短信或第三方平台。`OPENALEX_API_KEY` 仅保存在服务器 `.env`，Web 与 worker 共用且不得提交到 Git。`CREDENTIAL_ENCRYPTION_KEY` 只在后续通过 HTTPS 开放个人 key 设置时需要，可用 `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` 生成。`LLM_*` 可留空，系统会使用确定性规则分析。

公开部署不能把 OpenAlex 当作真正无限上游。平台管理员在 [OpenAlex API 设置](https://openalex.org/settings/api) 注册免费 key；普通搜索结果缓存 24 小时、空结果缓存 15 分钟、身份指纹缓存 30 天；并发的同名冷请求只允许一个 Web/worker 实际访问上游，其余请求等待同一 PostgreSQL 任务。额度状态按 `openalex:server` 写入 `upstream_rate_limits`，达到保护线后停止新的上游调用，优先返回旧缓存或已发布学者的本地结果；没有可用事实时提示稍后重试，不自动付费。

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

部署完成后，用户可直接在登录弹窗切换到“注册账号”。用户名为 3–64 位，只允许字母、数字、点、下划线和短横线；密码至少 12 位。注册按来源 IP 限制为每小时最多 10 次，并在成功后自动登录。首次登录会打开“API 设置”；用户从 OpenAlex 注册页复制自己的 key，系统验证成功后才允许搜索、生成画像和创建刷新任务。完整 key 不写入浏览器存储，也不会由任何读取接口返回。

生产环境的 key 提交接口强制 HTTPS；公网 IP + HTTP 模式只能用于不填写真实 key 的界面/部署验收。要正式开放 ScholarSearch，必须先绑定域名、启用 Caddy HTTPS 并设置 `COOKIE_SECURE=true`。

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
export OPENALEX_API_KEY='你的开发用 OpenAlex key'
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
- 上游搜索缓存与保护：`openalex_search_cache`、`openalex_identity_cache`、`openalex_search_jobs`、`upstream_rate_limits`
- 用户与会话：`app_users`、`user_api_credentials`、`auth_login_attempts`、`auth_registration_attempts`、`api_rate_limit_events`、`user_sessions`、`user_history`、`favorites`

数据库不暴露给浏览器，授权边界由 FastAPI 强制执行。迁移撤销 `PUBLIC` 默认权限，并只向 `scholar_app` 授予所需数据操作权限。

## API

| 接口 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/health`、`GET /api/ready` | 公开 | 进程与数据库健康检查 |
| `GET /api/search?name=...` | 必须登录、限速 | 搜索候选学者；返回共享缓存/本地索引/实时来源和更新时间 |
| `POST /api/profile` | 必须登录 | 返回最新画像并记录当前用户历史 |
| `POST /api/profile/stream` | 必须登录、限速 | 已有画像立即返回；过期画像异步排队，首次画像输出 NDJSON 进度流 |
| `GET /api/authors/{author_id}/works` | 必须登录 | 全量论文游标分页 |
| `POST /api/auth/register` | 公开、限速 | 创建本地账号并自动登录 |
| `POST /api/auth/login` | 公开、限速 | 用户名密码登录并设置会话 Cookie |
| `GET /api/auth/me` | 可匿名 | 查询当前会话 |
| `POST /api/auth/logout` | 可匿名 | 注销当前会话 |
| `GET /api/settings/openalex` | 必须登录 | 返回当前用户是否已配置、末四位提示和验证时间；不返回 key |
| `PUT /api/settings/openalex` | 必须登录 | 通过 OpenAlex `/rate-limit` 验证后加密保存当前用户 key |
| `DELETE /api/settings/openalex` | 必须登录 | 删除当前用户 key，并终止由其拥有的待处理任务 |
| `GET /api/history` | 必须登录 | 当前用户历史 |
| `GET/POST/DELETE /api/tracking...` | 必须登录 | 当前用户研究追踪、查看基线与停止追踪 |
| `POST /api/tracking/seen` | 必须登录 | 标记当前画像版本已查看 |
| `POST /api/tracking/{author_id}/refresh` | 必须登录、必须已追踪 | 幂等排队立即检查；由 worker 异步执行 |
| `GET /api/profiles/{scholar_id}/events` | 必须登录 | 画像状态 SSE |

旧 `/api/favorites...` 路由暂保留为兼容别名；新前端和新集成统一使用 `/api/tracking...`。数据库表名 `favorites` 属于历史内部实现，本阶段没有修改历史 migration。

## 测试

```bash
npm test
npm run lint
npm run build
npm run test:db
```

`npm test` 使用受控工作流与 in-memory Repository 做快速回归，并覆盖 key 加密、缺 key 错误、接口越权、worker 解密，以及论文关联字段绝不升级为任职/职称/学位声明。`npm run test:db` 启动标准 PostgreSQL，应用 Alembic 迁移，并验证结构、权限、事务发布、分页、会话、跨用户追踪与凭据隔离、搜索缓存持久性与任务去重、重建 Repository 后的数据持久性，以及旧缓存中的错误专业身份字段被剔除、论文关联证据从已保存元数据安全重建。外部 OpenAlex/Crossref 全链路另以手动真实数据验收，数据库测试中的受控工作流输出不冒充外部数据验证。

## 备份

`backup` 服务随 Compose 常驻运行，启动时立即备份，之后默认每 86400 秒备份一次，并删除超过 `BACKUP_RETENTION_DAYS` 的旧文件。手工额外生成一次备份：

```bash
docker compose exec backup backup-postgres
```

备份默认写入服务器项目目录的 `backups/`，也可通过 `.env` 的 `BACKUP_HOST_DIR` 指向挂载的数据盘；周期由 `BACKUP_INTERVAL_SECONDS` 配置。

生产环境还应把备份同步到对象存储或另一台机器，并定期验证 `pg_restore`；同一台 ECS 上的备份无法防御整机或云盘故障。

## 单机容量增长后的拆分

当前版本针对单台 ECS 直接启动优化。多个 Web 与 worker 实例可共享 PostgreSQL 缓存、按用户隔离的额度状态和 `FOR UPDATE SKIP LOCKED` 队列，不需要 Redis。数据量或并发增长后，可把 PostgreSQL 迁到同 VPC 的 RDS PostgreSQL，把数据库 URL 改为 RDS 私网地址，并水平扩展 Web/worker；迁移账号只在发布阶段使用。BYOK 把冷查询成本分配给发起用户，但仍不等于无限：单个用户超过 OpenAlex 免费/付费额度会收到 429；若要覆盖近乎无限的不同姓名冷查询，仍需用户购买额度或另行部署 OpenAlex 数据快照。

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
  App.tsx          # 身份确认、线性画像、登录、研究追踪与自动换版
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
