# -*- coding: utf-8 -*-
"""
旅游 Agent 核心：把知识库检索 + 大模型回答串起来。

设计对齐 01.py 的三个原则：
  1) 先检索、再回答（RAG）——不凭空编造目的地信息。
  2) 检索不到就如实说"知识库里没有"，而不是硬答（01.py 踩过"未知当成否定"的坑）。
  3) 无论用户用什么语言提问，一律用简体中文回答（对应 01.py 的 ZH_RULE）。

大模型走 DeepSeek 的 OpenAI 兼容接口，纯 HTTP 调用，不依赖 agent-framework。
"""

from __future__ import annotations

import os
import json
from typing import AsyncIterator

import httpx

from . import knowledge_base as kb


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL_ID = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")

REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=15.0)

# 对应 01.py 的 ZH_RULE
ZH_RULE = (
    "语言规则（必须遵守）：无论用户使用什么语言提问，你都必须用简体中文回答。"
    "包括调用工具前后的过渡句也必须是中文，不要输出英文句子。"
)

SYSTEM_PROMPT = f"""你是「小坤」——一位专业、热情的旅游顾问 Agent。

工作方式（必须遵守）：
1. 你的回答必须基于下面提供的【知识库资料】。资料中没有的目的地或信息，要明确告诉用户
   "我的知识库里暂时没有这个目的地的资料"，然后可以推荐知识库中相近的选项。
2. 绝不要编造知识库里没有的价格、签证政策、航班等具体信息。
3. 回答要有结构：先说结论，再展开理由。涉及花费、最佳季节、亮点时要具体。
4. 如果用户问了预算、季节、天数等条件，要主动用知识库里的花费和季节做匹配，指出"符合/不符合"。
5. 语气亲切自然，像一个有经验的旅行顾问在聊天，不要写成生硬的说明书。
6. 篇幅控制在 200-400 字，除非用户明确要求详细展开。

{ZH_RULE}
"""


def _history_messages(history: list[dict], max_turns: int = 6) -> list[dict]:
    """只保留最近几轮对话，避免上下文无限膨胀（对应 01.py 的上下文管理思路）。"""
    trimmed = history[-max_turns * 2 :] if history else []
    return [
        {"role": m["role"], "content": m["content"]}
        for m in trimmed
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]


def build_prompt(
    question: str,
    hits: list[dict],
    history: list[dict] | None = None,
    all_destinations: bool = False,
) -> list[dict]:
    """组装发给大模型的消息列表。"""
    context = kb.build_context(hits)
    if all_destinations:
        ctx_lines = []
        for d in kb.list_destinations():
            ctx_lines.append(
                f"- {d['name_zh']}（{d['name_en']}，{d['region']}）："
                f"最佳季节 {d['best_season']}；日均 {d['daily_cost']}；亮点 {'、'.join(d['highlights'])}"
            )
        context = "【知识库全部目的地】\n" + "\n".join(ctx_lines)

    user_block = (
        f"【知识库资料】\n{context}\n\n"
        f"【用户问题】\n{question}"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_history_messages(history or []))
    messages.append({"role": "user", "content": user_block})
    return messages


# ---------------------------------------------------------------------------
# 调用大模型
# ---------------------------------------------------------------------------
async def _chat_once(messages: list[dict], temperature: float = 0.6) -> str:
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _chat_stream(messages: list[dict], temperature: float = 0.6) -> AsyncIterator[str]:
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{BASE_URL}/chat/completions", json=payload, headers=headers
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {})
                piece = delta.get("content")
                if piece:
                    yield piece


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
async def answer(question: str, history: list[dict] | None = None) -> dict:
    """非流式问答，返回答案 + 命中的知识库来源。"""
    hits = kb.search(question, top_k=3)
    msgs = build_prompt(question, hits, history)
    text = await _chat_once(msgs)
    return {"answer": text, "sources": hits}


async def answer_stream(
    question: str, history: list[dict] | None = None
) -> AsyncIterator[dict]:
    """
    流式问答。依次产出：
      {"type": "sources", "sources": [...]}
      {"type": "delta", "text": "..."}   （多次）
      {"type": "done"}
      {"type": "error", "message": "..."}
    """
    hits = kb.search(question, top_k=3)
    yield {"type": "sources", "sources": hits}

    msgs = build_prompt(question, hits, history)
    try:
        async for piece in _chat_stream(msgs):
            yield {"type": "delta", "text": piece}
        yield {"type": "done"}
    except httpx.HTTPStatusError as e:
        yield {
            "type": "error",
            "message": f"大模型接口返回错误 {e.response.status_code}，请稍后重试。",
        }
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"生成回答时出错：{e}"}
