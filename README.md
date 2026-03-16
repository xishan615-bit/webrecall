# 🦞 WebRecall — 把浏览器变成你的 AI 外脑

> 一键收藏任意网页，AI Agent 随时调取、联想搜索、分类打标与全网深度调研。  
> Save any page in one click. Your AI agent can search, classify, and research across your personal knowledge base.

完全基于 Chrome 插件与本地 SQLite，零外部数据库依赖，**极简、轻量、极客闭环。**  
*Built on Chrome Extension + local SQLite. Zero external database required. Minimal, lightweight, self-contained.*

**[中文](#中文文档) · [English](#english-docs)**

---

## 中文文档

### ⚡ 架构：A / B 双线并行

所有抓取的数据永远只以 `~/.webrecall/pages.db` 单个 SQLite 文件形式留在你的电脑中。

#### 🅰️ A 线：极简本地收藏夹（个人收藏夹 2.0）
**定位**：即插即用、零负担的本地离线收藏夹管理器。

- **核心**：Chrome 插件 + 本地 `lite_server.py`（仅占 ~15MB 内存）
- **秒级存页**：点击 🦞 一键保存，HTML 正文清洗后落入本地 SQLite
- **实时搜库**：插件内输入关键词，支持 `AI+RAG` 联合检索。有 Lite Server 时走 SQLite，无服务时自动切换到内置 BM25 离线引擎

#### 🅱️ B 线：AI Agent 外脑中枢

- **MCP 挂载**：启动 `mcp/server.py`，Cursor / Claude Desktop / OpenClaw 瞬间获得跨库检索能力
- **LangGraph 多智能体**：
  - 💂 **Commander（司令官）**：解析你的自然语言指令，拆解成执行计划，按需调度下面三位专家，并最终汇总输出
  - 🗂️ **Classifier（分类专家）**：读取未打标的页面，用 AI 自动归类并写入 `tags` 字段，同时把新发现的类目和关键词写入**长期记忆表**（taxonomy）。这意味着它越用越聪明——下次分类时不会重复建类目，你的 A 线关键词搜索也会因为标签的丰富而命中更多结果（`AI+RAG` 精准命中标签 > 全文模糊匹配）
  - 📝 **Reporter（研究员）**：针对某个主题，批量检索相关本地资料并逐篇精读，综合梳理成结构化研究报告，找出知识盲区
  - 🌐 **Deep Researcher（外网侦察兵）**：拿着 Reporter 找出的盲区，穿透公网（DuckDuckGo）主动搜索最新内容，用户确认后自动存入收藏库，形成「本地积累 → AI 调研 → 新知识入库」的完整闭环

> **🛡️ 防幻觉机制**：所有写库操作（分类打标、新页入库）都会在终端中断，等待你手动输入 `yes` 确认后才执行。

---

### 🚀 极速上手

#### 前提条件
- Python **3.10+**（`python3 --version` 确认）
- Google Chrome 浏览器

#### 第一步：启动 Lite Server（A 线核心）

```bash
git clone https://github.com/xishan615-bit/webrecall.git
cd webrecall/backend

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python lite_server.py           # 保持此终端开着不要关！
# 看到 "🚀 WebRecall Lite Server starting on port 8001..." 即为成功
```

#### 第二步：安装 Chrome 插件

1. Chrome 地址栏输入 `chrome://extensions`
2. 右上角打开**开发者模式**
3. 点击**加载已解压的扩展程序** → 选择 `webrecall/extension/` 文件夹
4. 工具栏出现 🦞 图标，点击即可使用

#### 第三步（可选）：配置 MCP

在 Cursor / Claude Desktop / OpenClaw 的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "webrecall": {
      "command": "python",
      "args": ["/你的绝对路径/webrecall/mcp/server.py"]
    }
  }
}
```

#### 第四步（可选）：召唤 LangGraph 多智能体

```bash
# 在项目根目录执行（不是 backend/ 里）
cd webrecall

pip install langgraph langchain-openai httpx ddgs

# 配置 LLM API（任选其一）
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.deepseek.com"   # DeepSeek（推荐）
export OPENAI_MODEL_NAME="deepseek-chat"

# 启动
python -m agents.run
```

终端提示 `你 >` 后输入指令，例如：
> "把库里没分类的资料全部打上标签"  
> "帮我总结关于 RAG 的知识，然后去全网搜最新动态存入收藏"

---

### 📁 代码结构

```
webrecall/
├── extension/             # Chrome 插件（Manifest V3）
│   ├── background.js      # BM25 离线引擎 + 消息路由
│   ├── content.js         # 正文抓取与清洗
│   └── popup/             # 搜索 / 库管理 UI
├── backend/
│   ├── lite_server.py     # 本地轻量 API（SQLite 读写，~15MB 内存）
│   └── db/sqlite_store.py # SQLite DAO + FTS 建表
├── mcp/
│   └── server.py          # 标准 MCP 服务（供 AI 客户端调用）
├── agents/                # LangGraph 多智能体
│   ├── graph.py           # 图装配（Commander → 专家节点）
│   ├── tools.py           # LangChain 工具层
│   └── nodes/             # commander / classifier / reporter / deep_researcher
└── skills/                # Agent Skill 提示词包
```

---

## English Docs

### ⚡ Architecture: Dual Track A / B

All captured data is stored exclusively in a single SQLite file at `~/.webrecall/pages.db` on your machine.

#### 🅰️ Track A: Lightweight Local Bookmarks (Bookmarks 2.0)
**Goal**: Zero-setup, offline-first personal bookmark manager.

- **Core**: Chrome Extension + local `lite_server.py` (~15MB RAM)
- **One-click save**: Click 🦞 to save any page; cleaned text is written to local SQLite
- **Instant search**: Type in the popup with `keyword1+keyword2` AND logic. Falls back to built-in BM25 engine when Lite Server is offline

#### 🅱️ Track B: AI Agent Brain Hub

- **MCP integration**: Launch `mcp/server.py` and Cursor / Claude Desktop / OpenClaw instantly gets search tools over your knowledge base
- **LangGraph multi-agent**:
  - 💂 **Commander**: Parses your natural language instructions, decomposes them into a step-by-step plan, dispatches the right specialist agents, and synthesizes the final output
  - 🗂️ **Classifier**: Reads untagged pages, uses AI to assign tags and writes them back to the `tags` column in SQLite. Crucially, it also updates a **persistent taxonomy memory** (category tree + keyword bindings) — it gets smarter with every run and never creates duplicate categories. The tags it writes directly enrich Track A keyword search: `AI+RAG` hits a tag match before falling back to full-text scan
  - 📝 **Reporter**: Given a topic, retrieves and deep-reads all related saved articles, then synthesizes a structured research report and identifies knowledge gaps
  - 🌐 **Deep Researcher**: Takes the gaps identified by the Reporter and actively searches the web (DuckDuckGo). With your confirmation, it saves new findings into your library — closing the loop: *save → AI research → new knowledge in*

> **🛡️ Human-in-the-loop**: Every write operation pauses and requires you to type `yes` in the terminal before executing.

---

### 🚀 Quick Start

#### Prerequisites
- Python **3.10+** (verify with `python3 --version`)
- Google Chrome

#### Step 1: Start the Lite Server (Track A core)

```bash
git clone https://github.com/xishan615-bit/webrecall.git
cd webrecall/backend

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python lite_server.py           # Keep this terminal open!
# You should see: "🚀 WebRecall Lite Server starting on port 8001..."
```

#### Step 2: Load the Chrome Extension

1. Go to `chrome://extensions` in Chrome
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select the `webrecall/extension/` folder
4. The 🦞 icon appears in your toolbar — click to start saving pages

#### Step 3 (Optional): Configure MCP

Add to your Cursor / Claude Desktop / OpenClaw MCP config:

```json
{
  "mcpServers": {
    "webrecall": {
      "command": "python",
      "args": ["/absolute/path/to/webrecall/mcp/server.py"]
    }
  }
}
```

#### Step 4 (Optional): Run the LangGraph Agent

```bash
# Must run from the project ROOT (not inside backend/)
cd webrecall

pip install langgraph langchain-openai httpx ddgs

# Set your LLM API (pick one)
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.deepseek.com"   # DeepSeek (recommended)
export OPENAI_MODEL_NAME="deepseek-chat"

# Or use OpenAI directly:
# export OPENAI_API_KEY="sk-proj-..."

# Or use OpenRouter (Claude, Llama, etc.):
# export OPENAI_API_KEY="sk-or-..."
# export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
# export OPENAI_MODEL_NAME="anthropic/claude-3.5-sonnet"

python -m agents.run
```

At the `你 >` prompt, type commands like:
> "Classify all untagged pages in my library"  
> "Summarize everything I saved about RAG, then search the web for the latest multi-agent frameworks"

---

### 📁 Project Structure

```
webrecall/
├── extension/             # Chrome Extension (Manifest V3)
│   ├── background.js      # Offline BM25 engine + message routing
│   ├── content.js         # Page content extraction
│   └── popup/             # Search / library management UI
├── backend/
│   ├── lite_server.py     # Lightweight local API (SQLite R/W, ~15MB RAM)
│   └── db/sqlite_store.py # SQLite DAO + FTS table init
├── mcp/
│   └── server.py          # Standard MCP server (for AI clients)
├── agents/                # LangGraph multi-agent system
│   ├── graph.py           # Graph assembly (Commander → specialists)
│   ├── tools.py           # LangChain tool layer
│   └── nodes/             # commander / classifier / reporter / deep_researcher
└── skills/                # Agent skill prompt packages
```

---

## 📜 License

MIT
