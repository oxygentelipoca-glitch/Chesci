# ChemRoute — 化学合成路线智能分析系统

基于 RAG（检索增强生成）+ 知识图谱 + LLM Agent 的化学合成路线分析与实验方案生成平台。

## 核心能力

- **化学物质关系分析** — 查询化合物上下游原料、中间体、产物
- **产物谱系构建** — 通过知识图谱追溯合成路径
- **逆合成路线搜索** — 从目标产物反向检索已知合成路线
- **文献增强检索** — Hybrid RAG（Dense + BM25 + Reranker）检索论文/专利/实验数据
- **合成路线智能排序** — 多指标评分（收率、成本、安全性、环保、难度）
- **实验方案生成** — LLM Agent 根据路线和文献自动生成结构化实验方案

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue3 + Vite + Element Plus |
| 后端 | Python 3.12 + FastAPI |
| 业务数据库 | PostgreSQL（开发期兼容 SQLite） |
| 知识图谱 | Neo4j |
| 向量数据库 | ChromaDB |
| Embedding | BAAI/bge-base-zh-v1.5 |
| Reranker | BAAI/bge-reranker-base |
| LLM | DeepSeek / OpenAI 兼容 API |

## 快速开始

### 环境要求

- Python >= 3.12
- Docker & Docker Compose（用于 Neo4j、PostgreSQL）

### 本地开发

```bash
# 1. 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -e .

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 4. 初始化化学数据库（种子数据）
python scripts/seed_chemistry.py

# 5. 启动后端
uvicorn app.main:app --reload --port 8000
```

### Docker 部署

```bash
# 配置 API Key
export DEEPSEEK_API_KEY=your_key_here

# 一键启动（PostgreSQL + Neo4j + Backend + Frontend）
docker compose up --build
```

### 访问地址

- 前端：`http://localhost:8080`
- 后端 API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`
- Neo4j Browser：`http://localhost:7474`（用户名 neo4j，密码 chemroute_neo4j）

## 项目结构

```
chemroute/
├── app/                    # 后端主包
│   ├── main.py             # FastAPI 入口
│   ├── database.py         # 数据库连接（SQL + Neo4j）
│   ├── models.py           # 通用业务模型
│   ├── core/               # 认证、响应工具
│   ├── routers/            # API 路由
│   ├── services/           # 业务服务（RAG 等）
│   └── chemistry/          # 化学模块
│       ├── models.py       # 化合物/反应/文献 ORM
│       ├── parser.py       # 化学信息解析
│       ├── knowledge_graph.py  # 图谱操作
│       ├── retriever.py    # 文献检索
│       ├── scoring.py      # 路线评分
│       └── agent.py        # LLM Agent
├── utils/                  # 底层工具（BM25、文档加载、向量库）
├── frontend/               # Vue3 前端
├── scripts/                # 脚本
├── models/                 # 本地模型文件
├── documents/              # 内置文档资料
├── vector_db/              # Chroma 向量库
├── tests/                  # 测试
├── docker-compose.yml
└── pyproject.toml
```

## 种子数据

`scripts/seed_chemistry.py` 提供示例数据：

- **9 种化合物**：布洛芬、苯甲醛、肉桂酸、异丁苯 等
- **3 条反应**：Friedel-Crafts 酰基化、Knoevenagel 缩合、布洛芬水解
- **3 篇文献**：综述、英文论文、中文专利

```bash
# 写入关系数据库
python scripts/seed_chemistry.py

# 同时写入 Neo4j 知识图谱
python scripts/seed_chemistry.py --neo4j
```

## 检索配置

| 环境变量 | 默认值 | 说明 |
|------|------|------|
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | 重排序模型路径 |
| `RAG_MAX_DENSE_DISTANCE` | `1.05` | 稠密检索距离阈值 |
| `RAG_MIN_BM25_SCORE` | `8.0` | BM25 分数阈值 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 连接地址 |

## 开发路线

- [x] 第一阶段：架构设计 + 数据库
- [ ] 第二阶段：化学解析 + 知识图谱 + RAG + API
- [ ] 第三阶段：路线评分 + 前端界面
- [ ] 第四阶段：实验方案生成 + 用户系统
