# 技术架构说明

## 总体结构

```mermaid
flowchart LR
  CLIENT["Browser"] -->|"HTTP / HTTPS"| CADDY["Caddy gateway"]
  CADDY --> NGINX["React static + Nginx"]
  NGINX -->|"/api 同源代理"| API["FastAPI Web"]
  API -->|"SQLAlchemy + psycopg"| PG["PostgreSQL 17"]
  API -->|"冷启动"| WF["LangGraph"]
  WF --> OA["OpenAlex"]
  MAINT["Worker 每小时维护"] --> JOB["refresh_jobs"]
  WORKER["Refresh worker"] -->|"SKIP LOCKED"| JOB
  WORKER --> WF
  WORKER --> PG
  PG -->|"NOTIFY profile_status"| API
  API -->|"SSE profile event"| UI
  API -->|"SMTP Magic Link"| MAIL["邮件服务"]
```

| 层 | 技术 | 责任 |
|----|------|------|
| 前端 | Vite + React + TypeScript | 搜索、画像、登录、历史/收藏、SSE 与论文分页 |
| API | FastAPI | 公开查询、Cookie 会话、私有接口、NDJSON 与 SSE |
| 工作流 | LangGraph | OpenAlex 获取、分析、图谱和载荷格式化 |
| Repository | SQLAlchemy 2 + psycopg | 事务化事实数据、画像、用户、状态和队列 |
| 数据库 | 标准 PostgreSQL 17 | 数据、约束、索引、通知和并发队列 |
| Worker | 独立 Python 进程 | 定时入队、刷新、质量检查、重试和清理 |
| 公网入口 | Caddy + Nginx | 自动 HTTPS、静态资源、同源 API 代理和日志 |

## 数据模型

| 表 | 作用与关键约束 |
|----|----------------|
| `scholars` | 学者实体；`unique(source, source_author_id)`，不按姓名合并 |
| `scholar_aliases` | 中文、拼音和英文署名 |
| `institutions` | 机构实体；`unique(source, source_institution_id)` |
| `scholar_institutions` | 学者—机构多对多 |
| `works` | 全部论文；`unique(source, source_work_id)` |
| `authorships` | 论文—作者事实、顺序和原始署名 |
| `scholar_profiles` | 每位学者一份最新成功 JSONB、warnings、工作流版本和数据指纹 |
| `profile_status` | 轻量状态、版本和更新时间 |
| `refresh_jobs` | 任务状态、次数、退避、原因和错误 |
| `app_users` | 应用用户；规范化邮箱唯一 |
| `auth_login_tokens` | Magic Link 摘要、过期时间、使用时间和请求信息 |
| `user_sessions` | 不透明会话 token 摘要、过期和撤销时间 |
| `user_history` | 用户私有访问历史，同一用户/学者合并次数 |
| `favorites` | 用户私有收藏，复合主键去重 |

`backend/migrations/*.py` 是唯一结构来源。Alembic 使用数据库所有者账号，运行时使用固定受限角色 `scholar_app`。数据库仅位于服务端私网，不向浏览器开放；所有用户所有权检查由 FastAPI 完成。

## 画像读写流程

### 冷启动

1. API 无缓存时运行 LangGraph，通过 NDJSON 输出进度。
2. OpenAlex 作者详情和论文游标分页必须完整结束。
3. 质量检查比较 `works_count`、本次数量和上一成功数量。
4. 同一事务写入学者、机构、论文、authorship、最新画像和数据指纹。
5. `profile_status.version + 1` 并设为 `ready`；触发器发送轻量 PostgreSQL 通知。

### 缓存与后台更新

- 最新画像未超过 7 天时直接返回。
- 已过期时仍立即返回旧画像，并原子去重插入 `refresh_jobs`。
- 收藏学者使用 24 小时阈值；最近 30 天访问者使用 7 天阈值。
- 其他学者再次访问过期画像时才入队。
- 只有完整抓取成功才允许删除已消失的中心作者 authorship。

### Worker

Worker 使用 `FOR UPDATE SKIP LOCKED` 原子领取任务，支持多实例并发。失败按指数退避，最多 3 次；未通过质量门槛不会进入发布事务。每小时维护使用 PostgreSQL advisory lock，避免多 worker 重复调度，并清理过期 token、session 和 30 天前任务日志。维护任务还会回收锁定超过 30 分钟的失联 worker 任务：未满 3 次则重新排队，否则标记失败，同时同步画像状态。

## 身份认证

1. `POST /api/auth/magic-link` 规范化邮箱、限速并生成高熵随机 token。
2. API 先校验 `PUBLIC_APP_URL` 是无路径的 HTTP(S) origin；生产环境拒绝空值、`localhost` 和回环地址。
3. 数据库只保存 token 的 SHA-256 摘要；SMTP 邮件包含 `PUBLIC_APP_URL/api/auth/callback`。
4. 回调在单次事务中锁定并消费 token，创建或读取用户，然后创建会话。
5. 浏览器收到 `HttpOnly`、`SameSite=Lax` Cookie；生产环境同时启用 `Secure`。
6. 私有接口从会话摘要解析用户，并在 Repository 查询中限制 `user_id`。
7. 退出时服务端撤销会话并清除 Cookie。

开发环境只有在 `APP_ENV=development`、`AUTH_DEV_RETURN_MAGIC_LINK=true` 且 `PUBLIC_APP_URL` 指向本机回环地址时，才会在 UI 显示测试链接；生产环境禁止启用。公网请求遇到回环地址配置会返回 503，不创建或发送不可用 token。建议前后端同域部署，以简化 Cookie 和 CSRF 边界。

## 实时更新

`profile_status` 的 INSERT/UPDATE 触发 `pg_notify('profile_status', ...)`。FastAPI 内部持有一个共享 `LISTEN` 连接，把事件分发到订阅该学者的 SSE 客户端。前端仅在 `status=ready` 且新版本大于当前版本时重新请求画像；大型 JSONB 不进入通知载荷。

SSE 连接断开不会影响画像生成，浏览器重连后会先读取当前 `profile_status`，避免遗漏版本变化。

## 安全与权限

- PostgreSQL 不对公网开放；API 是唯一浏览器数据入口。
- 迁移撤销 `PUBLIC` 对 schema、表和 sequence 的默认权限。
- `scholar_app` 只用于 Web/worker，不能建表；迁移账号不提供给运行时。
- 登录和会话表使用摘要、过期时间、撤销标记及索引；Magic Link 请求按邮箱和 IP 限速。
- CORS 仅允许配置的前端域名，Cookie 请求启用 credentials。
- SMTP、数据库和 LLM 密钥全部为服务端配置，不进入 Vite bundle。

## 部署模型

仓库提供两种兼容部署方式：

1. **单机 Compose（当前交付）**：Caddy、Nginx 前端、Web、worker、迁移和 PostgreSQL 运行在一台 ECS。公网只暴露 Caddy 的 80/443，数据库端口仅绑定回环地址。Compose 的 Auth 默认值按生产安全模式关闭开发链接且不回退到 `localhost`；`deploy/bootstrap-aliyun.sh` 可为 Ubuntu 24.04 ECS 安装 Docker、配置可选 ACR 加速、补充 Swap、生成首次配置与定时备份；`deploy/deploy.sh` 负责后续每次发布的配置校验、回环地址拒绝、构建和健康等待。
2. **ECS + RDS（容量增长后）**：Caddy/Nginx、Web、worker 部署在 ECS，PostgreSQL 使用同 VPC 的 RDS。部署流水线先以迁移账号执行 Alembic，再启动受限账号的运行时服务。

无论采用哪种方式，公网只暴露 80/443；生产必须使用 HTTPS、安全 Cookie、正式 SMTP、独立备份和恢复演练。
