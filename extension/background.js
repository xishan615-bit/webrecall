const LITE_URL = "http://localhost:8001";
const LOCAL_PAGES_KEY = "wr_pages";

// ──────────────────────────────────────────────────────────────
// Tier 1：纯本地存储引擎（chrome.storage.local）
// ──────────────────────────────────────────────────────────────

/** 读取所有本地页面 */
async function localGetPages() {
  return new Promise((resolve) => {
    chrome.storage.local.get([LOCAL_PAGES_KEY], (res) => {
      resolve(res[LOCAL_PAGES_KEY] || []);
    });
  });
}

/** 写回全量页面 */
async function localSetPages(pages) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [LOCAL_PAGES_KEY]: pages }, resolve);
  });
}

/** 保存一个页面（去重：同 URL 覆盖更新） */
async function localSavePage(data) {
  try {
    const pages = await localGetPages();
    const domain = (() => {
      try { return new URL(data.url).hostname; } catch { return ""; }
    })();
    const excerpt = (data.text || "").replace(/\s+/g, " ").trim().slice(0, 800);
    const record = {
      url:      data.url,
      title:    data.title || data.url,
      domain,
      text:     (data.text || "").replace(/\s+/g, " ").trim().slice(0, 30000),
      excerpt,
      saved_at: data.saved_at || new Date().toISOString(),
    };
    const idx = pages.findIndex((p) => p.url === data.url);
    if (idx >= 0) pages[idx] = record;
    else pages.unshift(record);
    await localSetPages(pages);
    return { success: true, message: "已保存到本地" };
  } catch (e) {
    return { success: false, message: `保存失败：${e.message}` };
  }
}

/** 删除一个页面（按 URL） */
async function localDeletePage(url) {
  const pages = await localGetPages();
  await localSetPages(pages.filter((p) => p.url !== url));
  return { success: true };
}

/** 获取统计 */
async function localGetStats() {
  const pages = await localGetPages();
  return { total_pages: pages.length, total_chunks: 0, tier: "local" };
}

// ── BM25 关键词搜索（支持中文单字 + bigram 双字切分）──────────

/**
 * 分词：英文按空格，中文同时产出单字 + bigram 双字
 * 例："政务龙虾" → ["政","务","龙","虾","政务","务龙","龙虾"]
 * bigram 让复合词/专有名词（如"政务龙虾"）拥有唯一高 IDF token，
 * 避免单字"政"和"务"在无关文章中干扰排名。
 */
function tokenize(str) {
  const tokens = [];
  const normalized = (str || "")
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]/g, " ");

  const words = normalized.split(/\s+/).filter(Boolean);
  for (const w of words) {
    const cjk = w.match(/[\u4e00-\u9fff]/g) || [];
    const latin = w.replace(/[\u4e00-\u9fff]/g, "").trim();

    // 单字
    tokens.push(...cjk);
    if (latin.length > 0) tokens.push(latin);

    // CJK bigram（相邻两字对）
    for (let i = 0; i < cjk.length - 1; i++) {
      tokens.push(cjk[i] + cjk[i + 1]);
    }
  }
  return tokens.filter(t => t.length > 0);
}

/** 词频统计 */
function termFreq(tokens) {
  const tf = {};
  for (const t of tokens) tf[t] = (tf[t] || 0) + 1;
  return tf;
}

/** 从文本中截取包含命中词的 snippet（±80字符上下文） */
function extractSnippet(text, queryTokens) {
  if (!text) return "";
  const lower = text.toLowerCase();
  for (const token of queryTokens) {
    const idx = lower.indexOf(token);
    if (idx >= 0) {
      const start = Math.max(0, idx - 60);
      const end   = Math.min(text.length, idx + token.length + 120);
      return (start > 0 ? "…" : "") + text.slice(start, end).trim() + (end < text.length ? "…" : "");
    }
  }
  return text.slice(0, 150).trim() + (text.length > 150 ? "…" : "");
}

// ── 时间关键词解析（本地版）──────────────────────────────────
const TIME_WORDS = [
  { words: ["今天"], days: 1 },
  { words: ["昨天"], days: 2 },
  { words: ["前天"], days: 3 },
  { words: ["两天前", "2天前"], days: 3 },
  { words: ["三天前", "3天前"], days: 4 },
  { words: ["本周", "这周", "这个星期"], days: 7 },
  { words: ["上周", "上个星期"], days: 14 },
  { words: ["最近", "近期", "近来"], days: 7 },
  { words: ["一个月前", "上个月", "上月"], days: 35 },
  { words: ["两周前", "两个星期前"], days: 18 },
  { words: ["三周前"], days: 25 },
];

// 口语化词（无语义信息，搜索时应过滤掉）
const STOP_WORDS = new Set([
  "好像","那个","那篇","那条","帮我","找","有吗","一个","一篇","一条",
  "收藏","看过","读过","保存","的","了","也","大概","大约","记得","有没有",
]);

function parseTimeHint(query) {
  let days = null;
  let semantic = query;
  for (const { words, days: d } of TIME_WORDS) {
    for (const w of words) {
      if (query.includes(w)) {
        days = d;
        semantic = semantic.replace(w, " ");
      }
    }
  }
  for (const sw of STOP_WORDS) {
    semantic = semantic.replace(sw, " ");
  }
  semantic = semantic.replace(/\s+/g, " ").trim();
  return { days, semantic };
}

/**
 * BM25-style 本地搜索（时间感知版）
 * - "两天前好像" → 时间过滤(2天内) + 无关键词 → 按时间倒序返回
 * - "上周那篇 RAG" → 时间过滤(7天内) + BM25 搜 "RAG"
 * - "RAG" → 不限时间 BM25
 */
async function localSearch(query, limit = 8) {
  const pages = await localGetPages();
  if (!pages.length) return { results: [] };

  const { days, semantic } = parseTimeHint(query);

  // Step 1: 时间过滤
  const now = Date.now();
  let pool = days
    ? pages.filter((p) => now - new Date(p.saved_at).getTime() <= days * 86400 * 1000)
    : pages;

  // Step 2a: 纯时间查询（无语义关键词）→ 按时间倒序返回
  if (!semantic) {
    return {
      results: pool.slice(0, limit).map((p) => ({
        url:      p.url,
        title:    p.title,
        domain:   p.domain,
        saved_at: p.saved_at,
        score:    1,
        snippet:  p.excerpt || (p.text || "").slice(0, 120),
      })),
    };
  }

  // Step 2b: BM25 在时间过滤后的 pool 中跑
  if (!pool.length) return { results: [] };
  const qTokens = tokenize(semantic);
  if (!qTokens.length) return { results: [] };

  const docCount = pool.length;
  const docFreq = {};
  for (const page of pool) {
    const tokens = new Set(tokenize(page.title + " " + page.text));
    for (const t of tokens) docFreq[t] = (docFreq[t] || 0) + 1;
  }

  const idf = (t) => Math.log((docCount + 1) / ((docFreq[t] || 0) + 1)) + 1;

  const scored = pool.map((page) => {
    const fieldText = `${page.title} ${page.title} ${page.text}`;
    const tokens = tokenize(fieldText);
    const tf = termFreq(tokens);
    const totalTerms = tokens.length || 1;

    const k1 = 1.5, b = 0.75, avgdl = 300;
    let score = 0;
    for (const t of qTokens) {
      const f = tf[t] || 0;
      if (f === 0) continue;
      score += idf(t) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (totalTerms / avgdl)));
    }
    return {
      url:      page.url,
      title:    page.title,
      domain:   page.domain,
      saved_at: page.saved_at,
      score,
      snippet:  score > 0 ? extractSnippet(page.text, qTokens) : "",
    };
  });

  let results = scored
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);

  // 兜底：关键词过于口语化打不了分，退化为时间范围内最新页面
  if (!results.length && days) {
    results = pool.slice(0, limit).map((p) => ({
      url:      p.url,
      title:    p.title,
      domain:   p.domain,
      saved_at: p.saved_at,
      score:    0.5,
      snippet:  p.excerpt || (p.text || "").slice(0, 120),
    }));
  }

  return { results };
}

// ── 消息路由 ──────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // ── 本地操作 ──
  if (message.type === "SAVE_PAGE_LOCAL") {
    localSavePage(message.data).then(sendResponse);
    return true;
  }
  if (message.type === "SEARCH_LOCAL") {
    localSearch(message.query, message.limit || 8).then(sendResponse);
    return true;
  }
  if (message.type === "GET_PAGES_LOCAL") {
    localGetPages().then((pages) => sendResponse({ pages, total: pages.length }));
    return true;
  }
  if (message.type === "DELETE_PAGE_LOCAL") {
    localDeletePage(message.url).then(sendResponse);
    return true;
  }
  if (message.type === "GET_STATS_LOCAL") {
    localGetStats().then(sendResponse);
    return true;
  }

  // ── Lite Server 操作 ──
  if (message.type === "SAVE_PAGE") {
    savePage(message.data).then(sendResponse);
    return true;
  }
  if (message.type === "GET_STATS") {
    getStats().then(sendResponse);
    return true;
  }
});

// ── Lite Server API 调用（降级到 chrome.storage）─────────────
async function savePage(data) {
  // ① 尝试 lite server
  try {
    const resp = await fetch(`${LITE_URL}/api/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (resp.ok) return await resp.json();
  } catch {}

  // ② 兜底：存到 chrome.storage
  return await localSavePage(data);
}

async function getStats() {
  // ① lite server
  try {
    const resp = await fetch(`${LITE_URL}/api/stats`);
    if (resp.ok) return await resp.json();
  } catch {}
  // ② 本地
  return await localGetStats();
}
