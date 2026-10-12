# -*- coding: utf-8 -*-
"""
实验注册表：把 15 个实验统一成前端可用的元数据。

每个实验都声明：编号、标题、所属分组、说明、对应 01.py 的位置、输入控件类型。
前端只读这份表来渲染左侧导航和右侧面板，新增实验只要在这里加一条 + 写一个接口。
"""

from __future__ import annotations

EXPERIMENTS: list[dict] = [
    # ---------- 一 · 基础对话 ----------
    {
        "id": "exp1",
        "no": 1,
        "group": "基础对话",
        "title": "多工具 Agent",
        "desc": "智能体自主判断该调用哪个工具，并把工具结果组织成自然语言回答。",
        "source": "01.py 里 TravelAgent + get_destinations + check_destination_availability",
        "input": "chat",
        "placeholder": "例如：你们有哪些目的地？东京现在能订吗？",
        "samples": [
            "你们有哪些目的地？东京现在能订吗？",
            "开普敦可以预订吗？",
            "我想找个温暖的海滩度假地，有什么推荐？",
        ],
        "badge": "工具调用",
    },
    {
        "id": "exp2",
        "no": 2,
        "group": "基础对话",
        "title": "会话记忆",
        "desc": "多轮对话共享上下文，第二轮能接着第一轮的话往下说。",
        "source": "01.py 的 session_demo：agent.create_session()",
        "input": "chat",
        "placeholder": "先问有哪些目的地，再追问『哪几个温暖』试试",
        "samples": [
            "你们有哪些目的地可以订？",
            "我想去温暖一点的地方，哪些还能订？",
        ],
        "badge": "多轮",
    },
    {
        "id": "exp3",
        "no": 3,
        "group": "基础对话",
        "title": "结构化输出",
        "desc": "强制模型按固定表格返回，而不是自由发挥的文字，本地再做校验。",
        "source": "01.py 的 structured_demo：DestinationRecommendation + TravelRecommendations",
        "input": "text",
        "placeholder": "描述你的旅行偏好，例如：想看建筑和美食，预算 2000 美元",
        "samples": [
            "想看建筑和美食，预算 2000 美元",
            "喜欢海滩和潜水，预算不高，想省钱",
        ],
        "badge": "JSON",
    },
    {
        "id": "exp4",
        "no": 4,
        "group": "检索与工具",
        "title": "工具箱复用",
        "desc": "一次提问里同时包含两个需求，模型必须『先拿名单、再逐个查』，有序用两个工具。",
        "source": "01.py 的 travel_tool_demo：复用 travel_tools 工具箱",
        "input": "text",
        "placeholder": "例如：你们有哪些目的地？其中哪些现在还能订？",
        "samples": [
            "你们有哪些目的地？其中哪些现在还能订？",
            "列出所有目的地，并告诉我哪些已经订满了",
        ],
        "badge": "多工具",
    },
    {
        "id": "exp5",
        "no": 5,
        "group": "检索与工具",
        "title": "RAG 检索增强",
        "desc": "先查自己的知识库再回答。可切换『普通版』与『爱核对版』对比效果差异。",
        "source": "01.py 的 rag_demo：TravelRAGAgent vs TravelRAGCheckerAgent",
        "input": "text",
        "placeholder": "例如：预算有限想去温暖的地方，有什么推荐？",
        "samples": [
            "预算有限想去温暖的地方，有什么推荐？",
            "适合 4 月出行、日均 1000 元以内的目的地",
        ],
        "badge": "RAG",
        "options": [
            {"key": "checker", "label": "爱核对版（反复核实）", "type": "toggle", "default": False},
        ],
    },
    {
        "id": "exp6",
        "no": 6,
        "group": "基础对话",
        "title": "上下文管理",
        "desc": "长对话怎么『记得住、又不啰嗦』。两种手段：靠指令压缩，或靠工具主动写摘要。",
        "source": "01.py 的 context_management_demo：ContextAwareAgent + SummarizingTravelAgent",
        "input": "chat",
        "placeholder": "先说要去的国家和喜好，再补充预算日期，最后让它汇总",
        "samples": [
            "我打算去日本，喜欢寿司、寺庙和摄影。",
            "预算 2 万，一个人去 10 天，4 月出发。",
            "根据我前面说的，帮我汇总一份完整计划。",
        ],
        "badge": "摘要",
        "options": [
            {"key": "summarize", "label": "启用摘要工具", "type": "toggle", "default": False},
        ],
    },
    # ---------- 三 · 协作与编排 ----------
    {
        "id": "exp7",
        "no": 7,
        "group": "协作与编排",
        "title": "多智能体协作",
        "desc": "把大任务拆给两个专科智能体：目的地专家只管『去哪』，行程规划师只管『怎么去』。",
        "source": "01.py 的 multi_agent_demo：DestinationExpert + LogisticsPlanner",
        "input": "text",
        "placeholder": "例如：我想找个能看建筑、吃得好的地方，7 天左右",
        "samples": [
            "我想找个能看建筑、吃得好的地方，7 天左右",
            "预算不高但想看海，帮我定个目的地再排行程",
        ],
        "badge": "2 智能体",
    },
    {
        "id": "exp8",
        "no": 8,
        "group": "协作与编排",
        "title": "规划者 + 管家",
        "desc": "规划者先把需求拆成结构化任务清单，管家再拿着清单调用订票/订房/订活动工具逐条执行。",
        "source": "01.py 的 planner_concierge_demo：TravelPlanner + Concierge",
        "input": "text",
        "placeholder": "例如：为一对情侣规划 7 天巴黎艺术美食之旅，预算 5000 美元",
        "samples": [
            "为一对情侣规划 7 天巴黎艺术美食之旅，预算 5000 美元",
            "一家三口 5 天东京亲子游，预算 3 万人民币",
        ],
        "badge": "计划+执行",
    },
    {
        "id": "exp9",
        "no": 9,
        "group": "协作与编排",
        "title": "工作流流水线",
        "desc": "先画好流程图（谁接谁），再顺序执行。前台给出推荐，礼宾审核员批准或打回改进。",
        "source": "01.py 的 workflow_demo：FrontDesk → Reviewer，WorkflowBuilder + WorkflowViz",
        "input": "text",
        "placeholder": "例如：我想去巴黎，第一次去，帮我推荐个去处",
        "samples": [
            "我想去巴黎，第一次去，帮我推荐个去处",
            "去东京五天，想体验最地道的，不要游客路线",
        ],
        "badge": "流水线",
    },
    # ---------- 四 · 质量与治理 ----------
    {
        "id": "exp10",
        "no": 10,
        "group": "质量与治理",
        "title": "元认知：回退与自评",
        "desc": "主系统失败自动切备用系统，并如实告诉用户『我换了系统』；回复后还有第三方质量评估打分。",
        "source": "01.py 的 metacognition_demo：FlightBookingAgent + ResponseEvaluator",
        "input": "text",
        "placeholder": "试试查『柏林』的航班——它只在备用系统里，能触发回退",
        "samples": [
            "有哪些飞往柏林的航班？",
            "查一下去巴黎的航班",
            "帮我查去悉尼的航班",
        ],
        "badge": "回退",
    },
    {
        "id": "exp11",
        "no": 11,
        "group": "质量与治理",
        "title": "生产环境视角",
        "desc": "把一次 Agent 调用拆成可观测指标：各阶段耗时、工具调用次数、质量评分。",
        "source": "01.py 的 production_demo：耗时统计 + ResponseEvaluator 四项打分",
        "input": "text",
        "placeholder": "例如：我想在巴黎安排一天行程，推荐航班和活动",
        "samples": [
            "我想在巴黎安排一天行程，推荐航班和活动",
            "东京一日游怎么安排？帮我配个航班",
        ],
        "badge": "可观测",
    },
    {
        "id": "exp12",
        "no": 12,
        "group": "质量与治理",
        "title": "人工审批关卡",
        "desc": "低/中风险自动放行，高风险拦下由人决定批准/拒绝/上报；被拒后把原因反馈给模型重新提议。",
        "source": "01.py 的 gate_demo：classify_risk + tiered_gate + 修订循环 + JSONL 审计日志",
        "input": "text",
        "placeholder": "例如：给客户发送一封关于升舱选项的营销邮件（高风险，会被拦下）",
        "samples": [
            "给客户发送一封关于升舱选项的营销邮件",
            "查询西雅图未来几天的天气，用于客户行程规划",
            "为客户安排一个提醒：航班起飞前 24 小时提醒他办值机",
            "帮客户预订东京的酒店并更新行程记录",
        ],
        "badge": "人工审批",
    },
    # ---------- 五 · 信任与记忆 ----------
    {
        "id": "exp13",
        "no": 13,
        "group": "信任与记忆",
        "title": "长期记忆图谱",
        "desc": "把偏好抽成三元组存进知识图谱，脱离单次会话——换个新会话照样查得到。",
        "source": "01.py 的 cognee_demo（cognee 依赖太重，改用轻量图谱实现同等能力）",
        "input": "none",
        "badge": "知识图谱",
        "note": "原版用 cognee + GLiNER 抽取实体建图；这里用规则抽取已知字段，能力目标相同、精度略低。",
    },
    {
        "id": "exp14",
        "no": 14,
        "group": "信任与记忆",
        "title": "加密收据",
        "desc": "给智能体每一次工具调用盖章：Ed25519 签名 + 哈希链，篡改必被发现。全程不调用大模型。",
        "source": "01.py 的 receipt_demo：sign_receipt / verify_chain / ReceiptedTool",
        "input": "none",
        "badge": "Ed25519",
    },
    {
        "id": "exp15",
        "no": 15,
        "group": "信任与记忆",
        "title": "端到端集成",
        "desc": "选一组实验按序执行，实时查看每个阶段的耗时与产出，看整条链路如何串起来。",
        "source": "01.py 的 main()：把 14 个 demo 顺序跑一遍（此处改为可视化编排面板）",
        "input": "text",
        "placeholder": "例如：我想去东京，喜欢美食和寺庙，5 天，预算 1.5 万",
        "samples": [
            "我想去东京，喜欢美食和寺庙，5 天，预算 1.5 万",
            "10 月去欧洲，想看建筑，预算 8000",
        ],
        "badge": "编排",
    },
]


def by_id(exp_id: str) -> dict | None:
    return next((e for e in EXPERIMENTS if e["id"] == exp_id), None)


def groups() -> list[dict]:
    """按分组聚合，供前端渲染导航。"""
    order: list[str] = []
    bucket: dict[str, list] = {}
    for e in EXPERIMENTS:
        if e["group"] not in bucket:
            bucket[e["group"]] = []
            order.append(e["group"])
        bucket[e["group"]].append({
            "id": e["id"], "no": e["no"], "title": e["title"],
            "badge": e.get("badge"), "input": e["input"],
        })
    return [{"group": g, "items": bucket[g]} for g in order]


def public_list() -> list[dict]:
    """给前端的完整元数据（去掉内部字段）。"""
    return EXPERIMENTS
