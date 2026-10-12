# -*- coding: utf-8 -*-
"""
实验 7-9：多智能体协作与工作流编排。

对应 01.py：
  实验七  多智能体协作    → exp7_multi_agent
          ① DestinationExpert 只负责"去哪"，并查工具确认可订性
          ② LogisticsPlanner  只负责"怎么去"，做行程、选航班酒店
          用 "Do NOT ..." 划清职责边界，避免抢活
  实验八  规划者 + 管家   → exp8_planner_concierge
          ① 规划者：把请求拆成【结构化】任务清单（JSON）
          ② 管家：拿着清单调用订票/订房/订活动工具逐条执行
  实验九  工作流流水线    → exp9_workflow
          FrontDesk(前台) --推荐--> Concierge(礼宾审核员) --批准/改进-->
          先画流程图（谁接谁），再顺序执行
"""

from __future__ import annotations

import time

from . import llm, tools_lib as T
from .llm import Tool
from .exp_basics import _kb_brief


# ===========================================================================
# 实验七：多智能体协作
# ===========================================================================
DESTINATION_EXPERT = (
    "你是「目的地专家」，只负责回答『去哪』这一类问题。\n"
    "职责：根据用户的偏好推荐目的地，并用 check_destination_availability 工具确认可订性。\n"
    "边界：不要安排行程、不要选航班、不要订酒店——那些不是你的事。\n"
    "输出：一段简短的推荐（含为什么选它、是否可订）。 "
    + llm.ZH_RULE
)

LOGISTICS_PLANNER = (
    "你是「行程规划师」，只负责回答『怎么去、怎么安排』这一类问题。\n"
    "职责：基于既定目的地，安排每日行程节奏，并给出航班与住宿建议。\n"
    "边界：不要重新推荐目的地、不要质疑目的地选择——那是目的地专家的事。\n"
    "输出：分天的行程安排 + 交通住宿建议。 "
    + llm.ZH_RULE
)


async def exp7_multi_agent(question: str) -> dict:
    """两个专科智能体依次接力，各自只干自己的活。"""
    trace: list[dict] = []
    t0 = time.perf_counter()

    # ---------- ① 目的地专家（带工具） ----------
    step1 = await llm.run_tools(
        [
            {"role": "system", "content": DESTINATION_EXPERT + "\n\n可参考的资料：\n" + _kb_brief()},
            {"role": "user", "content": question},
        ],
        [Tool(T.get_destination_details)],
        temperature=0.5,
    )
    trace.append({
        "agent": "目的地专家 DestinationExpert",
        "role": "只负责『去哪』并核实可订性",
        "output": step1["content"],
        "tools": [s["tool"] for s in step1["steps"]],
    })

    # ---------- ② 行程规划师（接力，把专家的结论作为输入） ----------
    step2 = await llm.text(
        [
            {"role": "system", "content": LOGISTICS_PLANNER},
            {
                "role": "user",
                "content": (
                    f"用户的原始需求：{question}\n\n"
                    f"目的地专家给出的结论：\n{step1['content']}\n\n"
                    "请基于这个目的地，安排具体行程与交通住宿。"
                ),
            },
        ],
        temperature=0.5,
    )
    trace.append({
        "agent": "行程规划师 LogisticsPlanner",
        "role": "只负责『怎么去』，安排行程与交通住宿",
        "output": step2,
        "tools": [],
    })

    return {
        "trace": trace,
        "elapsed": round(time.perf_counter() - t0, 2),
    }


# ===========================================================================
# 实验八：规划者 + 管家
# ===========================================================================
PLANNER_SYSTEM = (
    "你是一位旅行规划智能体。当收到一个旅行需求时：\n"
    "1. 把它拆成具体的子任务（航班、酒店、活动、后勤）\n"
    "2. 给每个子任务指派合适的专员（flight_agent / hotel_agent / activity_agent）\n"
    "3. 设定优先级，并标出任务之间的依赖关系\n"
    "4. 估算总预算"
)

PLAN_SCHEMA = (
    '{"destination": "string", "trip_duration_days": 0, '
    '"subtasks": [{"task_id": 0, "description": "string", '
    '"assigned_agent": "flight_agent|hotel_agent|activity_agent", '
    '"priority": "high|medium|low", "dependencies": [0]}], '
    '"total_estimated_budget_usd": 0, "notes": "string"}'
)

CONCIERGE_SYSTEM = (
    "你是一位旅行管家，负责执行一份结构化旅行计划。"
    "请使用可用工具完成每一项子任务，按依赖关系顺序执行，最后汇总结果。 "
    + llm.ZH_RULE
)

CONCIERGE_TOOLS = [
    Tool(T.book_flight),
    Tool(T.reserve_hotel),
    Tool(T.book_activity),
]


async def exp8_planner_concierge(request: str) -> dict:
    """① 规划者出结构化清单 → ② 管家带着工具照着清单执行。"""
    t0 = time.perf_counter()

    # ---------- ① 规划者：结构化任务清单 ----------
    # 对应 01.py：不能用 options={"response_format": TravelPlan}（DeepSeek 报 400），
    # 所以走 json_object 模式 + 本地校验。
    plan, raw = await llm.json_call(
        system=PLANNER_SYSTEM,
        user=request,
        schema_hint=PLAN_SCHEMA,
    )

    plan_ok = bool(plan and isinstance(plan.get("subtasks"), list) and plan["subtasks"])
    if plan_ok:
        # 规范化字段，避免模型少给字段导致前端渲染崩
        plan.setdefault("destination", "未指定")
        plan.setdefault("trip_duration_days", 0)
        plan.setdefault("total_estimated_budget_usd", 0)
        plan.setdefault("notes", "")
        for i, st in enumerate(plan["subtasks"]):
            st.setdefault("task_id", i)
            st.setdefault("assigned_agent", "activity_agent")
            st.setdefault("priority", "medium")
            st.setdefault("dependencies", [])

    # ---------- ② 管家：照单执行 ----------
    exec_result = {"content": "", "steps": []}
    if plan_ok:
        lines = "\n".join(
            f"- [{t.get('priority')}] {t.get('task_id')}. {t.get('description')} "
            f"(专员: {t.get('assigned_agent')}, 依赖: {t.get('dependencies')})"
            for t in plan["subtasks"]
        )
        exec_result = await llm.run_tools(
            [
                {"role": "system", "content": CONCIERGE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"请执行以下旅行计划（目的地 {plan['destination']}，"
                        f"{plan['trip_duration_days']} 天，"
                        f"预算 ${plan['total_estimated_budget_usd']}）：\n{lines}"
                    ),
                },
            ],
            CONCIERGE_TOOLS,
            max_rounds=8,
            temperature=0.3,
        )

    return {
        "plan": plan,
        "plan_ok": plan_ok,
        "plan_raw": raw,
        "execution": exec_result["content"],
        "steps": exec_result["steps"],
        "elapsed": round(time.perf_counter() - t0, 2),
    }


# ===========================================================================
# 实验九：工作流流水线
# ===========================================================================
FRONT_DESK = (
    "你是「前台顾问」，负责接待用户并给出一次推荐。\n"
    "只给出【一条】最合适的推荐，言简意赅，不要闲聊。 "
    + llm.ZH_RULE
)

REVIEWER = (
    "你是「礼宾审核员」，负责判断前台给出的推荐是不是『最地道、不落俗套』的。\n"
    "如果认可，就以【批准】开头并给出最终推荐；\n"
    "如果不认可，就以【改进】开头，指出具体问题并给出更好的方案。 "
    + llm.ZH_RULE
)


def exp9_workflow_graph() -> dict:
    """工作流的拓扑（对应 01.py 的 WorkflowViz / Mermaid 输出）。"""
    return {
        "mermaid": (
            "graph LR\n"
            "    U([用户输入]) --> A[前台顾问 FrontDesk]\n"
            "    A -->|初步推荐| B[礼宾审核员 Reviewer]\n"
            "    B -->|批准| C([最终推荐])\n"
            "    B -->|改进建议| A"
        ),
        "nodes": [
            {"id": "FrontDesk", "label": "前台顾问", "desc": "一次只给一条推荐，言简意赅"},
            {"id": "Reviewer", "label": "礼宾审核员", "desc": "判断是否最地道，批准或给改进方向"},
        ],
        "edges": [
            {"from": "用户输入", "to": "前台顾问"},
            {"from": "前台顾问", "to": "礼宾审核员", "label": "初步推荐"},
            {"from": "礼宾审核员", "to": "前台顾问", "label": "改进建议"},
        ],
    }


async def exp9_workflow(question: str, max_rounds: int = 3) -> dict:
    """
    执行工作流：前台给出推荐 → 礼宾审核 → 不通过就打回前台改进，最多 max_rounds 轮。
    对应 01.py 的 WorkflowBuilder.add_edge(front_desk, reviewer) + workflow.run()。
    """
    t0 = time.perf_counter()
    stages: list[dict] = []
    draft = ""
    rejection: str | None = None
    approved = False

    for round_no in range(1, max_rounds + 1):
        # ---- 前台 ----
        fd_input = question
        if rejection:
            fd_input += (
                f"\n\n（上一版推荐被礼宾审核员打回，改进意见：{rejection}。"
                "请换一条更地道的推荐。）"
            )
        draft = await llm.text(
            [
                {"role": "system", "content": FRONT_DESK + "\n\n可参考资料：\n" + _kb_brief()},
                {"role": "user", "content": fd_input},
            ],
            temperature=0.8,
        )
        stages.append({
            "round": round_no, "stage": "前台顾问", "kind": "draft",
            "text": draft, "status": "已提交",
        })

        # ---- 礼宾审核 ----
        review = await llm.text(
            [
                {"role": "system", "content": REVIEWER},
                {
                    "role": "user",
                    "content": f"用户需求：{question}\n\n前台顾问的推荐：\n{draft}\n\n请审核。",
                },
            ],
            temperature=0.4,
        )
        ok = review.lstrip().startswith("【批准】") or "【批准】" in review[:20]
        stages.append({
            "round": round_no, "stage": "礼宾审核员", "kind": "review",
            "text": review, "status": "批准" if ok else "打回改进",
        })

        if ok:
            approved = True
            break
        rejection = review

    return {
        "stages": stages,
        "approved": approved,
        "final": draft,
        "rounds": len([s for s in stages if s["kind"] == "review"]),
        "elapsed": round(time.perf_counter() - t0, 2),
    }
