/**
 * content.js — WebRecall 页面内容提取
 * 支持 SPA（Twitter/Reddit/YouTube 等），通过拦截 pushState 追踪导航
 */

// ── SPA 导航追踪 ─────────────────────────────────────────
let _lastNavTime = Date.now();
let _currentUrl  = window.location.href;

// 拦截 history.pushState（React/Vue Router 的跳转方式）
const _origPushState = history.pushState.bind(history);
history.pushState = function (...args) {
  _origPushState(...args);
  _onNavigate();
};

// 拦截浏览器前进/后退
window.addEventListener("popstate", _onNavigate);

function _onNavigate() {
  const newUrl = window.location.href;
  if (newUrl !== _currentUrl) {
    _currentUrl  = newUrl;
    _lastNavTime = Date.now();
  }
}

// ── 消息监听 ──────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "EXTRACT_CONTENT") {
    _extractWithRetry().then(sendResponse);
    return true;  // 保持通道开放（async response）
  }
});

// ── 内容提取（SPA 感知） ──────────────────────────────────
async function _extractWithRetry() {
  // 如果距离上次导航不足 800ms，等待 React/Vue 完成渲染
  const elapsed = Date.now() - _lastNavTime;
  if (elapsed < 800) {
    await _sleep(800 - elapsed);
  }

  // 首次尝试
  let result = _doExtract();

  // 若内容太少（SPA 还没渲染完），最多再等 2 次
  if (result.text.length < 200) {
    await _sleep(600);
    result = _doExtract();
  }
  if (result.text.length < 200) {
    await _sleep(800);
    result = _doExtract();
  }

  return result;
}

function _doExtract() {
  // 移除无用元素再取文字，降低噪音
  const SKIP = ["script", "style", "noscript", "svg", "iframe",
                "nav", "footer", "[aria-hidden='true']"];
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll(SKIP.join(",")).forEach(el => el.remove());

  const text = (clone.innerText || "")
    .replace(/\s{3,}/g, "\n\n")  // 压缩空白
    .trim()
    .slice(0, 50000);

  return {
    url:   window.location.href,
    title: document.title || window.location.hostname,
    html:  document.documentElement.outerHTML,
    text,
  };
}

function _sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
