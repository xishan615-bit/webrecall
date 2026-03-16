#!/usr/bin/env python3
"""
scripts/native_host.py — WebRecall Native Messaging Host

Chrome 插件通过 Native Messaging 协议与本脚本通信，
本脚本负责启动 / 停止 / 监测 lite_server.py。

协议：每条消息 = 4字节 uint32 小端长度 + UTF-8 JSON 正文
支持的 action：
  status  — 返回当前 lite_server 运行状态
  start   — 启动 lite_server（幂等：已启动则直接返回 ok）
  stop    — 停止 lite_server
"""
import sys
import os
import json
import struct
import subprocess
import signal
import time

# ── 路径计算 ───────────────────────────────────────────────────
# 本脚本位于 webrecall/scripts/，lite_server 位于 webrecall/backend/
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")
LITE_SERVER = os.path.join(BACKEND_DIR, "lite_server.py")
PID_FILE    = os.path.join(BACKEND_DIR, ".lite_server.pid")
VENV_PYTHON = os.path.join(BACKEND_DIR, "venv", "bin", "python3")
LOG_FILE    = os.path.expanduser("~/.webrecall/native_host.log")

# 优先使用 venv python，否则按优先级尝试系统绝对路径（避免 Chrome sandbox strip PATH）
def _find_python():
    if os.path.exists(VENV_PYTHON):
        return VENV_PYTHON
    for p in ["/usr/bin/python3", "/usr/local/bin/python3",
              "/opt/homebrew/bin/python3", sys.executable]:
        if os.path.exists(p):
            return p
    return sys.executable

PYTHON = _find_python()


# ── Native Messaging I/O ───────────────────────────────────────

def read_message():
    """从 stdin 读取一条 Native Messaging 消息（4字节头 + JSON）。"""
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    raw_msg = sys.stdin.buffer.read(msg_len)
    return json.loads(raw_msg.decode("utf-8"))


def send_message(obj):
    """向 stdout 写一条 Native Messaging 消息。"""
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _log(msg):
    """写入调试日志到 ~/.webrecall/native_host.log"""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ── Lite Server 进程控制 ───────────────────────────────────────

def _read_pid():
    """读取 PID 文件，返回 int 或 None。"""
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _write_pid(pid: int):
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _process_alive(pid: int) -> bool:
    """检查 PID 是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def is_running() -> bool:
    pid = _read_pid()
    if pid and _process_alive(pid):
        return True
    # PID 失效，清理
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    return False


def start_server() -> dict:
    if is_running():
        _log("start_server: already running")
        return {"ok": True, "running": True, "message": "已在运行"}

    if not os.path.exists(LITE_SERVER):
        _log(f"start_server: lite_server.py not found at {LITE_SERVER}")
        return {"ok": False, "running": False, "message": f"找不到 lite_server.py：{LITE_SERVER}"}

    _log(f"start_server: python={PYTHON} server={LITE_SERVER}")
    try:
        proc = subprocess.Popen(
            [PYTHON, LITE_SERVER],
            cwd=BACKEND_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # 脱离当前进程组，关掉 native host 后依然运行
            start_new_session=True,
        )
        _write_pid(proc.pid)
        # 等待最多 3 秒，确认进程存活
        for _ in range(6):
            time.sleep(0.5)
            if _process_alive(proc.pid):
                _log(f"start_server: success pid={proc.pid}")
                return {"ok": True, "running": True, "message": "启动成功"}
        _log("start_server: process exited immediately")
        return {"ok": False, "running": False, "message": "进程启动后立即退出，请检查依赖是否安装"}
    except Exception as e:
        _log(f"start_server: exception {e}")
        return {"ok": False, "running": False, "message": str(e)}


def _kill_by_port(port: int = 8001) -> bool:
    """使用 lsof 查找并 kill 占用指定端口的进程，作为 PID 文件的 fallback。"""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True
        )
        pids = [int(p.strip()) for p in result.stdout.strip().splitlines() if p.strip().isdigit()]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        return bool(pids)
    except Exception:
        return False


def stop_server() -> dict:
    pid = _read_pid()
    if pid and _process_alive(pid):
        # PID 文件有效：精确 kill
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(6):
                time.sleep(0.5)
                if not _process_alive(pid):
                    if os.path.exists(PID_FILE):
                        os.remove(PID_FILE)
                    _log(f"stop_server: stopped pid={pid}")
                    return {"ok": True, "running": False, "message": "已停止"}
            # 强杀
            os.kill(pid, signal.SIGKILL)
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
            _log(f"stop_server: force-killed pid={pid}")
            return {"ok": True, "running": False, "message": "已强制停止"}
        except Exception as e:
            _log(f"stop_server: exception killing pid={pid}: {e}")
            return {"ok": False, "running": True, "message": str(e)}
    else:
        # PID 文件无效/缺失 → fallback：按端口 kill
        _log("stop_server: PID file invalid, fallback to port-based kill")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        killed = _kill_by_port(8001)
        if killed:
            time.sleep(1.0)
            _log("stop_server: killed by port")
            return {"ok": True, "running": False, "message": "已停止"}
        else:
            _log("stop_server: no process found on port 8001")
            return {"ok": True, "running": False, "message": "服务未运行"}


# ── 主循环 ────────────────────────────────────────────────────

def main():
    _log(f"native_host started: python={PYTHON} backend={BACKEND_DIR}")
    while True:
        msg = read_message()
        if msg is None:
            _log("read_message returned None, exiting")
            break

        action = msg.get("action", "")
        _log(f"action={action}")

        if action == "status":
            running = is_running()
            resp = {"ok": True, "running": running,
                    "message": "运行中" if running else "已停止"}
            _log(f"status resp: {resp}")
            send_message(resp)

        elif action == "start":
            result = start_server()
            _log(f"start resp: {result}")
            send_message(result)

        elif action == "stop":
            result = stop_server()
            _log(f"stop resp: {result}")
            send_message(result)

        else:
            resp = {"ok": False, "running": is_running(),
                    "message": f"未知指令：{action}"}
            _log(f"unknown action resp: {resp}")
            send_message(resp)


if __name__ == "__main__":
    main()
