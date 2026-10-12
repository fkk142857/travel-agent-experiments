#★ 这两行是"防崩溃补丁",必须放在最前面(在任何 print 之前)★
#原因:Windows 中文控制台默认用 GBK 编码,遇到 emoji(🌴🏖️ 等)会直接抛
#      UnicodeEncodeError: 'gbk' codec can't encode character ... 让程序崩溃。
#做法:把标准输出/错误输出的编码强制切成 UTF-8,这样 emoji 和中文都能正常输出。
#      errors="replace" 是保险丝:万一真有字符编不出来,也只显示成 ? 而不会崩溃。
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

#导入python自带的日志模块
import logging
#关掉多余的日志信息,让输出干净点
logging.getLogger("agent_framework.openai").setLevel(logging.ERROR)

#python自带的,用来读取环境变量(.env里的环境变量)
import os
#第三方小工具,专门读取.env文件
import dotenv
#Annotated:python 自带的"类型标注"工具,用来给参数附加一段文字说明
#用法:Annotated[类型, "给模型看的参数描述"]
#@tool 装饰器会读取这段描述,当作"这个参数是干嘛的"发给模型,帮它填对参数
from typing import Annotated
#OpenAIChatCompletionClient:走"聊天补全"协议的客户端,兼容 DeepSeek / MiniMax 等第三方 OpenAI 服务
#注意:另一个 OpenAIChatClient 走的是更新的 Responses 协议,DeepSeek 的工具调用还不兼容,所以这里不能用它
from agent_framework.openai import OpenAIChatCompletionClient
# 将普通的python函数变成智能体能调用的工具
#WorkflowBuilder:工作流建造者(把多个智能体连成一条流水线)
#WorkflowViz:工作流可视化(输出 Mermaid / DiGraph 文本,或导出图片)
from agent_framework import tool, WorkflowBuilder, WorkflowViz

#datetime/timezone:获取当前时间和时区(给审计日志打时间戳用)
from datetime import datetime, timezone
#Path:把"文件路径"当成对象来处理,读写文件更顺手
from pathlib import Path
#time:获取"时间戳"秒数,用来给代码计时(两个时间点相减 = 耗时)
import time
#hashlib:算哈希。作用是把任意内容压成一段固定长度的"指纹",且无法反推
import hashlib
#base64:把二进制数据转成文本(只用 64 个安全字符),方便放进 JSON / URL
import base64
#copy:里面有 deepcopy(深拷贝),复制出一份完全独立的对象
import copy
#json:python 自带的工具,用来把"JSON 文字" ↔ "python 字典"互相转换
import json
#空白表格模板,可以自定义(实验三"结构化输出"要用它定义回答格式)
#ValidationError:当模型返回的内容不符合模板时,抛出的错误(用来"校验")
from pydantic import BaseModel, ValidationError
#find_dotenv()从当前目录往上找 .env 文件
#load_dotenv(...)把里面的内容读进来
#把.env里的配置"读进内存"
dotenv.load_dotenv(dotenv.find_dotenv())

#★ 以下是已删除的 Azure 配置段 ★
#原文曾在这里读取 AZURE_AI_PROJECT_ENDPOINT / AZURE_AI_MODEL_DEPLOYMENT_NAME 并创建
#一个 Azure 连接器。因为本机没有配置 Azure 环境变量,那段会直接 raise ValueError 让
#整个脚本一启动就崩,所以整段删除。以后要用 Azure 时,把下面几行取消注释即可:
#
#   endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
#   deployment_name = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
#   azure_provider = OpenAIChatCompletionClient(
#       model=deployment_name,
#       base_url=endpoint,
#       api_key=os.getenv("AZURE_AI_API_KEY"),
#   )

#DeepSeek 的 API 密钥(在你自己的 .env 里,不会进 git)
api_key = os.getenv("DEEPSEEK_API_KEY")
#DeepSeek 的接口地址
base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
#用哪个模型
model = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")

#如果密钥没填,提前报错,别等联网时才失败
if not api_key or api_key.startswith("..."):
    raise ValueError(
        "请在 .env 文件里填写 DEEPSEEK_API_KEY（从 https://platform.deepseek.com/ 获取）。"
    )

provider = OpenAIChatCompletionClient(
    #默认用哪个模型
    model=model,
    #接口地址(DeepSeek 兼容 OpenAI 格式)
    base_url=base_url,
    #用什么身份认证:这里是 API 密钥
    api_key=api_key,
)

#@tool是装饰器,给函数加装一堆额外信息,然后注册给模型.函数会变成智能体能看见能调用的工具
#approval_mode="never_require",模型调用工具无需人为确认
@tool(approval_mode="never_require")
#get_destinations()模型靠这个来点名调用
#-> list[str]:函数返回一个字符串列表，给人和IDE看的提示
def get_destinations() -> list[str]:
    #表面看只是"函数说明"，但在智能体里它是工具描述——框架会把它原文发给模型。
    #模型就是靠这段话来判断："用户问旅行推荐时，我该不该调用 get_destinations？"
    #所以描述要写得清楚。如果写成 """abc"""，模型就不知道啥时候该用它了。
    #这里用英文，是因为模型对英文描述的理解通常更准（课程所有示例都写英文）。
    """Get a list of popular vacation destinations."""
    return [
        "Barcelona",
        "Paris",
        "Berlin",
        "Tokyo",
        "Sydney",
        "New York City",
        "Cairo",
        "Cape Town",
        "Rio de Janeiro",
        "Bali",
    ]

@tool(approval_mode="never_require")
#自定义函数，检查目的地是否可以预订
def check_destination_availability(
    #参数名：destination,类型是str，描述是"目的地"
    destination: Annotated[str, "The destination to check availability for"]
) -> str:
    """Check if a vacation destination is currently available for booking."""
    #★ 关键:每个城市都要写"英文名"和"中文名"两套键 ★
    #为什么?工具内部本来只用英文,但用户用中文提问时,模型会把参数原样传成中文("东京")。
    #      如果这里只有 "Tokyo",available.get("东京", False) 就查不到 →
    #      静默返回默认值 False → 明明可订,却告诉用户"不可预订"(实测踩过这个坑)。
    available = {
        #巴塞罗那
        "Barcelona": True,   "巴塞罗那": True,
        #东京
        "Tokyo": True,       "东京": True,
        #开普敦(故意设为不可订,用来演示"查不到已满"的情况)
        "Cape Town": False,  "开普敦": False,
        #温哥华
        "Vancouver": True,   "温哥华": True,
        #迪拜(故意设为不可订,用来演示)
        "Dubai": False,      "迪拜": False,
    }
    #★ 关键:先判断"有没有这个城市的数据",再判断"能不能订" ★
    #为什么?查不到其实有两种完全不同的情况:
    #   ① 数据里压根没这个城市 → 应回答"暂无数据"(未知)
    #   ② 确实有,只是订满了     → 才回答"不可预订"
    #如果两种都用默认值 False 兜底,"没数据"就会被答成"不可预订"——这是把"未知"当"否",
    #会误导用户(实测出现过,而且模型会自己编城市名来查,然后一本正经说"都订满了")。
    if destination not in available:
        return f"No availability data for {destination}."

    is_available = available[destination]
    return f"{destination} is {'available' if is_available else 'not available'} for booking."
#★ 全文件通用的一条"语言规则"(写一次,所有智能体复用)★
#为什么单独抽出来?
#  ① 模型偶尔会用英文写"过渡句"(比如调用工具前先说 "I'll check that for you."),
#     把规则写得越明确、越靠前,这种情况就越少。
#  ② 抽成变量后,以后想统一调整措辞,只改这一处,不用满文件找。
#⚠️ 注意措辞里特意点名了"调用工具前后的短句"和"不要用英文开头",
#   这两句就是针对那个漏网的过渡句。
ZH_RULE = (
    "Language rule (MUST follow): Always respond in Simplified Chinese "
    "(简体中文), regardless of the language the user writes in. "
    "EVERY sentence must be in Chinese - including any short sentence you write "
    "before or after calling a tool. Never output English, and never start your "
    "reply with an English sentence such as 'I will check...'. "
)

#★ 把要用的工具先装进一个"工具箱"列表 ★
#好处:
#  ① 一眼看清这个智能体到底有哪些工具
#  ② 同一个工具箱可以交给多个智能体,不用每次重写一遍
#  ③ 以后要加/减工具,只改这一行
travel_tools = [get_destinations, check_destination_availability]

#用连接器"造"一个智能体。一个智能体需要两样东西:
#  ① instructions 指令 = 它是谁、该怎么表现(相当于"岗位说明书")
#  ② tools 工具 = 它能调用的函数(相当于它的"手")
agent = provider.as_agent(
    #给智能体起个名字(方便看日志、调试时辨认)
    name="TravelAgent",
    #instructions:告诉它"你是谁、该怎么做"。
    #这里特意写明"Use the get_destinations tool",否则模型不一定知道该去用那个工具。
    #同样要写明 check_destination_availability 的用途,否则模型宁可"猜"也不去查。
    #最后一句要求"必须用简体中文回答",所以哪怕提问是英文,它也会用中文回。
    #(工具函数的描述依然保持英文——模型对英文描述的工具理解更准,这两件事互不影响)
    instructions=(
        "You are a helpful travel agent. Help users find their perfect vacation "
        "destination based on their preferences. Use the get_destinations tool "
        "to see available destinations. "
        "Use the check_destination_availability tool whenever the user asks "
        "whether a specific destination can be booked or is available - always "
        "check with the tool instead of guessing. "
        #语言规则统一走上面定义的 ZH_RULE
        + ZH_RULE
    ),
    #把上面的"工具箱"整包交给它(注意:只有放进去的工具,模型才看得见、才调用得到)
    tools=travel_tools,
)

class DestinationRecommendation(BaseModel):
    destination: str
    available: bool
    best_season: str
    highlights: list[str]
    estimated_budget_usd: int


class TravelRecommendations(BaseModel):
    recommendations: list[DestinationRecommendation]
    personalized_note: str


@tool(approval_mode="never_require")
def get_destination_details(
    #destination参数名，“盒子”的名字
    #：“盒子”的规格是什么
    #annotated:注解
    #str:盒子只能装文字
    destination: Annotated[str, "The destination to look up"]
) -> DestinationRecommendation:
    """Get structured details about a vacation destination."""
    #★ 数据表:与 get_destinations() 的 10 个城市对齐 ★
    #(演示用假数据,数值随便改;available 表示当前能不能订)
    details = {
        "Barcelona": DestinationRecommendation(
            destination="Barcelona",
            available=True,
            best_season="May-Jun",
            highlights=["Beach", "Architecture", "Nightlife"],
            estimated_budget_usd=2000,
        ),
        "Paris": DestinationRecommendation(
            destination="Paris",
            available=True,
            best_season="Apr-Jun",
            highlights=["Museums", "Cuisine", "Fashion"],
            estimated_budget_usd=2400,
        ),
        "Berlin": DestinationRecommendation(
            destination="Berlin",
            available=True,
            best_season="May-Sep",
            highlights=["History", "Art", "Nightlife"],
            estimated_budget_usd=1500,
        ),
        "Tokyo": DestinationRecommendation(
            destination="Tokyo",
            available=True,
            best_season="Mar-Apr",
            highlights=["Culture", "Food", "Technology"],
            estimated_budget_usd=2500,
        ),
        "Sydney": DestinationRecommendation(
            destination="Sydney",
            available=True,
            best_season="Oct-Mar",
            highlights=["Beach", "Harbour", "Outdoors"],
            estimated_budget_usd=2200,
        ),
        "New York City": DestinationRecommendation(
            destination="New York City",
            available=True,
            best_season="Apr-Jun",
            highlights=["Theatre", "Museums", "Food"],
            estimated_budget_usd=3000,
        ),
        "Cairo": DestinationRecommendation(
            destination="Cairo",
            available=True,
            best_season="Oct-Apr",
            highlights=["Pyramids", "Museums", "Markets"],
            estimated_budget_usd=1200,
        ),
        "Cape Town": DestinationRecommendation(
            destination="Cape Town",
            available=False,
            best_season="Nov-Mar",
            highlights=["Nature", "Wine", "Adventure"],
            estimated_budget_usd=1800,
        ),
        "Rio de Janeiro": DestinationRecommendation(
            destination="Rio de Janeiro",
            available=True,
            best_season="Dec-Mar",
            highlights=["Beach", "Carnival", "Mountains"],
            estimated_budget_usd=1700,
        ),
        "Bali": DestinationRecommendation(
            destination="Bali",
            available=True,
            best_season="Apr-Oct",
            highlights=["Beach", "Temples", "Rice Terraces"],
            estimated_budget_usd=1300,
        ),
    }

    #★ 顺手补上"中文名"键 ★
    #为什么?用户用中文提问时,模型会把参数原样传成中文("东京")。
    #      如果这里只有英文键,就会查不到 → 返回下面的"默认空卡片"(全是 Unknown / $0)。
    #做法:用一张"英文名 → 中文名"对照表,把中文键自动指向同一个对象,
    #      这样不用把 10 个城市手写两遍(改数据时也只改一处)。
    zh_names = {
        "Barcelona": "巴塞罗那",
        "Paris": "巴黎",
        "Berlin": "柏林",
        "Tokyo": "东京",
        "Sydney": "悉尼",
        "New York City": "纽约",
        "Cairo": "开罗",
        "Cape Town": "开普敦",
        "Rio de Janeiro": "里约热内卢",
        "Bali": "巴厘岛",
    }
    details.update({zh: details[en] for en, zh in zh_names.items() if en in details})

    return details.get(
        #要找的名字
        destination,
        #找不到给的默认卡
        DestinationRecommendation(
            destination=destination,
            available=False,
            best_season="Unknown",
            highlights=[],
            estimated_budget_usd=0,
        ),
    )

#===================================================================
#RAG(检索增强)的核心资料:一份"我们自己的"知识库 + 检索工具
#===================================================================
#什么叫 RAG?= Retrieval-Augmented Generation(检索增强生成)
#简单说:模型自己的知识可能过时/不准,所以先准备一份自己的资料,
#       让它"先查资料、再回答"。下面这段就是 RAG 里 R(检索)的部分。
#★ 注意:知识库里的介绍是英文的(课程原文),但智能体最终会用中文回答 ★
TRAVEL_KNOWLEDGE_BASE = {
    "Barcelona": "Barcelona is Spain's cosmopolitan capital of Catalonia. Best visited Mar-May or Sep-Nov. Known for Gaudí architecture, La Rambla, beaches. Average daily cost: $150-200.",
    "Tokyo": "Tokyo is Japan's capital, mixing ultramodern with traditional. Best visited Mar-Apr (cherry blossoms) or Oct-Nov. Known for Shibuya, temples, sushi. Average daily cost: $200-250.",
    "Paris": "Paris is France's capital and a global center for art, fashion, and culture. Best visited Apr-Jun or Sep-Oct. Known for Eiffel Tower, Louvre, cuisine. Average daily cost: $180-250.",
    "Cape Town": "Cape Town sits on South Africa's southwest tip. Best visited Nov-Mar. Known for Table Mountain, wine regions, wildlife. Average daily cost: $100-150.",
}


@tool(approval_mode="never_require")
def search_travel_knowledge(
    #query参数名，盒子的名字
    #str:盒子只能装文字
    #annotated:注解
    #"The search query about a travel destination"参数说明,给AI的说明你是干什么的
    query: Annotated[str, "The search query about a travel destination"]
) -> str:
    #文档字符串,给AI看的说明,告诉AI这个工具是干什么的
    """Search the travel knowledge base for destination information."""
    #准备一个空列表来存储搜索结果
    results = []
    #遍历字典中的每一个键值对,destination是键(地名)，info是值(介绍)
    #.items()方法返回字典中的所有键值对(键，值)
    for destination, info in TRAVEL_KNOWLEDGE_BASE.items():
        #.lower()全部转化成小写
        #搜索词是不是地名的一部份
        #.split()方法把字符串分割成单词列表
        #any()方法判断列表中是否有True元素,只要有一个成立就返回True
        #把搜索词按空格拆成几个词,只要有一个出现在介绍里就算匹配上了
        if query.lower() in destination.lower() or any(
            word in info.lower() for word in query.lower().split()
        ):
            #命中的结果添加到列表里,**加粗显示
            results.append(f"**{destination}**: {info}")
    return (
        "\n\n".join(results)
        if results
        else "No matching destinations found in the knowledge base."
    )


#===================================================================
#实验三:结构化输出(强制模型按"固定表格"回答,而不是自由发挥的文字)
#===================================================================
#★ 同样必须包在 async def 里(因为里面有 await),否则报 'await' outside function ★
#  structured_agent 写成局部变量,同样不会覆盖上面那个 TravelAgent
async def structured_demo():
    #provider.as_agent让provider变身为一个智能体
    structured_agent = provider.as_agent(
        name="StructuredTravelExpert",
        #中文回答要求:否则这个智能体(以及它返回的 JSON 内容)都会是英文
        instructions=(
            "You are a travel expert. Recommend destinations based on traveler preferences. "
            "Use the get_destination_details tool. "
            #语言规则统一走 ZH_RULE
            + ZH_RULE
        ),
        tools=[get_destination_details],
    )

    #★ 改造点1:DeepSeek 不支持"把 pydantic 模型直接当 response_format"这种强校验写法 ★
    #   那是 OpenAI / Azure 的能力,DeepSeek 会直接返回 400:
    #       This response_format type is unavailable now
    #DeepSeek 只支持 {"type": "json_object"} 这种"JSON 模式":
    #   它保证"输出一定是合法 JSON",但不保证"字段符合我们的模板"。
    #所以改成两步走:
    #   ① 在提示词里把模板(要哪些字段)写清楚,并要求只输出 JSON
    #   ② 拿到文字后,自己用 pydantic 校验(model_validate)→ 得到 TravelRecommendations 对象
    #
    #★ 改造点2:把"可选城市名单"直接写进提示词 ★
    #为什么?这个智能体只有"按名字查详情"的工具,看不到城市名单,
    #      所以它以前会凭常识猜出"京都""伊斯坦布尔"这类数据库里没有的城市,
    #      查不到就返回空卡片,结果 3 条推荐全是 Unknown / $0。
    #做法:把名单摆在它面前,并强制"只能从里面选"。
    #⚠️ 维护提醒:这份名单要和上面的 get_destinations() 以及 get_destination_details()
    #   的数据表保持一致,否则又会推荐出查不到的城市。
    allowed = (
        "Barcelona, Paris, Berlin, Tokyo, Sydney, "
        "New York City, Cairo, Cape Town, Rio de Janeiro, Bali"
    )
    response = await structured_agent.run(
        "请为一位热爱人文与美食、预算 2500 美元的旅行者推荐 3 个目的地。"
        f"你只能从下面这份名单里挑选:{allowed}。"
        "绝对不要推荐名单以外的城市。"
        "只返回一个 JSON 对象(不要 markdown、不要任何多余文字)。"
        #⚠️ 关键:JSON 的"字段名"必须保持英文(要和上面 pydantic 模板的字段对上,
        #   写中文会直接校验失败);但字段里的"内容"(城市名、季节、亮点、说明)
        #   请用简体中文书写。
        "字段名必须用英文,字段内容请用简体中文,格式严格如下:"
        '{"recommendations": [{"destination": "string", "available": true, '
        '"best_season": "string", "highlights": ["string"], "estimated_budget_usd": 0}], '
        '"personalized_note": "string"}',
        #option：一个“可选项”的参数
        #{}：用字典来设置
        #回答的格式:json_object = 只要求"是合法 JSON",字段结构靠上面的提示词约束
        options={"response_format": {"type": "json_object"}},
    )

    #把模型返回的文字 → 解析成 JSON → 再用模板校验
    try:
        raw = json.loads(str(response))
        #检查AI是否按表格格式返回(不符合模板就抛 ValidationError)
        result = TravelRecommendations.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as e:
        print("模型返回的内容不符合模板,校验失败:")
        print("  ", type(e).__name__, str(e)[:300])
        print("原始回答:", response)
        return

    #result.recommendations:报告里面一叠目的地卡片
    #rec:一张张取出来，每次拿到的卡片叫rec
    for rec in result.recommendations:
        #这些标签是代码里写死的,和模型无关,所以要单独改成中文
        status = "可预订" if rec.available else "不可预订"
        print(f"{rec.destination}（{status}）")
        print(f"  最佳季节:{rec.best_season}")
        print(f"  亮点:{', '.join(rec.highlights)}")
        print(f"  预估预算:${rec.estimated_budget_usd}")
        print()
    print(f"说明:{result.personalized_note}")


#asyncio:python自带的"异步工具",用来启动异步函数
import asyncio



#===================================================================
#实验二:用"会话(session)"让智能体记住聊过什么
#===================================================================
#★ 为什么要把代码放进 async def 里?★
#  1) await 只能写在 async def 函数内部(写在文件顶层会报 SyntaxError)
#  2) 这里的 agent 是"局部变量"(函数内部的变量),它不会覆盖上面那个 TravelAgent
#     ——两个智能体各自独立,互不干扰
async def session_demo():
    #把provider变成一个智能体
    agent = provider.as_agent(
        name="TravelAvailabilityAgent",
        instructions=(
            "You are a travel booking agent. Help users check destination availability "
            "and make recommendations. Always check availability before recommending a destination. "
            #语言规则统一走 ZH_RULE
            + ZH_RULE
        ),
        tools=[check_destination_availability],
    )
    #让智能体新建一个会话,赋值给session,一直用session来控制会话,智能体就会记得聊过什么。
    session = agent.create_session()

    #run()是智能体最核心的函数:接受一个字符串作为输入,返回一个字符串作为输出。
    #Turn 1: Ask about available destinations
    response = await agent.run(
        "Which destinations do you have available?",
        session=session,
    )
    #f允许嵌入变量=文字模板+填空
    print(f"Agent: {response}")

    # Turn 2: Follow-up question — the agent remembers the conversation
    response = await agent.run(
        "I'd like to go somewhere warm. What's available?",
        session=session,
    )
    print(f"Agent: {response}")


#===================================================================
#实验四:多智能体协作(把一个大任务拆给两个"专科智能体"分工完成)
#===================================================================
#思路:不让一个智能体什么都干,而是像公司一样分工——
#   ① 目的地专家(DestinationExpert):只负责"去哪",并查工具确认可订性
#   ② 行程规划师(LogisticsPlanner):只负责"怎么去",做行程、选航班酒店
#两个人的职责用 "Do NOT ..." 互相划清界限,避免抢活或重复回答。
#★ 同样必须包在 async def 里(因为里面有 await)★
#  两个智能体都是函数内的局部变量,不会覆盖上面的 agent
async def multi_agent_demo():
    destination_agent = provider.as_agent(
        name="DestinationExpert",
        tools=[get_destination_details],
        #★ 改造点:把"可选城市名单"写进指令 ★
        #为什么?这个智能体只有"按名字查详情"的工具,看不到城市名单,
        #      所以它以前会凭常识猜出"墨西哥城""河内""伊斯坦布尔"这类数据库里没有的城市,
        #      查不到就返回空卡片,导致给不出任何推荐,后面的行程规划师也跟着空转。
        #⚠️ 维护提醒:这份名单要和 get_destinations()、get_destination_details()、
        #   structured_demo() 里的 allowed 保持一致。
        #中文回答要求:否则这个智能体会用英文回答(它原本的指令是英文的)
        instructions="""You are a destination research specialist. Your only job is to:
1. Evaluate destinations based on traveler preferences
2. Check availability using the provided tool
3. Return a short ranked list with pros/cons
Do NOT discuss flights, hotels, or logistics — another agent handles that.
You MUST choose ONLY from this exact list of available destinations:
Barcelona, Paris, Berlin, Tokyo, Sydney, New York City, Cairo, Cape Town, Rio de Janeiro, Bali.
Never mention or recommend a city outside this list.
""" + ZH_RULE,
    )

    logistics_agent = provider.as_agent(
        name="LogisticsPlanner",
        #中文回答要求:同上
        instructions="""You are a travel logistics planner. Your only job is to:
1. Create a day-by-day itinerary for the chosen destination
2. Suggest flight and hotel options within the stated budget
3. Note visa requirements and travel insurance recommendations
Do NOT recommend destinations — another agent handles that.
""" + ZH_RULE,
    )

    # Step 1: Destination Expert picks the best options
    dest_response = await destination_agent.run(
        "I want a week of culture and food for under $2500. Where should I go?"
    )
    print("=== Destination Expert ===")
    print(dest_response)

    # Step 2: Logistics Planner builds the trip plan
    #★ 关键:把第 1 个智能体的输出,当作第 2 个智能体的输入 → 这就是"串联协作"
    logistics_response = await logistics_agent.run(
        f"Plan a week-long trip based on this recommendation:\n{dest_response}"
    )
    print("\n=== Logistics Planner ===")
    print(logistics_response)


#===================================================================
#实验五:复用"工具箱" + 一次提问同时用到两个工具
#===================================================================
#★ 这题的看点:一个提问里同时包含两个需求
#   "What destinations do you have?"  → 要调 get_destinations(列名单)
#   "Which ones are still available?" → 要调 check_destination_availability(查可订性)
#   智能体必须"先拿名单、再逐个查",把两个工具有序地用起来。
#★ 同样必须包在 async def 里(因为有 await)★
async def travel_tool_demo():
    #直接把上面那个 travel_tools 工具箱复用过来(不用再写一遍)
    agent = provider.as_agent(
        name="TravelToolAgent",
        instructions=(
            "You are a travel agent. Use the available tools to answer questions "
            "about destinations and availability. "
            #语言规则统一走 ZH_RULE
            + ZH_RULE
        ),
        tools=travel_tools,
    )

    #一次提问,两个需求 → 看它会不会把两个工具都用上
    response = await agent.run(
        "What destinations do you have? Which ones are still available?"
    )
    print(response)


#===================================================================
#实验七:RAG(检索增强)—— 先查自己的知识库,再回答
#===================================================================
#这一节对比两个智能体,感受"提示词细致程度"带来的差别:
#   ① TravelRAGAgent       : 普通版,查一次库就回答
#   ② TravelRAGCheckerAgent: 挑剔版,查完还要"用城市名再查一次核对",确保信息完整
#两个都用同一个 search_travel_knowledge 工具。
#★ 同样必须包在 async def 里(因为有 await)★
#  注意:你的课程原文写的是 client.as_agent(...),这里改成了 provider.as_agent(...),
#       因为本文件里的连接器变量名叫 provider。
async def rag_demo():
    # ---------- ① 普通版:查一次就回答 ----------
    agent = provider.as_agent(
        tools=[search_travel_knowledge],
        name="TravelRAGAgent",
        #你是一位知识渊博的旅行顾问。在回答关于目的地的问题之前：
        #一定要先搜索旅行知识库
        #答案要基于检索到的信息
        #如果信息不在知识库里，就明确说明
        #给出具体细节，比如费用、最佳季节、亮点
        instructions="""You are a knowledgeable travel advisor. Before answering questions about destinations:
1. ALWAYS search the travel knowledge base first
2. Base your answers on retrieved information
3. If information is not in the knowledge base, say so clearly
4. Provide specific details like costs, best seasons, and highlights.
""" + ZH_RULE,
    )
    response = await agent.run(
        "I'm interested in visiting somewhere with great architecture. What destinations would you recommend?",
    )
    print(response)

    print("\n" + "-" * 30 + " 下面换成「爱核对」的智能体 " + "-" * 30 + "\n")

    # ---------- ② 挑剔版:反复核对 ----------
    checker_agent = provider.as_agent(
        tools=[search_travel_knowledge],
        name="TravelRAGCheckerAgent",
        #你是一位一丝不苟的旅行顾问，会反复核对你的推荐。
        #回答旅行问题时：
        #先搜索相关目的地
        #对于找到的每个目的地，用它的名字再搜一次，获取完整详情
        #用核实过的信息比较各个选项
        #给出最终推荐，包含具体费用、最佳旅行时间、亮点
        #如果某个细节看起来不完整，再搜一次确认，然后再回答
        instructions="""You are a meticulous travel advisor who double-checks recommendations.
When answering travel questions:
1. Search for relevant destinations first
2. For each destination found, search again with the destination name to get full details
3. Compare the options using verified information
4. Present a final recommendation with specific costs, best travel times, and highlights
5. If any detail seems incomplete, search once more to confirm before responding.
""" + ZH_RULE,
    )

    response = await checker_agent.run(
        "I have a $175/day budget and want to travel in April. Which destinations fit my budget and timing?",
    )
    print(response)


#===================================================================
#实验八:人工审批关卡(Human-in-the-loop Gate)
#===================================================================
#核心思想:智能体想"动手"之前,必须先过一道关卡。
#   低风险 → 自动放行
#   中风险 → 自动放行(但排队等批量复查)
#   高风险 → 拦下来,由人决定:批准 / 拒绝 / 上报
#   被拒绝后 → 把"拒绝原因"反馈给模型,让它改一版再来 = 修订循环
#
#★ 与原示例的 3 处差异(为适配本机环境)★
#  1) 原示例用 Azure OpenAI 的 Responses API + az login 认证;
#     本机没有 Azure 配置(实测 AZURE_OPENAI_ENDPOINT 等均为空),
#     所以改用本文件已有的 DeepSeek provider。
#  2) 原示例是笔记本代码,这里包成 async def(因为里面有 await)。
#  3) 风险关键词表里补上了中文词 —— 否则模型用中文提动作时,
#     一个词都匹配不上,会全部落到"未知 → medium",演示不出分级效果。
#
#⚠️ 运行后会在项目目录里生成审计日志文件:gate_log_<时间戳>.jsonl

#DEMO_MODE=True  → 全自动演示:高风险第 0 次被拒、重试后自动批准(展示循环机制)
#DEMO_MODE=False → 真人在终端里输入 approve / deny / escalate
DEMO_MODE = True

#每次运行用带时间戳的独立文件名,避免多次运行互相覆盖
GATE_LOG_PATH = Path(
    f"gate_log_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
)

#------------------- 风险关键词表 -------------------
#英文词是原示例的;中文词是本次新增的(原因见上方差异说明 3)
#★ 已做的一处安全修正(方案B)★
#  原表里有 "weather" / 中文的 "天气" —— 但这是个【名词】,不是动作词。
#  后果:只要动作句里"提到天气",就会被判成低风险自动执行,例如
#        "今天天气不错" → low(实测过)。而低风险表的本意是"只读类动作"。
#  所以这里把 weather / 天气 删掉了,只保留真正的动词。
#  现在"今天天气不错"会被判成 medium(认不出→兜底),走批量复查,更安全。
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

#自动放行的说明文案
AUTO_APPROVE_REASONS = {
    "low": "自动批准(低风险)",
    "medium": "自动批准(中风险,已排队等批量复查)",
}


def classify_risk(action: str) -> str:
    """把动作分成 low / medium / high 三级。

    关键词启发式:先查高风险(最严重),再查低风险(只读类),
    最后查中风险(会改数据的)。**认不出来的动作默认归 medium,不是 low**。
    为什么?只读关键词表总会有盲区,把"看不懂的动作"送进批量复查,
    比直接自动执行要安全得多。
    """
    text = action.lower()
    #any(...):只要关键词表里有一个词出现在动作里,就成立
    if any(kw in text for kw in HIGH_RISK_KEYWORDS):
        return "high"
    if any(kw in text for kw in LOW_RISK_KEYWORDS):
        return "low"
    if any(kw in text for kw in MEDIUM_RISK_KEYWORDS):
        return "medium"
    #兜底:认不出来就归 medium(而不是 low),交给批量复查
    return "medium"


def gate_action(action_description: str, risk_tier: str, attempt: int = 0) -> dict:
    """执行一次"行动前关卡",返回决定字典(decision / reason / ts 等)。

    decision 只能是三者之一:approve / deny / escalate。
    遇到 EOF 或无法识别的输入时,安全默认 = deny(拒绝)。
    """
    print(f"[关卡] 待审批动作({risk_tier},第 {attempt} 次尝试):{action_description}")

    if DEMO_MODE:
        #演示模式:高风险第 0 次拒绝,重试时按剧本自动通过(专门用来演示循环机制)
        if risk_tier == "high":
            decision = "approve" if attempt >= 1 else "deny"
            reason = (
                "DEMO_MODE:高风险动作重试后按剧本批准(演示循环机制)"
                if attempt >= 1
                else "DEMO_MODE:高风险动作在首次尝试被拒绝"
            )
        else:
            decision = "approve"
            reason = f"DEMO_MODE:对 {risk_tier} 风险的固定回复"
    else:
        #真人模式:在终端里等你输入
        try:
            raw = input("[关卡] 批准(approve)/ 拒绝(deny)/ 上报(escalate)? ")
            raw = raw.strip().lower()
        except EOFError:
            #输入流"到头了"(比如管道里没数据):不能崩,当作空输入处理
            raw = ""
        if raw in {"approve", "deny", "escalate"}:
            decision, reason = raw, "操作员输入"
        elif raw == "":
            decision, reason = "deny", "没有收到输入,安全默认=拒绝"
        else:
            decision, reason = "deny", f"无法识别的输入 {raw!r},安全默认=拒绝"

    return {
        "decision": decision,
        "reason": reason,
        "action": action_description,
        "risk_tier": risk_tier,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def tiered_gate(action: str, attempt: int = 0) -> dict:
    """先分级、再过关卡。低/中风险自动批准,高风险才拦下来。"""
    tier = classify_risk(action)
    if tier in AUTO_APPROVE_REASONS:
        return {
            "decision": "approve",
            "reason": AUTO_APPROVE_REASONS[tier],
            "action": action,
            "risk_tier": tier,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    #只有高风险才会走到这里,去问人
    return gate_action(action, tier, attempt=attempt)


def log_decision(decision: dict) -> None:
    """把一次关卡决定追加写入 JSONL 审计日志(不管批准还是拒绝都留一笔)。"""
    #"a" = 追加到文件末尾,不覆盖旧内容
    with GATE_LOG_PATH.open("a", encoding="utf-8") as f:
        #json.dumps:把字典转成 JSON 文字
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")


#用于"提议动作"的智能体(替代原示例里的 Azure OpenAI 调用)
#注意:这里套用 ZH_RULE 让它说中文,所以上面的关键词表必须包含中文词
planner_agent = provider.as_agent(
    name="ActionPlanner",
    instructions=(
        "You are an action planner for an agent. Propose ONE concrete next action "
        "toward the user's goal, as a single short sentence. "
        "If a prior rejection reason is given, propose a DIFFERENT action that "
        "addresses that reason. "
        "Reply with the action sentence ONLY - no explanation, no bullet points, "
        "no quotes. "
        + ZH_RULE
    ),
)


async def propose_action(goal: str, prior_rejection: str | None = None) -> str:
    """让大模型为某个目标提一个具体的下一步动作。

    如果传入了"上一次的拒绝原因",它会被反馈回去,
    这样模型下一次就会避开同样的坑。
    """
    user_text = f"目标:{goal}"
    if prior_rejection:
        #把拒绝原因一并告诉它
        user_text += f"\n\n上一版提议被拒绝了,原因:{prior_rejection}"
    response = await planner_agent.run(user_text)
    return str(response).strip()


async def run_with_revision(goal: str, max_revisions: int = 2) -> dict:
    """提议 → 过关 → 被拒就修订,最多修订 max_revisions 次。"""
    prior_reason: str | None = None
    decision: dict = {}
    #range(max_revisions + 1) = 第 1 次尝试 + 最多 max_revisions 次重试
    for attempt in range(max_revisions + 1):
        action = await propose_action(goal, prior_rejection=prior_reason)
        decision = tiered_gate(action, attempt=attempt)
        decision["attempt"] = attempt
        log_decision(decision)
        if decision["decision"] == "approve":
            return decision
        #没批准 → 记下拒绝原因,下一轮喂回给模型
        prior_reason = decision["reason"]
    #循环用完还没通过
    return {**decision, "final": "max_revisions_reached"}


async def gate_demo():
    """端到端演示:三个不同风险等级的目标。"""
    goals = [
        "查询西雅图未来几天的天气,用于客户行程规划。",
        "为客户安排一个提醒:航班起飞前 24 小时提醒他办理值机。",
        "给客户发送一封关于高级升舱选项的营销邮件。",
    ]

    for goal in goals:
        print(f"\n=== 目标:{goal} ===")
        outcome = await run_with_revision(goal, max_revisions=1)
        print(f"[最终] {outcome['decision']}({outcome['reason']})")

    print(f"\n=== 审计日志({GATE_LOG_PATH.name})===")
    for line in GATE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        print(f"  [{record['risk_tier']:6s}] {record['decision']:8s} "
              f"attempt={record.get('attempt', '?')} action={record['action'][:140]}")


#===================================================================
#实验九:规划者 + 管家(先"任务分解",再"照着计划干活")
#===================================================================
#分工:
#   ① planning_agent  = 规划者:把"7 天巴黎情侣游"拆成一张【结构化】任务清单
#   ② concierge_agent = 管家  :拿着这张清单,调用订票/订房/订活动工具逐条执行
#★ 与原示例的 3 处差异(和实验三/七的处理方式一致)★
#   1) 原示例用 Azure Microsoft Foundry(FoundryChatClient + DefaultAzureCredential),
#      本机没配 Azure 环境变量 → 改用本文件已有的 DeepSeek provider。
#   2) 原示例用 options={"response_format": TravelPlan} 这种强校验写法,
#      DeepSeek 不支持(会返回 400: This response_format type is unavailable)。
#      改成和实验三一样的"JSON 模式 + 自己用 pydantic 校验"。
#   3) 原示例是笔记本代码,这里包成 async def;并套用 ZH_RULE 让输出为中文。

#------------------- 结构化输出的数据模型 -------------------
class TravelSubTask(BaseModel):
    task_id: int
    description: str
    assigned_agent: str    # "flight_agent" / "hotel_agent" / "activity_agent"
    priority: str          # "high" / "medium" / "low"
    dependencies: list[int] = []   # 依赖哪些前置任务(按 task_id)


class TravelPlan(BaseModel):
    destination: str
    trip_duration_days: int
    subtasks: list[TravelSubTask]
    total_estimated_budget_usd: int
    notes: str


#------------------- 三个"专业工具"(模拟订票/订房/订活动) -------------------
#注:原示例写的是 @tool(不带参数)。本文件里其他工具都用
#   @tool(approval_mode="never_require") —— 意思是"模型调用时无需人工确认"。
#   保持一致,否则演示可能卡在"等待批准"上。
@tool(approval_mode="never_require")
def book_flight(
    #字符串,参数名,类型,给AI的说明
    destination: Annotated[str, "The destination city"],
    departure_date: Annotated[str, "Departure date (YYYY-MM-DD)"],
    return_date: Annotated[str, "Return date (YYYY-MM-DD)"],
) -> str:
    """Search and book flights for the trip."""
    return f"Flight booked to {destination}: {departure_date} → {return_date}, confirmation #FLT-{hash(destination) % 10000:04d}"


@tool(approval_mode="never_require")
def reserve_hotel(
    city: Annotated[str, "The city for the hotel"],
    check_in: Annotated[str, "Check-in date (YYYY-MM-DD)"],
    check_out: Annotated[str, "Check-out date (YYYY-MM-DD)"],
    guests: Annotated[int, "Number of guests"],
) -> str:
    """Reserve a hotel room in the destination city."""
    return f"Hotel reserved in {city}: {check_in} to {check_out} for {guests} guests, confirmation #HTL-{hash(city) % 10000:04d}"


@tool(approval_mode="never_require")
def book_activity(
    activity_name: Annotated[str, "Name of the activity or tour"],
    date: Annotated[str, "Date of the activity (YYYY-MM-DD)"],
    participants: Annotated[int, "Number of participants"],
) -> str:
    """Book a tour, museum visit, or other activity."""
    return f"Activity booked: {activity_name} on {date} for {participants} people, confirmation #ACT-{hash(activity_name) % 10000:04d}"


#★ 同样必须包在 async def 里(因为有 await)★
async def planner_concierge_demo():
    # ---------- ① 规划者:把请求拆成结构化任务清单 ----------
    planning_agent = provider.as_agent(
        name="TravelPlanner",
        #把它拆分成具体的子任务(航班、酒店、活动、后勤)
        #把每个子任务分配给相应的专业智能体
        #设定优先级，并找出任务之间的依赖关系
        instructions="""You are a travel planning agent. When given a travel request:
1. Break it into specific subtasks (flights, hotels, activities, logistics)
2. Assign each subtask to the appropriate specialist agent
3. Set priorities and identify dependencies between tasks
4. Estimate the total budget
""" + ZH_RULE,
    )

    #★ 这里不能用 options={"response_format": TravelPlan}(DeepSeek 会报 400)★
    #  改成两步走:① json_object 模式 + 提示词里写清字段结构
    #            ② 拿到后自己用 TravelPlan.model_validate() 校验
    plan_prompt = (
        "Plan a 7-day trip to Paris for a couple interested in art, cuisine, and history. "
        "Budget around $5000. "
        "只返回一个 JSON 对象(不要 markdown、不要多余文字)。"
        #字段名必须英文(要和 pydantic 模板对上),字段内容用简体中文
        "字段名用英文、字段内容用简体中文,格式严格如下:"
        '{"destination": "string", "trip_duration_days": 0, '
        '"subtasks": [{"task_id": 0, "description": "string", '
        '"assigned_agent": "flight_agent|hotel_agent|activity_agent", '
        '"priority": "high|medium|low", "dependencies": [0]}], '
        '"total_estimated_budget_usd": 0, "notes": "string"}'
    )
    result = await planning_agent.run(
        plan_prompt,
        options={"response_format": {"type": "json_object"}},
    )

    try:
        plan = TravelPlan.model_validate(json.loads(str(result)))
    except (json.JSONDecodeError, ValidationError) as e:
        print("计划解析/校验失败:", type(e).__name__, str(e)[:300])
        print("原始回答:", result)
        return

    print(f"目的地:{plan.destination}")
    print(f"天数:{plan.trip_duration_days} 天")
    print(f"预算:${plan.total_estimated_budget_usd}")
    print("\n子任务:")
    for task in plan.subtasks:
        print(f"  [{task.priority}] {task.task_id}. {task.description} → {task.assigned_agent}")

    print("\n" + "-" * 30 + " 下面交给管家执行 " + "-" * 30 + "\n")

    # ---------- ② 管家:拿着计划去干活 ----------
    concierge_agent = provider.as_agent(
        name="Concierge",
        instructions="""You are a travel concierge executing a structured travel plan.
Use the available tools to fulfil each subtask. Work through the subtasks in order,
respecting dependencies. Summarise the results when finished.
""" + ZH_RULE,
        tools=[book_flight, reserve_hotel, book_activity],
    )

    #把任务清单拼成一段文字,当作执行指令
    #join 的规则:把前面的字符串插到后面每一项中间
    subtask_lines = "\n".join(
        f"- [{t.priority}] {t.task_id}. {t.description} "
        f"(agent: {t.assigned_agent}, deps: {t.dependencies})"
        for t in plan.subtasks
    )
    execution_prompt = (
        f"Execute the following travel plan for {plan.destination} "
        f"({plan.trip_duration_days} days, ${plan.total_estimated_budget_usd} budget):\n"
        f"{subtask_lines}"
    )

    exec_response = await concierge_agent.run(execution_prompt)
    print(exec_response)


#===================================================================
#实验十:工作流(Workflow)—— 把多个智能体连成一条流水线
#===================================================================
#思路:前面几个实验都是"代码手动按顺序调用智能体";这一节改成"声明式"——
#      先画好流程图(谁接谁),再交给框架自动跑。
#
#   FrontDesk(前台顾问) --推荐--> Concierge(礼宾审核员) --批准/改进-->
#
#两台机器的职责"互相制衡":
#   前台:一次只给一条推荐,言简意赅,不闲聊
#   礼宾:判断这条推荐是不是"最地道、不落俗套"的;是就批准,不是就给出改进方向
#
#★ 与原示例的差异 ★
#  1) 原示例用 Azure Microsoft Foundry(FoundryChatClient + AzureCliCredential),
#     本机没配 Azure 环境变量 → 改用本文件已有的 DeepSeek provider。
#  2) 原示例是笔记本代码,这里包成 async def(有 await)。
#  3) 去掉了 IPython/SVG 那套"在笔记本里内嵌画图"的代码(普通脚本里显示不了图片);
#     但保留了 Mermaid / DiGraph 文本输出,以及可选的 SVG 导出(缺 graphviz 会自动跳过)。
#  4) 套用 ZH_RULE 让输出为中文。

#------------------- 审核员(礼宾)的身份与职责 -------------------
#你是一名酒店礼宾员,对于如何为旅行者提供最地道、最原汁原味的体验颇有见地。
#你的目标是判断前台旅行顾问为旅行者推荐的,是否是最理想的、不落俗套(非游客式)的体验。
#如果是,就说明该推荐已获批准。
#如果不是,就给出如何改进这条建议的思路——但不要用具体的例子。
REVIEWER_NAME = "Concierge"
REVIEWER_INSTRUCTIONS = """
    You are a hotel concierge who has opinions about providing the most local and authentic experiences for travelers.
    The goal is to determine if the front desk travel agent has recommended the best non-touristy experience for a traveler.
    If so, state that it is approved.
    If not, provide insight on how to refine the recommendation without using a specific example.
    """

#------------------- 前台顾问的身份与职责 -------------------
#你是一名前台旅行顾问,有十年从业经验;因为要接待大量客户,所以你以言简意赅著称。
#你的目标是为旅行者提供最值得去的活动和地点。
#每次回复只给出一条推荐。
#你对手头的目标全神贯注。
#不要浪费时间闲聊。
#在打磨想法时,请考虑(别人给出的)建议。
FRONTDESK_NAME = "FrontDesk"
FRONTDESK_INSTRUCTIONS = """
    You are a Front Desk Travel Agent with ten years of experience and are known for brevity as you deal with many customers.
    The goal is to provide the best activities and locations for a traveler to visit.
    Only provide a single recommendation per response.
    You're laser focused on the goal at hand.
    Don't waste time with chit chat.
    Consider suggestions when refining an idea.
    """

#------------------- 创建两个智能体 -------------------
reviewer_agent = provider.as_agent(
    name=REVIEWER_NAME,
    instructions=REVIEWER_INSTRUCTIONS + ZH_RULE,
)

front_desk_agent = provider.as_agent(
    name=FRONTDESK_NAME,
    instructions=FRONTDESK_INSTRUCTIONS + ZH_RULE,
)


async def workflow_demo():
    #------------------- 搭建工作流(声明式:先画图,再执行) -------------------
    workflow = (
        #start_executor:指定"起点"是谁(用户的话先交给它)
        WorkflowBuilder(start_executor=front_desk_agent)
        #add_edge:连一条边 —— 从"前台"流向"审核"
        .add_edge(front_desk_agent, reviewer_agent)
        #build:收尾,生成真正的工作流
        .build()
    )

    #------------------- 可视化(把流程图打成文本) -------------------
    print("生成工作流可视化...")
    viz = WorkflowViz(workflow)
    print("Mermaid 字符串:\n=======")
    print(viz.to_mermaid())
    print("=======")
    print("DiGraph 字符串:\n=======")
    print(viz.to_digraph())
    print("=======")

    #导出 SVG 需要额外的 graphviz(库 + 系统程序);没装就优雅跳过,不让程序崩
    try:
        svg_file = viz.export(format="svg")
        print(f"SVG 已保存到:{svg_file}")
    except Exception as e:
        #ImportError:通常是缺少 graphviz 库
        print(f"已跳过 SVG 导出(装 graphviz 后可启用):{type(e).__name__}: {e}")

    #------------------- 运行工作流 -------------------
    #把用户的话喂给起点(前台),框架会自动沿着边一路往下跑
    events = await workflow.run("I would like to go to Paris.")
    #get_outputs():把工作流里"输出节点"的产出收集成列表
    #★ 实测提醒:这里会返回 2 条(前台 + 审核员 都算输出节点),
    #   而原示例注释写的是"只有审核员一个"。所以别硬取 outputs[0],
    #   全部打印出来最直观;列表里最后一条 = 流水线末端(审核员)的结论。
    outputs = events.get_outputs()

    print(f"\n=== 工作流输出(共 {len(outputs)} 条,最后一条 = 流水线末端)===")
    for i, out in enumerate(outputs, 1):
        #原示例写的是 result.replace("None", "") —— 但没赋值回去,等于白做。这里真的替换。
        text = str(out.text).replace("None", "")
        print(f"\n--- 第 {i} 个输出 ---")
        print(text)


#===================================================================
#实验十一:元认知设计模式(自我反思 + 回退 + 自我评估)
#===================================================================
#核心思想:让智能体"自己监督自己"——
#   ① 回退(fallback):主系统挂了就去备用系统,而且要【如实告诉用户 "我换了系统"】
#   ② 自我反思:每次回复后,自己评估一下"答得完不完整、有没有用"
#   ③ 第三方评估:再派一个"质量评估员"给回复打分(完整性 / 准确性 / 有用性)
#
#★ 与原示例的差异 ★
#  1) 原示例用 Azure Microsoft Foundry(FoundryChatClient + DefaultAzureCredential),
#     本机没配 Azure 环境变量 → 改用本文件已有的 DeepSeek provider。
#  2) 原示例是笔记本代码,这里包成 async def(有 await)。
#  3) 套用 ZH_RULE 让输出为中文。
#  4) ★小修正★ 原示例里评估用的 response 变量被两次赋值覆盖了
#     (评估提示词写的是 "Paris 的问题",实际塞进去的却是 Berlin 的回复),
#     这里拆成 response_paris / response_berlin 两个变量。

#------------------- 主 / 备 两个航班工具 -------------------
@tool(approval_mode="never_require")
def get_flight_times(
    #destination: 参数名
    #Annotated:给类型"贴标签"——这段文字 AI 会读到
    destination: Annotated[str, "The destination city"]
) -> str:
    #工具说明
    """Get available flight times for a destination (primary source)."""
    flights = {
        "Paris": "Departures: 08:00, 12:30, 17:45 — from $350",
        "Tokyo": "Departures: 11:00, 23:30 — from $890",
        "Barcelona": "Departures: 07:15, 14:00, 19:30 — from $280",
    }
    if destination in flights:
        return flights[destination]
    #故意抛错 —— 专门用来演示"主系统失败 → 切备用系统"的回退流程
    raise Exception(f"404: No flights found for {destination} in primary system")


@tool(approval_mode="never_require")
def get_flight_times_backup(
    destination: Annotated[str, "The destination city"]
) -> str:
    """Get available flight times from backup system (used when primary fails)."""
    backup_flights = {
        "Berlin": "Departures: 09:00, 16:00 — from $220",
        "Sydney": "Departures: 22:00 — from $1200",
        "New York City": "Departures: 06:00, 10:30, 15:00, 20:00 — from $450",
    }
    return backup_flights.get(
        destination,
        f"No flights found for {destination} in any system. Please try again later.",
    )


async def metacognition_demo():
    #------------------- ① 带"回退能力"的自我反思智能体 -------------------
    #查询航班时:
    #1. 首先尝试主要航班系统(get_flight_times)
    #2. 如果主要系统失败(404 错误),先承认该错误,再尝试备用系统(get_flight_times_backup)
    #3. 始终向用户解释发生了什么——对"回退"保持透明
    #4. 如果两个系统都失败,请道歉并给出替代建议
    #在每次回复后,简要评估一下你的回答是否完整、是否有帮助。
    flight_agent = provider.as_agent(
        tools=[get_flight_times, get_flight_times_backup],
        name="FlightBookingAgent",
        instructions="""You are a flight booking agent with self-reflection capabilities.

When looking up flights:
1. Try the primary flight system first (get_flight_times)
2. If the primary system fails (404 error), acknowledge the error and try the backup system (get_flight_times_backup)
3. Always explain to the user what happened — be transparent about fallbacks
4. If both systems fail, apologize and suggest alternatives

After each response, briefly evaluate whether your answer was complete and helpful.
""" + ZH_RULE,
    )

    #测试 1:目的地只在【主系统】里(Paris)
    print("=== 测试 1:目的地在主系统里 ===")
    response_paris = await flight_agent.run(
        "What flights are available to Paris?",
    )
    print(response_paris)

    #测试 2:目的地只在【备用系统】里(Berlin)→ 看它会不会自己回退
    print("\n=== 测试 2:目的地只在备用系统里 ===")
    response_berlin = await flight_agent.run(
        "What flights are available to Berlin?",
    )
    print(response_berlin)

    #------------------- ② 自我评估智能体 -------------------
    #你是一个旅行代理回复的质量评估员。
    #给定一个旅行问题以及该代理的回复,请从以下方面进行评估:
    #1. 完整性:它是否回答了问题的所有部分?(1-5 分)
    #2. 准确性:信息是否正确?(1-5 分)
    #3. 有用性:旅行者会觉得这有用吗?(1-5 分)
    #请给出简短的评估,包含各项评分,以及一条改进建议。
    eval_agent = provider.as_agent(
        tools=[get_flight_times, get_flight_times_backup],
        name="ResponseEvaluator",
        instructions="""You are a quality evaluator for travel agent responses.
Given a travel question and the agent's response, evaluate:
1. Completeness: Did it answer all parts of the question? (1-5)
2. Accuracy: Is the information correct? (1-5)
3. Helpfulness: Would a traveler find this useful? (1-5)
Provide a brief evaluation with scores and one suggestion for improvement.
""" + ZH_RULE,
    )

    #评估测试 1 的回复(注意:这里用 response_paris,不要用被覆盖过的变量)
    eval_prompt = (
        "Question: What flights are available to Paris?\n"
        f"Agent Response: {response_paris}\n\n"
        "Please evaluate the above response."
    )

    evaluation = await eval_agent.run(eval_prompt)
    print("\n=== 自我评估(Self-Evaluation) ===")
    print(evaluation)


#===================================================================
#实验十二:生产环境视角(可观测性 + 质量评估)
#===================================================================
#前面十一个实验关注"能不能跑通";这一节关注"上线后怎么盯住它"——
#   ① 可观测性(observability):至少先把【耗时】量出来
#      (真实生产里还会看 token 消耗、失败率、每次调用了哪些工具等)
#   ② 质量评估:派一个评估员给回复打分(完整性 / 准确性 / 有用性 / 总分)
#
#★ 与原示例的差异 ★
#  1) 原示例用 Azure Microsoft Foundry(FoundryChatClient + DefaultAzureCredential),
#     本机没配 Azure 环境变量 → 改用本文件已有的 DeepSeek provider。
#  2) 原示例是笔记本代码,这里包成 async def(有 await)。
#  3) 套用 ZH_RULE 让输出为中文。

#------------------- 两个业务工具:航班 + 活动 -------------------
@tool(approval_mode="never_require")
def get_flight_info(destination: Annotated[str, "The destination city"]) -> str:
    """Get flight information for a destination."""
    flights = {
        "Paris": "BA 304, 08:30-11:45, $350",
        "Tokyo": "JL 044, 11:00-07:00+1, $890",
        "Barcelona": "VY 7821, 07:15-10:30, $280",
    }
    return flights.get(destination, f"No flights found to {destination}")


@tool(approval_mode="never_require")
def get_activity_suggestions(destination: Annotated[str, "The destination city"]) -> str:
    """Get activity suggestions for a destination."""
    activities = {
        "Paris": "Louvre Museum, Eiffel Tower, Seine River Cruise, Montmartre walking tour",
        "Tokyo": "Senso-ji Temple, Tsukiji Market tour, Shibuya Crossing, teamLab Borderless",
        "Barcelona": "Sagrada Familia, Park Güell, La Boqueria Market, Gothic Quarter walk",
    }
    return activities.get(destination, f"No activities found for {destination}")


async def production_demo():
    #------------------- ① 带"计时"的可观测智能体 -------------------
    agent = provider.as_agent(
        tools=[get_flight_info, get_activity_suggestions],
        name="TravelAgent",
        instructions=(
            "You are a helpful travel agent. Use the available tools to help users "
            "plan their trips. Provide comprehensive, actionable travel advice. "
            + ZH_RULE
        ),
    )

    #time.time():返回"从 1970-01-01 0:00:00 到现在的秒数"
    #拿到两个时间点一减,就是这次调用的耗时
    start_time = time.time()
    response = await agent.run(
        "I want to plan a day trip in Paris. What flights and activities do you recommend?",
    )
    elapsed = time.time() - start_time
    print(f"响应耗时 {elapsed:.2f} 秒:\n{response}")

    #------------------- ② 质量评估智能体 -------------------
    #你从以下几个标准来评估旅行代理的回复:
    #1. 完整性(1-5 分):是否既涵盖了航班,又涵盖了活动?
    #2. 准确性(1-5 分):信息是否前后一致?
    #3. 有用性(1-5 分):旅行者会觉得这可以直接照着做吗?
    #4. 总体评分(1-5 分)
    #请为每一项给出评分,并各附一句简短说明。
    evaluator = provider.as_agent(
        name="ResponseEvaluator",
        instructions="""You evaluate travel agent responses on these criteria:
1. Completeness (1-5): Did it cover flights AND activities?
2. Accuracy (1-5): Is the information consistent?
3. Helpfulness (1-5): Would a traveler find this actionable?
4. Overall Score (1-5)
Provide scores and a brief explanation for each.
""" + ZH_RULE,
    )

    evaluation = await evaluator.run(f"Evaluate this travel agent response:\n\n{response}")
    print(f"\n评估结果:\n{evaluation}")


#===================================================================
#实验十三:上下文管理(长对话怎么"记得住、又不啰嗦")
#===================================================================
#长对话的两个难题:
#   ① 记不住 —— 用户前面说过的话, 后面就忘了
#   ② 记得太多 —— 全都塞回给模型, token 蹭蹭涨, 又慢又贵
#这一节演示两种应对手段:
#   手段一(ContextAwareAgent)     : 靠【指令】要求它"把前文压缩成要点、记住偏好、别重复"
#   手段二(SummarizingTravelAgent): 靠【工具】主动把偏好写进一条"摘要记录", 后面引用摘要
#
#★ 与原示例的差异 ★
#  1) 原示例用 Azure Microsoft Foundry → 改用本文件已配好的 DeepSeek provider。
#  2) 原示例是笔记本代码, 这里包成 async def(有 await)。
#  3) 套用 ZH_RULE 让输出为中文。

async def context_management_demo():
    #=================================================================
    #手段一:靠"指令"管理上下文
    #=================================================================
    agent = provider.as_agent(
        name="ContextAwareAgent",
        instructions="""You are a helpful travel planning assistant with excellent memory management.
When conversations get long:
1. Summarize previous context into key points
2. Track user preferences mentioned earlier
3. Reference previous decisions without repeating full details
Always maintain continuity while being concise.
""" + ZH_RULE,
    )

    #create_session():开一个"会话"。同一个 session 里的多轮对话共享上下文,
    #这就是智能体"记得住"的原因。
    session = agent.create_session()

    #第 1 轮:初始偏好
    response = await agent.run(
        "I'm planning a trip to Japan. I love sushi, temples, and photography.",
        session=session,
    )
    print(f"第 1 轮: {response}\n")

    #第 2 轮:补充细节
    response = await agent.run(
        "My budget is $3000 and I'll be traveling solo for 10 days in April.",
        session=session,
    )
    print(f"第 2 轮: {response}\n")

    #第 3 轮:测试它能不能把前两轮合起来回答
    response = await agent.run(
        "Based on everything I've told you so far, what's the one thing you'd recommend I not miss?",
        session=session,
    )
    print(f"第 3 轮: {response}\n")

    #第 4 轮:继续加信息(住宿偏好)
    response = await agent.run(
        "What about accommodation? I prefer traditional Japanese inns.",
        session=session,
    )
    print(f"第 4 轮: {response}\n")

    #第 5 轮:中途改主意(改到十月)
    response = await agent.run(
        "Actually, I've changed my mind about the dates. I'll go in October instead for the autumn colors.",
        session=session,
    )
    print(f"第 5 轮: {response}\n")

    #第 6 轮:让它把"完整计划"汇总一遍 —— 最能看出它到底记住了多少
    response = await agent.run(
        "Summarize my complete travel plan so far - destination, budget, duration, "
        "interests, accommodation, and timing.",
        session=session,
    )
    print(f"第 6 轮: {response}\n")

    #=================================================================
    #手段二:靠"工具"主动做摘要
    #=================================================================
    @tool(approval_mode="never_require")
    def summarize_preferences(conversation_notes: str) -> str:
        """Summarize accumulated user preferences into a compact format."""
        return f"[SUMMARY] User preferences recorded: {conversation_notes}"

    print("\n" + "-" * 20 + " 手段二:带摘要工具的智能体 " + "-" * 20 + "\n")

    #CONTEXT MANAGEMENT RULES:
    #1. 收集了若干偏好后,调用 summarize_preferences() 把摘要记录下来
    #2. 用户让你回忆细节时,引用你记录过的摘要
    #3. 回复要简洁 —— 不要把整段历史重新说一遍
    summarizing_agent = provider.as_agent(
        name="SummarizingTravelAgent",
        instructions="""You are a helpful travel planning assistant that actively manages conversation context.

CONTEXT MANAGEMENT RULES:
1. After gathering several user preferences, call summarize_preferences() to record a compact summary
2. When the user asks you to recall details, reference your recorded summaries
3. Keep responses concise - avoid restating the entire history

PLANNING PROCESS:
1. Gather user preferences (destination, budget, dates, interests)
2. Summarize preferences using the tool
3. Create recommendations based on the summary
4. Update the summary when preferences change
""" + ZH_RULE,
        tools=[summarize_preferences],
    )

    summary_session = summarizing_agent.create_session()

    #一次性把一堆偏好倒给它,并明确要求"用摘要工具记录"
    response = await summarizing_agent.run(
        "I want to visit Greece. I love seafood, history, and island hopping. "
        "Budget is $4000 for two weeks. Traveling with my partner in June. "
        "Please record these preferences using your summarization tool.",
        session=summary_session,
    )
    print(f"Agent: {response}\n")

    #再让它"根据你记录的内容"给建议 —— 看它会不会去引用摘要
    response = await summarizing_agent.run(
        "Now, based on what you've recorded, suggest the top 3 islands we should visit.",
        session=summary_session,
    )
    print(f"Agent: {response}\n")


#===================================================================
#实验十四:Cognee 长期记忆(知识图谱)
#===================================================================
#这一节用 cognee 把资料变成"知识图谱", 让智能体拥有【跟会话无关的长期记忆】。
#和实验十三的区别:
#   实验十三 —— 记忆只在"同一个 session"里有效, 换个会话就忘了
#   cognee   —— 记忆存在数据库/图谱里, 换新会话照样查得到
#
#★ 本部分需要额外安装 cognee, 所以做了"没装就跳过"的保护 ★
#   安装命令:pip install "cognee[gliner]"
#     [gliner] 会带上本地小模型(实体抽取 + 向量化), 首次运行自动下载, 免 API key
#   没装 / 跑不起来 → 只打印一行提示, 不影响前面 13 个部分
#
#★ 与原示例的差异 ★
#  1) 原示例的 Azure Foundry 客户端 → 改用本文件已有的 DeepSeek provider。
#  2) 原示例是笔记本代码, 这里包成 async def。
#  3) 套用 ZH_RULE 让输出为中文。
#  4) 去掉了 os.environ["LLM_API_KEY"] = ... 那两行 ——
#     走本地模型路线时不需要任何 API key。

#先用 try/except 检查 cognee 装没装(装没装都不能让整个文件挂掉)
try:
    import cognee
    from cognee.modules.search.types import SearchType
    from cognee import visualize_graph

    _COGNEE_AVAILABLE = True
except ImportError:
    _COGNEE_AVAILABLE = False


async def cognee_demo():
    #------------------- 0) 没装就优雅跳过 -------------------
    if not _COGNEE_AVAILABLE:
        print("⏭️  本部分需要 cognee, 但当前未安装, 已跳过。")
        print('   安装方法: pip install "cognee[gliner]"')
        print("   装好后本部分会自动启用。")
        return

    try:
        #================= 1) 准备 Cognee 存储目录 =================
        #Path(...):把字符串变成"路径对象"
        #.resolve():转成绝对路径
        DATA_ROOT = Path('.data_storage').resolve()
        SYSTEM_ROOT = Path('.cognee_system').resolve()

        #mkdir:创建文件夹
        #parents=True:父文件夹不存在就自动创建
        #exist_ok=True:文件夹已存在也不报错
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        SYSTEM_ROOT.mkdir(parents=True, exist_ok=True)

        #cognee.config:配置总台;这两行告诉 cognee 数据仓库放哪里
        cognee.config.data_root_directory(str(DATA_ROOT))
        cognee.config.system_root_directory(str(SYSTEM_ROOT))

        #prune_data:清空数据仓库
        await cognee.prune.prune_data()
        #metadata=True:连元数据一起清掉
        await cognee.prune.prune_system(metadata=True)
        print("✅ Cognee 存储已配置并重置")

        #================= 2) 准备三份原始素材 =================
        developer_intro = (
            #你好,我是一名 AI/后端工程师。
            "Hi, I'm an AI/Backend engineer. "
            #我用 Pydantic 构建 FastAPI 服务,编写大量基于 asyncio/aiohttp 的管道,
            "I build FastAPI services with Pydantic, heavy asyncio/aiohttp pipelines, "
            #并通过 pytest-asyncio 进行生产级测试。
            "and production testing via pytest-asyncio. "
            #我曾在 AWS、Azure 和 Google Cloud 上交付过低延迟 API。
            "I've shipped low-latency APIs on AWS, Azure, and GoogleCloud."
        )

        python_zen_principles = """
# The Zen of Python: Practical Guide

## Key Principles With Guidance

### 1. Beautiful is better than ugly
Prefer descriptive names, clear structure, and consistent formatting.

### 2. Explicit is better than implicit
Be clear about behavior, imports, and types.

### 3. Simple is better than complex
Choose straightforward solutions first.

### 4. Flat is better than nested
Use early returns to reduce indentation.

## Modern Python Tie-ins
- Type hints reinforce explicitness
- Context managers enforce safe resource handling
- Dataclasses improve readability for data containers
"""

        human_agent_conversations = """
"conversations": [
    {
      "topic": "async/await patterns",
      "user_query": "I'm building a web scraper that needs to handle thousands of URLs concurrently. What's the best way to structure this with asyncio?",
      "assistant_response": "Use asyncio with aiohttp, a semaphore to cap concurrency, TCPConnector for connection pooling, and context managers for session lifecycle."
    },
    {
      "topic": "dataclass vs pydantic",
      "user_query": "When should I use dataclasses vs Pydantic models?",
      "assistant_response": "For API input/output, prefer Pydantic: runtime validation, type coercion, JSON serialization. Integrates cleanly with FastAPI."
    },
    {
      "topic": "testing patterns",
      "user_query": "What's the best approach for pytest with async functions?",
      "assistant_response": "Use pytest-asyncio, async fixtures, and an isolated test database or mocks to reliably test async code."
    },
    {
      "topic": "error handling and logging",
      "user_query": "What's the best approach for production-ready error management?",
      "assistant_response": "Centralized error handling with custom exceptions, structured logging, and FastAPI middleware."
    }
  ]
"""
        print("✅ 数据源已准备就绪")

        #================= 3) 入库 + 建知识图谱 =================
        #cognee.add(...):Cognee 的"收数据"接口
        #node_set=[...]:给这份数据打个标签 / 归个类(后面可以按标签定向搜索)
        await cognee.add(developer_intro, node_set=["developer_data"])
        await cognee.add(human_agent_conversations, node_set=["developer_data"])
        await cognee.add(python_zen_principles, node_set=["principles_data"])

        #cognify():① 把长文本切成小块 ② 让模型把小块向量化 ③ 存进数据库, 建成知识图谱
        await cognee.cognify()
        print("✅ 知识图谱已建成")

        #================= 4) 可视化知识图谱 =================
        await visualize_graph('./cognee_graph.html')
        print("📊 图谱已存到 cognee_graph.html — 用浏览器打开就能看")

        #================= 5) 用 memify 丰富记忆 =================
        #在已建好的图谱上"再加工一轮": 从已有节点和关系里推导出新的规律与更丰富的关系
        await cognee.memify()
        print("✅ 记忆已用 memify 丰富")

        #================= 6) 定义两个查询工具 =================
        @tool(approval_mode="never_require")
        async def search_knowledge(
            query: Annotated[str, "Natural-language question to search the knowledge graph"],
        ) -> str:
            """Search the Cognee knowledge graph for relevant developer knowledge, best practices, and past conversations."""
            #cognee.search():cognee 的查询接口
            results = await cognee.search(
                #query_text:cognee 规定的参数名,意思是"用自然语言写的查询文本"
                query_text=query,
                #SearchType:一个枚举(预先定好的常量集),只能用点号从里面挑一个
                #GRAPH_COMPLETION:走知识图谱, 生成一段完整回答
                query_type=SearchType.GRAPH_COMPLETION,
            )
            if not results:
                return "No relevant knowledge found."
            return str(results)

        @tool(approval_mode="never_require")
        async def search_principles(
            query: Annotated[str, "Question about Python principles or best practices"],
        ) -> str:
            """Search only the Python principles subset of the knowledge graph."""
            #NodeSet:枚举值,代表知识图谱中的"节点集合"(即上面的 node_set 标签)
            from cognee.modules.engine.models.node_set import NodeSet
            results = await cognee.search(
                query_text=query,
                query_type=SearchType.GRAPH_COMPLETION,
                #按"分类集合"这个维度筛
                node_type=NodeSet,
                #分类集合的名字是 principles_data → 定向搜索
                node_name=["principles_data"],
            )
            if not results:
                return "No relevant principles found."
            return str(results)

        print("✅ Cognee 工具已定义: search_knowledge, search_principles")

        #================= 7) 创建带工具的智能体 =================
        coding_agent = provider.as_agent(
            name="CodingAssistant",
            instructions=(
                "You are an expert coding assistant with access to a knowledge graph "
                "containing developer profiles, Python best practices, and past conversations.\n\n"
                "WORKFLOW:\n"
                "1. Use search_knowledge() to find relevant information from the full knowledge graph.\n"
                "2. Use search_principles() when the question is specifically about Python best practices.\n"
                "3. Combine retrieved knowledge with your own expertise to give comprehensive answers.\n"
                "4. Reference the developer's known tech stack (FastAPI, asyncio, Pydantic) when relevant. "
                + ZH_RULE
            ),
            #★ 工具必须交给 agent, 否则它根本不知道有这两个工具(原示例这里差点漏了)
            tools=[search_knowledge, search_principles],
        )
        print("✅ CodingAssistant 智能体已创建")

        #================= 8) 会话内多轮对话(工作记忆) =================
        session = coding_agent.create_session()

        response = await coding_agent.run(
            "How does my AsyncWebScraper implementation align with Python's design principles?",
            session=session,
        )
        print("🤖 Agent:", response)

        response = await coding_agent.run(
            "Based on what you just said, when should I pick dataclasses versus Pydantic for this work?",
            session=session,
        )
        print("🤖 Agent:", response)
        print("\n💡 智能体把「工作记忆(上一轮回答)」和 Cognee 知识图谱合在一起用了。")

        #================= 9) 换新会话(长期记忆还在) =================
        session_2 = coding_agent.create_session()

        response = await coding_agent.run(
            "What logging guidance should I follow for incident reviews?",
            session=session_2,
        )
        print("🤖 Agent:", response)
        print("\n💡 这是新会话, 但智能体依然能访问完整的 Cognee 知识图谱。")

        response = await coding_agent.run(
            "How should variables be named according to Python best practices?",
            session=session_2,
        )
        print("🤖 Agent:", response)

    except Exception as e:
        #不阻塞:只打印错误, 让后面部分照常跑(错误照打出来, 方便排查)
        print(f"⚠️  cognee 部分运行出错, 已跳过(不影响其他部分): {type(e).__name__}")
        print(f"    {e}")


#===================================================================
#实验十五:加密收据(给智能体每一次工具调用"盖章")
#===================================================================
#核心思想:智能体每调用一次工具, 就生成一张【经过数字签名】的收据。
#   ① 收据里只存"参数的哈希"和"结果的哈希", 不存原文 → 不会泄露支付令牌等敏感信息
#   ② 签名用 Ed25519(私钥签、公钥验), 公钥随身带 → 任何人离线就能验签
#   ③ 收据首尾相连成"链"(每张记录上一张的哈希)→ 改动中间任何一张都会暴露
#
#★ 这一节和前面几节不同:它【不调用任何大模型】, 纯粹是密码学 + 数据结构,
#   所以不需要 API key, 装好依赖就能完整跑通。
#★ 依赖:pynacl(Ed25519 签名)、jcs(RFC 8785 JSON 规范化)
#   安装:pip install pynacl jcs   (本机已装好)
#
#★ 与原示例的差异 ★
#  1) 原示例是笔记本代码, 这里包成普通函数(里面没有 await, 不需要 async)。
#  2) 把演示步骤收进 receipt_demo(), 方便在 main() 里按顺序调用。

#依赖检查(和实验十四同理:装没装都不能让整个文件挂掉)
try:
    from nacl import signing
    from nacl.exceptions import BadSignatureError
    from jcs import canonicalize

    _RECEIPT_DEPS_OK = True
except ImportError:
    _RECEIPT_DEPS_OK = False


#------------------- 三个辅助函数 -------------------
def b64url_nopad(data: bytes) -> str:
    """把二进制转成 base64url 文字(去掉末尾的 = 填充), 方便放进 JSON"""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(s: str) -> bytes:
    """把 base64url 文字解回二进制。编码时去掉了 = , 所以这里要先补回来。"""
    #计算需要补几个 = :当长度已经是 4 的倍数时要补 0 个, 所以要再 % 4 一次
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + padding)


def sha256_canonical(obj) -> str:
    """对「JCS 规范化后的字节」算 SHA-256, 返回带算法前缀的十六进制字符串"""
    #canonicalize:按 JCS(RFC 8785)规则生成唯一确定的字节序列(消除字典顺序差异)
    canonical = canonicalize(obj)
    digest = hashlib.sha256(canonical).hexdigest()
    return f"sha256:{digest}"


def sign_receipt(payload: dict, signing_key, verify_key) -> dict:
    """三步:规范化 → 哈希 → 签名, 然后把签名和公钥附加到收据上"""
    #① 规范化
    canonical = canonicalize(payload)
    #② 哈希:用 .digest()(二进制), 因为下一步签名需要二进制
    message_hash = hashlib.sha256(canonical).digest()
    #③ 签名:用私钥对"哈希值"签名(不是对原文)
    signature_bytes = signing_key.sign(message_hash).signature
    return {
        **payload,   #** 展开:把 payload 的所有字段原样放进新字典
        #⚠️ signature 字段本身【不参与】上面的签名计算, 它是"签完之后"才加上去的
        "signature": {
            "alg": "EdDSA",                                 #声明算法:Ed25519 属于 EdDSA 家族
            "sig": b64url_nopad(signature_bytes),           #签名(二进制)→ 文字, 才能进 JSON
            "public_key": b64url_nopad(bytes(verify_key)),  #公钥也带上 → 审核员可离线验签
        },
    }


def verify_receipt(receipt: dict) -> bool:
    """验证收据签名 —— 只靠收据本身就能验, 不需要联网、也不需要查密钥目录"""
    sig_obj = receipt.get("signature")
    if not sig_obj or sig_obj.get("alg") != "EdDSA":
        return False
    #⭐ 关键:把 signature 字段"摘掉", 还原出当初被签的那份内容
    #(签名时是签完才加上 signature, 所以验签时必须先摘掉 —— 两边严格对称)
    payload = {k: v for k, v in receipt.items() if k != "signature"}
    message_hash = hashlib.sha256(canonicalize(payload)).digest()
    try:
        verify_key = signing.VerifyKey(b64url_decode(sig_obj["public_key"]))
        #⚠️ 验签失败时不是返回 False, 而是抛异常, 所以必须 try/except
        verify_key.verify(message_hash, b64url_decode(sig_obj["sig"]))
        return True
    except BadSignatureError:
        #签名对不上 —— 说明被篡改了(这是"预期内的正常失败")
        return False
    except Exception as exc:
        #其它意外错误(公钥格式错、数据损坏等)也当作无效, 但打印出来便于排查
        print(f"验证出错: {exc}")
        return False


def receipt_hash(receipt: dict) -> str:
    """算「整张收据(含签名)」的哈希 —— 用来把收据串成链"""
    #注意区分:
    #  tool_args_hash / result_hash → 算的是"不含签名"的业务数据
    #  receipt_hash                → 算的是"含签名"的完整收据(用来串联链条)
    digest = hashlib.sha256(canonicalize(receipt)).hexdigest()
    return f"sha256:{digest}"


def make_receipt(
    tool_name: str,
    tool_args: dict,
    tool_result,
    sequence: int,
    previous_receipt_hash,
    signing_key,
    verify_key,
    agent_id: str = "contoso-travel-bot",
    policy_id: str = "contoso-travel-policy-v3",
) -> dict:
    """一步到位:组装 payload → 签名 → 返回收据"""
    payload = {
        "type": "agent.tool_call.v1",    #收据类型 + 版本号(v1), 便于将来演进
        "agent_id": agent_id,            #谁执行的操作
        "tool_name": tool_name,          #用了哪个工具
        #⚠️ 只存哈希而不是原文 —— 防止收据泄露敏感信息(如支付令牌)
        "tool_args_hash": sha256_canonical(tool_args),
        "result_hash": sha256_canonical(tool_result),
        "policy_id": policy_id,          #依据哪份策略执行的
        #ISO 8601 UTC 时间, 如 "2026-06-15T08:30:00Z"(Z = UTC)
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sequence": sequence,            #链中的序号
        "previous_receipt_hash": previous_receipt_hash,   #前一张的哈希;第一张为 None
    }
    return sign_receipt(payload, signing_key, verify_key)


def verify_chain(chain: list) -> list:
    """验证整条链(三重检查):
      ① 每张收据的签名有效
      ② 每张(除创世外)必须正确引用上一张的哈希
      ③ 序号必须等于它在列表中的位置
    """
    results = []
    for i, receipt in enumerate(chain):
        #【检查 1】签名有效吗?
        sig_ok = verify_receipt(receipt)
        #【检查 2】链链接对吗?
        if i == 0:
            #创世收据:没有前一张 → previous_receipt_hash 必须是 None
            chain_ok = receipt["previous_receipt_hash"] is None
        else:
            #重算"前一张"的哈希, 看是否与它记录的 prev 一致
            chain_ok = receipt["previous_receipt_hash"] == receipt_hash(chain[i - 1])
        #【检查 3】序号对吗?
        seq_ok = receipt["sequence"] == i
        results.append({
            "index": i,
            "tool": receipt["tool_name"],
            "signature_valid": sig_ok,
            "chain_link_valid": chain_ok,
            "sequence_valid": seq_ok,
            #三项全部为真才算整体有效
            "overall_valid": sig_ok and chain_ok and seq_ok,
        })
    return results


class ReceiptedTool:
    """把任意函数包一层:每次调用都【自动】生成一张签名收据, 并串成链"""

    def __init__(self, name, fn, signing_key, verify_key, agent_id, policy_id):
        self.name = name            #工具名(写进收据)
        self.fn = fn                #被包装的【原始函数】(真正干活的还是它)
        self.signing_key = signing_key
        self.verify_key = verify_key
        self.agent_id = agent_id
        self.policy_id = policy_id
        self.receipts: list = []    #本工具自己的收据链, 从空开始

    def __call__(self, *args, **kwargs):
        #__call__ 让"实例"可以像函数一样被调用
        #*args / **kwargs:原样接收任意数量、任意形式的位置参数和关键字参数

        #① 先真正执行原函数 —— 收据是"附带产生"的, 不影响原有功能
        result = self.fn(*args, **kwargs)

        #② 有历史就用最后一张的哈希, 没有就是 None(第一张)
        previous_hash = receipt_hash(self.receipts[-1]) if self.receipts else None

        #③ 生成收据
        receipt = make_receipt(
            tool_name=self.name,
            #把本次调用参数记进收据:list(args) 转成列表(JSON 友好), kwargs 本就是字典
            tool_args={"args": list(args), "kwargs": kwargs},
            tool_result=result,
            sequence=len(self.receipts),      #序号 = 已有收据数(0,1,2...自动递增)
            previous_receipt_hash=previous_hash,
            signing_key=self.signing_key,
            verify_key=self.verify_key,
            agent_id=self.agent_id,
            policy_id=self.policy_id,
        )

        #④ 把新收据追加到链尾
        self.receipts.append(receipt)

        #⑤ ⭐ 返回【原函数的返回值】—— 调用方感觉不到"被包装过", 完全透明
        return result


def mock_lookup_flights(origin: str, destination: str, departure_date: str) -> list:
    """一个"模拟的"航班查询函数(用写死的数据, 便于不依赖外网完整跑通)"""
    return [
        {"flight": "QF11", "price": 1850, "stops": 0},
        {"flight": "UA864", "price": 1620, "stops": 1},
    ]


def receipt_demo():
    """演示:签收据 → 验签 → 篡改被发现 → 串成链 → 包装工具"""
    #------------------- 0) 没装依赖就跳过 -------------------
    if not _RECEIPT_DEPS_OK:
        print("⏭️  本部分需要 pynacl 和 jcs, 当前未安装, 已跳过。")
        print("   安装方法: pip install pynacl jcs")
        return

    #=================== 第 1 步:签第一张收据 ===================
    #一对密钥 = 私钥(签名用, 必须保密) + 公钥(验签用, 可以公开)
    #generate():当场随机生成一对全新的密钥
    #⚠️ 这里在内存里生成只为教学演示;生产环境应存进 HSM / 密钥保管库
    signing_key = signing.SigningKey.generate()
    #公钥由私钥"配套推导"出来, 所以才能校验收据
    verify_key = signing_key.verify_key
    print(f"公钥(Ed25519, 32 字节): {b64url_nopad(bytes(verify_key))}")

    #工具的参数:代理到底让工具做了什么
    tool_args = {
        "origin": "SYD",              #出发地:悉尼
        "destination": "LAX",         #目的地:洛杉矶
        "departure_date": "2026-06-15",
        "passengers": 2,
    }
    #工具的返回结果
    tool_result = [
        {"flight": "QF11", "price": 1850, "stops": 0},
        {"flight": "UA864", "price": 1620, "stops": 1},
        {"flight": "DL11", "price": 1740, "stops": 0},
    ]

    payload = {
        "type": "agent.tool_call.v1",
        "agent_id": "contoso-travel-bot",
        "tool_name": "lookup_flights",
        "tool_args_hash": sha256_canonical(tool_args),
        "result_hash": sha256_canonical(tool_result),
        "policy_id": "contoso-travel-policy-v3",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sequence": 0,
        "previous_receipt_hash": None,   #第一张没有前置 → 创世收据
    }

    print("\n--- 收据负载(payload)---")
    print(json.dumps(payload, indent=2))

    #用私钥签, 并把公钥一并带上
    receipt = sign_receipt(payload, signing_key, verify_key)
    print("\n--- 签名后的收据 ---")
    print(json.dumps(receipt, indent=2))

    print(f"\n收据有效吗: {verify_receipt(receipt)}")      #预期:True

    #=================== 第 2 步:篡改收据 ===================
    print("\n" + "-" * 20 + " 篡改测试 " + "-" * 20)
    #deepcopy:复制出一份"完全独立"的收据, 改副本不会弄脏原始 receipt
    tampered = copy.deepcopy(receipt)

    #篡改 policy_id —— 这正是攻击者可能干的事:把策略改成更宽松的, 好让行为显得合规
    original_policy = tampered["policy_id"]
    tampered["policy_id"] = "contoso-travel-policy-PERMISSIVE"

    print(f"原本的 policy_id: {original_policy}")
    print(f"篡改的 policy_id: {tampered['policy_id']}")
    #改字段 → 规范字节变了 → SHA-256 变了 → 与签名时的哈希对不上 → 验签失败
    print(f"篡改后的收据有效吗: {verify_receipt(tampered)}")   #预期:False

    #=================== 第 3 步:把收据串成链 ===================
    print("\n" + "-" * 20 + " 收据链 " + "-" * 20)

    #模拟一次真实订票流程:查航班 → 占座 → 确认预订, 每一步都留一张收据
    r0 = make_receipt(
        tool_name="lookup_flights",
        tool_args={"origin": "SYD", "destination": "LAX", "date": "2026-06-15"},
        tool_result=[{"flight": "QF11", "price": 1850}],
        sequence=0,
        previous_receipt_hash=None,       #⚠️ 没有前一张 → 创世
        signing_key=signing_key,
        verify_key=verify_key,
    )
    r1 = make_receipt(
        tool_name="hold_seat",
        tool_args={"flight": "QF11", "seat": "14A", "hold_minutes": 30},
        tool_result={"hold_id": "H8472", "expires_at": "2026-06-15T15:00:00Z"},
        sequence=1,
        previous_receipt_hash=receipt_hash(r0),   #⭐ 把 r0 的哈希写进来 → 形成链
        signing_key=signing_key,
        verify_key=verify_key,
    )
    r2 = make_receipt(
        tool_name="confirm_booking",
        #支付令牌只留占位符(脱敏)
        tool_args={"hold_id": "H8472", "payment_token": "tok_redacted"},
        tool_result={"booking_ref": "CT-09182", "status": "confirmed"},
        sequence=2,
        previous_receipt_hash=receipt_hash(r1),   #⭐ 链继续
        signing_key=signing_key,
        verify_key=verify_key,
    )
    chain = [r0, r1, r2]

    for i, r in enumerate(chain):
        print(f"收据 {i}: 工具={r['tool_name']}, 前一张哈希={r['previous_receipt_hash']}")

    print("\n--- 整条链的验证结果 ---")
    for r in verify_chain(chain):
        status = "VALID" if r["overall_valid"] else "INVALID"
        print(f"收据 {r['index']} ({r['tool']:>18}): {status}")      #预期:三张全 VALID

    #=================== 第 4 步:篡改链条中间那张 ===================
    print("\n" + "-" * 20 + " 篡改链中间那张 " + "-" * 20)
    #把占座时长从 30 分钟改成 9999 分钟 —— 比实际授权的宽松得多
    tampered_chain = [copy.deepcopy(r) for r in chain]
    #攻击者改了参数, 为了"自圆其说"也得把哈希一起改掉;
    #但哈希一改, 签名(针对旧哈希算的)就对不上了 → 必然暴露
    tampered_chain[1]["tool_args_hash"] = sha256_canonical(
        {"flight": "QF11", "seat": "14A", "hold_minutes": 9999}
    )

    for r in verify_chain(tampered_chain):
        status = "VALID" if r["overall_valid"] else "INVALID"
        why = ""
        if not r["overall_valid"]:
            reasons = []
            if not r["signature_valid"]:
                reasons.append("签名")
            if not r["chain_link_valid"]:
                reasons.append("链链接")
            if not r["sequence_valid"]:
                reasons.append("序号")
            why = " (失败项: " + ", ".join(reasons) + ")"
        print(f"收据 {r['index']} ({r['tool']:>18}): {status}{why}")
    #预期:r0 仍 VALID;r1 签名失败;r2 链链接失败

    #=================== 第 5 步:自动生成收据的包装器 ===================
    print("\n" + "-" * 20 + " 自动收据包装器 " + "-" * 20)
    #用 ReceiptedTool 把普通函数"包一层", 加上自动签名收据的能力
    receipted_lookup = ReceiptedTool(
        name="lookup_flights",
        fn=mock_lookup_flights,          #⭐ 被包装的原始函数
        signing_key=signing_key,
        verify_key=verify_key,
        agent_id="contoso-travel-bot",
        policy_id="contoso-travel-policy-v3",
    )

    #用法和原来【一模一样】—— 看不出它其实被包装过(这就是"透明")
    #每调用一次, 就会自动多生成一张签名收据
    receipted_lookup(origin="SYD", destination="LAX", departure_date="2026-06-15")
    receipted_lookup(origin="SYD", destination="NRT", departure_date="2026-07-02")
    receipted_lookup(origin="MEL", destination="SIN", departure_date="2026-08-10")

    print(f"工具被调用了 {len(receipted_lookup.receipts)} 次。")
    print("每次调用都自动生成了一张签名收据, 并链接到前一张。")
    for r in verify_chain(receipted_lookup.receipts):
        status = "VALID" if r["overall_valid"] else "INVALID"
        print(f"收据 {r['index']} ({r['tool']}): {status}")


#await:异步等待。调用模型要联网、要花时间,用 await 让程序"等结果回来",而不是死等卡住。
#(笔记本里可以直接用 await;普通 .py 脚本里必须写在 async def 函数内)
async def main():
    #agent.run("...") = 把这句用户的话交给智能体,它自己去:
    #   判断要不要用工具 -> 调工具 -> 拿到结果 -> 组织成自然语言回答
    #注意:agent 会记住上下文,连续多次 run 会像"同一次对话"一样延续
    #提问也换成中文,和"中文回答"保持一致
    response = await agent.run(
        "我想找一个温暖的海滩度假地,你有什么推荐?"
    )
    #response 是完整的回复对象(里面含文字、工具调用记录等),直接 print 看结果
    print(response)

    print("\n" + "=" * 40 + " 流式输出 " + "=" * 40 + "\n")

    #stream=True:流式输出,结果一小块一小块地返回(像打字机一样,不用等全部生成完)
    #注意:stream=True 返回的是"异步迭代器",所以必须用 async for(不能用普通的 for)
    #      而且它同样必须写在 async def 函数内部
    async for chunk in agent.run(
        "Tell me about Tokyo as a travel destination", stream=True
    ):
        #end=""打印不换行，flush=true立刻将内容推到屏幕，不缓存
        print(chunk, end="", flush=True)

    #流式输出结束后补一个换行,让命令行提示符回到新的一行
    print()

    #第三部分:会话记忆演示(函数定义见上方 session_demo)
    print("\n" + "=" * 40 + " 会话记忆(session)演示 " + "=" * 40 + "\n")
    await session_demo()

    #第四部分:结构化输出演示(函数定义见上方 structured_demo)
    print("\n" + "=" * 40 + " 结构化输出演示 " + "=" * 40 + "\n")
    await structured_demo()

    #第五部分:多智能体协作演示(函数定义见上方 multi_agent_demo)
    print("\n" + "=" * 40 + " 多智能体协作演示 " + "=" * 40 + "\n")
    await multi_agent_demo()

    #第六部分:工具箱复用 + 一次提问用两个工具(函数定义见上方 travel_tool_demo)
    print("\n" + "=" * 40 + " 工具箱演示 " + "=" * 40 + "\n")
    await travel_tool_demo()

    #第七部分:RAG(检索增强)演示(函数定义见上方 rag_demo)
    print("\n" + "=" * 40 + " RAG(检索增强)演示 " + "=" * 40 + "\n")
    await rag_demo()

    #第八部分:人工审批关卡演示(函数定义见上方 gate_demo)
    print("\n" + "=" * 40 + " 人工审批关卡演示 " + "=" * 40 + "\n")
    await gate_demo()

    #第九部分:规划者 + 管家演示(函数定义见上方 planner_concierge_demo)
    print("\n" + "=" * 40 + " 规划者+管家演示 " + "=" * 40 + "\n")
    await planner_concierge_demo()

    #第十部分:工作流演示(函数定义见上方 workflow_demo)
    print("\n" + "=" * 40 + " 工作流演示 " + "=" * 40 + "\n")
    await workflow_demo()

    #第十一部分:元认知设计模式演示(函数定义见上方 metacognition_demo)
    print("\n" + "=" * 40 + " 元认知设计模式演示 " + "=" * 40 + "\n")
    await metacognition_demo()

    #第十二部分:生产环境视角演示(函数定义见上方 production_demo)
    print("\n" + "=" * 40 + " 生产环境视角演示 " + "=" * 40 + "\n")
    await production_demo()

    #第十三部分:上下文管理演示(函数定义见上方 context_management_demo)
    print("\n" + "=" * 40 + " 上下文管理演示 " + "=" * 40 + "\n")
    await context_management_demo()

    #第十四部分:Cognee 长期记忆演示(函数定义见上方 cognee_demo)
    print("\n" + "=" * 40 + " Cognee 长期记忆演示 " + "=" * 40 + "\n")
    await cognee_demo()

    #第十五部分:加密收据演示(普通函数, 里面没有 await)
    print("\n" + "=" * 40 + " 加密收据演示 " + "=" * 40 + "\n")
    receipt_demo()


#只有直接运行这个文件时才执行(被别的文件 import 时不会自动跑)
if __name__ == "__main__":
    asyncio.run(main())