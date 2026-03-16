"""
agents/nodes/deep_researcher.py — 深度调研员（已修复：inline interrupt() 确认门）

修复：
  - Bug2: 存档确认用 interrupt()，确认后立刻调用 save_new_page()
  - Bug3: 去掉双重 interrupt，改用节点内 interrupt()
"""
import os, json
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from ..state import WebRecallState
from ..tools import RESEARCHER_TOOLS, save_new_page, search_knowledge_base
from ..external_search_tools import EXTERNAL_SEARCH_TOOLS

_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

SYSTEM_PROMPT = """你是 WebRecall 深度调研员。

你会收到 Reporter 识别的知识盲区列表，进行外部调研。

工作流：
1. 按时效性排序盲区，优先处理最重要的3个
2. 选择平台（GitHub/DuckDuckGo/Reddit） → 搜索 → 阅读页面
3. 每找到一篇：先用 search_knowledge_base 确认本地没有（重复不存）
4. 整理新发现，输出拓展报告，**最后一行**必须是：
   SAVE_PAGES: [{"url":"...","title":"...","content":"...摘要..."}]
   若无新发现，写 SAVE_PAGES: []

5. 附上3条延伸话题推荐

注意：若外部搜索工具不可用，如实说明即可。
"""

_all_tools = RESEARCHER_TOOLS + EXTERNAL_SEARCH_TOOLS
_agent = create_react_agent(
    _llm, _all_tools, prompt=SystemMessage(content=SYSTEM_PROMPT)
)


def _extract_save_pages(text: str) -> list[dict]:
    import re
    match = re.search(r"SAVE_PAGES:\s*(\[.*\])", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return []


def deep_researcher_node(state: WebRecallState) -> dict:
    gaps = state.get("report_gaps", [])
    topic = state.get("user_input", "")

    if not gaps:
        return {
            "research_findings": "本地知识库已充分覆盖，无需外部调研。",
            "pending_confirm": None,
            "plan_step": state.get("plan_step", 0) + 1,
        }

    gaps_str = "\n".join(f"- {g}" for g in gaps)
    prompt = f"""话题：{topic}

研究员发现的知识盲区：
{gaps_str}

请调研并生成拓展报告。"""

    result = _agent.invoke({"messages": [("user", prompt)]})
    findings = result["messages"][-1].content
    pages_to_save = _extract_save_pages(findings)

    # 去掉 SAVE_PAGES 行，只展示报告给用户
    import re
    display = re.sub(r"\nSAVE_PAGES:.*", "", findings, flags=re.DOTALL).strip()

    if pages_to_save:
        # ── 存档确认门 ──────────────────────────────────────
        preview_lines = [f"📦 发现 {len(pages_to_save)} 篇新资料：\n"]
        for i, p in enumerate(pages_to_save, 1):
            preview_lines.append(f"{i}. **{p.get('title','（无标题）')}**")
            preview_lines.append(f"   🔗 {p.get('url','')}")
            if p.get("content"):
                preview_lines.append(f"   📝 {p['content'][:100]}...")
            preview_lines.append("")
        preview_str = "\n".join(preview_lines)

        user_response = interrupt({
            "action": "research_save",
            "preview": preview_str,
            "message": f"{display}\n\n{'─'*40}\n{preview_str}\n"
                       f"是否将以上 {len(pages_to_save)} 篇存入知识库？(yes/no)"
        })

        confirmed = str(user_response).strip().lower() in (
            "yes", "y", "是", "确认", "ok", "好", "1"
        )
        saved_urls = []
        if confirmed:
            for p in pages_to_save:
                try:
                    save_new_page.invoke({
                        "url": p["url"],
                        "title": p.get("title", ""),
                        "content": p.get("content", ""),
                    })
                    saved_urls.append(p["url"])
                except Exception:
                    pass

        return {
            "messages": result["messages"],
            "research_findings": display,
            "new_pages_saved": saved_urls,
            "pending_confirm": None,
            "plan_step": state.get("plan_step", 0) + 1,
        }

    # 没有新内容需要存档，直接返回
    return {
        "messages": result["messages"],
        "research_findings": display,
        "pending_confirm": None,
        "plan_step": state.get("plan_step", 0) + 1,
    }
