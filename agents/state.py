"""
agents/state.py — WebRecall 多 Agent 全局状态
"""
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class WebRecallState(TypedDict):
    # 对话历史（自动合并）
    messages: Annotated[list, add_messages]

    # Commander 决策
    user_input: str
    intent: Optional[str]          # query | classify | report | research | full | overview
    plan: list[str]                 # ["retrieval","report","research"] 等
    plan_step: int                  # 当前执行步骤索引

    # 子 Agent 产出
    retrieved_pages: list[dict]     # webrecall_search 结果
    report_draft: Optional[str]     # Reporter 输出
    report_gaps: list[str]          # Reporter 识别的知识盲区
    research_findings: Optional[str] # Deep Researcher 输出
    new_pages_saved: list[str]      # 已存档的 URL 列表

    # 质检 & 重试
    quality_ok: bool
    retry_count: int

    # 人工确认门
    pending_confirm: Optional[dict]  # {action, description, payload}
    user_confirmed: Optional[bool]

    # 最终输出
    final_response: Optional[str]
    error: Optional[str]
