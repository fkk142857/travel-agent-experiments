# -*- coding: utf-8 -*-
"""
FastAPI 后端：小坤 · 旅游 Agent 实验台。

路由分两类：
  /api/exps*        —— 实验元数据（前端渲染导航用）
  /api/exp/{id}     —— 每个实验的执行接口

保留原有的 /api/chat* 作为"自由问答"入口（对应最初的小坤问答页）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import agent, auth, experiments, knowledge_base as kb
from . import exp_basics as E1
from . import exp_agents as E2
from . import exp_quality as E3
#将exp_trust引进来，起个小名叫E4
from . import exp_trust as E4

STATIC_DIR = Path(__file__).parent / "static"

# 前端资源版本号占位符。index.html 里写成 ?v={%V%}，
# 由 GET / 在返回前替换成真实版本串。
_ASSET_PLACEHOLDER = "{%V%}"
_ASSET_FILES = ("app.js", "style.css", "index.html")


def asset_version() -> str:
    """用静态资源的最大 mtime 当版本号 —— 文件一变，URL 就变。

    这样浏览器一定重新拉取，不需要手动改版本常量。
    """
    stamps: list[float] = []
    for name in _ASSET_FILES:
        f = STATIC_DIR / name
        try:
            stamps.append(f.stat().st_mtime)
        except OSError:
            continue
    return str(int(max(stamps))) if stamps else "0"


class NoCacheStatic(StaticFiles):
    """静态资源一律要求浏览器回源校验。

    默认的 StaticFiles 不带 Cache-Control，浏览器会走启发式缓存、
    可能长时间使用旧文件（表现为"改了代码但页面没变"）。
    这里加 no-cache + must-revalidate：仍保留 ETag/304 的省流效果，
    但保证拿到的永远是最新内容。
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

app = FastAPI(title="小坤 · 旅游 Agent 实验台", version="2.0.0")

# ---------------------------------------------------------------------------
# 启动校验：缺 API key 直接拒绝启动
# ---------------------------------------------------------------------------
# 这里以前靠源码里写死的兜底 key 兜着，结果是两件坏事：
#   1) 忘了配 .env 也照样跑，配置问题被掩盖，出问题很难查；
#   2) 那把 key 成了源码的一部分，一旦把项目推到 GitHub 就跟着泄露了。
# 现在改成 fail fast：缺失就报错，并明确告诉人往哪儿填。
# ---------------------------------------------------------------------------
if not os.getenv("DEEPSEEK_API_KEY", "").strip():
    raise RuntimeError(
        "未配置 DEEPSEEK_API_KEY，服务拒绝启动。\n"
        "  1. 在项目根目录创建 .env（可复制 .env.example 当模板），填写：\n"
        '         DEEPSEEK_API_KEY="sk-你的密钥"\n'
        "  2. .env 已被 .gitignore 忽略，不会进入 git 仓库。\n"
        "  3. 本地请用 `python run.py` 启动（它会先加载 .env）；\n"
        "     若直接 `uvicorn app.main:app`，需自行保证该环境变量已注入。"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 访问口令：配了 ACCESS_PASSWORD 才生效，否则全部放行（本地开发用）
auth.register_gate(app)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list)


class ExpRequest(BaseModel):
    """通用实验请求：不同实验按需取用其中的字段。"""
    question: str = Field("", max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)
    text: str = Field("", max_length=2000)
    options: dict = Field(default_factory=dict)


class GateResumeRequest(BaseModel):
    goal: str
    action: str
    human_decision: str          # approve | deny | escalate
    prior_reason: str | None = None
    attempt: int = 0


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": agent.MODEL_ID,
        "destinations": len(kb.list_destinations()),
        "experiments": len(experiments.EXPERIMENTS),
    }


@app.get("/api/destinations")
async def destinations():
    return {"items": kb.list_destinations()}


@app.get("/api/exps")
async def exps():
    return {
        "experiments": experiments.public_list(),
        "groups": experiments.groups(),
    }


# ---------------------------------------------------------------------------
# 自由问答（最初的小坤问答页）
# ---------------------------------------------------------------------------
@app.post("/api/chat")
async def chat(req: ChatRequest):
    return await agent.answer(req.question, [m.model_dump() for m in req.history])


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    history = [m.model_dump() for m in req.history]

    async def gen():
        async for event in agent.answer_stream(req.question, history):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# 实验 1-6
# ---------------------------------------------------------------------------
@app.post("/api/exp/exp1")
async def api_exp1(req: ExpRequest):
    return await E1.exp1_tools(req.question)


@app.post("/api/exp/exp2")
async def api_exp2(req: ExpRequest):
    return await E1.exp2_session(req.question, [m.model_dump() for m in req.history])


@app.post("/api/exp/exp3")
async def api_exp3(req: ExpRequest):
    return await E1.exp3_structured(req.question or req.text)


@app.post("/api/exp/exp4")
async def api_exp4(req: ExpRequest):
    return await E1.exp4_toolbox(req.question)


@app.post("/api/exp/exp5")
async def api_exp5(req: ExpRequest):
    return await E1.exp5_rag(req.question, checker=bool(req.options.get("checker")))


@app.post("/api/exp/exp6")
async def api_exp6(req: ExpRequest):
    return await E1.exp6_context(
        req.question, [m.model_dump() for m in req.history],
        summarize=bool(req.options.get("summarize")),
    )


# ---------------------------------------------------------------------------
# 实验 7-9
# ---------------------------------------------------------------------------
@app.post("/api/exp/exp7")
async def api_exp7(req: ExpRequest):
    return await E2.exp7_multi_agent(req.question)


@app.post("/api/exp/exp8")
async def api_exp8(req: ExpRequest):
    return await E2.exp8_planner_concierge(req.question)


@app.get("/api/exp/exp9/graph")
async def api_exp9_graph():
    return E2.exp9_workflow_graph()


@app.post("/api/exp/exp9")
async def api_exp9(req: ExpRequest):
    return await E2.exp9_workflow(req.question)


# ---------------------------------------------------------------------------
# 实验 10-12
# ---------------------------------------------------------------------------
@app.post("/api/exp/exp10")
async def api_exp10(req: ExpRequest):
    return await E3.exp10_metacognition(req.question)


@app.post("/api/exp/exp11")
async def api_exp11(req: ExpRequest):
    return await E3.exp11_observability(req.question)


@app.post("/api/exp/exp12")
async def api_exp12(req: ExpRequest):
    return await E3.exp12_gate(req.question or req.text)


@app.post("/api/exp/exp12/resume")
async def api_exp12_resume(req: GateResumeRequest):
    if req.human_decision not in ("approve", "deny", "escalate"):
        raise HTTPException(400, "human_decision 必须是 approve / deny / escalate")
    return await E3.exp12_resume(
        goal=req.goal, action=req.action, human_decision=req.human_decision,
        prior_reason=req.prior_reason, attempt=req.attempt,
    )


@app.get("/api/exp/exp12/log")
async def api_exp12_log(limit: int = 30):
    return {"entries": E3.read_gate_log(limit)}


@app.delete("/api/exp/exp12/log")
async def api_exp12_log_clear():
    E3.clear_gate_log()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 实验 13-15
# ---------------------------------------------------------------------------
@app.get("/api/exp/exp13/graph")
async def api_exp13_graph():
    return E4.exp13_memory_graph()


@app.post("/api/exp/exp13/remember")
async def api_exp13_remember(req: ExpRequest):
    return E4.exp13_memory_remember(req.text or req.question)


@app.post("/api/exp/exp13/ask")
async def api_exp13_ask(req: ExpRequest):
    return await E4.exp13_memory_ask(req.question)


@app.delete("/api/exp/exp13")
async def api_exp13_reset():
    return E4.exp13_memory_reset()


@app.post("/api/exp/exp14")
async def api_exp14(req: ExpRequest):
    return await E4.exp14_receipts(req.text)


#当有人用get方式访问/api/exp/exp15/stages"这个网址时，执行下面这个异步函数
#get：访问方式，只负责拿数据。
#/api/exp/exp15/stages：网址路径。api（接口）- exp（实验）- 15（实验编号）- stages（阶段）
#
@app.get("/api/exp/exp15/stages")
async def api_exp15_stages():
    # 返回一个字典，里面包含一个键为"stages"，值为E4.PIPELINE_STAGES
    # PIPELINE_STAGES = [
    #{"id": "exp5",  "name": "RAG 检索",     "desc": "先从知识库取资料"},
    #{"id": "exp7",  "name": "多智能体分工", "desc": "目的地专家 + 行程规划师接力"},
    #{"id": "exp9",  "name": "工作流审核",   "desc": "前台产出 → 礼宾批准/打回"},
    #{"id": "exp11", "name": "可观测性",     "desc": "统计耗时与质量分"},
#]
# 将这个4个阶段的清单，套上一个“stages”的标签，打包发给前端
    return {"stages": E4.PIPELINE_STAGES}


@app.post("/api/exp/exp15")
async def api_exp15(req: ExpRequest):
    return await E4.exp15_pipeline(req.question, req.options.get("stages"))


# ---------------------------------------------------------------------------
# 静态页
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    # no-store：首页绝不能进浏览器缓存。
    # 否则会话失效后，浏览器仍用缓存的 HTML 渲染出实验台外壳，
    # 但接口全被 401 拦掉，用户看到的是"页面打开了却说没通过校验"。
    #
    # 同时把 {%V%} 换成静态资源版本号：只要 app.js / style.css 变了，
    # 引用它们的 URL 就变，浏览器必然重新拉取 —— 从根上避免
    # "代码改了但用户跑的是旧 JS" 这类问题。
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace(_ASSET_PLACEHOLDER, asset_version())
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


app.mount("/static", NoCacheStatic(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# 兜底：未知路径不要甩 JSON 404
#
# 为什么要这个：链接被从聊天/文档里复制时，容易带上 markdown 的 `**`
# 或其它尾巴，变成 /**. 直接返回 {"detail":"Not Found"} 用户完全看不懂。
# 页面请求一律重定向回首页；/api/ 前缀保持 JSON 404，方便前端排错。
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return RedirectResponse("/", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
