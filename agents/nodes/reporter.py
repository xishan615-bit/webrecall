"""
agents/nodes/reporter.py — 研究员节点

职责：多轮检索 → 精读核心文章 → 三维分析 → Critic 自评 → 输出联合报告 + gaps
"""
import os, re
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from ..state import WebRecallState
from ..tools import REPORTER_TOOLS

_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

SYSTEM_PROMPT = """你是 WebRecall 研究员，专注于深度分析本地知识库。

工作流：
1. 调用 get_library_overview() 了解库规模
2. 用 search_knowledge_base() 检索指定话题（支持 + 联合检索）
   - 核心词: topic
   - 联合检索: topic+子话题1, topic+子话题2
   - 最多 3 轮，每轮调整关键词
3. 若结果 <3 篇 → 直接返回"本地资料不足"，停止
4. 精读前 5 篇：get_page_content(url)
5. 三维分析：
   ① 共识：≥2篇同时提到的观点，加 [引用编号]
   ② 分歧：不同来源立场不一致，如实标注，不强行下结论
   ③ 脉络：按时间线排序，梳理观点演进
6. Critic 自评（必做）：
   - 是否回答了用户问题？
   - 引用 URL 是否来自 search 结果（不可编造）？
   - 有哪些明显盲区？
7. 输出标准报告格式（Markdown，含 ## 知识盲区 章节，列出盲区 list）

严禁：
- ❌ 编造未在库中存在的引用来源
- ❌ 访问外部互联网
- ❌ 强行解决矛盾分歧
"""

_agent = create_react_agent(_llm, REPORTER_TOOLS, prompt=SystemMessage(content=SYSTEM_PROMPT))


def reporter_node(state: WebRecallState) -> dict:
    """运行研究员 ReAct agent，输出联合报告和知识盲区列表。"""
    topic = _extract_topic(state.get("user_input", ""))
    result = _agent.invoke({
        "messages": [("user", f"请对「{topic}」话题生成一份联合报告。")]
    })
    report = result["messages"][-1].content

    # 提取盲区列表
    gaps = _extract_gaps(report)
    suggest_research = len(gaps) > 0

    return {
        "messages": result["messages"],
        "report_draft": report,
        "report_gaps": gaps,
        "plan_step": state.get("plan_step", 0) + 1,
        # 质检：报告字数 < 100 字视为失败
        "quality_ok": len(report) >= 100,
        "retry_count": state.get("retry_count", 0),
    }


def _extract_topic(user_input: str) -> str:
    """从用户输入中提取研究话题。"""
    # 简单规则：去掉常见动词前缀
    for prefix in ["帮我分析", "帮我总结", "分析一下", "总结一下",
                   "生成报告", "写一份", "整理一下", "调研"]:
        user_input = user_input.replace(prefix, "").strip()
    return user_input or "当前收藏话题"


def _extract_gaps(report: str) -> list[str]:
    """从报告的「知识盲区」章节提取盲区列表。"""
    gaps = []
    in_gaps = False
    for line in report.split("\n"):
        if "知识盲区" in line or "盲区" in line and "##" in line:
            in_gaps = True
            continue
        if in_gaps and line.startswith("##"):
            break
        if in_gaps and line.strip().startswith(("-", "•", "*", "·")):
            gap = line.strip().lstrip("-•*· ").strip()
            if gap:
                gaps.append(gap)
    return gaps[:5]  # 最多返回 5 个盲区
