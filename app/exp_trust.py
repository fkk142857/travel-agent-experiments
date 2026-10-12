# -*- coding: utf-8 -*-
"""
实验 13-15：长期记忆、加密收据、端到端集成。

对应 01.py：
  实验13  Cognee 长期记忆（知识图谱）   → exp13_memory
  实验14  加密收据（给工具调用盖章）     → exp14_receipts
  实验15  端到端集成                     → exp15_pipeline

★ 关于实验13的一处诚实说明 ★
  01.py 用的是 cognee + GLiNER 做实体抽取建图，依赖极重（要额外下载模型），
  云端沙箱装不动。这里改为【轻量知识图谱】：用规则的实体/关系抽取
  （目的地 → 属性、目的地 → 亮点、目的地 → 地区）直接构图。
  两者达到的能力目标是同一个：让记忆脱离单次会话，跨会话可查。
  区别在抽取精度——cognee 能理解自由文本里的隐含关系，这套只能识别已知字段。

★ 关于实验15 ★
  01.py 的 main() 是把 14 个 demo 从头到尾顺序跑一遍，是命令行演示。
  网页上原样重放没有意义（用户看不懂一堆 print）。这里改成
  【可视化编排面板】：选一组实验，按序执行，实时显示每个阶段的耗时与产出。
"""

from __future__ import annotations

import time
import base64
import hashlib
import copy
from datetime import datetime, timezone

from . import llm, knowledge_base as kb
from .exp_basics import exp1_tools, exp5_rag, _kb_brief
from .exp_agents import exp7_multi_agent, exp9_workflow
from .exp_quality import exp10_metacognition, exp11_observability

# ===========================================================================
# 实验十三：长期记忆（轻量知识图谱，替代 cognee）
# ===========================================================================
_MEMORY_STORE: dict[str, dict] = {}   # 进程内的"知识图谱"，模拟脱离会话的持久记忆


def _extract_triples(text: str) -> list[dict]:
    """从自由文本里抽取三元组（主体-关系-客体）。

    这是 cognee 的核心能力；这里用规则做简化版：
      命中知识库里的目的地 → 建立 目的地-属性 的边
      再按关键词判断用户表达了哪一类偏好
    """
    triples: list[dict] = []
    q = text.lower()

    for d in kb.list_destinations():
        hit = d["name_zh"] in text or d["name_en"].lower() in q
        if not hit:
            continue
        subj = d["name_zh"]
        # 目的地 → 地区 / 季节 / 花费 / 亮点（结构化属性直接成边）
        triples.append({"s": subj, "p": "位于", "o": d["region"]})
        triples.append({"s": subj, "p": "最佳季节", "o": d["best_season"]})
        triples.append({"s": subj, "p": "日均花费", "o": d["daily_cost"]})
        for h in d["highlights"][:3]:
            triples.append({"s": subj, "p": "亮点", "o": h})

    # 偏好类信息（对应 cognee 从对话里抽"用户偏好"）
    prefs = {
        "建筑": "建筑", "美食": "美食", "海滩": "海滩", "文化": "文化",
        "历史": "历史", "自然": "自然", "购物": "购物", "寺庙": "寺庙",
        "预算": "预算敏感", "便宜": "预算敏感", "性价比": "预算敏感",
        "蜜月": "蜜月", "亲子": "亲子", "独自": "独自旅行", "摄影": "摄影",
    }
    for kw, label in prefs.items():
        if kw in text:
            triples.append({"s": "旅行者", "p": "偏好", "o": label})

    # 时间偏好
    for m in ["1月", "2月", "3月", "4月", "5月", "6月",
              "7月", "8月", "9月", "10月", "11月", "12月"]:
        if m in text:
            triples.append({"s": "旅行者", "p": "计划出行", "o": m})

    return triples


def exp13_memory_remember(text: str) -> dict:
    """把一段话"记住"—— 抽三元组并入图。"""
    triples = _extract_triples(text)
    for t in triples:
        key = f"{t['s']}|{t['p']}|{t['o']}"
        _MEMORY_STORE[key] = {
            **t,
            "added_at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "source": text[:60],
        }
    return {"added": len(triples), "total": len(_MEMORY_STORE), "graph": exp13_memory_graph()}


def exp13_memory_graph() -> dict:
    """返回当前知识图谱（节点 + 边），供前端可视化。"""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid: str):
        if nid not in nodes:
            kind = "traveler" if nid == "旅行者" else (
                "destination" if any(d["name_zh"] == nid for d in kb.list_destinations()) else "attribute"
            )
            nodes[nid] = {"id": nid, "kind": kind}

    for t in _MEMORY_STORE.values():
        add_node(t["s"])
        add_node(t["o"])
        edges.append({"from": t["s"], "to": t["o"], "label": t["p"]})

    return {"nodes": list(nodes.values()), "edges": edges, "triple_count": len(_MEMORY_STORE)}


async def exp13_memory_ask(question: str) -> dict:
    """跨会话提问：先用图谱做检索，再让模型基于图谱回答。

    这正是 cognee 的价值所在——记忆不在"会话"里，而在图谱里，
    所以换一个新会话照样查得到。
    """
    graph = exp13_memory_graph()
    if not graph["nodes"]:
        return {"answer": "知识图谱还是空的，先在上面『记住一段话』吧。", "graph": graph, "used": []}

    # 从图谱里捞与问题相关的边（简单按词重合度）
    used = []
    for e in graph["edges"]:
        if e["from"] in question or e["to"] in question:
            used.append(e)
    if not used:
        # 兜底：把所有和"旅行者"相关的偏好带上
        used = [e for e in graph["edges"] if e["from"] == "旅行者"][:8]
    used = used[:15]

    graph_ctx = "\n".join(f"{e['from']} --{e['label']}--> {e['to']}" for e in used)
    answer = await llm.text(
        [
            {
                "role": "system",
                "content": (
                    "你是旅行顾问。下面是从【长期记忆知识图谱】里检索出来的事实，"
                    "请严格基于这些事实回答，不要编造图谱之外的偏好。 "
                    + llm.ZH_RULE
                ),
            },
            {
                "role": "user",
                "content": f"记忆图谱检索结果：\n{graph_ctx}\n\n用户问题：{question}",
            },
        ],
        temperature=0.4,
    )
    return {"answer": answer, "graph": graph, "used": used}


def exp13_memory_reset() -> dict:
    _MEMORY_STORE.clear()
    return {"ok": True, "graph": exp13_memory_graph()}


# ===========================================================================
# 实验十四：加密收据
# 这一节【不调用任何大模型】，纯粹是密码学 + 数据结构。
# 逻辑与 01.py 逐步对齐，只把 print 换成结构化返回。
# ===========================================================================
try:
    from nacl import signing
    from nacl.exceptions import BadSignatureError
    from jcs import canonicalize

    RECEIPT_DEPS_OK = True
except ImportError:
    RECEIPT_DEPS_OK = False


def b64url_nopad(data: bytes) -> str:
    """把二进制转成 base64url 文字（去掉末尾的 = 填充），方便放进 JSON。"""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(s: str) -> bytes:
    """把 base64url 文字解回二进制（先补回被去掉的 =）。"""
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + padding)


def sha256_canonical(obj) -> str:
    """对「JCS 规范化后的字节」算 SHA-256，返回带算法前缀的十六进制串。

    JCS(RFC 8785) 保证同一份数据的字节序列唯一，消除字典键序差异。
    """
    return f"sha256:{hashlib.sha256(canonicalize(obj)).hexdigest()}"


def sign_receipt(payload: dict, signing_key, verify_key) -> dict:
    """三步：规范化 → 哈希 → 签名，然后把签名和公钥附加到收据上。"""
    canonical = canonicalize(payload)
    message_hash = hashlib.sha256(canonical).digest()
    signature_bytes = signing_key.sign(message_hash).signature
    return {
        **payload,
        # ⚠️ signature 字段本身【不参与】签名计算，它是"签完之后"才加上去的
        "signature": {
            "alg": "EdDSA",
            "sig": b64url_nopad(signature_bytes),
            "public_key": b64url_nopad(bytes(verify_key)),
        },
    }


def verify_receipt(receipt: dict) -> bool:
    """验证收据签名 —— 只靠收据本身就能验，不需要联网、也不需要查密钥目录。"""
    sig_obj = receipt.get("signature")
    if not sig_obj or sig_obj.get("alg") != "EdDSA":
        return False
    # ⭐ 关键：把 signature 字段"摘掉"，还原出当初被签的那份内容
    #    （签名时是签完才加 signature，所以验签必须严格对称地摘掉）
    payload = {k: v for k, v in receipt.items() if k != "signature"}
    message_hash = hashlib.sha256(canonicalize(payload)).digest()
    try:
        verify_key = signing.VerifyKey(b64url_decode(sig_obj["public_key"]))
        # ⚠️ 验签失败不是返回 False，而是抛异常
        verify_key.verify(message_hash, b64url_decode(sig_obj["sig"]))
        return True
    except BadSignatureError:
        return False
    except Exception:  # noqa: BLE001
        return False


def receipt_hash(receipt: dict) -> str:
    """算「整张收据（含签名）」的哈希 —— 用来把收据串成链。

    注意与上面两个哈希区分：
      tool_args_hash / result_hash → 算"不含签名"的业务数据
      receipt_hash                → 算"含签名"的完整收据（用于串联链条）
    """
    return f"sha256:{hashlib.sha256(canonicalize(receipt)).hexdigest()}"


def make_receipt(
    tool_name: str,
    tool_args: dict,
    tool_result,
    sequence: int,
    previous_receipt_hash,
    signing_key,
    verify_key,
    agent_id: str = "xiaokun-travel-bot",
    policy_id: str = "xiaokun-travel-policy-v3",
) -> dict:
    """一步到位：组装 payload → 签名 → 返回收据。"""
    payload = {
        "type": "agent.tool_call.v1",
        "agent_id": agent_id,
        "tool_name": tool_name,
        # ⚠️ 只存哈希不存原文 —— 防止收据泄露敏感信息（如支付令牌）
        "tool_args_hash": sha256_canonical(tool_args),
        "result_hash": sha256_canonical(tool_result),
        "policy_id": policy_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sequence": sequence,
        "previous_receipt_hash": previous_receipt_hash,
    }
    return sign_receipt(payload, signing_key, verify_key)


def verify_chain(chain: list) -> list:
    """验证整条链（三重检查）：
      ① 每张收据的签名有效
      ② 每张（除创世外）必须正确引用上一张的哈希
      ③ 序号必须等于它在列表中的位置
    """
    results = []
    for i, receipt in enumerate(chain):
        sig_ok = verify_receipt(receipt)
        if i == 0:
            chain_ok = receipt["previous_receipt_hash"] is None
        else:
            chain_ok = receipt["previous_receipt_hash"] == receipt_hash(chain[i - 1])
        seq_ok = receipt["sequence"] == i
        results.append({
            "index": i,
            "tool": receipt["tool_name"],
            "signature_valid": sig_ok,
            "chain_link_valid": chain_ok,
            "sequence_valid": seq_ok,
            "overall_valid": sig_ok and chain_ok and seq_ok,
        })
    return results


class ReceiptedTool:
    """把任意函数包一层：每次调用都【自动】生成一张签名收据，并串成链。"""

    def __init__(self, name, fn, signing_key, verify_key, agent_id, policy_id):
        self.name = name
        self.fn = fn
        self.signing_key = signing_key
        self.verify_key = verify_key
        self.agent_id = agent_id
        self.policy_id = policy_id
        self.receipts: list = []

    def __call__(self, *args, **kwargs):
        result = self.fn(*args, **kwargs)
        previous_hash = receipt_hash(self.receipts[-1]) if self.receipts else None
        receipt = make_receipt(
            tool_name=self.name,
            tool_args={"args": list(args), "kwargs": kwargs},
            tool_result=result,
            sequence=len(self.receipts),
            previous_receipt_hash=previous_hash,
            signing_key=self.signing_key,
            verify_key=self.verify_key,
            agent_id=self.agent_id,
            policy_id=self.policy_id,
        )
        self.receipts.append(receipt)
        # ⭐ 返回【原函数的返回值】—— 调用方感觉不到"被包装过"，完全透明
        return result


def mock_lookup_flights(origin: str, destination: str, departure_date: str) -> list:
    """一个模拟的航班查询函数（用写死数据，不依赖外网）。"""
    return [
        {"flight": "QF11", "price": 1850, "stops": 0},
        {"flight": "UA864", "price": 1620, "stops": 1},
    ]


async def exp14_receipts(payload_text: str = "") -> dict:
    """
    完整演示五步（结构与 01.py 一一对应）：
      ① 签第一张收据
      ② 篡改收据 → 验签失败
      ③ 把收据串成链（查航班 → 占座 → 确认预订）
      ④ 篡改链条中间那张 → 精确定位失败项
      ⑤ ReceiptedTool 包装器自动生成收据
    """
    if not RECEIPT_DEPS_OK:
        return {"ok": False, "error": "需要 pynacl 和 jcs 依赖，当前未安装。pip install pynacl jcs"}

    signing_key = signing.SigningKey.generate()
    # 公钥由私钥"配套推导"出来，所以才能校验收据
    verify_key = signing_key.verify_key

    # ---------- ① 签第一张 ----------
    tool_args = {"origin": "SYD", "destination": "LAX",
                 "departure_date": "2026-06-15", "passengers": 2}
    tool_result = [
        {"flight": "QF11", "price": 1850, "stops": 0},
        {"flight": "UA864", "price": 1620, "stops": 1},
        {"flight": "DL11", "price": 1740, "stops": 0},
    ]
    payload = {
        "type": "agent.tool_call.v1",
        "agent_id": "xiaokun-travel-bot",
        "tool_name": "lookup_flights",
        "tool_args_hash": sha256_canonical(tool_args),
        "result_hash": sha256_canonical(tool_result),
        "policy_id": "xiaokun-travel-policy-v3",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sequence": 0,
        "previous_receipt_hash": None,
    }
    receipt = sign_receipt(payload, signing_key, verify_key)

    # ---------- ② 篡改 ----------
    tampered = copy.deepcopy(receipt)
    original_policy = tampered["policy_id"]
    tampered["policy_id"] = "xiaokun-travel-policy-PERMISSIVE"

    # ---------- ③ 串成链 ----------
    r0 = make_receipt(
        tool_name="lookup_flights",
        tool_args={"origin": "SYD", "destination": "LAX", "date": "2026-06-15"},
        tool_result=[{"flight": "QF11", "price": 1850}],
        sequence=0, previous_receipt_hash=None,
        signing_key=signing_key, verify_key=verify_key,
    )
    r1 = make_receipt(
        tool_name="hold_seat",
        tool_args={"flight": "QF11", "seat": "14A", "hold_minutes": 30},
        tool_result={"hold_id": "H8472", "expires_at": "2026-06-15T15:00:00Z"},
        sequence=1, previous_receipt_hash=receipt_hash(r0),
        signing_key=signing_key, verify_key=verify_key,
    )
    r2 = make_receipt(
        tool_name="confirm_booking",
        # 支付令牌只留占位符（脱敏）
        tool_args={"hold_id": "H8472", "payment_token": "tok_redacted"},
        tool_result={"booking_ref": "CT-09182", "status": "confirmed"},
        sequence=2, previous_receipt_hash=receipt_hash(r1),
        signing_key=signing_key, verify_key=verify_key,
    )
    chain = [r0, r1, r2]

    # ---------- ④ 篡改链中间那张 ----------
    tampered_chain = [copy.deepcopy(r) for r in chain]
    # 把占座时长从 30 分钟改成 9999 分钟 —— 比实际授权宽松得多
    # 攻击者改了参数，为了"自圆其说"也得改哈希；但哈希一改，签名（针对旧哈希算的）就对不上
    tampered_chain[1]["tool_args_hash"] = sha256_canonical(
        {"flight": "QF11", "seat": "14A", "hold_minutes": 9999}
    )

    # ---------- ⑤ 包装器 ----------
    receipted_lookup = ReceiptedTool(
        name="lookup_flights",
        fn=mock_lookup_flights,
        signing_key=signing_key,
        verify_key=verify_key,
        agent_id="xiaokun-travel-bot",
        policy_id="xiaokun-travel-policy-v3",
    )
    receipted_lookup(origin="SYD", destination="LAX", departure_date="2026-06-15")
    receipted_lookup(origin="SYD", destination="NRT", departure_date="2026-07-02")
    receipted_lookup(origin="MEL", destination="SIN", departure_date="2026-08-10")

    def slim(r):
        return {
            "tool_name": r["tool_name"],
            "agent_id": r["agent_id"],
            "policy_id": r["policy_id"],
            "sequence": r["sequence"],
            "timestamp": r["timestamp"],
            "previous_receipt_hash": r["previous_receipt_hash"],
            "tool_args_hash": r["tool_args_hash"],
            "result_hash": r["result_hash"],
            "signature": {
                "alg": r["signature"]["alg"],
                "sig": r["signature"]["sig"],
                "public_key": r["signature"]["public_key"],
            },
        }

    def chain_view(results, receipts):
        return [
            {**res, "receipt": slim(rec)} for res, rec in zip(results, receipts)
        ]

    return {
        "ok": True,
        "public_key": b64url_nopad(bytes(verify_key)),
        "step1": {
            "payload": payload,
            "receipt": slim(receipt),
            "valid": verify_receipt(receipt),
        },
        "step2": {
            "original_policy": original_policy,
            "tampered_policy": tampered["policy_id"],
            "valid_after_tamper": verify_receipt(tampered),
        },
        "step3": {
            "chain": chain_view(verify_chain(chain), chain),
            "all_valid": all(r["overall_valid"] for r in verify_chain(chain)),
        },
        "step4": {
            "chain": chain_view(verify_chain(tampered_chain), tampered_chain),
        },
        "step5": {
            "calls": len(receipted_lookup.receipts),
            "chain": chain_view(
                verify_chain(receipted_lookup.receipts), receipted_lookup.receipts
            ),
        },
    }


# ===========================================================================
# 实验十五：端到端集成面板
# ===========================================================================
PIPELINE_STAGES = [
    {"id": "exp5", "name": "RAG 检索", "desc": "先从知识库取资料"},
    {"id": "exp7", "name": "多智能体分工", "desc": "目的地专家 + 行程规划师接力"},
    {"id": "exp9", "name": "工作流审核", "desc": "前台产出 → 礼宾批准/打回"},
    {"id": "exp11", "name": "可观测性", "desc": "统计耗时与质量分"},
]


async def exp15_pipeline(question: str, stages: list[str] | None = None) -> dict:
    """按选定阶段顺序执行，逐步返回每阶段的产出。"""
    selected = stages or [s["id"] for s in PIPELINE_STAGES]
    runs: list[dict] = []

    for sid in selected:
        meta = next((s for s in PIPELINE_STAGES if s["id"] == sid), None)
        if not meta:
            continue
        t0 = time.perf_counter()
        try:
            if sid == "exp5":
                r = await exp5_rag(question, checker=False)
                out = r["answer"]
                extra = {"sources": [x["name_zh"] for x in r["sources"]]}
            elif sid == "exp7":
                r = await exp7_multi_agent(question)
                out = r["trace"][-1]["output"] if r["trace"] else ""
                extra = {"agents": [s["agent"] for s in r["trace"]]}
            elif sid == "exp9":
                r = await exp9_workflow(question, max_rounds=2)
                out = r["final"]
                extra = {"approved": r["approved"], "rounds": r["rounds"]}
            elif sid == "exp11":
                r = await exp11_observability(question)
                out = r["answer"]
                extra = {"metrics": r["metrics"], "scores": r["scores"]}
            else:
                continue
            runs.append({
                "id": sid, "name": meta["name"], "status": "ok",
                "ms": round((time.perf_counter() - t0) * 1000),
                "output": out, "extra": extra,
            })
        except Exception as e:  # noqa: BLE001
            runs.append({
                "id": sid, "name": meta["name"], "status": "error",
                "ms": round((time.perf_counter() - t0) * 1000),
                "output": f"{type(e).__name__}: {e}", "extra": {},
            })

    return {
        "runs": runs,
        "total_ms": sum(r["ms"] for r in runs),
        "ok_count": sum(1 for r in runs if r["status"] == "ok"),
    }
