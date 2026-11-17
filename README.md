# ChemFinder — 化学合成路线智能分析系统

ChemFinder 面向高校化学实验课和课题组。输入起始原料、目标产物及设备上限，用户可以比较已记录的合成路线，按原文页码复核证据，并把所选路线导出为可编辑的实验方案草案。

## 参赛团队

**ChemFinder** · 团队编号 **44590** · **兰州交通大学**

| 成员 | 项目分工 |
|---|---|
| 甘祖德 | 反应数据模型、后端接口与实验室条件评分 |
| 陈俊宏 | PDF 提取、检索增强与论文证据核对 |
| 张意博 | 前端路线比较、图谱交互与演示验证 |

[技术报告 PDF](docs/competition/技术报告.pdf) · [技术报告可编辑稿](docs/competition/技术报告.md)

## 核心能力与技术架构

| 用户操作 | 主要实现 |
|---|---|
| 导入和校对反应 | FastAPI、pdfplumber、Pydantic 与 DeepSeek 兼容接口，支持 SciFinder 导出及文本型期刊论文 |
| 按实验室条件比较 | SQLModel 查询反应、条件和文献，先按满足的约束数排序，再按收率、步骤、温度和试剂风险加权排序 |
| 回查论文与资料 | 路线卡保留来源页和引文。文档问答使用 Chroma、BGE 与 BM25 融合检索，可启用重排 |
| 绘制结构、浏览图谱 | Vue 3、Vue Router、Vite、ECharts；结构草图支持 SMILES 和 SVG 导出 |
| 生成草案 | 将所选路线、用户阈值及文献来源传给模型，支持编辑和 Markdown 导出，本地演示可离线整理记录 |

本地评审使用 SQLite 用户库和化学库。知识图谱可从反应库构建，另提供可选 Neo4j 同步。后端依赖见 [pyproject.toml](pyproject.toml) 和 [uv.lock](uv.lock)，前端依赖见 [package.json](frontend/package.json) 和 [package-lock.json](frontend/package-lock.json)，配置项见 [.env.example](.env.example)。

## 快速开始

### 本地比赛演示（无需模型密钥）

准备 Python 3.12、uv、Node.js 22.12+ 和 npm。首次安装依赖需要联网；下面的路线演示使用 SQLite，不需要 Docker、Neo4j、嵌入模型或 SciFinder 账号。在仓库根目录执行：

```bash
uv sync --locked --no-install-project --python 3.12
.venv/bin/python scripts/seed_chemistry.py
export DATABASE_URL="sqlite:///$PWD/.chemroute-demo/demo-users.db"
export CHEMISTRY_DB_URL="sqlite:///$PWD/.chemroute-demo/demo-reactions.db"
export DEEPSEEK_API_KEY=""  # 即使本地 .env 有密钥，本次路线演示也使用离线模式
.venv/bin/python -m uvicorn app.main:app --port 8000
```

第二个终端从仓库根目录启动前端：

```bash
cd frontend
npm ci
npm run dev
```

打开 Vite 输出的本地地址（默认 http://localhost:5173）。用演示账号 `demo` 和密码 `demo123` 登录，点击「打开演示案例」即可填入苯甲醛和肉桂酸。也可以自行注册。如果 8000 端口已占用，可把后端命令改为 `--port 18000`，并在前端终端执行 `CHEMFINDER_BACKEND_URL=http://127.0.0.1:18000 npm run dev`。

1. 输入目标 **肉桂酸**、起始原料 **苯甲醛**、最高温度 **80 °C**，开始分析。
2. 展开「并排比较两条路线」。模拟来源卡 A 的记录是 **65 °C / 72%**，满足温度约束；B 是 **110 °C / 90%**，即使收率更高也不满足。把上限改为 **45 °C** 再分析，两条都不应显示为完全匹配。
3. 在比较表的下拉框选取带论文链接的路线。作者在第 227 页记录了回流 5 小时，80 °C 上限应显示“证据不足”。点开收率链接可核对第 228 页表 1 的化合物 1，收率为 85.3 ± 2.9%。最低收率筛选按报告值加减 2.9 个百分点核对，阈值落在区间内部时显示“证据不足”。[原文表 1](https://journal.ugm.ac.id/ijc/article/download/21626/14331#page=3)
4. 在比较表里选一条路线生成草案，核对温度、来源和筛选上限，再编辑并导出 Markdown。无密钥时，正文只整理已有记录；配置模型后才生成 AI 草案。SciFinder PDF 提取也需要模型密钥，文档问答另需本地嵌入模型。

赛前可在仓库根目录运行 `.venv/bin/python scripts/check_demo.py`。它会新建临时数据库，自动验证重复初始化、两组温度上限和离线草案，不需要启动服务器。

### Docker Compose 部署

```bash
docker compose up -d --build
# 首次部署后，向容器使用的化学库写入三条比赛演示记录
docker compose exec backend /app/.venv/bin/python scripts/seed_chemistry.py --configured-databases
```

### 访问地址

- 前端：`http://localhost:8080`
- 后端 API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`
- Neo4j Browser：`http://localhost:7474`（用户名 neo4j，密码 chemroute_neo4j）

### 从 PDF 导入反应

在“合成路线规划”里选择文档类型。SciFinder 导出按 Scheme 提取。期刊论文按 PDF 页码提取作者报告的反应，预览中可对照条件、收率和原文短句。设置模型密钥后上传文本型 PDF，检查预览并修正名称或数值，再点击“确认校对并导入数据库”。保存后的路线卡和 Markdown 草案可按文件名和页码回查。扫描件需要先做 OCR。

也可以通过脚本提取并导入：

```bash
python scripts/extract_scifinder_llm.py path/to/scifinder-export.pdf --max-schemes 5 --import-db
```

导入写入 `CHEMISTRY_DB_URL` 指向的化学数据库，并按 PDF SHA-256 指纹跳过已导入的 Scheme。在线 PDF 提取目前最多选择 20 个 Scheme。

## 项目结构

```
Chesci/
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

## 演示数据来源

演示库包含两条模拟记录和一条公开论文记录。已有演示库重新运行种子脚本即可补入论文。论文数据来自 Rudyanto 与 Hartanti 于 2008 年在 *Indonesian Journal of Chemistry* 发表的研究。两处链接分别定位到实验段和收率表，导出的 Markdown 保留这两处定位。[论文 DOI](https://doi.org/10.22146/ijc.21626) · [论文记录](docs/published-cinnamic-acid.json)

[两条路线的原始示例](docs/demo-routes.json)由项目人工编写，温度、时间和收率仅用来验证检索与排序。两张模拟来源卡没有 DOI，不代表真实论文或实验依据。初始化脚本复用人工校对后的入库流程；重复执行同一版本不会新增记录。默认仅写入 `.chemroute-demo/` 下独立的用户库和反应库，不需要复制现有数据库或 PDF。

## 检索配置

| 环境变量 | 默认值 | 说明 |
|------|------|------|
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | 重排序模型路径 |
| `RAG_MAX_DENSE_DISTANCE` | `1.05` | 稠密检索距离阈值 |
| `RAG_MIN_BM25_SCORE` | `8.0` | BM25 分数阈值 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 连接地址 |

## 比赛版本进度

- [x] 本地从空数据库初始化演示数据，注册并登录。
- [x] 按目标、起始原料和最高温度检索、比较路线，核对来源，编辑并导出 Markdown 草案。
- [x] 路线卡与并排比较显示每项实验室约束的满足、冲突或证据不足；卡片可展开综合评分权重和计分依据，导出草案保留原始记录与来源位置。
- [x] 用公开原文核对一条苯甲醛到肉桂酸的路线，关联实验条件和收率表的具体页码。
- [x] 通过在线模型从期刊论文 PDF 生成预览，确认入库后按起始原料、产物和温度检索，并验证同一文件重复确认。
- [ ] 录制普通话演示视频并提交正式材料。
