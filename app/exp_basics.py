# -*- coding: utf-8 -*-
"""
实验 1-6：基础对话与检索。

对应 01.py：
  实验一  多工具 Agent        → exp1_tools
  实验二  会话记忆(session)   → exp2_session
  实验三  结构化输出          → exp3_structured
  实验四  工具箱复用          → exp4_toolbox
  实验五  RAG 检索增强        → exp5_rag
  实验六  上下文管理          → exp6_context
"""

from __future__ import annotations

import time

from . import llm, tools_lib as T
from .llm import Tool

# ---------------------------------------------------------------------------
# 实验一：多工具 Agent
# 01.py 做法：agent + get_destinations + check_destination_availability 两个工具
# ---------------------------------------------------------------------------
EXP1_TOOLS = [
    Tool(T.get_destinations),
    Tool(T.check_destination_availability),
]

EXP1_SYSTEM = (
    "你是一位乐于助人的旅游顾问，帮用户找到心仪的度假目的地。"
    "当用户想了解有哪些目的地时，调用 get_destinations 工具。"
    "当用户询问某个目的地能不能预订时，必须调用 check_destination_availability 工具核实，"
    "不要凭猜测回答。 "
    + llm.ZH_RULE
)


async def exp1_tools(question: str) -> dict:
    t0 = time.perf_counter()
    result = await llm.run_tools(
        [
            {"role": "system", "content": EXP1_SYSTEM},
            {"role": "user", "content": question},
        ],
        EXP1_TOOLS,
    )
    return {
        "answer": result["content"],
        "steps": result["steps"],
        "elapsed": round(time.perf_counter() - t0, 2),
    }


# ---------------------------------------------------------------------------
# 实验二：会话记忆
# 01.py 做法：agent.create_session()，多轮 run 共享上下文
# 这里由前端传完整 history，后端每轮带着历史一起发（等价效果）
# ---------------------------------------------------------------------------
EXP2_SYSTEM = (
    "你是一位旅游预订顾问，帮用户确认目的地的可订情况并给出推荐。"
    "给出推荐前务必先查可订性。 "
    + llm.ZH_RULE
)


async def exp2_session(question: str, history: list[dict]) -> dict:
    msgs = [{"role": "system", "content": EXP2_SYSTEM}]
    msgs.extend(_clean_history(history))
    msgs.append({"role": "user", "content": question})

    result = await llm.run_tools(msgs, [Tool(T.check_destination_availability)])
    return {
        "answer": result["content"],
        "steps": result["steps"],
        "turns": len(history) // 2 + 1,
    }


# ---------------------------------------------------------------------------
# 实验三：结构化输出
# 01.py 做法：DestinationRecommendation / TravelRecommendations 两个 pydantic 模型
#              DeepSeek 不支持 response_format=模型，所以走 json_object + 本地校验
# ---------------------------------------------------------------------------
EXP3_SCHEMA = (
    '{"recommendations": [{"destination": "string", "available": true, '
    '"best_season": "string", "highlights": ["string"], '
    '"estimated_budget_usd": 0}], "personalized_note": "string"}'
)


async def exp3_structured(preference: str) -> dict:
    parsed, raw = await llm.json_call(
        system=(
            "你是一位旅游专家，根据旅客偏好推荐目的地。"
            "只能推荐知识库中确实存在的目的地，并可参考以下资料：\n"
            + _kb_brief()
        ),
        user=f"旅行者偏好：{preference}",
        schema_hint=EXP3_SCHEMA,
    )
    if parsed is None:
        return {"ok": False, "raw": raw, "error": "模型返回的不是合法 JSON"}

    # 本地校验（对应 01.py 的 pydantic ValidationError 处理）
    recs = parsed.get("recommendations")
    if not isinstance(recs, list) or not recs:
        return {"ok": False, "raw": raw, "error": "recommendations 字段缺失或为空"}

    normalized = []
    for r in recs[:3]:
        if not isinstance(r, dict):
            continue
        normalized.append({
            "destination": str(r.get("destination", "")),
            "available": bool(r.get("available", False)),
            "best_season": str(r.get("best_season", "")),
            "highlights": [str(h) for h in (r.get("highlights") or [])][:5],
            "estimated_budget_usd": int(r.get("estimated_budget_usd") or 0),
        })

    return {
        "ok": True,
        "recommendations": normalized,
        "personalized_note": str(parsed.get("personalized_note", "")),
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# 实验四：工具箱复用
# 01.py 看点：一次提问里同时包含两个需求
#   "有哪些目的地？" → get_destinations
#   "哪些还能订？"   → check_destination_availability
#   模型必须"先拿名单、再逐个查"，把两个工具有序用起来
# ---------------------------------------------------------------------------
async def exp4_toolbox(question: str) -> dict:
    # 直接复用实验一的同一个工具箱对象，对应 01.py 的 travel_tools 复用
    result = await llm.run_tools(
        [
            {
                "role": "system",
                "content": (
                    "你是旅游顾问。如果用户既想知道有哪些目的地、又想知道哪些还能预订，"
                    "你必须先调用 get_destinations 拿到名单，再对关心的目的地调用 "
                    "check_destination_availability 逐个核实，最后汇总回答。 "
                    + llm.ZH_RULE
                ),
            },
            {"role": "user", "content": question},
        ],
        EXP1_TOOLS,
        max_rounds=8,
    )
    # 统计每个工具被调了几次（这是"工具箱复用"最直观的证据）
    counts: dict[str, int] = {}
    for s in result["steps"]:
        counts[s["tool"]] = counts.get(s["tool"], 0) + 1
    return {"answer": result["content"], "steps": result["steps"], "tool_counts": counts}


# ---------------------------------------------------------------------------
# 实验五：RAG 检索增强
# 01.py 对比两个智能体：普通版（查一次）vs 挑剔版（用城市名再查一次核对）
# ---------------------------------------------------------------------------
async def exp5_rag(question: str, checker: bool = False) -> dict:
    from . import knowledge_base as kb

    hits = kb.search(question, top_k=3)

    if checker:
        # 挑剔版：对每个命中的目的地，再用它的名字检索一次，拿到更完整的资料
        extra = []
        for h in hits[:3]:
            again = kb.search(h["name_zh"], top_k=1)
            if again and again[0]["key"] not in {x["key"] for x in extra}:
                extra.append(again[0])
        merged = {h["key"]: h for h in hits}
        for e in extra:
            merged.setdefault(e["key"], e)
        hits = list(merged.values())[:4]

    context = kb.build_context(hits)
    style = (
        "你是一位一丝不苟的旅行顾问，会反复核对你的推荐："
        "先检索相关目的地，对每个找到的目的地用它的名字再确认一次，"
        "然后用核实过的信息做比较，最后给出含具体花费、最佳时间、亮点的推荐。"
        if checker
        else "你是一位知识渊博的旅行顾问：回答前先看知识库资料，"
             "答案必须基于检索到的信息；资料里没有的，要明确说明。"
    )

    answer = await llm.text(
        [
            {"role": "system", "content": style + " " + llm.ZH_RULE},
            {
                "role": "user",
                "content": f"【知识库资料】\n{context}\n\n【用户问题】\n{question}",
            },
        ]
    )
    return {"answer": answer, "sources": hits, "mode": "checker" if checker else "standard"}


# ---------------------------------------------------------------------------
# 实验六：上下文管理
# 01.py 两种手段：
#   手段一 ContextAwareAgent     —— 靠【指令】要求压缩前文、记住偏好
#   手段二 SummarizingTravelAgent —— 靠【工具】主动把偏好写进摘要记录
# ---------------------------------------------------------------------------
EXP6_CONTEXT_SYSTEM = (
    "你是一位善于管理上下文的旅行规划助手。当对话变长时：\n"
    "1. 把先前的上下文压缩成要点\n"
    "2. 记住用户早先提到的偏好\n"
    "3. 引用先前的决定时不要重复完整细节\n"
    "始终在保持连贯的同时做到简洁。 "
    + llm.ZH_RULE
)


async def exp6_context(question: str, history: list[dict], summarize: bool = False) -> dict:
    """summarize=True 走手段二（带摘要工具），否则走手段一（纯指令）。"""
    msgs = [{"role": "system", "content": EXP6_CONTEXT_SYSTEM}]
    msgs.extend(_clean_history(history))
    msgs.append({"role": "user", "content": question})

    if summarize:
        result = await llm.run_tools(
            msgs,
            [Tool(T.summarize_preferences)],
            temperature=0.4,
        )
        # 把历次摘要抽出来单独展示
        summaries = [
            s["result"] for s in result["steps"] if s["tool"] == "summarize_preferences"
        ]
        return {
            "answer": result["content"],
            "steps": result["steps"],
            "summaries": summaries,
            "mode": "tool",
        }

    answer = await llm.text(msgs, temperature=0.4)
    return {"answer": answer, "steps": [], "summaries": [], "mode": "instruction"}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _clean_history(history: list[dict], max_turns: int = 8) -> list[dict]:
    """只保留最近几轮，对应 01.py 的上下文管理思路。"""
    trimmed = history[-max_turns * 2 :] if history else []
    return [
        {"role": m["role"], "content": m["content"]}
        for m in trimmed
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]


def _kb_brief() -> str:
    from . import knowledge_base as kb
    return "\n".join(
        f"- {d['name_zh']}（{d['region']}）：最佳季节 {d['best_season']}；"
        f"日均 {d['daily_cost']}；亮点 {'、'.join(d['highlights'])}"
        for d in kb.list_destinations()
    )
