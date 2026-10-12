# -*- coding: utf-8 -*-
"""
实验共用的工具函数库。

01.py 里有三个工具：get_destinations / check_destination_availability / get_destination_details，
它们在多个实验里被反复复用（01.py 用 travel_tools = [...] 这个"工具箱列表"来复用）。
这里把它们集中实现一次，各实验按需取用，对应 01.py 实验四的"工具箱复用"思想。
"""

from __future__ import annotations

from . import knowledge_base as kb

# 与 01.py 一致：故意把部分目的地设为"已满"，用来演示可订性查询
AVAILABILITY: dict[str, bool] = {
    "Barcelona": True, "巴塞罗那": True,
    "Paris": True, "巴黎": True,
    "Tokyo": True, "东京": True,
    "Sydney": True, "悉尼": True,
    "Bali": True, "巴厘岛": True,
    "New York City": True, "纽约": True,
    "Cairo": True, "开罗": True,
    "Berlin": True, "柏林": True,
    "Rio de Janeiro": True, "里约热内卢": True,
    "Istanbul": True, "伊斯坦布尔": True,
    # 这两个故意设为不可订（对应 01.py 里的 Cape Town / Dubai）
    "Cape Town": False, "开普敦": False,
    "Chiang Mai": False, "清迈": False,
}


def get_destinations() -> list[str]:
    """Get a list of popular vacation destinations."""
    return [d["name_zh"] for d in kb.list_destinations()]


def check_destination_availability(destination: str) -> str:
    """Check if a vacation destination is currently available for booking."""
    # ★ 对应 01.py 的一处修正：区分"没有这个城市的数据"和"有数据但已满"
    #   否则查不到会被答成"不可预订"，把"未知"当成"否"，误导用户。
    if destination not in AVAILABILITY:
        # 再试一次中文名匹配
        for d in kb.list_destinations():
            if destination in (d["name_zh"], d["name_en"]):
                destination = d["name_en"]
                break
        else:
            return f"知识库中没有 {destination} 的可订性数据。"

    ok = AVAILABILITY[destination]
    return f"{destination} 目前{'可以预订' if ok else '已订满，暂不可预订'}。"


def get_destination_details(destination: str) -> dict:
    """Get structured details about a vacation destination."""
    hits = kb.search(destination, top_k=1)
    if not hits:
        return {"destination": destination, "found": False, "message": "知识库中没有该目的地"}
    d = hits[0]
    return {
        "destination": d["name_zh"],
        "found": True,
        "available": AVAILABILITY.get(d["key"], True),
        "best_season": d["best_season"],
        "daily_cost": d["daily_cost"],
        "highlights": d["highlights"],
        "intro": d["intro"],
    }


def search_travel_knowledge(query: str) -> str:
    """Search the travel knowledge base for destination information."""
    hits = kb.search(query, top_k=3)
    if not hits:
        return "知识库中没有找到相关目的地的资料。"
    return "\n\n".join(
        f"【{h['name_zh']}】{h['intro']} 最佳季节：{h['best_season']}；日均花费：{h['daily_cost']}"
        for h in hits
    )


# 航班工具（对应 01.py 实验十一的"主系统 / 备用系统"）
_PRIMARY_FLIGHTS = {
    "Paris": "出发班次：08:00、12:30、17:45 — 起价 ¥2500",
    "东京": "出发班次：11:00、23:30 — 起价 ¥6300",
    "Tokyo": "出发班次：11:00、23:30 — 起价 ¥6300",
    "巴塞罗那": "出发班次：07:15、14:00、19:30 — 起价 ¥2000",
    "Barcelona": "出发班次：07:15、14:00、19:30 — 起价 ¥2000",
}
_BACKUP_FLIGHTS = {
    "Berlin": "出发班次：09:00、16:00 — 起价 ¥1600",
    "柏林": "出发班次：09:00、16:00 — 起价 ¥1600",
    "Sydney": "出发班次：22:00 — 起价 ¥8600",
    "悉尼": "出发班次：22:00 — 起价 ¥8600",
    "纽约": "出发班次：06:00、10:30、15:00、20:00 — 起价 ¥3200",
    "New York City": "出发班次：06:00、10:30、15:00、20:00 — 起价 ¥3200",
}


def get_flight_times(destination: str) -> str:
    """Get available flight times for a destination (primary source)."""
    if destination in _PRIMARY_FLIGHTS:
        return _PRIMARY_FLIGHTS[destination]
    # ★ 对应 01.py：故意抛错，专门用来演示"主系统失败 → 切备用系统"的回退流程
    raise Exception(f"404: 主系统中未找到 {destination} 的航班")


def get_flight_times_backup(destination: str) -> str:
    """Get available flight times from backup system (used when primary fails)."""
    return _BACKUP_FLIGHTS.get(
        destination, f"备用系统中也没有找到 {destination} 的航班，请稍后再试。"
    )


def get_flight_info(destination: str) -> str:
    """Get flight information for a destination."""
    return get_flight_times(destination) if destination in _PRIMARY_FLIGHTS else _BACKUP_FLIGHTS.get(
        destination, f"未找到飞往 {destination} 的航班"
    )


def get_activity_suggestions(destination: str) -> str:
    """Get activity suggestions for a destination."""
    hits = kb.search(destination, top_k=1)
    if not hits:
        return f"未找到 {destination} 的活动建议"
    d = hits[0]
    return f"{d['name_zh']}推荐活动：{'、'.join(d['highlights'])}。{d['tips']}"


# 预订工具（对应 01.py 实验八的三个"专业工具"）
def book_flight(destination: str, departure_date: str, return_date: str) -> str:
    """Search and book flights for the trip."""
    code = abs(hash(destination)) % 10000
    return f"已预订飞往 {destination} 的航班：{departure_date} → {return_date}，确认号 #FLT-{code:04d}"


def reserve_hotel(city: str, check_in: str, check_out: str, guests: int) -> str:
    """Reserve a hotel room in the destination city."""
    code = abs(hash(city)) % 10000
    return f"已在 {city} 预订酒店：{check_in} 至 {check_out}，{guests} 位客人，确认号 #HTL-{code:04d}"


def book_activity(activity_name: str, date: str, participants: int) -> str:
    """Book a tour, museum visit, or other activity."""
    code = abs(hash(activity_name)) % 10000
    return f"已预订活动：{activity_name}，{date}，{participants} 人，确认号 #ACT-{code:04d}"


def summarize_preferences(conversation_notes: str) -> str:
    """Summarize accumulated user preferences into a compact format."""
    return f"[偏好摘要] 已记录：{conversation_notes}"
