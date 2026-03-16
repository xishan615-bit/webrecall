"""
agents/run.py — WebRecall Agent CLI 入口（已修复：snapshot.tasks 读 interrupt 值）

用法：
  cd webrecall
  source backend/venv/bin/activate
  OPENAI_API_KEY=sk-... python -m agents.run

可选配置：
  OPENAI_MODEL_NAME=deepseek-chat              # 自定义模型
  OPENAI_BASE_URL=https://api.deepseek.com     # 兼容 OpenAI 的各类平台网关
"""
import os
import sys
import uuid
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

if not os.getenv("OPENAI_API_KEY"):
    print("❌ 请设置 OPENAI_API_KEY 环境变量（或写入 .env 文件）")
    print("💡 WebRecall 目前支持任意兼容 OpenAI 格式的模型 API（如 DeepSeek, OpenRouter, 通义千问等）")
    print("👉 若使用第三方接口，请一并设置 OPENAI_BASE_URL 和 OPENAI_MODEL_NAME")
    sys.exit(1)

from langgraph.types import Command
from .graph import graph
from .state import WebRecallState


def print_banner():
    print("\n" + "=" * 55)
    print("  🤖 WebRecall Agent System")
    print("  Commander · Classifier · Reporter · Deep Researcher")
    print("=" * 55)
    print("  直接输入需求，Commander 自动分派")
    print("  示例：「帮我整理收藏」「分析 RAG 相关文章」「调研 LangGraph」")
    print("  输入 quit 退出\n")


def run_interactive():
    print_banner()
    thread_id = str(uuid.uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n收工！👋")
            break

        if user_input.lower() in ("quit", "exit", "退出", "q"):
            print("收工！👋")
            break
        if not user_input:
            continue

        initial: WebRecallState = {
            "messages":         [{"role": "user", "content": user_input}],
            "user_input":       user_input,
            "intent":           None,
            "plan":             [],
            "plan_step":        0,
            "retrieved_pages":  [],
            "report_draft":     None,
            "report_gaps":      [],
            "research_findings": None,
            "new_pages_saved":  [],
            "quality_ok":       True,
            "retry_count":      0,
            "pending_confirm":  None,
            "user_confirmed":   None,
            "final_response":   None,
            "error":            None,
        }

        print("\n🤔 Commander 正在分析...\n")

        try:
            _stream_until_interrupt(config, initial)

            # 处理 interrupt() 暂停（可能多轮）
            snapshot = graph.get_state(config)
            while snapshot.next:
                interrupt_value = _get_interrupt_value(snapshot)
                _print_interrupt(interrupt_value)

                user_reply = input("\n你 > ").strip()
                _stream_until_interrupt(config, Command(resume=user_reply))
                snapshot = graph.get_state(config)

            # 最终回复
            final = graph.get_state(config).values.get("final_response")
            if final:
                print(f"\n🤖 Commander >\n{final}\n")

        except Exception as e:
            print(f"\n❌ 出错了：{e}\n")
            import traceback; traceback.print_exc()

        print()


def _stream_until_interrupt(config, input_or_command):
    """流式运行图，打印 AI 过程消息，直到图完成或 interrupt 暂停。"""
    for event in graph.stream(input_or_command, config, stream_mode="values"):
        msgs = event.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", None)
            if content and not event.get("final_response"):
                # 打印截断的过程消息
                preview = content[:150] + "…" if len(content) > 150 else content
                print(f"  ⚙️  {preview}")


def _get_interrupt_value(snapshot) -> dict | str:
    """从 snapshot.tasks 中提取 interrupt() 传入的值。"""
    for task in getattr(snapshot, "tasks", []):
        for intr in getattr(task, "interrupts", []):
            return intr.value
    # fallback: 看 pending_confirm
    return snapshot.values.get("pending_confirm", {}) or "确认操作"


def _print_interrupt(value):
    """友好地打印中断确认消息。"""
    print("\n" + "=" * 55)
    if isinstance(value, dict):
        msg = value.get("message") or value.get("preview") or str(value)
    else:
        msg = str(value)
    print(msg)
    print("=" * 55)


if __name__ == "__main__":
    run_interactive()
