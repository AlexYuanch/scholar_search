# ScholarSearch 科研助手

ScholarSearch 是一个面向教师、学生和科研团队的学者情报平台。它不只检索论文，而是围绕**作者、论文、机构、研究方向、合作关系和时间线**生成可核验、可比较、可持续追踪的学者画像。

## 平台功能

| 功能 | 可以解决的问题 |
|---|---|
| 学者画像 | 快速了解研究方向、代表成果、影响指标和近期变化 |
| 学术成果 | 按年份、方向和引用查看论文，并回到公开来源核验 |
| 合作关系 | 查看核心合作者、共同论文和可交互合作网络 |
| 研究脉络 | 理解研究阶段、方向迁移以及问题—方法—贡献演进 |
| 同行与机构 | 发现值得关注的同行、潜在合作对象、选题重合和相关机构 |
| 对比与追踪 | 对比两位学者，保存查询历史，并持续跟踪最新研究进展 |

## 页面展示

### 平台首页

![ScholarSearch 平台首页](docs/images/platform-home.jpg)

### 学者画像

![ScholarSearch 学者画像查询结果](docs/images/scholar-profile-result.jpg)

## 工作流设计

![ScholarSearch 学者画像工作流](docs/images/scholar-workflow.svg)

一次画像生成主要经过四个阶段：

1. **身份与数据核验**：联合 OpenAlex、公开 ORCID、Crossref 和 DBLP，按 DOI/题名年份核对并保守处理同名学者；如果作者档案缺失，系统还会从精确匹配论文的署名、机构、DOI 与合作者生成待确认候选。Google Scholar 预留 SerpApi 可选接口，不配置时自动跳过。
2. **Agent 学术分析**：协调 Agent 根据当前证据动态拆分代表作、合作、机构与研究延续性任务，并行交给专业 Worker 分析。
3. **关系与图谱生成**：构建合作网络、研究脉络，并发现同行、合作对象和相关机构。
4. **证据审查与发布**：审查 Agent 将问题返回总结 Agent 修改并再次审核；达到循环上限后仍由确定性门禁决定发布，失败时保留最近一次成功画像。

画像由后台 Worker 持续执行。查询进入队列后，页面可正常切换；任务完成时通过 SSE 通知前端并加载最新结果。

## 设计原则

- **准确优先**：身份冲突时宁可提示画像可能不完整，也不混入疑似他人的论文。
- **结论可追溯**：方向、变化和合作判断尽量关联到真实论文、作者和来源记录。
- **模型不替代证据**：LongCat Agent 优先负责理解与归纳，失败时自动回退 DeepSeek，确定性规则负责校验和发布门禁。

## 技术架构

| 层级 | 技术 |
|---|---|
| 前端 | React 19、Vite、TypeScript、Tailwind CSS |
| API | FastAPI、SQLAlchemy、Server-Sent Events |
| 工作流 | LangGraph、多 Agent 路由、独立 Worker |
| 数据 | PostgreSQL、OpenAlex、Crossref、公开 ORCID、DBLP；可选 Google Scholar |
| 模型 | LongCat-2.0 优先、DeepSeek 回退 |
| 部署 | Docker Compose、Caddy、Nginx、Alembic |

## 快速启动

```bash
cp .env.example .env
# 按注释填写数据库密码、OpenAlex 和可选 LLM 配置
./deploy/deploy.sh
```

启动后访问 `.env` 中的 `PUBLIC_APP_URL`。普通用户可自行注册；用户名支持中英文、大小写字母和内部空格，密码至少 8 位。

本地开发：

```bash
npm install
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
npm run db:up
npm run db:migrate
cd backend && .venv/bin/python -m uvicorn main:app --reload --port 5800
# 另一个终端
npm run dev
```

## 测试

```bash
npm run test
npm run lint
npm run build
npm run test:db
```

需要定位线上工作流耗时或模型回退时，可在已配置生产同等环境变量的后端容器中运行脱敏追踪：

```bash
python trace_workflow.py \
  --author-id A5100700361 \
  --output /tmp/workflow-trace.json
```

追踪只记录节点状态摘要、数量、模型和耗时，不保存密钥、完整提示词或模型原始响应。示例见 [Kaiming He 线上工作流透明测试](docs/WORKFLOW_TRACE_KAIMING_HE_20260730.md)。

更完整的产品边界、数据模型和部署说明见：

- [产品说明](docs/PRODUCT.md)
- [系统架构](docs/ARCHITECTURE.md)
- [协作交接](session-handoff.md)
