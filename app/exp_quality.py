# -*- coding: utf-8 -*-
"""
实验 10-12：质量、可观测与人工治理。

对应 01.py：
  实验十  元认知设计模式   → exp10_metacognition
          ① 回退(fallback)：主系统挂了去备用系统，并【如实告诉用户"我换了系统"】
          ② 自我反思：每次回复后评估自己答得完不完整、有没有用
          ③ 第三方评估：再派一个"质量评估员"给回复打分
  实验十一 生产环境视角    → exp11_observability
          ① 可观测性：至少把【耗时】量出来
          ② 质量评估：完整性 / 准确性 / 有用性 / 总分
  实验十二 人工审批关卡    → exp12_gate
          低风险 → 自动放行
          中风险 → 自动放行（但排队等批量复查）
          高风险 → 拦下来，由人决定：批准 / 拒绝 / 上报
          被拒后 → 把拒绝原因反馈给模型，让它改一版 = 修订循环
"""

from __future__ import annotations

import time
import json
from datetime import datetime, timezone
from pathlib import Path

from . import llm, tools_lib as T
from .llm import Tool

GATE_LOG_PATH = Path(__file__).parent.parent / "gate_log_web.jsonl"


# ===========================================================================
# 实验十：元认知（回退 + 自我反思 + 第三方评估）
# ===========================================================================
FLIGHT_AGENT_SYSTEM = (
    "你是一位具备自我反思能力的机票预订顾问。\n"
    "查询航班时：\n"
    "1. 先尝试主系统（get_flight_times）\n"
    "2. 如果主系统失败（404 错误），先如实承认这个错误，再尝试备用系统（get_flight_times_backup）\n"
    "3. 一定要向用户解释发生了什么——对『回退』保持透明\n"
    "4. 如果两个系统都失败，道歉并给出替代建议\n"
    "回答完成后，简要评估一下你的回答是否完整、是否有帮助。 "
    + llm.ZH_RULE
)

EVALUATOR_SYSTEM = (
    "你是旅行代理回复的质量评估员。给定一个旅行问题和代理的回复，请评估：\n"
    "1. 完整性：它是否回答了问题的所有部分？（1-5 分）\n"
    "2. 准确性：信息是否正确？（1-5 分）\n"
    "3. 有用性：旅行者会觉得这有用吗？（1-5 分）\n"
    "请给出简短评估、各项评分和一条改进建议。 "
    + llm.ZH_RULE
)


async def exp10_metacognition(question: str) -> dict:
    t0 = time.perf_counter()

    # ---------- ① 带回退能力的智能体 ----------
    result = await llm.run_tools(
        [
            {"role": "system", "content": FLIGHT_AGENT_SYSTEM},
            {"role": "user", "content": question},
        ],
        [Tool(T.get_flight_times), Tool(T.get_flight_times_backup)],
        max_rounds=6,
    )

    # 从步骤里还原"有没有发生回退"
    fallback = None
    for s in result["steps"]:
        if s["tool"] == "get_flight_times" and "失败" in str(s["result"]):
            fallback = {"triggered": True, "reason": str(s["result"])[:120],
                        "destination": s["arguments"].get("destination")}
        elif s["tool"] == "get_flight_times_backup":
            fallback = {**(fallback or {"triggered": True, "reason": ""}),
                        "backup_used": True,
                        "backup_result": str(s["result"])[:160]}
    if fallback is None:
        fallback = {"triggered": False, "backup_used": False}

    # ---------- ② 第三方质量评估 ----------
    evaluation = await llm.text(
        [
            {"role": "system", "content": EVALUATOR_SYSTEM},
            {
                "role": "user",
                "content": f"问题：{question}\n\n代理的回复：\n{result['content']}\n\n请评估以上回复。",
            },
        ],
        temperature=0.3,
    )

    # 尝试从评估文字里抽出三项分数
    scores = _parse_scores(evaluation)

    return {
        "answer": result["content"],
        "steps": result["steps"],
        "fallback": fallback,
        "evaluation": evaluation,
        "scores": scores,
        "elapsed": round(time.perf_counter() - t0, 2),
    }


# ===========================================================================
# 实验十一：生产环境视角（可观测性 + 质量评估）
# ===========================================================================
PRODUCTION_SYSTEM = (
    "你是一位乐于助人的旅游顾问。请使用可用工具帮用户规划行程，"
    "提供全面、可执行的旅行建议。 "
    + llm.ZH_RULE
)

SCORE_SYSTEM = (
    "你评估旅游代理的回复，标准如下：\n"
    "1. 完整性（1-5）：是否既涵盖了航班，又涵盖了活动？\n"
    "2. 准确性（1-5）：信息是否前后一致？\n"
    "3. 有用性（1-5）：旅行者会觉得这可以直接照着做吗？\n"
    "4. 总体评分（1-5）\n"
    "请为每一项给出评分和一句简短说明。 "
    + llm.ZH_RULE
)


async def exp11_observability(question: str) -> dict:
    """把一次完整的 Agent 调用拆成可观测的指标：各阶段耗时 + 工具调用 + 质量分。"""
    timeline: list[dict] = []

    # ---------- 阶段 1：Agent 执行（含工具调用） ----------
    t0 = time.perf_counter()
    result = await llm.run_tools(
        [
            {"role": "system", "content": PRODUCTION_SYSTEM},
            {"role": "user", "content": question},
        ],
        [Tool(T.get_flight_info), Tool(T.get_activity_suggestions)],
        max_rounds=6,
    )
    llm_ms = round((time.perf_counter() - t0) * 1000)
    timeline.append({"stage": "Agent 推理 + 工具调用", "ms": llm_ms})

    # ---------- 阶段 2：质量评估 ----------
    t1 = time.perf_counter()
    evaluation = await llm.text(
        [
            {"role": "system", "content": SCORE_SYSTEM},
            {"role": "user", "content": f"请评估这条旅游代理回复：\n\n{result['content']}"},
        ],
        temperature=0.3,
    )
    eval_ms = round((time.perf_counter() - t1) * 1000)
    timeline.append({"stage": "质量评估", "ms": eval_ms})

    total_ms = llm_ms + eval_ms
    scores = _parse_scores(evaluation)

    return {
        "answer": result["content"],
        "steps": result["steps"],
        "evaluation": evaluation,
        "scores": scores,
        "metrics": {
            "total_ms": total_ms,
            "llm_ms": llm_ms,
            "eval_ms": eval_ms,
            "tool_calls": len(result["steps"]),
            "answer_chars": len(result["content"]),
            # 粗估 token：中文约 1.5 字/token
            "est_tokens": int(len(result["content"]) / 1.5),
        },
        "timeline": timeline,
    }


# ===========================================================================
# 实验十二：人工审批关卡
# ===========================================================================
# 关键词表直接沿用 01.py（含中文词），并保留那处安全修正：
# 删掉了 "weather" / "天气" —— 它是名词不是动作词，
# 否则"今天天气不错"会被误判成低风险自动放行。
LOW_RISK_KEYWORDS = {
    "look", "lookup", "search", "fetch", "read", "query", "view",
    "get", "list", "summarize",
    "查", "查询", "搜索", "阅读", "查看", "获取", "列出", "总结", "概述",
}
HIGH_RISK_KEYWORDS = {
    "send", "email", "post", "publish", "charge", "pay", "transfer",
    "delete", "drop", "cancel", "refund",
    "发送", "邮件", "发布", "收费", "付款", "支付", "转账", "删除", "取消", "退款",
}
MEDIUM_RISK_KEYWORDS = {
    "cache", "schedule", "reminder", "book", "reserve", "update",
    "increment", "log",
    "缓存", "安排", "日程", "提醒", "预订", "预约", "更新", "递增", "记录",
}

AUTO_APPROVE_REASONS = {
    "low": "自动批准（低风险）",
    "medium": "自动批准（中风险，已排队等批量复查）",
}

RISK_LABELS = {"low": "低风险", "medium": "中风险", "high": "高风险"}


def classify_risk(action: str) -> str:
    """把动作分成 low / medium / high 三级。

    先查高风险（最严重），再查低风险（只读类），最后查中风险。
    ★ 认不出来的动作默认归 medium，不是 low —— 只读词表总有盲区，
      把"看不懂的动作"送进批量复查，比直接自动执行安全得多。
    """
    text = action.lower()
    for kw in HIGH_RISK_KEYWORDS:
        if kw in text:
            return "high"
    for kw in LOW_RISK_KEYWORDS:
        if kw in text:
            return "low"
    for kw in MEDIUM_RISK_KEYWORDS:
        if kw in text:
            return "medium"
    return "medium"


def gate_action(action: str, risk_tier: str, attempt: int = 0,
                human_decision: str | None = None) -> dict:
    """执行一次"行动前关卡"。

    decision 只能是 approve / deny / escalate。
    无人值守时（human_decision=None）遇到高风险会挂起等前端审批。
    """
    if risk_tier in AUTO_APPROVE_REASONS:
        return {
            "decision": "approve",
            "reason": AUTO_APPROVE_REASONS[risk_tier],
            "action": action,
            "risk_tier": risk_tier,
            "auto": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    if human_decision in ("approve", "deny", "escalate"):
        return {
            "decision": human_decision,
            "reason": f"操作员输入：{human_decision}",
            "action": action,
            "risk_tier": risk_tier,
            "auto": False,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    # 需要人工审批但还没给决定 → 挂起
    return {
        "decision": "pending",
        "reason": "高风险动作，等待人工审批",
        "action": action,
        "risk_tier": risk_tier,
        "auto": False,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def log_decision(decision: dict) -> None:
    """把一次关卡决定追加写入 JSONL 审计日志（不管批准还是拒绝都留一笔）。"""
    with GATE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")


def read_gate_log(limit: int = 30) -> list[dict]:
    """读取审计日志（最新的排在前面）。"""
    if not GATE_LOG_PATH.exists():
        return []
    lines = GATE_LOG_PATH.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:][::-1]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clear_gate_log() -> None:
    if GATE_LOG_PATH.exists():
        GATE_LOG_PATH.unlink()


ACTION_PLANNER_SYSTEM = (
    "你是一个智能体的动作规划器。针对用户的目标，提出【一个】具体的下一步动作，"
    "用一句简短的话表达。\n"
    "如果给出了上一版的拒绝原因，请提出一个【不同】的动作来回应那个原因。\n"
    "只回复那一句动作描述——不要解释、不要分点、不要引号。 "
    + llm.ZH_RULE
)


async def propose_action(goal: str, prior_rejection: str | None = None) -> str:
    """让大模型为某个目标提一个具体的下一步动作。

    传入"上一次的拒绝原因"后，它会被反馈回去，模型下一次就会避开同样的坑。
    （对应 01.py 的 propose_action）
    """
    user_text = f"目标：{goal}"
    if prior_rejection:
        user_text += f"\n\n上一版提议被拒绝了，原因：{prior_rejection}"

    raw = await llm.text(
        [
            {"role": "system", "content": ACTION_PLANNER_SYSTEM},
            {"role": "user", "content": user_text},
        ],
        temperature=0.7,
    )
    # 清洗：去掉可能带上的引号/前缀
    s = raw.strip().strip('"').strip("「」").strip()
    for prefix in ("动作：", "建议：", "下一步："):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    return s.split("\n")[0].strip()


async def exp12_gate(goal: str, max_revisions: int = 2) -> dict:
    """
    提议 → 过关 → 被拒就修订，最多 max_revisions 次。

    返回里若 need_approval=True，说明卡在人工审批上，
    需要前端带着 human_decision 重新调用才会继续。
    """
    prior_reason: str | None = None
    attempts: list[dict] = []
    decision: dict = {}

    for attempt in range(max_revisions + 1):
        action = await propose_action(goal, prior_rejection=prior_reason)
        tier = classify_risk(action)
        decision = gate_action(action, tier, attempt=attempt)
        entry = {**decision, "attempt": attempt, "risk_label": RISK_LABELS.get(tier, tier)}
        attempts.append(entry)

        if decision["decision"] == "pending":
            # 高风险且无人审批：停在这里，把待审批动作交给前端
            log_decision(entry)
            return {
                "status": "pending",
                "need_approval": True,
                "pending": entry,
                "goal": goal,
                "attempts": attempts,
                "resume_from": attempt,
                "prior_reason": prior_reason,
            }

        log_decision(entry)

        if decision["decision"] == "approve":
            return {
                "status": "approved",
                "need_approval": False,
                "final": entry,
                "goal": goal,
                "attempts": attempts,
            }

        # 被拒 → 记下原因，下一轮喂回给模型
        prior_reason = decision["reason"]

    return {
        "status": "max_revisions_reached",
        "need_approval": False,
        "final": {**decision, "final": "达到最大修订次数"},
        "goal": goal,
        "attempts": attempts,
    }


async def exp12_resume(goal: str, action: str, human_decision: str,
                       prior_reason: str | None = None,
                       attempt: int = 0) -> dict:
    """人工给出审批决定后，继续这条流程。"""
    tier = classify_risk(action)
    decision = gate_action(action, tier, attempt=attempt, human_decision=human_decision)
    entry = {**decision, "attempt": attempt, "risk_label": RISK_LABELS.get(tier, tier)}
    log_decision(entry)

    attempts = [entry]

    if human_decision == "approve":
        return {"status": "approved", "need_approval": False, "final": entry,
                "goal": goal, "attempts": attempts}

    if human_decision == "escalate":
        return {"status": "escalated", "need_approval": False, "final": entry,
                "goal": goal, "attempts": attempts}

    # deny → 把拒绝原因反馈给模型，让它重新提一版
    feedback = f"操作员拒绝了该动作，原因：{entry['reason']}"
    resumed = await exp12_gate(goal, max_revisions=1)
    return {
        "status": resumed["status"],
        "need_approval": resumed.get("need_approval", False),
        "final": resumed.get("final"),
        "pending": resumed.get("pending"),
        "goal": goal,
        "attempts": attempts + resumed["attempts"],
        "denied_reason": feedback,
    }


# ===========================================================================
# 辅助：从评估文字里抽取分数
# ===========================================================================
import re

_SCORE_PATTERNS = [
    ("completeness", r"完整性[^\d]{0,20}(\d)"),
    ("accuracy", r"准确性[^\d]{0,20}(\d)"),
    ("helpfulness", r"有用性[^\d]{0,20}(\d)"),
    ("overall", r"(?:总体评分|总分|总体)[^\d]{0,20}(\d)"),
]


def _parse_scores(text: str) -> dict:
    out: dict[str, int] = {}
    for key, pat in _SCORE_PATTERNS:
        m = re.search(pat, text or "")
        if m:
            v = int(m.group(1))
            if 1 <= v <= 5:
                out[key] = v
    return out
