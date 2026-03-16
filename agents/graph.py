"""
agents/graph.py — LangGraph 主图装配（已修复：移除 human_confirm 节点）

修复：
  - 移除 interrupt_before: 交由各节点内部 interrupt() 控制
  - 移除 human_confirm 节点（确认逻辑已内联到 classifier/deep_researcher）
  - route_from_commander 不再映射 "retrieval" → 因为 commander 内联处理
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import WebRecallState
from .nodes.commander import commander_node
from .nodes.classifier import classifier_node
from .nodes.reporter import reporter_node
from .nodes.deep_researcher import deep_researcher_node


# ── 路由函数 ────────────────────────────────────────────────

def route_from_commander(state: WebRecallState) -> str:
    """
    Commander 输出后按 plan[plan_step] 路由。
    "retrieval" 由 commander 内联处理，这里只路由其他步骤。
    """
    plan      = state.get("plan", [])
    plan_step = state.get("plan_step", 0)
    intent    = state.get("intent")

    if not plan or not intent:
        return END

    if plan_step >= len(plan):
        return END

    current = plan[plan_step]
    return {
        "classify":   "classifier",
        "report":     "reporter",
        "research":   "deep_researcher",
        "stats":      END,
        "retrieval":  END,   # 不应到达（commander 内联处理了），保险起见结束
    }.get(current, END)


def route_after_specialist(state: WebRecallState) -> str:
    """专家节点完成后→回 commander（commander 决定是否继续下一步或汇总）。"""
    return "commander"


# ── 图装配 ─────────────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(WebRecallState)

    builder.add_node("commander",       commander_node)
    builder.add_node("classifier",      classifier_node)
    builder.add_node("reporter",        reporter_node)
    builder.add_node("deep_researcher", deep_researcher_node)

    builder.add_edge(START, "commander")

    # Commander → 专家节点
    builder.add_conditional_edges("commander", route_from_commander, {
        "classifier":      "classifier",
        "reporter":        "reporter",
        "deep_researcher": "deep_researcher",
        END:               END,
    })

    # 专家节点 → 回 commander
    for specialist in ("classifier", "reporter", "deep_researcher"):
        builder.add_edge(specialist, "commander")

    return builder


def compile_graph():
    """编译带内存持久化的图（MemorySaver 支持 interrupt() 和多轮对话）。"""
    memory = MemorySaver()
    return build_graph().compile(checkpointer=memory)
    # 注意：不设 interrupt_before，interrupt() 已内联到各节点中


graph = compile_graph()
