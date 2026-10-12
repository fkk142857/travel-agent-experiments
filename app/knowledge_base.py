# -*- coding: utf-8 -*-
"""
旅游知识库（RAG 的 R —— 检索源）

基准来自 01.py 里的 TRAVEL_KNOWLEDGE_BASE 与 search_travel_knowledge 工具。
这里做了三件事：
  1) 把知识库从 4 个城市扩充到 12 个，并补充"中文条目"，
     让中文提问也能直接命中（01.py 的痛点是中英混查容易漏）。
  2) 每条知识拆成结构化字段（最佳季节 / 日均花费 / 亮点 / 贴士），
     前端可以直接渲染成卡片，而不是只丢一段英文文本给模型。
  3) 检索从"关键词朴素匹配"升级为"分词 + 字段加权打分"，
     召回更稳，同时保留 01.py 里那种"命不中就如实说不知道"的原则。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Destination:
    """一个目的地的结构化知识条目。"""

    key: str                      # 唯一键（英文名，用于索引）
    name_en: str                  # 英文名
    name_zh: str                  # 中文名
    region: str                   # 所在地区
    best_season: str              # 最佳旅行季节
    daily_cost: str               # 人均日均花费
    highlights: list[str] = field(default_factory=list)   # 亮点标签
    intro: str = ""               # 介绍正文
    tips: str = ""                # 实用贴士
    visa: str = ""                # 签证 / 入境提示

    # 派生出来的检索别名词（中文名、英文名、地区、亮点都算）
    @property
    def aliases(self) -> list[str]:
        return [self.key, self.name_en, self.name_zh, self.region]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 知识库本体
# ---------------------------------------------------------------------------
_DESTINATIONS: list[Destination] = [
    Destination(
        key="Barcelona",
        name_en="Barcelona",
        name_zh="巴塞罗那",
        region="西班牙 · 加泰罗尼亚",
        best_season="3-5 月 / 9-11 月",
        daily_cost="日均 ¥1100-1500（约 $150-200）",
        highlights=["高迪建筑", "海滩", "夜生活", "美食市场"],
        intro=(
            "巴塞罗那是西班牙加泰罗尼亚的首府，地中海畔的艺术之城。"
            "圣家堂、米拉之家、巴特罗之家等高迪作品构成城市名片，"
            "兰布拉大道与波盖利亚市场则是最有烟火气的去处。"
        ),
        tips="旺季（6-8 月）海滩非常拥挤且住宿翻倍，建议 5 月或 10 月出行；地铁 T-casual 10 次票最划算。",
        visa="申根签证，需提前 1-2 个月预约。",
    ),
    Destination(
        key="Paris",
        name_en="Paris",
        name_zh="巴黎",
        region="法国 · 法兰西岛",
        best_season="4-6 月 / 9-10 月",
        daily_cost="日均 ¥1300-1800（约 $180-250）",
        highlights=["博物馆", "美食", "时尚", "塞纳河"],
        intro=(
            "巴黎是法国的首都，全球艺术、时尚与文化中心。"
            "埃菲尔铁塔、卢浮宫、奥赛博物馆、蒙马特高地是经典必去，"
            "街区咖啡馆与面包店本身就是一种旅行方式。"
        ),
        tips="卢浮宫等热门博物馆务必提前网上预约；museum pass 适合一天看 2 个以上馆的行程。",
        visa="申根签证。",
    ),
    Destination(
        key="Tokyo",
        name_en="Tokyo",
        name_zh="东京",
        region="日本 · 关东",
        best_season="3-4 月（樱花）/ 10-11 月（红叶）",
        daily_cost="日均 ¥1400-1800（约 $200-250）",
        highlights=["涩谷", "寺庙神社", "寿司", "动漫街区"],
        intro=(
            "东京是日本首都，超现代与传统并置。"
            "涩谷十字路口、浅草寺、明治神宫、筑地场外市场各有味道，"
            "周边一日游可去镰仓、箱根、日光。"
        ),
        tips="樱花季（3 月底-4 月初）机票酒店要提前 3 个月订；西瓜卡（Suica）可绑定手机直接刷卡。",
        visa="日本旅游签证，单次/三年多次可选。",
    ),
    Destination(
        key="Cape Town",
        name_en="Cape Town",
        name_zh="开普敦",
        region="南非 · 西开普省",
        best_season="11-3 月（南半球夏季）",
        daily_cost="日均 ¥750-1100（约 $100-150）",
        highlights=["桌山", "葡萄酒庄", "野生动物", "好望角"],
        intro=(
            "开普敦位于南非西南端，桌山与两大洋交汇。"
            "可登山、游酒庄（斯泰伦博斯）、走企鹅滩，"
            "也是自驾花园大道的起点。"
        ),
        tips="风大，桌山缆车常因天气停运，建议留出备选日；自驾注意左侧通行。",
        visa="南非签证，需提供行程与资金证明。",
    ),
    Destination(
        key="Bali",
        name_en="Bali",
        name_zh="巴厘岛",
        region="印度尼西亚 · 巴厘省",
        best_season="4-10 月（旱季）",
        daily_cost="日均 ¥600-900（约 $85-130）",
        highlights=["海滩", "印度教寺庙", "梯田", "瑜伽静修"],
        intro=(
            "巴厘岛是印尼最负盛名的度假岛，"
            "乌布的梯田与瑜伽静修、乌鲁瓦图的悬崖庙、"
            "水明漾的日落海滩构成主要玩法。"
        ),
        tips="岛上包车按天计费更划算；注意只有持证兑换点换汇，避免汇率陷阱。",
        visa="落地签（VOA），可在线申请电子签。",
    ),
    Destination(
        key="New York City",
        name_en="New York City",
        name_zh="纽约",
        region="美国 · 纽约州",
        best_season="4-6 月 / 9-11 月",
        daily_cost="日均 ¥2000-2800（约 $280-390）",
        highlights=["百老汇", "博物馆", "中央公园", "多元美食"],
        intro=(
            "纽约是美国的金融与文化中心。"
            "大都会博物馆、现代艺术博物馆（MoMA）、百老汇音乐剧、"
            "中央公园与高线公园是经典组合。"
        ),
        tips="地铁 7 日无限次票（OMNY 封顶）适合密集出行；百老汇可去 TKTS 折扣亭买当日票。",
        visa="美国 B1/B2 签证，面签排期较长需尽早。",
    ),
    Destination(
        key="Cairo",
        name_en="Cairo",
        name_zh="开罗",
        region="埃及 · 开罗省",
        best_season="10-4 月",
        daily_cost="日均 ¥450-800（约 $60-110）",
        highlights=["金字塔", "埃及博物馆", "汗哈利利市场", "尼罗河"],
        intro=(
            "开罗是埃及首都，吉萨金字塔群与大埃及博物馆坐落于此，"
            "老城区的伊斯兰建筑与汗哈利利市场适合半日漫步。"
        ),
        tips="金字塔景区内主动搭讪的\"导游\"多为收费陷阱；夏季高温，建议清晨前往。",
        visa="埃及签证，可落地签（需酒店与返程凭证）。",
    ),
    Destination(
        key="Sydney",
        name_en="Sydney",
        name_zh="悉尼",
        region="澳大利亚 · 新南威尔士州",
        best_season="10-3 月（南半球夏季）",
        daily_cost="日均 ¥1600-2200（约 $220-310）",
        highlights=["歌剧院", "海港大桥", "邦迪海滩", "蓝山"],
        intro=(
            "悉尼是澳大利亚最大城市，"
            "歌剧院与海港大桥构成的天际线是标志性景观，"
            "邦迪到库吉的海岸步道、蓝山一日游都很经典。"
        ),
        tips="市区到机场可直接刷交通卡；海滩日晒强，务必高倍防晒。",
        visa="澳大利亚访客签证（600 类），在线申请。",
    ),
    Destination(
        key="Berlin",
        name_en="Berlin",
        name_zh="柏林",
        region="德国 · 柏林州",
        best_season="5-9 月",
        daily_cost="日均 ¥900-1400（约 $125-195）",
        highlights=["历史遗迹", "博物馆岛", "街头艺术", "夜生活"],
        intro=(
            "柏林是德国首都，欧洲近代史的现场。"
            "柏林墙遗址、勃兰登堡门、博物馆岛、"
            "以及克罗伊茨贝格的街头艺术与夜生活都值得花时间。"
        ),
        tips="博物馆岛 3 日通票性价比高；柏林欢迎卡含公交，适合多日游。",
        visa="申根签证。",
    ),
    Destination(
        key="Rio de Janeiro",
        name_en="Rio de Janeiro",
        name_zh="里约热内卢",
        region="巴西 · 里约州",
        best_season="12-3 月",
        daily_cost="日均 ¥1100-1700（约 $150-235）",
        highlights=["基督像", "科帕卡巴纳海滩", "桑巴", "面包山"],
        intro=(
            "里约热内卢是巴西最著名的海滨城市，"
            "基督像与面包山的俯瞰视角震撼，"
            "科帕卡巴纳与伊帕内玛海滩、桑巴舞学校构成城市节奏。"
        ),
        tips="狂欢节（2 月前后）期间物价与治安压力大，需提前规划；避免携带大量现金。",
        visa="巴西签证（部分情况可电子签）。",
    ),
    Destination(
        key="Istanbul",
        name_en="Istanbul",
        name_zh="伊斯坦布尔",
        region="土耳其 · 马尔马拉地区",
        best_season="4-5 月 / 9-11 月",
        daily_cost="日均 ¥700-1100（约 $95-150）",
        highlights=["圣索菲亚", "蓝色清真寺", "大巴扎", "博斯普鲁斯"],
        intro=(
            "伊斯坦布尔横跨欧亚两洲，"
            "圣索菲亚大教堂、蓝色清真寺、托普卡帕宫集中反映了拜占庭与奥斯曼文明，"
            "博斯普鲁斯海峡游船是最经典的体验。"
        ),
        tips="清真寺参观需注意着装；大巴扎砍价从报价三成起谈。",
        visa="土耳其电子签（e-Visa），在线申请便利。",
    ),
    Destination(
        key="Chiang Mai",
        name_en="Chiang Mai",
        name_zh="清迈",
        region="泰国 · 北部",
        best_season="11-2 月（凉季）",
        daily_cost="日均 ¥400-700（约 $55-100）",
        highlights=["古城寺庙", "夜市", "山地咖啡", "大象保护营"],
        intro=(
            "清迈是泰国北部文化重镇，"
            "古城内寺庙密集、生活节奏舒缓，"
            "周边有因他农山、大象保护营与手作市集。"
        ),
        tips="3-4 月为烧芭季，空气较差，敏感人群避开；双条车按路段议价。",
        visa="泰国签证，中泰互免签政策下短期停留更便利。",
    ),
]


def _build_index() -> dict[str, Destination]:
    idx: dict[str, Destination] = {}
    for d in _DESTINATIONS:
        idx[d.key] = d
        idx[d.name_zh] = d
    return idx


INDEX: dict[str, Destination] = _build_index()


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------
_STOP_WORDS = {
    "我想", "想", "去", "的", "了", "吗", "呢", "和", "与", "推荐", "一下",
    "哪里", "哪个", "什么", "怎么", "怎样", "适合", "请问", "帮我", "有没有",
    "预算", "旅行", "旅游", "度假", "怎么样", "好玩", "值得",
}


def _tokenize(text: str) -> list[str]:
    """极简分词：英文按词，中文按 2-gram 切分。够用且零依赖。"""
    text = text.lower().strip()
    tokens: list[str] = []
    # 英文/数字词
    tokens.extend(re.findall(r"[a-z0-9]+", text))
    # 中文 2-gram
    han = re.findall(r"[\u4e00-\u9fff]+", text)
    for chunk in han:
        if len(chunk) == 1:
            tokens.append(chunk)
        for i in range(len(chunk) - 1):
            tokens.append(chunk[i : i + 2])
    return tokens


def search(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """
    检索知识库。返回按相关度排序的条目（附带 score 与命中字段）。

    打分规则（字段加权）：
      目的地名称直接命中  → +10
      别名词命中          → +4
      亮点标签命中        → +3
      正文/贴士命中       → +1
    与 01.py 的朴素匹配相比，这里能区分"只是文中提了一句"和"就是问这个地方"。
    """
    if not query or not query.strip():
        return []

    q = query.lower()
    raw_tokens = _tokenize(query)
    tokens = [t for t in raw_tokens if t not in _STOP_WORDS]

    scored: list[tuple[float, Destination, list[str]]] = []

    for d in _DESTINATIONS:
        score = 0.0
        matched: list[str] = []

        # 1) 名称直接命中（最高权重）
        for alias in d.aliases:
            a = alias.lower()
            if a and a in q:
                score += 10.0
                matched.append(alias)
                break

        # 2) 亮点标签
        for h in d.highlights:
            hl = h.lower()
            if hl in q or any(t in hl for t in tokens):
                score += 3.0
                matched.append(h)

        # 3) 地区
        if d.region.split("·")[0].strip().lower() in q:
            score += 2.0

        # 4) 正文 / 贴士 / 季节 / 花费
        body = f"{d.intro} {d.tips} {d.best_season} {d.daily_cost} {d.region}".lower()
        hit_body = sum(1 for t in set(tokens) if t and t in body)
        if hit_body:
            score += min(hit_body, 5) * 1.0

        # 5) 季节性 / 预算类问句的软加分
        if any(k in q for k in ("季节", "时候", "月份", "几月", "天气")):
            score += 0.5
        if any(k in q for k in ("预算", "花费", "多少钱", "费用", "贵")):
            score += 0.5

        if score > 0:
            scored.append((score, d, matched))

    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[dict[str, Any]] = []
    for score, d, matched in scored[:top_k]:
        item = d.to_dict()
        item["score"] = round(score, 2)
        item["matched"] = sorted(set(matched))
        results.append(item)
    return results


def list_destinations() -> list[dict[str, Any]]:
    """返回全部目的地的精简列表（给前端做卡片展示）。"""
    return [
        {
            "key": d.key,
            "name_zh": d.name_zh,
            "name_en": d.name_en,
            "region": d.region,
            "best_season": d.best_season,
            "daily_cost": d.daily_cost,
            "highlights": d.highlights,
        }
        for d in _DESTINATIONS
    ]


def get(key: str) -> Destination | None:
    return INDEX.get(key)


def build_context(results: list[dict[str, Any]]) -> str:
    """把检索结果拼成给大模型看的上下文。"""
    if not results:
        return "（知识库中没有找到相关目的地资料。）"
    blocks = []
    for r in results:
        blocks.append(
            f"【{r['name_zh']} / {r['name_en']}】\n"
            f"地区：{r['region']}\n"
            f"最佳季节：{r['best_season']}\n"
            f"日均花费：{r['daily_cost']}\n"
            f"亮点：{'、'.join(r['highlights'])}\n"
            f"介绍：{r['intro']}\n"
            f"贴士：{r['tips']}\n"
            f"签证：{r['visa']}"
        )
    return "\n\n".join(blocks)
