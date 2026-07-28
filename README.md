# ScholarSearch 科研助手

面向教师、学生和科研团队的学者研究助手：把分散的论文、作者、机构、研究方向、合作关系和时间线整理成可理解、可比较、可持续追踪的研究画像。当前版本使用 OpenAlex、Crossref、公开 ORCID 与 PostgreSQL 17 自托管数据层。

## 当前能力

- 中文姓名同时检索原名、姓在前拼音和姓在后拼音；候选使用姓名、ORCID、机构、共同论文、共同合作者和研究主题进行保守身份聚类，不同 ORCID 或证据不足的同名者保持分开。
- 被判定为同一学者的拆分 OpenAlex 档案联合获取论文并归到主身份；研究方向由 OpenAlex 细粒度 topics、keywords 与标题高频短语交叉提取，宽泛学科标签降权。
- 联合论文执行准确优先的身份净化：公开 ORCID 论文作为强锚点，Crossref 作者 ORCID、OpenAlex 机构和稳定合作者用于扩展主论文簇；主题相似不能单独证明同一身份，大型无连接冲突簇也会排除并提示画像可能不完整。
- LangGraph 分页获取 OpenAlex 论文，以 DOI 查询 Crossref 出版元数据，并读取无需密钥的 ORCID 公共论文记录；来源裁决和身份净化后再生成引用统计、研究方向、兴趣演化、代表论文和合作网络。
- DeepSeek 多 Agent 链路由“分析规划、研究方向、研究变化、学者总结、证据复核”五个 Agent 组成；Flash 默认处理常规任务，规划判定复杂或输出校验失败时自动升级 Pro。方向 Agent 拒绝论文标题式标签；变化 Agent 必须解释研究问题、方法或应用变化并引用真实论文 ID，不能只复述数量。
- 概览以简洁“数据说明”展示当前收录、更新时间、来源和可能遗漏；DOI、Crossref、冲突与分页细节折叠到辅助说明。
- 最终总结经过证据审查，论文依据必须能回溯到裁决后的统一论文集；不通过审查的新画像不会发布。
- 已有画像立即从 PostgreSQL 返回；超过刷新阈值或用户点击“更新资料”时，只向 `refresh_jobs` 幂等排队，由 worker 异步重跑 OpenAlex、ORCID、Crossref、身份裁决和全部 Agent，旧画像在新版本发布前继续可用。
- PostgreSQL 规范化保存学者、机构、论文和署名关系，并保留一份最近成功画像用于质量对比和自动更新。
- 学者搜索使用 PostgreSQL 持久缓存：相同规范化姓名共享结果，冷请求由 `openalex_search_jobs` 合并为一个上游任务，身份指纹单独缓存 30 天；平台 OpenAlex 免费额度不足或上游限流时，可返回旧缓存或已发布真实学者的本地索引结果。
- 研究追踪学者每天更新画像，并每 7 天更新一次领域候选；近 30 天访问学者每 7 天更新画像。失败不会覆盖最近一次成功画像或领域样本。
- 研究追踪记录用户上次看过的论文数、引用数和画像版本；后台发现新增论文、引用或可检测的方向变化后提示，查看最新版后自动清除。
- 追踪面板展示排队、更新中、成功和失败状态，支持立即检查、重试、查看画像和停止追踪；立即检查只排队，不在 Web 请求中同步运行工作流。
- 匿名访问首先看到简洁产品首页，不会自动弹出登录框；用户提交搜索时才要求登录或注册，成功后自动继续刚才的搜索。HttpOnly Cookie 会话保护查询、私有历史和研究追踪。
- OpenAlex API key 由平台管理员写入服务器 `.env`，普通用户注册登录后即可查询，无需理解或配置数据源密钥。搜索、首次画像和后台追踪统一使用服务端 key；个人 key 接口仅作为未来 HTTPS 能力保留，当前界面不展示。
- 搜索与画像生成按账号和来源 IP 限速，避免公开注册用户短时间重复触发外部数据抓取。
- PostgreSQL `LISTEN/NOTIFY` 经 FastAPI SSE 推送排队、更新、失败和版本变化，前端同步按钮状态并在成功后自动加载新版画像。
- Compose 常驻备份服务每天生成 PostgreSQL 自定义格式备份，默认保留 7 天。
- 全量论文游标分页；文章详情、查询历史和研究追踪在桌面端使用自适应双栏，在窄屏端使用可滚动抽屉。
- 导航、搜索区、画像卡片和合作图随浏览器宽高重排；从候选、合作者、历史或研究追踪跳转时同步当前搜索姓名。
- 候选卡只展示机构、ORCID、研究方向、论文、引用、h-index 和最近发表年份，支持按机构、方向、ORCID 与学术指标筛选排序；内部身份分组、档案数量、归并信号和指纹不进入用户主界面。主搜索与对比搜索都要求用户选择目标学者后才生成画像。
- 学者简介和依据由结构化画像事实按当前界面语言生成，不再复用后端固定语言文本。OpenAlex `affiliations` 和论文 `raw_affiliation_strings` 继续作为内部消歧与核验证据，但概览不再重复展示机构历史和署名原文。任职与教育字段只有在独立来源明确支持时才展示。
- 画像按“研究画像 → 研究方向与核心指标 → 近期研究变化 → 研究方向时间线 → 学术成果 → 合作关系 → 研究脉络 → 数据说明”组织，优先回答学术用户关心的问题。
- 研究方向时间线标签可点击；切换到论文栏完成挂载后再滚动到全部论文，并按该年份和精确方向筛选。研究图谱同步以 JSON 合并方式保留 `analysis_topics`，不会再把筛选依据覆盖为 0 篇。
- 画像保留“学者概览 / 学术成果 / 合作关系 / 研究脉络 / 学术视野”五栏切换；标题链接到当前学者的 OpenAlex 主页，合作姓名和图节点先打开详情侧栏，只有用户点击“查询画像”才切换学者，合作连线用于查看共同论文。
- 支持选择第二位学者进行证据化对比，覆盖研究方向、时间线、代表作、论文与引用、影响力、合作者和近期变化；每项均展示统计依据。
- “学术视野”只回答应该关注谁、合作谁、哪些研究可能重合以及关注哪些机构。它按长期与近四年主题自动发现最多 60 位候选，先补全 8 位、再按 4 位一批进入既有动态研究图谱，最多分析 20 位；候选发现不直接决定推荐，LLM 不参与评分。
- 学术视野用一个去重列表呈现学习参考、同行动态、合作人选和选题重合，可直接查看画像、追踪或预选到现有学者对比；只有实际产生可靠结果的用途才显示筛选入口，避免空分类占据页面。“全部”视图按每位学者证据最强的角色展示，推荐语引用具体共同方向、代表成果和最有区分度的图谱证据，不再只替换姓名套用统一理由。稳定合作者留在合作关系页，代表作移入学术成果，方向延续和选题特征留在研究脉络。“相关机构”合并展示真实机构的主题活动、合著记录和已分析学者，当前学者的机构置顶，机构卡不重复罗列相同发现主题；不再使用容易误导的“近期活跃 / 合作线索”分类，不推断实验室团队，不输出机构质量排名。页面不再展示底部通用计算说明，单条推荐依据和机构数据范围仍保留。
- 学术视野的时间归一化分位只对每个主题池排序一次，代表作延续统计使用后缀位集去重；同一图谱快照的分析和比较由进程内有界缓存复用。缓存最多保留 32 项、5 分钟过期，并在任一研究图谱或当前领域发现状态变化时自动失效；并发的相同请求只执行一次计算。
- 画像总览按最近发表年份比较连续两个三年阶段，展示论文数量变化、近期开始活跃及研究比重升降，并用六年矩阵呈现方向演化。
- 动态研究图谱以单个学者为范围，增量保存规范论文、作者/机构/主题、合作、引用与时间线关系；每条关系带来源、更新时间和置信度，数据库唯一键阻止重复关系。
- “研究图谱”栏不重复论文栏或合作网络，而是提供研究阶段、相邻阶段方向迁移信号、主题—阶段强度矩阵、基于摘要的问题—方法—贡献演进和学者本人论文间的内部引用主线；阶段、迁移、矩阵和摘要证据统一按最新到最早展示。方向标签具有明确的点击、键盘焦点和可访问名称，并读取真实主题详情 API。
- 图谱首次构建走单学者全量 OpenAlex，之后按最近成功时间减 30 天使用免费计划支持的 `from_publication_date` 重叠增量；新画像发布时间晚于图谱成功时间时也判定图谱待更新。只有用户打开“研究图谱”栏时才按需排队，普通画像访问不会提前消耗共享额度；首屏显示纳入论文、覆盖年份、摘要证据、内部引用和身份核验风险，完整重建入口只在上一轮失败后出现。
- 首个图谱批次成功前，读取接口不会把画像表中已有论文或机构冒充为图谱结果；后续批次失败时继续展示最近成功版本。任务按学者去重、最多尝试 3 次，30 分钟 worker lease 超时后重排或失败，最终失败只能由新的人工/访问请求重新排队。
- 有 OpenAlex 摘要的论文保存抽取式问题、方法、贡献、方向关系和原句证据，并明确标为“基于摘要”；摘要缺失时这些字段保持空值，不生成替代内容。
- 流式画像只展示“核验身份、聚合学术成果、分析研究轨迹、核验分析依据”四个用户阶段；前端区分无结果、网络、超时、限流、登录失效和任务失败，并支持重试。OpenAlex 搜索限流会保留 `Retry-After` 并返回 HTTP 429，不会误报为内部 500。切换学者时会取消旧搜索、画像、论文分页和实时换版请求，避免旧响应覆盖新学者。

## 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | Vite、React 19、TypeScript、Tailwind CSS v4 |
| UI / 图谱 | Radix primitives、lucide-react、vis-network |
| API | FastAPI、Uvicorn、SQLAlchemy 2、psycopg |
| 工作流 | LangGraph |
| 数据源 / 模型 | OpenAlex、Crossref；DeepSeek V4 或其他 OpenAI 兼容 LLM |
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
| `LLM_API_KEY` | DeepSeek API key | DeepSeek API key |
| `LLM_BASE_URL` | `https://api.deepseek.com` | `https://api.deepseek.com` |
| `LLM_FAST_MODEL` | `deepseek-v4-flash` | `deepseek-v4-flash` |
| `LLM_STRONG_MODEL` | `deepseek-v4-pro` | `deepseek-v4-pro` |

密码会被拼入数据库连接 URL，当前模板要求使用足够长的字母、数字、下划线和短横线组合。不要在密码中放 `@`、`:`、`/`、`#`、`%` 等未编码 URL 字符。

保持以下生产安全项不变：

```dotenv
APP_ENV=production
```

本地账号不依赖邮箱、短信或第三方平台。`OPENALEX_API_KEY` 仅保存在服务器 `.env`，Web 与 worker 共用且不得提交到 Git。`CREDENTIAL_ENCRYPTION_KEY` 只在后续通过 HTTPS 开放个人 key 设置时需要，可用 `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` 生成。`LLM_API_KEY` 留空时所有 Agent 安全降级到可复算规则；启用时必须同时填写 Base URL、Flash/Pro 模型、路由模式和 Pro 每日调用上限。模型 key、提示词和原始响应不进入前端或数据库。

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

部署完成后，匿名用户先进入产品首页；点击右上角登录，或提交搜索后在弹窗中登录/注册。用户名为 3–64 位，只允许字母、数字、点、下划线和短横线；密码至少 12 位。注册按来源 IP 限制为每小时最多 10 次，成功后自动登录并继续待执行搜索。普通用户不需要配置 OpenAlex key，平台统一使用服务器 `.env` 中的 key。

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

打开 <http://localhost>，可先匿名浏览首页；提交搜索后在弹窗中注册账号。

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

- 学术事实：`scholars`、`scholar_aliases`、`institutions`、`scholar_institutions`、`works`、`work_external_ids`、`authorships`
- 动态图谱：`research_topics`、`work_topics`、`scholar_topics`、`collaborations`、`collaboration_works`、`work_citations`、`paper_insights`、`timeline_events`
- 图谱同步：`research_graph_sync_state`、`research_graph_refresh_jobs`
- 领域发现：`field_discovery_state`、`field_discovery_candidates`、`field_discovery_institutions`、`field_discovery_jobs`；候选与机构外键复用既有图谱实体
- 画像与任务：`scholar_profiles`、`profile_status`、`refresh_jobs`
- 上游搜索缓存与保护：`openalex_search_cache`、`openalex_identity_cache`、`openalex_search_jobs`、`upstream_rate_limits`
- 用户与会话：`app_users`、`user_api_credentials`、`auth_login_attempts`、`auth_registration_attempts`、`api_rate_limit_events`、`user_sessions`、`user_history`、`favorites`、`scholar_intelligence_feedback`

数据库不暴露给浏览器，授权边界由 FastAPI 强制执行。迁移撤销 `PUBLIC` 默认权限，并只向 `scholar_app` 授予所需数据操作权限。

## API

| 接口 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/health`、`GET /api/ready` | 公开 | 进程与数据库健康检查 |
| `GET /api/search?name=...` | 必须登录、限速 | 搜索候选学者；返回共享缓存/本地索引/实时来源和更新时间 |
| `POST /api/profile` | 必须登录 | 返回最新画像并记录当前用户历史 |
| `POST /api/profile/stream` | 必须登录、限速 | 已有画像立即返回；过期画像异步排队，首次画像输出 NDJSON 进度流 |
| `POST /api/authors/{author_id}/profile/refresh` | 必须登录、限速 | 幂等排队完整画像工作流；旧画像保持可用，SSE 推送任务状态和新版本 |
| `GET /api/authors/{author_id}/works` | 必须登录 | 全量论文游标分页 |
| `GET /api/authors/{author_id}/research-graph` | 必须登录 | 单学者研究阶段、方向迁移、主题矩阵、摘要演进与引用脉络 |
| `POST /api/authors/{author_id}/research-graph/refresh` | 必须登录、限速 | 仅在缺失、过期或失败时幂等排队；`force_rebuild=true` 只用于失败后的单学者重建 |
| `GET /api/research-graph/objects/{type}/{id}` | 必须登录 | 返回作者、论文、机构或主题详情 |
| `GET /api/authors/{author_id}/intelligence` | 必须登录 | 返回兼容分析字段、四类确定性推荐、领域发现覆盖状态和相关机构；打开学术视野时按需排队 |
| `POST /api/authors/{author_id}/intelligence/discover` | 必须登录、限速 | 幂等请求领域候选发现与渐进补图；返回发现、分析、排队、失败及目标数量 |
| `GET /api/intelligence/field` | 必须登录 | 兼容返回目标学者的领域参考列表 |
| `POST /api/intelligence/compare` | 必须登录 | 按同一确定性口径比较学者、兼容团队模式或机构主题活动 |
| `POST /api/intelligence/feedback` | 必须登录 | 按用户记录“有帮助/不准确”，不改变评分或学术事实 |
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

`npm test` 使用受控工作流与 in-memory Repository 做快速回归，并覆盖 ORCID 身份锚定、无 ORCID 降级、大型冲突簇排除、标题式方向拒绝、Trajectory 论文证据门禁、接口越权、worker 行为，以及学术视野的数据不足、新学者、跨领域高引用、同名、弱贡献角色、短期方向变化、稳定合作者排除、合作/竞争区分、渐进 8+4 补图、排名稳定性、缓存隔离/失效/容量/并发复用。`npm run test:db` 启动标准 PostgreSQL，应用 Alembic 迁移，并验证结构、权限、事务发布、论文筛选在研究图谱同步前后保持一致、会话、跨用户追踪、搜索缓存、图谱持久性、领域发现关系复用、快照版本失效和确定性分析。外部 OpenAlex/Crossref/ORCID/DeepSeek 全链路另以真实数据验收。

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
  research_graph.py # OpenAlex 增量批次与摘要证据抽取
  research_graph_repository.py # 图谱关系、队列与读取投影
  migrations/      # Alembic 迁移
src/
  App.tsx          # 身份确认、四栏画像、登录、研究追踪与自动换版
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
