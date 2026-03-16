// ── WebRecall Popup ───────────────────────────────────────────
// 状态由 Lite Server 开关直接决定，无需轮询
// Lite Server 开 → 强化模式 | 关 → 本地模式

const LITE_URL = "http://localhost:8001";

// ── 状态：单一真相来源 ────────────────────────────────────────
let liteOnline  = false; // Lite Server 是否在线
let nmAvailable = null;  // Native Messaging Host 是否可用

// ── 元素引用 ──────────────────────────────────────────────────
const btnSave      = document.getElementById("btn-save");
const saveLabel    = document.getElementById("save-label");
const saveFeedback = document.getElementById("save-feedback");
const statusDot    = document.getElementById("status-dot");
const statusLabel  = document.getElementById("status-label");

const tabSearch   = document.getElementById("tab-search");
const tabLibrary  = document.getElementById("tab-library");
const tabGuide    = document.getElementById("tab-guide");
const panelSearch  = document.getElementById("panel-search");
const panelLibrary = document.getElementById("panel-library");
const panelGuide   = document.getElementById("panel-guide");

const searchInput   = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const libraryList   = document.getElementById("library-list");
const libraryCount  = document.getElementById("library-count");

const liteDot   = document.getElementById("lite-dot");
const liteLabel = document.getElementById("lite-label");
const btnLite   = document.getElementById("btn-lite");
const liteHint  = document.getElementById("lite-hint");

let searchTimer = null;

// ── 核心：更新全局状态 UI ─────────────────────────────────────
function applyMode() {
  if (liteOnline) {
    statusDot.className   = "status-dot online";
    statusLabel.textContent = "强化模式";
    document.getElementById("status-card-icon").textContent  = "🟡";
    document.getElementById("status-card-title").textContent = "强化模式";
    document.getElementById("status-card-desc").textContent  = "Lite Server 在线，保存写入 SQLite，MCP 可检索";
    liteDot.className     = "lite-dot on";
    liteLabel.textContent = "运行中";
    btnLite.textContent   = "关闭";
    btnLite.className     = "btn-lite stop";
    btnLite.disabled      = false;
    liteHint.textContent  = "";
  } else {
    statusDot.className   = "status-dot local";
    statusLabel.textContent = "本地模式";
    document.getElementById("status-card-icon").textContent  = "🔴";
    document.getElementById("status-card-title").textContent = "本地模式";
    document.getElementById("status-card-desc").textContent  = "数据存于浏览器本地。启动 Lite Server 后 MCP Agent 可检索";
    liteDot.className     = "lite-dot off";
    liteLabel.textContent = "已停止";
    btnLite.textContent   = nmAvailable === false ? "未安装" : "启动";
    btnLite.className     = "btn-lite start";
    btnLite.disabled      = nmAvailable === false;
    if (nmAvailable === false) {
      liteHint.textContent = "⚠️ 请先运行 install-native-host.sh";
      liteHint.className   = "lite-hint warn";
    } else {
      liteHint.textContent = "纯 SQLite，不需要 Ollama（~15MB 内存）";
      liteHint.className   = "lite-hint";
    }
  }
}

// ── Tab 切换 ──────────────────────────────────────────────────
function switchTab(tab) {
  [tabSearch, tabLibrary, tabGuide].forEach(t => t.classList.remove("active"));
  [panelSearch, panelLibrary, panelGuide].forEach(p => p.style.display = "none");
  if (tab === "search") {
    tabSearch.classList.add("active");
    panelSearch.style.display = "flex";
    searchInput.focus();
  } else if (tab === "library") {
    tabLibrary.classList.add("active");
    panelLibrary.style.display = "flex";
    loadLibrary();
  } else {
    tabGuide.classList.add("active");
    panelGuide.style.display = "flex";
  }
}
tabSearch.addEventListener("click", () => switchTab("search"));
tabLibrary.addEventListener("click", () => switchTab("library"));
tabGuide.addEventListener("click", () => switchTab("guide"));
document.getElementById("btn-refresh-library").addEventListener("click", loadLibrary);

// ── Lite Server 控制（Native Messaging）──────────────────────
const NM_HOST = "com.webrecall.native";

function sendNativeMessage(action) {
  // MV3 popup 不能直接调 sendNativeMessage，必须通过 background service worker 中转
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({ type: "NATIVE_MESSAGE", action }, (resp) => {
        const err = chrome.runtime.lastError;
        if (err) {
          console.warn(`[WebRecall] NM ${action} error:`, err.message);
          resolve({ ok: false, running: false, message: err.message });
        } else {
          console.log(`[WebRecall] NM ${action} response:`, resp);
          resolve(resp || { ok: false, running: false, message: "无响应" });
        }
      });
    } catch (e) {
      console.warn(`[WebRecall] NM ${action} exception:`, e.message);
      resolve({ ok: false, running: false, message: e.message });
    }
  });
}

/** 直接 HTTP 健康检查 Lite Server 是否在线 */
async function _checkHealth() {
  try {
    const resp = await fetch(`${LITE_URL}/health`, { signal: AbortSignal.timeout(2000) });
    return resp.ok;
  } catch { return false; }
}

function _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

btnLite.addEventListener("click", async () => {
  btnLite.disabled = true;
  liteHint.textContent = "";
  liteHint.className   = "lite-hint";

  // 实时检查当前状态（不依赖可能过期的 liteOnline 变量）
  const currentlyRunning = await _checkHealth();
  console.log("[WebRecall] btn click, currentlyRunning=", currentlyRunning);

  if (currentlyRunning) {
    // ── 关闭 ────────────────────────────────────────────────
    btnLite.textContent = "关闭中...";

    // ① NM stop
    const nmResult = await sendNativeMessage("stop");
    console.log("[WebRecall] NM stop result:", nmResult);

    // ② 无论 NM 是否成功，都尝试 HTTP /shutdown 兜底
    try {
      await fetch(`${LITE_URL}/shutdown`, {
        method: "POST",
        signal: AbortSignal.timeout(3000),
      });
    } catch (e) {
      console.warn("[WebRecall] HTTP /shutdown:", e.message);
    }

    // ③ 等 1.5s 后确认
    await _sleep(1500);
    liteOnline = await _checkHealth();

    if (liteOnline) {
      liteHint.textContent = "❌ 关闭失败，请在终端手动停止";
      liteHint.className   = "lite-hint warn";
    }

  } else {
    // ── 启动 ────────────────────────────────────────────────
    btnLite.textContent = "启动中...";

    const nmResult = await sendNativeMessage("start");
    console.log("[WebRecall] NM start result:", nmResult);

    // 等 3s 后 health check 确认
    await _sleep(3000);
    liteOnline = await _checkHealth();

    if (!liteOnline) {
      const reason = nmResult.message || "请在终端手动运行 python lite_server.py";
      liteHint.textContent = `❌ 启动失败：${reason}`;
      liteHint.className   = "lite-hint warn";
    }
  }

  applyMode();
});

// ── 库管理 ────────────────────────────────────────────────────
let libTab = "pending"; // "pending" | "done"
const libTabPending = document.getElementById("lib-tab-pending");
const libTabDone    = document.getElementById("lib-tab-done");

libTabPending.addEventListener("click", () => { libTab = "pending"; libTabPending.classList.add("active"); libTabDone.classList.remove("active"); loadLibrary(); });
libTabDone.addEventListener("click",    () => { libTab = "done";    libTabDone.classList.add("active"); libTabPending.classList.remove("active"); loadLibrary(); });

async function loadLibrary() {
  libraryList.innerHTML = '<div class="search-hint">加载中...</div>';
  try {
    let pages = [], total = 0;
    try {
      const resp = await fetch(`${LITE_URL}/api/pages`, { signal: AbortSignal.timeout(2000) });
      if (resp.ok) {
        const data = await resp.json();
        pages = data.pages || [];
        total = data.total || 0;
      } else throw new Error();
    } catch {
      const res = await chrome.runtime.sendMessage({ type: "GET_PAGES_LOCAL" });
      pages = res?.pages || [];
      total = res?.total || 0;
    }

    // 按 classified_at 分流
    const pending = pages.filter(p => !p.classified_at && !p.tags?.length);
    const done    = pages.filter(p =>  p.classified_at ||  p.tags?.length);
    const shown   = libTab === "pending" ? pending : done;

    libraryCount.textContent = libTab === "pending"
      ? `待整理 ${pending.length} 篇`
      : `已整理 ${done.length} 篇`;

    renderLibrary(shown);
  } catch {
    libraryList.innerHTML = '<div class="search-hint">⚠️ 无法加载</div>';
  }
}

function renderLibrary(pages) {
  if (!pages.length) {
    libraryList.innerHTML = '<div class="search-hint">还没有保存任何页面 — 点击「💾 保存当前页面」开始吧！</div>';
    return;
  }
  libraryList.innerHTML = "";
  for (const p of pages) {
    const tags = Array.isArray(p.tags) ? p.tags : (p.tags ? JSON.parse(p.tags) : []);
    const tagsHtml = tags.length
      ? `<div class="result-tags">${tags.map(t => `<span class="result-tag">${escHtml(t)}</span>`).join("")}</div>`
      : "";
    const item = document.createElement("div");
    item.className = "page-item";
    item.innerHTML = `
      <div class="page-info">
        <div class="page-item-title" title="${escHtml(p.url)}">${escHtml(p.title || p.url)}</div>
        ${tagsHtml}
        <div class="page-item-meta">${escHtml(p.domain || "")} · ${formatTimeAgo(p.saved_at)}</div>
      </div>
      <button class="btn-delete" title="删除">🗑</button>
    `;
    item.querySelector(".page-item-title").addEventListener("click", () => chrome.tabs.create({ url: p.url }));
    item.querySelector(".btn-delete").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`删除「${p.title || p.url}」？`)) return;
      try {
        if (liteOnline) {
          await fetch(`${LITE_URL}/api/pages?url=${encodeURIComponent(p.url)}`, { method: "DELETE" });
        } else {
          await chrome.runtime.sendMessage({ type: "DELETE_PAGE_LOCAL", url: p.url });
        }
      } catch { alert("删除失败"); return; }
      item.style.opacity = "0";
      item.style.transition = "opacity 0.3s";
      setTimeout(() => { item.remove(); loadLibrary(); }, 300);
    });
    libraryList.appendChild(item);
  }
}

// ── Live Search ──────────────────────────────────────────────
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (!q) {
    searchResults.innerHTML = '<div class="search-hint">输入关键词，实时显示相关页面</div>';
    return;
  }
  searchResults.innerHTML = '<div class="result-searching">🔍 搜索中...</div>';
  searchTimer = setTimeout(() => doSearch(q), 300);
});

searchInput.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
  e.preventDefault();
  const q = searchInput.value.trim();
  if (!q) return;
  clearTimeout(searchTimer);
  doSearch(q);
});

function _parseTimeHint(query) {
  const TIME_MAP = [
    { words: ["今天"], days: 1 }, { words: ["昨天"], days: 2 },
    { words: ["前天", "两天前", "2天前"], days: 3 }, { words: ["三天前", "3天前"], days: 4 },
    { words: ["本周", "这周", "最近", "近期"], days: 7 }, { words: ["上周"], days: 14 },
    { words: ["上个月", "一个月前"], days: 35 },
  ];
  const STOP = ["好像","那个","那篇","那条","帮我","找","收藏","看过","读过","的","了","大概","记得"];
  let days = null, semantic = query;
  for (const { words, days: d } of TIME_MAP)
    for (const w of words)
      if (query.includes(w)) { days = d; semantic = semantic.replace(w, " "); }
  for (const sw of STOP) semantic = semantic.replace(sw, " ");
  return { days, semantic: semantic.replace(/\s+/g, " ").trim() };
}

async function doSearch(q) {
  try {
    let results = [];
    if (liteOnline) {
      try {
        const { days, semantic } = _parseTimeHint(q);
        let url = `${LITE_URL}/api/search?q=${encodeURIComponent(semantic || q)}&limit=8`;
        if (days) url += `&days=${days}`;
        const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
        const data = await resp.json();
        results = data.results || [];
      } catch {
        // lite 失败降级到本地
        const res = await chrome.runtime.sendMessage({ type: "SEARCH_LOCAL", query: q, limit: 8 });
        results = res?.results || [];
      }
    } else {
      const res = await chrome.runtime.sendMessage({ type: "SEARCH_LOCAL", query: q, limit: 8 });
      results = res?.results || [];
    }
    renderSearchResults(results, q);
  } catch {
    searchResults.innerHTML = '<div class="search-hint">⚠️ 搜索暂时不可用</div>';
  }
}

function highlight(text, q) {
  if (!q || !text) return escHtml(text || "");
  const escaped = escHtml(text);
  // 同时支持空格分词和 + 分词，每个词独立高亮
  const tokens = q.trim().split(/[\s+]+/).filter(t => t.length > 0).map(t =>
    t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  if (!tokens.length) return escaped;
  const re = new RegExp(`(${tokens.join("|")})`, "gi");
  return escaped.replace(re, '<mark class="hl">$1</mark>');
}

function renderSearchResults(results, q = "") {
  if (!results.length) {
    searchResults.innerHTML = '<div class="search-hint">没有找到相关页面，换个关键词试试</div>';
    return;
  }
  searchResults.innerHTML = "";
  for (const r of results) {
    const tags = Array.isArray(r.tags) ? r.tags : [];
    const tagsHtml = tags.length
      ? `<div class="result-tags">${tags.map(t => `<span class="result-tag">${highlight(t, q)}</span>`).join("")}</div>`
      : "";
    const card = document.createElement("div");
    card.className = "result-card";
    card.innerHTML = `
      <div class="result-title">${highlight(r.title || r.url, q)}</div>
      ${tagsHtml}
      <div class="result-meta">
        <span class="result-domain">${escHtml(r.domain || "")}</span>
        <span>${formatTimeAgo(r.saved_at)}</span>
      </div>
      ${r.snippet ? `<div class="result-snippet">${highlight(r.snippet, q)}</div>` : ""}
    `;
    card.addEventListener("click", () => chrome.tabs.create({ url: r.url }));
    searchResults.appendChild(card);
  }
}

// ── 保存当前页面 ──────────────────────────────────────────────
btnSave.addEventListener("click", async () => {
  btnSave.disabled = true;
  saveLabel.textContent = "正在提取内容...";
  showFeedback("", false);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    let pageData;
    try {
      pageData = await chrome.tabs.sendMessage(tab.id, { type: "EXTRACT_CONTENT" });
    } catch {
      showFeedback("❌ 此页面无法保存（系统页面）", true);
      return;
    }

    saveLabel.textContent = "正在保存...";
    const result = await chrome.runtime.sendMessage({
      type: "SAVE_PAGE",
      data: {
        url:      pageData.url,
        title:    pageData.title,
        content:  pageData.text || "",
        html:     pageData.html || "",
        saved_at: new Date().toISOString(),
      },
    });

    if (result?.success) {
      showFeedback(liteOnline ? "✅ 已存入 SQLite！" : "✅ 已存到本地！");
    } else {
      showFeedback(`❌ ${result?.message || "保存失败"}`, true);
    }
  } catch {
    showFeedback("❌ 发生错误", true);
  } finally {
    btnSave.disabled = false;
    saveLabel.textContent = "保存当前页面";
  }
});

// ── 工具函数 ──────────────────────────────────────────────────
function showFeedback(msg, isError = false) {
  saveFeedback.textContent = msg;
  saveFeedback.className = "save-feedback" + (isError ? " error" : "");
  if (msg) setTimeout(() => { saveFeedback.textContent = ""; saveFeedback.className = "save-feedback"; }, 3000);
}

function formatTimeAgo(isoStr) {
  if (!isoStr) return "";
  try {
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60)    return "刚刚";
    if (diff < 3600)  return `${Math.floor(diff/60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff/3600)} 小时前`;
    return `${Math.floor(diff/86400)} 天前`;
  } catch { return ""; }
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── 初始化：只做一次状态检测 ─────────────────────────────────
(async () => {
  // 查询 Lite Server 是否在线
  try {
    const resp = await fetch(`${LITE_URL}/health`, { signal: AbortSignal.timeout(2000) });
    liteOnline = resp.ok;
  } catch {
    liteOnline = false;
  }

  // 检测 Native Messaging Host 是否可用（不阻塞）
  sendNativeMessage("status").then((result) => {
    nmAvailable = !result.message?.includes("not found") && !result.message?.includes("native");
    applyMode();
  });

  applyMode();
})();
