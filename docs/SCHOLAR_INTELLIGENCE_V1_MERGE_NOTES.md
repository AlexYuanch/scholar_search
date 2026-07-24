# ScholarSearch 学者情报产品 V1 合并说明

## 分支与版本

- [COMPUTED｜高] 源分支：`feat/scholar-intelligence-v1`
- [COMPUTED｜高] 建议目标分支：`codex/postgres-aliyun-deployment`
- [COMPUTED｜高] 功能实现最新 commit：`a15b445ce89530da9fa039f861aaf9e03c189920`
- [COMPUTED｜高] 起始 Ali 基线 commit：`4d37b858ad1d1f564ece947ca87a6ebd9d9029bb`
- [COMPUTED｜高] 建议阶段 tag：`scholar-intelligence-v1`
- [COMPUTED｜高] 本说明生成时未执行 merge，未创建或推送上述建议 tag。

> 本文档自身会作为功能实现 commit 之后的纯文档提交进入源分支。合并时请以
> `origin/feat/scholar-intelligence-v1` 的 HEAD 为准；上面的 commit 是最后一个功能代码提交。

## 本次新功能

- [COMPUTED｜高] 学者搜索保留中文名、英文名和拼音检索；候选卡展示身份置信度、主要/其他关联机构、ORCID、合并档案数及同名区分依据，并要求用户明确确认身份。
- [COMPUTED｜高] 主要关联机构采用最近六年稳定覆盖规则，避免单篇新论文导致机构漂移。
- [COMPUTED｜高] 学者画像按“简介、当前主要研究方向、研究方向时间线、近期研究变化、论文/引用/h-index、代表论文、全部论文、合作网络、数据核验与局限”顺序展示。
- [COMPUTED｜高] 研究方向时间线可以跳转并筛选对应真实论文；学者姓名、合作者姓名及合作图节点可以跳转。
- [COMPUTED｜高] 学者比较覆盖研究方向、研究时间线、代表作、论文与引用、影响力、合作者和近期变化，并逐项显示依据。
- [COMPUTED｜高] “收藏”已统一为“研究追踪”，支持新增论文、新增引用、研究方向变化、最近更新时间、任务状态、立即检查、查看画像和停止追踪。
- [COMPUTED｜高] `POST /api/tracking/{author_id}/refresh` 强制登录与追踪所有权，复用数据库刷新任务和 Worker，包含重复排队保护，不在 Web 请求中同步执行完整工作流。
- [COMPUTED｜高] OpenAlex 搜索缓存、身份指纹、冷请求合并、上游额度状态和任务归属持久化至 PostgreSQL。
- [COMPUTED｜高] 每位用户独立配置 OpenAlex API key；key 验证后加密存储，Web 和 Worker 根据任务请求用户读取。
- [COMPUTED｜高] 用户界面补全四阶段进度、无结果、网络错误、超时、限流、登录失效、Worker 失败、重试和切换学者取消旧请求。
- [COMPUTED｜高] 中英文画像、依据、日期和界面文案完整本地化。

## 测试结果

- [COMPUTED｜高] `npm run lint`：通过。
- [COMPUTED｜高] `npm run build`：通过；保留合作图动态分块 515.49 kB 提示和 Node `module.register()` 弃用提示。
- [COMPUTED｜高] 后端完整 pytest：`108 passed, 15 skipped`；保留两条既有依赖弃用 warning。
- [COMPUTED｜高] `npm run test:db`：`15 passed`。
- [COMPUTED｜高] `docker compose config --quiet`：通过。
- [COMPUTED｜高] 测试完成后工作区干净，本地功能分支与远程同名分支指向同一 commit。

## Migration

[COMPUTED｜高] 本阶段新增两条 migration，未修改任何历史 migration：

1. `20260724_0006_openalex_cache.py`
   - 新增 OpenAlex 搜索缓存、身份缓存、搜索任务和上游额度状态表。
2. `20260724_0007_user_openalex_credentials.py`
   - 新增加密用户凭据表。
   - 为画像刷新任务和 OpenAlex 搜索任务增加请求用户字段。

## 新增环境变量

[COMPUTED｜高] 生产环境新增一个必填变量：

- `CREDENTIAL_ENCRYPTION_KEY`：44 字符 Fernet key；Web 与 Worker 必须使用同一个稳定值。

[COMPUTED｜高] 以下 OpenAlex 缓存与额度参数为可选调优变量，均有默认值：

- `OPENALEX_SEARCH_CACHE_TTL_SECONDS`
- `OPENALEX_EMPTY_SEARCH_CACHE_TTL_SECONDS`
- `OPENALEX_INCOMPLETE_SEARCH_CACHE_TTL_SECONDS`
- `OPENALEX_LOCAL_SEARCH_CACHE_TTL_SECONDS`
- `OPENALEX_IDENTITY_CACHE_TTL_SECONDS`
- `OPENALEX_SEARCH_COALESCE_WAIT_SECONDS`
- `OPENALEX_SEARCH_COALESCE_POLL_SECONDS`
- `OPENALEX_MIN_REMAINING_CREDITS`

[COMPUTED｜高] 服务器不再需要共享 `OPENALEX_API_KEY`；OpenAlex key 由登录用户在页面中配置。

## 合并后重点检查

1. [COMPUTED｜高] 运行 migration，并确认数据库位于 `20260724_0007 (head)`。
2. [COMPUTED｜高] 确认 Web 与 Worker 使用同一个稳定的 `CREDENTIAL_ENCRYPTION_KEY`。
3. [COMPUTED｜高] 确认生产域名启用 HTTPS，并设置 `COOKIE_SECURE=true`。
4. [COMPUTED｜高] 验证 OpenAlex key 的注册入口、验证、保存、替换和删除。
5. [COMPUTED｜高] 验证搜索候选必须经过身份确认，主要机构不会被单篇新论文改变。
6. [COMPUTED｜高] 验证英文模式下画像、依据和日期没有中文残留。
7. [COMPUTED｜高] 验证研究方向时间线能够跳转到对应真实论文。
8. [COMPUTED｜高] 验证学者比较七类指标及依据完整。
9. [COMPUTED｜高] 验证研究追踪能够持久化，Worker 能消费刷新任务，重复刷新不会创建重复任务。
10. [COMPUTED｜高] 使用两个账号验证凭据、追踪记录和刷新任务不能跨用户访问。

## 回滚

- [COMPUTED｜高] 建议旧版本回滚 tag：`scholar-profile-baseline-v1`。
- [COMPUTED｜高] 该 annotated tag 解引用后指向 Ali 起始基线 `4d37b858ad1d1f564ece947ca87a6ebd9d9029bb`。
- [COMMON｜高] 如果数据库已经升级，可以先回滚应用代码并保留新增的兼容性 schema。
- [COMMON｜高] 如果还需要删除新增表和字段，应先备份数据库，并在仍包含 `0006/0007` migration 的代码上执行 `alembic downgrade 20260722_0005`，再切换旧 tag；该操作会删除 OpenAlex 缓存和用户保存的 OpenAlex 凭据。
