<div align="center">

# 🌴 小坤 · 旅游 Agent 实验台

**一个把「大模型智能体（Agent）」的 15 个核心能力，做成可点击、可观察、可对比的 Web 实验台。**
从多工具调用、RAG 检索，到多智能体协作、人工审批、加密收据——每个实验都能在浏览器里实时跑一遍，并看到模型「思考了什么、调用了什么、返回了什么」。

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-4B6EF5?logo=openai&logoColor=white)](https://platform.deepseek.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](#-许可协议)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#-参与贡献)

</div>

---

## 📖 项目简介

本项目是一个**教学 + 演示**性质的智能体实验台。它把「构建一个企业级 AI 客服/旅行助手」所需的关键技术点，拆成 **15 个彼此独立又层层递进的小实验**，封装在一个清爽的 Web 界面里。

和「读文档学 Agent」不同，这里的每个实验都是**活的**：

- 你在输入框里说一句话，能立刻看到 Agent 调用了哪些工具、参数是什么、结果如何；
- 可以开关「爱核对版」「启用摘要工具」等选项，**直观对比不同策略的效果差异**；
- 后端把耗时分阶段暴露出来，能像看仪表盘一样看一次调用的「生产环境指标」。

> 前端（`HTML/CSS/JS`）+ 后端（`FastAPI`）+ 大模型（`DeepSeek`，OpenAI 兼容协议）三段式，零构建步骤，`pip install` 后一条命令即可跑起来。

---

## ✨ 功能亮点

| 能力 | 说明 |
| --- | --- |
| 🧩 **15 个渐进式实验** | 从基础对话 → 检索与工具 → 协作与编排 → 质量与治理 → 信任与记忆，五条主线 |
| 🔧 **显式 Function Calling 循环** | 不用框架黑盒，每一步「模型要调工具 → 执行 → 回填」都可见可控 |
| 🔍 **可对比实验设计** | 如 RAG 的「普通版 vs 爱核对版」、上下文管理的「指令压缩 vs 主动摘要」 |
| 📊 **可观测性面板** | 分阶段耗时、工具调用次数、四项质量评分一目了然 |
| 🛡️ **信任与安全** | 人工审批关卡（分级放行）、Ed25519 签名收据 + 哈希链防篡改 |
| 🧠 **长期记忆** | 偏好抽取成三元组存入知识图谱，跨会话可查 |
| 🎨 **零构建前端** | 原生 JS + CSS，无需 npm / webpack，打开即用 |

---

## 🧪 15 个实验一览

项目按「认知难度」分为 5 个阶段，每个实验都对应一个可执行的 API 与前端面板。

### 一 · 基础对话

| # | 实验 | 核心概念 | 你会看到什么 |
| :-: | --- | --- | --- |
| 1 | **多工具 Agent** | Tool Calling | Agent 自主判断该调用哪个工具，并把结果组织成自然语言 |
| 2 | **会话记忆** | Session / Context | 多轮对话共享上下文，第二轮能接上第一轮的话 |
| 3 | **结构化输出** | JSON Schema + 校验 | 强制模型按固定表格返回，而非自由发挥的文字 |
| 6 | **上下文管理** | 摘要压缩 | 长对话如何「记得住、又不啰嗦」 |

### 二 · 检索与工具

| # | 实验 | 核心概念 | 你会看到什么 |
| :-: | --- | --- | --- |
| 4 | **工具箱复用** | 多工具编排 | 一句话里含两个需求，模型「先拿名单、再逐个查」 |
| 5 | **RAG 检索增强** | 检索 + 生成 | 先查知识库再回答，可切换「爱核对版」对比效果 |

### 三 · 协作与编排

| # | 实验 | 核心概念 | 你会看到什么 |
| :-: | --- | --- | --- |
| 7 | **多智能体协作** | Multi-Agent | 目的地专家只管「去哪」，行程规划师只管「怎么去」 |
| 8 | **规划者 + 管家** | Planner / Executor | 规划者拆任务清单，管家拿清单逐条执行订票订房 |
| 9 | **工作流流水线** | Workflow Graph | 先画流程图（谁接谁）再顺序执行，含审核打回 |

### 四 · 质量与治理

| # | 实验 | 核心概念 | 你会看到什么 |
| :-: | --- | --- | --- |
| 10 | **元认知：回退与自评** | Fallback + Self-Eval | 主系统失败自动切备用，并如实告知；回复后有第三方打分 |
| 11 | **生产环境视角** | Observability | 各阶段耗时、工具调用次数、质量评分 |
| 12 | **人工审批关卡** | Human-in-the-loop | 低/中风险放行，高风险拦下由人批准/拒绝/上报 |

### 五 · 信任与记忆

| # | 实验 | 核心概念 | 你会看到什么 |
| :-: | --- | --- | --- |
| 13 | **长期记忆图谱** | Knowledge Graph | 偏好抽成三元组存图，换新会话照样查得到 |
| 14 | **加密收据** | Ed25519 + 哈希链 | 每次工具调用盖章签名，篡改必被发现（不调大模型） |
| 15 | **端到端集成** | Pipeline | 选一组实验按序执行，实时看整条链路的耗时与产出 |

---

## 🏗️ 技术栈

- **后端**：Python 3.10+ · [FastAPI](https://fastapi.tiangolo.com/) · Uvicorn · Pydantic v2
- **大模型**：DeepSeek（`deepseek-chat`），走 **OpenAI 兼容协议**，通过 `httpx` 直接调用
- **前端**：原生 HTML / CSS / JavaScript（零构建、零依赖）
- **密码学**：PyNaCl（Ed25519 签名）· JCS（RFC 8785 JSON 规范化）
- **配置**：`python-dotenv`

> 💡 **为什么不用 Agent 框架？** 原型的 15 个实验最初基于 `agent-framework` 实现。本项目将其能力用**纯 HTTP + 显式工具循环**重写：一方面减少重依赖、发布更稳；另一方面每一步过程都可见——这正是「实验台」最需要的。

---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/fkk142857/travel-agent-experiments.git
cd travel-agent-experiments
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置环境变量

复制模板并填写你的 DeepSeek 密钥：

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

编辑 `.env`：

```dotenv
DEEPSEEK_API_KEY="sk-你的密钥"      # 必填，从 https://platform.deepseek.com/ 获取
DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
DEEPSEEK_MODEL_ID="deepseek-chat"
ACCESS_PASSWORD=""                  # 可选：配置后打开页面需输口令
PORT=8000
```

> 🔐 `.env` 已被 `.gitignore` 忽略，**不会**进入仓库。项目在缺少 `DEEPSEEK_API_KEY` 时会**拒绝启动**，避免配置问题被静默掩盖。

### 4. 启动

```bash
python run.py
```

打开浏览器访问 **<http://localhost:8000>** 即可开始体验。

> ⚠️ 请务必使用 `python run.py` 启动——它会先加载 `.env`。若直接 `uvicorn app.main:app`，需自行保证环境变量已注入。

---

## 📂 目录结构

```
travel-agent-experiments/
├── app/
│   ├── main.py            # FastAPI 入口：路由、静态资源、启动校验、鉴权挂载
│   ├── agent.py           # 面向「对话」场景的 Agent 封装
│   ├── llm.py             # 通用大模型客户端：chat / stream / JSON 模式 / 工具循环
│   ├── knowledge_base.py  # 旅游知识库（12 个目的地）+ 分词加权检索
│   ├── tools_lib.py       # 可被 Agent 调用的工具集
│   ├── experiments.py     # 实验注册表：15 个实验的元数据（前端据此渲染）
│   ├── exp_basics.py      # 实验 1–6：基础对话 & 检索工具
│   ├── exp_agents.py      # 实验 7–9：协作与编排
│   ├── exp_quality.py     # 实验 10–12：质量与治理
│   ├── exp_trust.py       # 实验 13–15：信任与记忆（图谱 / 收据 / 集成）
│   ├── auth.py            # 访问口令中间件（可选）
│   └── static/            # 前端：index.html / app.js / style.css
├── 01.py                  # 原始单体原型脚本（15 个 demo 的起源）
├── run.py                 # 本地启动入口（先加载 .env 再起服务）
├── requirements.txt
├── .env.example           # 环境变量模板
└── .gitignore
```

---

## 🔌 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 实验台主页 |
| `GET` | `/api/health` | 健康检查（供部署平台探活） |
| `GET` | `/api/exps` | 15 个实验的元数据（导航用） |
| `GET` | `/api/destinations` | 知识库目的地列表 |
| `POST` | `/api/chat` · `/api/chat/stream` | 自由问答（含流式） |
| `POST` | `/api/exp/exp{1..15}` | 执行对应编号的实验 |
| `GET` | `/api/exp/exp9/graph` | 工作流流程图（Mermaid） |
| `POST` | `/api/exp/exp12/resume` | 高风险操作的人工裁决续跑 |
| `GET`/`DELETE` | `/api/exp/exp12/log` | 审批审计日志 |
| `GET` | `/api/exp/exp13/graph` | 长期记忆知识图谱 |
| `POST` | `/api/exp/exp13/remember` · `/ask` | 写入 / 查询长期记忆 |
| `GET` | `/api/exp/exp15/stages` · `POST /api/exp/exp15` | 端到端流水线的阶段与执行 |

交互式接口文档：启动后访问 **<http://localhost:8000/docs>**（FastAPI 自动生成）。

---

## 🛡️ 安全设计

- **密钥不入库**：所有凭据走 `.env`，`.gitignore` 已排除；源码中不存在任何硬编码密钥。
- **启动即校验**：缺少 `DEEPSEEK_API_KEY` 时明确报错并提示配置路径，而不是悄悄用兜底值跑起来。
- **可选访问口令**：配置 `ACCESS_PASSWORD` 后启用鉴权——服务端会话表 + 闲置超时（8 小时）+ 摘要比对（`hmac.compare_digest` 防时序攻击）。
- **可验证审计**：实验 12 的审批日志以 JSONL 落盘；实验 14 用 Ed25519 签名 + 哈希链为工具调用盖章，篡改可被检测。

---

## 📄 许可协议

本项目基于 **MIT License** 开源，欢迎自由使用与二次开发。

---

<div align="center">

**如果这个项目对你有帮助，欢迎点一个 ⭐ Star！**

Made with ❤️ by [fkk142857](https://github.com/fkk142857)

</div>
