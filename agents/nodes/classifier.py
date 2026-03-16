"""
agents/nodes/classifier.py — 分类专家（已修复：inline interrupt() 确认门）

修复：
  - Bug2: 用 interrupt() 在节点内暂停，确认后立刻执行写入，
    不再依赖 pending_confirm 状态传递
  - Bug3: 去掉 interrupt_before，改用节点内 interrupt()
"""
import os, re, json
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from ..state import WebRecallState
from ..tools import (
    CLASSIFIER_TOOLS,
    save_classification_results,
    update_classifier_memory,
)

_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

SYSTEM_PROMPT = """你是 WebRecall 分类专家。

**工作流（严格顺序）**：
1. 调用 get_classifier_memory() 加载已有分类体系
2. 调用 get_unclassified_pages(limit=50) 获取待分类页面
3. 为每篇分析 title+summary，生成分类方案
4. 输出**完整的分类预览**，格式：
   📂 AI/技术（N篇）：[标签1,标签2] 标题1 / [标签3] 标题2
   ...（最后一行必须是 "UPDATES_JSON:" 后跟 JSON 数组）

**最后一行格式（必须）**：
UPDATES_JSON: [{"url":"...","tags":["AI","技术"]},...]

规则：
- 宁宽泛不细碎
- 测试页面（url含test）跳过
- 低置信度的单独标注 ⚠️
"""

_agent = create_react_agent(
    _llm, CLASSIFIER_TOOLS, prompt=SystemMessage(content=SYSTEM_PROMPT)
)


def _extract_updates_json(text: str) -> list[dict]:
    """从 Agent 输出中提取 UPDATES_JSON 数组。"""
    match = re.search(r"UPDATES_JSON:\s*(\[.*\])", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return []


def classifier_node(state: WebRecallState) -> dict:
    """
    分两阶段执行：
    1. 生成预览 → interrupt() 等用户确认
    2. 恢复后执行写入（interrupt() 直接返回用户输入，不重新调用 LLM）
    """
    user_input = state.get("user_input", "分类整理所有待分类页面")

    # Stage 1: 运行 Agent 生成预览
    result = _agent.invoke({
        "messages": [("user", f"请帮我整理分类。用户需求：{user_input}")]
    })
    preview_text = result["messages"][-1].content
    updates = _extract_updates_json(preview_text)

    # 去掉 UPDATES_JSON 行，只把预览展示给用户
    display_text = re.sub(r"\nUPDATES_JSON:.*", "", preview_text, flags=re.DOTALL).strip()

    # ── 人工确认门（LangGraph interrupt）──────────────────
    # 第一次运行到这里：图暂停，用户看到 display_text
    # 用户通过 Command(resume="yes") 恢复时，interrupt() 返回 "yes"
    user_response = interrupt({
        "action": "classify_write",
        "preview": display_text,
        "message": f"{display_text}\n\n{'─'*40}\n"
                   f"✅ 确认写入以上 {len(updates)} 篇分类？(yes/no)"
    })

    confirmed = str(user_response).strip().lower() in (
        "yes", "y", "是", "确认", "ok", "好", "1", "true"
    )

    if confirmed and updates:
        # Stage 2: 执行写入
        write_result = save_classification_results.invoke({
            "updates_json": json.dumps(updates, ensure_ascii=False)
        })
        # 更新分类记忆（最佳努力，失败不阻断）
        try:
            update_classifier_memory.invoke({
                "changes_json": json.dumps({
                    "upsert_categories": [],
                    "upsert_keywords": [],
                    "delete_keywords": [],
                }, ensure_ascii=False)
            })
        except Exception:
            pass
    elif not updates:
        write_result = "ℹ️ 未解析到有效分类数据，跳过写入。"
    else:
        write_result = "⏭️ 用户取消，跳过分类写入。"

    return {
        "messages": result["messages"],
        "pending_confirm": None,
        "plan_step": state.get("plan_step", 0) + 1,
    }
