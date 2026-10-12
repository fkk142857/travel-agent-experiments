# -*- coding: utf-8 -*-
"""
通用大模型客户端（OpenAI 兼容协议 / DeepSeek）。

把 01.py 里 agent-framework 的能力用纯 HTTP 重新实现，作为全部实验的公共底座：
  - chat()        : 单轮对话
  - stream()      : 流式对话
  - JSON 模式     : 结构化输出（对应 01.py 实验三）
  - run_tools()   : 完整的 function calling 循环（对应 01.py 的实验一/四/七/八/十等）

为什么自己写工具循环而不用框架？
  01.py 用的是 agent-framework，它会自动把 @tool 函数转成 schema、自动跑"模型要求 → 执行 → 回填"的循环。
  这里把那个循环显式写出来，一方面少一个重依赖（发布更稳），另一方面每一步都可见——
  实验中要展示"模型调了哪个工具、参数是什么、返回什么"，显式循环才好把过程暴露给前端。
"""

from __future__ import annotations

import os
import json
import inspect
from typing import Any, Callable, AsyncIterator

import httpx

API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL_ID = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")

TIMEOUT = httpx.Timeout(90.0, connect=15.0)

# 对应 01.py 的 ZH_RULE
ZH_RULE = (
    "语言规则（必须遵守）：无论用户使用什么语言提问，你都必须用简体中文回答。"
    "包括调用工具前后的过渡句也必须是中文，不要输出英文句子。"
)


class LLMError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 底层 HTTP
# ---------------------------------------------------------------------------
async def _post(path: str, payload: dict, stream: bool = False):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    client = httpx.AsyncClient(timeout=TIMEOUT)
    return client, headers


async def chat(
    messages: list[dict],
    temperature: float = 0.6,
    json_mode: bool = False,
    tools: list[dict] | None = None,
    model: str | None = None,
) -> dict:
    """单轮对话，返回完整 message 对象（可能带 tool_calls）。"""
    payload: dict[str, Any] = {
        "model": model or MODEL_ID,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers)
        if resp.status_code >= 400:
            raise LLMError(f"LLM {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
    return data["choices"][0]["message"]


async def text(
    messages: list[dict], temperature: float = 0.6, json_mode: bool = False
) -> str:
    """只要文字结果。"""
    msg = await chat(messages, temperature=temperature, json_mode=json_mode)
    return msg.get("content") or ""


async def stream(messages: list[dict], temperature: float = 0.6) -> AsyncIterator[str]:
    """流式输出，逐块产出文字。"""
    payload = {"model": MODEL_ID, "messages": messages, "temperature": temperature, "stream": True}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream(
            "POST", f"{BASE_URL}/chat/completions", json=payload, headers=headers
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise LLMError(f"LLM {resp.status_code}: {body[:300]!r}")
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
                piece = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                if piece:
                    yield piece


# ---------------------------------------------------------------------------
# 工具（function calling）
# ---------------------------------------------------------------------------
class Tool:
    """把一个普通函数包装成模型可调用的工具。

    对应 01.py 里的 @tool 装饰器 + Annotated 参数说明。
    """

    def __init__(self, fn: Callable, description: str | None = None):
        self.fn = fn
        self.name = fn.__name__
        self.description = description or (inspect.getdoc(fn) or "")
        self.params = self._build_params(fn)

    @staticmethod
    def _build_params(fn: Callable) -> dict:
        sig = inspect.signature(fn)
        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            ann = p.annotation
            if ann in (int,):
                t = "integer"
            elif ann in (float,):
                t = "number"
            elif ann in (bool,):
                t = "boolean"
            elif ann in (list, list[str]):
                t = "array"
            else:
                t = "string"
            entry: dict[str, Any] = {"type": t}
            # 01.py 用 Annotated[str, "说明"] 给模型写参数描述，这里读不出来就留空
            if t == "array":
                entry["items"] = {"type": "string"}
            props[pname] = entry
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        return {
            "type": "object",
            "properties": props,
            "required": required,
        }

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params,
            },
        }

    async def call(self, args: dict) -> Any:
        result = self.fn(**args)
        if inspect.isawaitable(result):
            result = await result
        return result


def as_schemas(tools: list[Tool]) -> list[dict]:
    return [t.schema() for t in tools]


async def run_tools(
    messages: list[dict],
    tools: list[Tool],
    max_rounds: int = 5,
    temperature: float = 0.6,
    on_event: Callable[[dict], None] | None = None,
    model: str | None = None,
) -> dict:
    """
    完整的工具调用循环：模型要求调用工具 → 我们执行 → 把结果回填 → 再问模型，
    直到模型给出最终文字回答（或达到 max_rounds 上限）。

    返回 {"content": 最终文字, "steps": [每次工具调用的记录], "messages": 完整消息}
    """
    schemas = as_schemas(tools) if tools else None
    by_name = {t.name: t for t in tools}
    steps: list[dict] = []
    convo = list(messages)

    for _ in range(max_rounds):
        msg = await chat(convo, temperature=temperature, tools=schemas, model=model)
        convo.append(msg)

        calls = msg.get("tool_calls") or []
        if not calls:
            return {"content": msg.get("content") or "", "steps": steps, "messages": convo}

        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            tool = by_name.get(name)
            if tool is None:
                result: Any = f"错误：不存在名为 {name} 的工具"
            else:
                try:
                    result = await tool.call(args)
                except Exception as e:  # noqa: BLE001
                    # 01.py 实验十一特意用"抛错"来演示主系统失败→切备用系统，
                    # 所以这里不能把异常吞掉，要如实回填给模型，让它自己决定回退。
                    result = f"工具执行失败：{type(e).__name__}: {e}"

            step = {
                "tool": name,
                "arguments": args,
                "result": result if isinstance(result, (str, int, float, bool)) else json.dumps(result, ensure_ascii=False, default=str),
            }
            steps.append(step)
            if on_event:
                on_event({"type": "tool", **step})

            convo.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": step["result"] if isinstance(step["result"], str) else json.dumps(step["result"], ensure_ascii=False),
            })

    # 轮次用尽：再要一次纯文字总结
    final = await chat(convo, temperature=temperature, model=model)
    return {"content": final.get("content") or "", "steps": steps, "messages": convo}


# ---------------------------------------------------------------------------
# 便捷：JSON 结构化输出（对应 01.py 实验三/八）
# ---------------------------------------------------------------------------
async def json_call(
    system: str, user: str, schema_hint: str, retries: int = 2
) -> tuple[Any, str]:
    """
    让模型返回 JSON，自己解析校验。
    01.py 里踩过的坑：DeepSeek 不支持 options={"response_format": TravelPlan} 这种强校验，
    会报 400。所以这里统一走 json_object 模式 + 提示词写字段结构 + 本地解析。
    返回 (解析后的对象, 原始文本)。
    """
    msgs = [
        {"role": "system", "content": system + "\n" + ZH_RULE},
        {
            "role": "user",
            "content": (
                f"{user}\n\n"
                f"只返回一个 JSON 对象，不要 markdown 代码块、不要多余文字。\n"
                f"字段名用英文、字段内容用简体中文，格式严格如下：\n{schema_hint}"
            ),
        },
    ]
    last_raw = ""
    for _ in range(retries + 1):
        last_raw = await text(msgs, temperature=0.3, json_mode=True)
        parsed = _try_json(last_raw)
        if parsed is not None:
            return parsed, last_raw
    return None, last_raw


def _try_json(raw: str) -> Any | None:
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1] if len(s.split("```")) > 1 else s
        if s.startswith("json"):
            s = s[4:]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        # 退一步：截取第一个 { 到最后一个 }
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            try:
                return json.loads(s[i : j + 1])
            except json.JSONDecodeError:
                return None
    return None
