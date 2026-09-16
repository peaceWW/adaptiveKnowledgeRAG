# Adaptive Knowledge RAG

策略驱动的企业知识平台：按知识类型选择抽取、索引与检索策略，而不是「文档切片 → 向量库 → 问答」的单一流水线。

当前实现覆盖知识入库、人工审核、自适应检索、图谱与评估。无 Docker 时自动降级（SQLite、内存向量、本地文件），可在单机直接跑通。

## 功能一览

| 模块 | 说明 |
| --- | --- |
| 工作台 | 知识库健康度、处理任务、待审核数量 |
| 智能问答 | Adaptive Chat：意图识别、Retrieval Planner、混合检索、完整性检查、引用溯源 |
| 知识库 | 多知识库、领域、策略绑定、ACL |
| 文档管理 | 上传 → AI 分析 → 策略确认 → 知识抽取（六步向导） |
| 知识审核 | 原文对照编辑知识单元，通过 / 拒绝 / 下一条 |
| 知识目录 | 本体/目录思维导图，叶子节点查看原文引用 |
| 策略中心 | Knowledge Strategy、40+ Knowledge Role、预览与自定义 Role |
| 检索中心 | 按文档管理关键字/元数据索引（增改删/重建/清空）+ Retrieval Planner |
| 知识图谱 | 概念-知识单元关系浏览 |
| 评估中心 | 检索/答案评估、策略对比、Golden Dataset |
| 模型中心 | Prompt / Skill 模板 |
| 系统管理 | 用户、ACL、运行配置 |

演示账号（首次启动自动 seed）：`alice` 普通用户、`bob` 知识专家、`carol` 算法工程师、`admin` 管理员。页面右上角可切换。

## 架构

```
文档上传 ─► 解析/分类 ─► Knowledge Strategy ─► 知识单元抽取
                                              │
                                              ▼
                              人工审核 ─► 发布 ─► 向量 / 关键字 / 图谱索引
                                              │
用户提问 ─► Query Understanding ─► Retrieval Planner
       ─► 向量召回 + 关键字/元数据 + 图扩展 ─► RRF / Rerank
       ─► Completeness 检查（可二次检索）─► 带引用答案
```

技术栈：

- 后端：Python 3.12+ / FastAPI / LangGraph / SQLAlchemy
- 前端：Vue 3 / Vite / Ant Design Vue
- 可选基础设施：Postgres、Redis、Qdrant、MinIO、Elasticsearch、Neo4j（见 `docker-compose.yml`）
- 模型：OpenAI 兼容网关（推荐 DashScope 接入千问）；未配置 `MODEL_API_KEY` 时走启发式，不阻塞本地演示

## 目录结构

```text
AdaptiveKnowledgeRAG/
├── backend/                 # FastAPI 应用
│   ├── app/
│   │   ├── api/             # HTTP 接口（kb / documents / chat / retrieval …）
│   │   ├── domain/          # 知识类型、Strategy、Ontology、Role
│   │   ├── ingestion/       # 解析 → 分类 → 抽取 → 索引
│   │   ├── retrieval/       # Planner、融合、查询工作流、文档索引
│   │   ├── completeness/    # 答案完整性检查
│   │   ├── model_gateway/   # LLM / Embedding / Rerank
│   │   ├── storage/         # DB、Qdrant、ES、MinIO、Neo4j
│   │   ├── observability/   # 指标与追踪
│   │   ├── seed.py          # 空库初始化
│   │   └── main.py
│   ├── fixtures/            # 示例芯片文档
│   ├── prompts/             # Prompt 模板 YAML
│   ├── tests/
│   └── workers/
├── frontend/                # Vue 3 控制台
│   └── src/views/           # 各业务页面
├── docs/                    # 架构方案、页面原型
├── scripts/                 # 跨平台部署与启停
│   ├── akrag.ps1            # Windows 主脚本
│   ├── akrag.sh             # Linux/macOS 主脚本
│   ├── windows/             # deploy/start/stop/…
│   └── linux/
├── docker-compose.yml       # 可选中间件
├── pyproject.toml
├── .env.example
├── deploy.bat / deploy.sh
├── start.bat  / start.sh
├── stop.bat   / stop.sh
├── restart.bat / restart.sh
└── status.bat / status.sh
```

后端接口前缀为 `/api`，文档见启动后的 `http://127.0.0.1:8000/docs`。前端开发服务器把 `/api` 代理到后端。

## 环境要求

- Python **3.12+** 与 [uv](https://docs.astral.sh/uv/)
- Node.js **18+**（含 npm）
- 可选：Docker / Docker Compose（完整中间件）
- 可选：`MODEL_API_KEY`（真实 LLM；留空亦可运行。千问示例见下方配置）

## 一键部署与启停

仓库根目录即可执行。首次请先 **deploy**，再 **start**。

### Windows

```bat
deploy.bat
start.bat
status.bat
stop.bat
```

带基础设施（需 Docker）：

```bat
deploy.bat -WithInfra
start.bat -WithInfra
stop.bat -All
```

等价 PowerShell：

```powershell
.\scripts\akrag.ps1 deploy
.\scripts\akrag.ps1 start
.\scripts\akrag.ps1 status
.\scripts\akrag.ps1 stop
.\scripts\akrag.ps1 logs
.\scripts\akrag.ps1 infra-up
.\scripts\akrag.ps1 infra-down
```

也可双击 `scripts\windows\start.bat` 等脚本。

### Linux / macOS

```bash
chmod +x deploy.sh start.sh stop.sh restart.sh status.sh scripts/akrag.sh scripts/linux/*.sh
./deploy.sh
./start.sh
./status.sh
./stop.sh
```

带基础设施：

```bash
./deploy.sh --with-infra
./start.sh --with-infra
./stop.sh --all
```

主脚本：

```bash
./scripts/akrag.sh deploy|start|stop|restart|status|infra-up|infra-down|logs
```

### 脚本命令说明

| 命令 | 作用 |
| --- | --- |
| `deploy` | 创建 `.env`、`uv sync`、`npm install`；无 Docker 时数据库改为 SQLite |
| `deploy --with-infra` / `-WithInfra` | 上述步骤 + `docker compose up -d` |
| `start` | 后台启动后端 `:8000` 与前端 `:5173` |
| `stop` | 停止前后端（按 PID 与端口） |
| `stop --all` / `-All` | 同时 `docker compose down` |
| `restart` | 停止后再次启动 |
| `status` | 查看端口与 Docker 状态 |
| `infra-up` / `infra-down` | 只管理中间件 |
| `logs` | 打印 `.run/backend.log`、`.run/frontend.log` 尾部 |

进程 PID 与日志在项目根目录 `.run/`。

启动成功后：

- 控制台：http://localhost:5173/
- 后端健康检查：http://127.0.0.1:8000/health
- OpenAPI：http://127.0.0.1:8000/docs

## 手动启动（不使用脚本）

```bash
# 配置
cp .env.example .env
# 无 Docker 时建议改为：
# DATABASE_URL=sqlite+aiosqlite:///./data/akrag.db

uv sync
cd frontend && npm install && cd ..

# 可选中间件
docker compose up -d

# 后端（在仓库根目录执行，以便读取 .env 与 data/）
uv run uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# 前端
cd frontend && npm run dev
```

## 降级行为

| 依赖 | 不可用时 |
| --- | --- |
| Postgres | 自动改用 `data/akrag.db`（SQLite） |
| Qdrant | 进程内向量 |
| MinIO | 磁盘 `data/storage`（MinIO 可用时再多写一份） |
| Elasticsearch | 本地关键字索引 + SQL 回退 |
| Neo4j | 图谱能力降级 |
| `MODEL_API_KEY` | 启发式分类/抽取/问答 |

## 配置

复制 `.env.example` 为 `.env`。常用项：

```env
DATABASE_URL=postgresql+asyncpg://akrag:akrag@localhost:5432/akrag
# 或 sqlite+aiosqlite:///./data/akrag.db

# 推荐：DashScope compatible-mode 接入千问（走现有 OpenAI 协议网关，无需另装 SDK）
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_API_KEY=
MODEL_LLM=qwen-plus
MODEL_VISION=qwen-vl-plus
MODEL_EMBEDDING=text-embedding-v3
EMBEDDING_DIM=1024

QDRANT_URL=http://localhost:6333
ELASTICSEARCH_URL=http://localhost:9200
NEO4J_URI=bolt://localhost:7687
MINIO_ENDPOINT=localhost:9000
STORAGE_DIR=data/storage
```

`EMBEDDING_DIM` 必须与 embedding 模型输出维一致（千问 `text-embedding-v3` 默认 1024）。换维后需要重建 Qdrant collection（删除已有 `knowledge_units` 或更换 `QDRANT_COLLECTION`），否则向量写入会失败。千问 embedding 单次最多 10 条，网关按 `EMBEDDING_BATCH_SIZE`（默认 10）切批；超过限制会整批失败并退回 hash 向量。图/公式的 Vision 调用使用 `MODEL_VISION`，留空则回退到 `MODEL_LLM`。

上传的原文保存在 `STORAGE_DIR/originals/{知识库id}/{文档id}/`，抽取的图/公式/表 PNG 在 `STORAGE_DIR/images/{文档id}/`。知识单元带 `image_url`（`/api/documents/{id}/assets?key=...`），问答与审核页用该地址引用图片，不再只有文件名。已入库文档需重新抽取后才会写入新的 `image_url` 与磁盘截图。

仍可把 `MODEL_BASE_URL` 指到任何 OpenAI 兼容端点。无 `MODEL_API_KEY` 时分类、抽取与问答走启发式，不阻塞本地演示。

`docker-compose.yml` 默认账号与示例环境变量一致（Postgres `akrag/akrag`，MinIO `minioadmin`，Neo4j `neo4j/akrag-neo4j`）。

## 知识处理闭环

1. **文档管理** 上传 PDF/MD/TXT/HTML/DOCX/PPT 等  
2. AI 识别领域与知识类型，推荐 Strategy  
3. 确认策略后抽取 Knowledge Unit  
4. **知识审核** 对照原文编辑并发布  
5. **检索中心** 维护文档关键字与元数据索引  
6. **智能问答** 按问题类型规划检索并给出带来源的答案  
7. **评估中心** 用 Golden Dataset 衡量召回与完整性  

更完整的产品说明见 `docs/架构方案.md`、`docs/页面原型.md`。

## 开发

```bash
uv sync --extra dev
uv run pytest backend/tests
```

代码入口：`backend/app/main.py`（`lifespan` 中初始化存储并 seed）。前端路由：`frontend/src/router.ts`。
