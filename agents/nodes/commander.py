"""
agents/nodes/commander.py — 总控 Commander（已修复：内联检索、路由循环）

修复：
  - Bug1: retrieval 步骤在 commander 内联执行，不再产生 self-loop
  - 多步 plan 正确推进
"""
import os, re, json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from ..state import WebRecallState
from ..tools import search_knowledge_base, get_library_overview


# ── LLM（只用于意图识别，不绑定工具避免不必要 tool call）──
_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

INTENT_PROMPT = """你是 WebRecall 的总控 Agent（内务大臣）。

根据用户输入判断：
- intent: query | classify | report | research | full | overview
- plan: 执行步骤列表

映射规则：
- 找/搜/查/有没有 → intent=query, plan=["retrieval"]
- 整理/分类/打标签 → intent=classify, plan=["classify"]
- 分析/总结/报告/综述 → intent=report, plan=["retrieval","report"]
- 调研/深挖/最新进展 → intent=research, plan=["retrieval","report","research"]
- 全面研究/系统整理 → intent=full, plan=["retrieval","report","research","classify"]
- 有多少/统计/概览 → intent=overview, plan=["stats"]

**必须**输出以下 JSON 格式（用代码块包裹）：
```json
{"intent": "report", "plan": ["retrieval","report"], "clarification": null}
```
若意图模糊，clarification 填追问，intent/plan 置 null。"""


def commander_node(state: WebRecallState) -> dict:
    plan = state.get("plan", [])
    plan_step = state.get("plan_step", 0)

    # ① 所有步骤已完成 → 汇总输出
    if plan and plan_step >= len(plan):
        return _synthesize(state)

    # ② 已有 plan，当前步骤是 retrieval → 内联执行
    if plan and plan_step < len(plan) and plan[plan_step] == "retrieval":
        return _do_retrieval(state)

    # ③ 已有 plan，其他步骤 → 透传（路由器根据 plan[plan_step] 发到对应节点）
    if plan and plan_step > 0:
        return {"plan_step": plan_step}

    # ④ 首次进入 → 识别意图
    user_input = state.get("user_input", "")
    response = _llm.invoke([
        SystemMessage(content=INTENT_PROMPT),
        HumanMessage(content=user_input),
    ])

    raw = response.content if hasattr(response, "content") else str(response)
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = {}
    else:
        parsed = {}

    intent       = parsed.get("intent")
    new_plan     = parsed.get("plan") or []
    clarification = parsed.get("clarification")

    if clarification:
        return {
            "messages": [AIMessage(content=clarification)],
            "intent": None, "plan": [], "plan_step": 0,
        }
    if not intent:
        # 降级默认
        intent, new_plan = "query", ["retrieval"]

    base = {
        "intent": intent,
        "plan": new_plan,
        "plan_step": 0,
        "retry_count": 0,
        "retrieved_pages": [],
        "report_gaps": [],
        "new_pages_saved": [],
    }

    # ⑤ 首步就是 retrieval → 立刻内联执行
    if new_plan and new_plan[0] == "retrieval":
        return _do_retrieval({**state, **base})

    return base


def _do_retrieval(state: WebRecallState) -> dict:
    """内联执行检索步骤，不走额外节点，避免路由循环。"""
    user_input = state.get("user_input", "")
    plan_step  = state.get("plan_step", 0)

    result_text = search_knowledge_base.invoke({"query": user_input, "limit": 15})

    # 简单解析：把文本行里的 URL 提取出来作为 retrieved_pages
    pages = []
    for line in result_text.split("\n"):
        if "🔗" in line:
            url = line.split("🔗")[-1].strip()
            pages.append({"url": url, "title": "", "snippet": ""})

    return {
        "retrieved_pages": pages,
        "plan_step": plan_step + 1,          # 推进到下一步
        "messages": [AIMessage(content=result_text)],
    }


def _synthesize(state: WebRecallState) -> dict:
    """所有步骤完成，整合输出。"""
    intent = state.get("intent", "query")
    parts  = []

    if intent == "overview":
        parts.append(state.get("final_response") or "")

    elif intent == "query":
        pages = state.get("retrieved_pages", [])
        if pages:
            parts.append(f"为你找到 {len(pages)} 条相关结果：")
            for i, p in enumerate(pages[:5], 1):
                title = p.get("title") or p.get("url", "")
                parts.append(f"{i}. {title}  {p.get('url','')}")
        else:
            parts.append("未找到相关页面。")

    elif intent in ("report", "research", "full"):
        if state.get("report_draft"):
            parts.append(state["report_draft"])
        if state.get("research_findings"):
            parts.append("\n---\n")
            parts.append(state["research_findings"])
        gaps = state.get("report_gaps", [])
        if gaps and intent == "report":
            parts.append(f"\n\n> 💡 发现 {len(gaps)} 个知识盲区，是否要深度调研？")

    elif intent == "classify":
        parts.append("✅ 分类整理完成。可在「已整理」标签查看结果。")

    final = "\n".join(parts)
    return {
        "final_response": final,
        "messages": [AIMessage(content=final)],
    }
