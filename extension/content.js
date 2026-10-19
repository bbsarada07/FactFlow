// NemesisAI content script: floating verdict badge, plus inline verify buttons on
// WhatsApp Web, X/Twitter and Instagram. All UI lives in shadow roots so page CSS can't leak in.
(() => {
  if (window.__nemesisLoaded) return;
  window.__nemesisLoaded = true;

  const COLORS = {
    FALSE: "#FF2D2D",
    TRUE: "#00E676",
    MISLEADING: "#FF6B00",
    UNVERIFIED: "#8888A0",
    SATIRE: "#B04FD0",
  };
  const colorFor = (v) => COLORS[v] || COLORS.UNVERIFIED;
  const clip = (s, n) => { s = String(s || "").trim(); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; };
  const pct = (c) => (c == null ? "" : `${Math.round(c * 100)}%`);
  const esc = (s) =>
    String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const BASE_CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: Inter, "Segoe UI", system-ui, sans-serif; }
    @keyframes nm-in { from { transform: translateX(120%); opacity: 0; } to { transform: none; opacity: 1; } }
    @keyframes nm-spin { to { transform: rotate(360deg); } }
    @keyframes nm-fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
    .spin { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,.2); border-top-color: #FF2D2D; border-radius: 50%; animation: nm-spin .8s linear infinite; flex: none; }
    .verdict { display: inline-block; font-weight: 700; font-size: 11px; letter-spacing: 1px; padding: 3px 8px; border-radius: 6px; color: #fff; }
    .mono { font-family: "JetBrains Mono", Consolas, monospace; }
  `;

  // ── Floating badge (top-right) ─────────────────────────────────────
  let badgeHost = null;
  let badgeRoot = null;
  let dismissTimer = null;

  function ensureBadge() {
    if (badgeRoot) return badgeRoot;
    badgeHost = document.createElement("nemesis-badge");
    badgeHost.style.cssText = "position:fixed;top:16px;right:16px;z-index:2147483647;";
    badgeRoot = badgeHost.attachShadow({ mode: "open" });
    document.documentElement.appendChild(badgeHost);
    return badgeRoot;
  }

  function renderBadge(inner, accent, autoDismiss) {
    const root = ensureBadge();
    clearTimeout(dismissTimer);
    root.innerHTML = `
      <style>${BASE_CSS}
        .card { width: 280px; background: rgba(13,13,18,.94); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
          border: 1px solid rgba(255,255,255,.08); border-left: 3px solid ${accent}; border-radius: 14px; padding: 14px 16px;
          color: #F0F0F5; box-shadow: 0 12px 40px rgba(0,0,0,.55), 0 0 32px ${accent}33; animation: nm-in .35s cubic-bezier(.25,.46,.45,.94); }
        .row { display: flex; align-items: center; gap: 8px; }
        .close { margin-left: auto; background: none; border: 0; color: #8888A0; cursor: pointer; font-size: 16px; line-height: 1; padding: 2px; }
        .close:hover { color: #fff; }
        .summary { font-size: 12.5px; line-height: 1.5; color: #C8C8D8; margin: 10px 0 8px; }
        .brand { font-size: 10px; letter-spacing: 2px; color: #8888A0; }
        .brand b { color: #FF2D2D; }
        .conf { font-size: 12px; color: #F0F0F5; }
      </style>
      <div class="card" role="status">${inner}</div>`;
    root.querySelector(".close")?.addEventListener("click", hideBadge);
    if (autoDismiss) dismissTimer = setTimeout(hideBadge, 8000);
  }

  function hideBadge() {
    clearTimeout(dismissTimer);
    if (badgeHost) badgeHost.remove();
    badgeHost = null;
    badgeRoot = null;
  }

  const brand = `<div class="brand mono"><b>N</b>EMESISAI</div>`;

  function showPending() {
    renderBadge(
      `<div class="row"><div class="spin"></div><span style="font-size:13px;font-weight:600">Verifying claim…</span>
       <button class="close" aria-label="Close">×</button></div>
       <div class="summary">Six agents are tracing sources and checking the evidence.</div>${brand}`,
      "#FF2D2D",
      false
    );
  }

  function showResult(r) {
    const c = colorFor(r.verdict);
    renderBadge(
      `<div class="row"><span class="verdict" style="background:${c};color:${r.verdict === "TRUE" ? "#04140b" : "#fff"}">${esc(r.verdict)}</span>
       <span class="conf mono">${pct(r.confidence)} confidence</span><button class="close" aria-label="Close">×</button></div>
       <div class="summary">${esc(clip(r.summary || r.fact || r.claim, 170))}</div>${brand}`,
      c,
      true
    );
  }

  function showError(message) {
    renderBadge(
      `<div class="row"><span class="verdict" style="background:#2A2A3A">ERROR</span><button class="close" aria-label="Close">×</button></div>
       <div class="summary">${esc(message)}</div>${brand}`,
      "#8888A0",
      true
    );
  }

  // ── Platform adapters ──────────────────────────────────────────────
  const host = location.hostname;
  const ADAPTERS = {
    whatsapp: {
      match: host === "web.whatsapp.com",
      container: (el) => el.closest("[data-id]"),
      text: (c) => {
        const parts = [...c.querySelectorAll("span.selectable-text, div.copyable-text span[dir]")].map((n) => n.innerText.trim());
        const text = [...new Set(parts)].filter(Boolean).join("\n");
        return text || (c.querySelector(".copyable-text") || c).innerText;
      },
      mount: (c) => (c.querySelector(".copyable-text") || c).parentElement || c,
    },
    twitter: {
      match: host === "x.com" || host === "twitter.com" || host === "mobile.twitter.com",
      container: (el) => el.closest('article[data-testid="tweet"]'),
      text: (c) => (c.querySelector('[data-testid="tweetText"]') || c).innerText,
      mount: (c) => (c.querySelector('[data-testid="tweetText"]') || c).parentElement || c,
    },
    instagram: {
      match: host.endsWith("instagram.com"),
      container: (el) => el.closest("article") || el.closest('div[role="row"]'),
      text: (c) => {
        const h1 = c.querySelector("h1");
        if (h1 && h1.innerText.trim().length > 10) return h1.innerText;
        const spans = [...c.querySelectorAll('span[dir="auto"]')].map((s) => s.innerText.trim());
        return spans.sort((a, b) => b.length - a.length)[0] || c.innerText;
      },
      mount: (c) => c,
    },
  };
  const platformName = Object.keys(ADAPTERS).find((k) => ADAPTERS[k].match) || null;
  const adapter = platformName ? ADAPTERS[platformName] : null;

  const cleanText = (t) => String(t || "").replace(/\s+\n/g, "\n").replace(/[ \t]+/g, " ").trim().slice(0, 5000);

  // Inline verdict chip rendered on the message bubble itself.
  function inlineChip(container) {
    const mount = adapter.mount(container);
    let chipHost = mount.querySelector(":scope > nemesis-inline");
    if (!chipHost) {
      chipHost = document.createElement("nemesis-inline");
      chipHost.style.cssText = "display:block;margin:6px 0 2px;";
      chipHost.attachShadow({ mode: "open" });
      mount.appendChild(chipHost);
    }
    const root = chipHost.shadowRoot;
    return {
      pending() {
        root.innerHTML = `<style>${BASE_CSS}
          .chip { display:inline-flex; align-items:center; gap:8px; background:rgba(13,13,18,.92); border:1px solid #2A2A3A;
            border-radius:10px; padding:6px 10px; color:#C8C8D8; font-size:12px; animation: nm-fade .3s ease; }</style>
          <div class="chip"><div class="spin"></div>NemesisAI is checking this…</div>`;
      },
      result(r) {
        const c = colorFor(r.verdict);
        root.innerHTML = `<style>${BASE_CSS}
          .chip { display:block; max-width: 360px; background:rgba(13,13,18,.94); border:1px solid ${c}55; border-left:3px solid ${c};
            border-radius:10px; padding:8px 10px; color:#E0E0EA; font-size:12px; line-height:1.45; animation: nm-fade .3s ease;
            box-shadow: 0 0 18px ${c}22; }
          .top { display:flex; align-items:center; gap:8px; margin-bottom:4px; }
          .conf { color:#8888A0; font-size:11px; }
          .x { margin-left:auto; background:none; border:0; color:#8888A0; cursor:pointer; font-size:14px; }</style>
          <div class="chip"><div class="top"><span class="verdict" style="background:${c};color:${r.verdict === "TRUE" ? "#04140b" : "#fff"}">${esc(r.verdict)}</span>
          <span class="conf mono">${pct(r.confidence)} · NemesisAI</span><button class="x" aria-label="Dismiss">×</button></div>
          ${esc(clip(r.fact || r.summary, 220))}</div>`;
        root.querySelector(".x").addEventListener("click", () => chipHost.remove());
      },
      error(msg) {
        root.innerHTML = `<style>${BASE_CSS} .chip{display:inline-block;background:rgba(13,13,18,.92);border:1px solid #2A2A3A;border-radius:10px;padding:6px 10px;color:#FF8A8A;font-size:12px;}</style>
          <div class="chip">NemesisAI: ${esc(msg)}</div>`;
      },
    };
  }

  function verifyInline(container) {
    const text = cleanText(adapter.text(container));
    if (text.length < 8) {
      showError("This message has no text to verify.");
      return;
    }
    const chip = inlineChip(container);
    chip.pending();
    chrome.runtime.sendMessage({ type: "NEMESIS_VERIFY_TEXT", text, platform: platformName }, (resp) => {
      if (chrome.runtime.lastError) return chip.error("Extension was reloaded — refresh the page.");
      if (resp && resp.ok) chip.result(resp.result);
      else chip.error((resp && resp.error) || "Verification failed");
    });
  }

  // Hover "V" button positioned over the hovered message/post.
  if (adapter) {
    const btnHost = document.createElement("nemesis-hover");
    btnHost.style.cssText = "position:fixed;z-index:2147483646;display:none;";
    const btnRoot = btnHost.attachShadow({ mode: "open" });
    btnRoot.innerHTML = `<style>${BASE_CSS}
      button { width:26px; height:26px; border-radius:50%; border:1px solid rgba(255,255,255,.2); background:#FF2D2D; color:#fff;
        font-weight:800; font-size:13px; cursor:pointer; box-shadow:0 0 16px rgba(255,45,45,.55); transition: transform .15s; }
      button:hover { transform: scale(1.12); }</style>
      <button title="Verify with NemesisAI" aria-label="Verify with NemesisAI">V</button>`;
    document.documentElement.appendChild(btnHost);

    let current = null;
    let hideTimer = null;

    const place = () => {
      if (!current || !current.isConnected) return (btnHost.style.display = "none");
      const r = current.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) return (btnHost.style.display = "none");
      btnHost.style.top = `${Math.max(4, r.top + 4)}px`;
      btnHost.style.left = `${Math.min(innerWidth - 34, r.right - 32)}px`;
      btnHost.style.display = "block";
    };

    document.addEventListener(
      "mouseover",
      (e) => {
        if (btnHost.contains(e.target)) return clearTimeout(hideTimer);
        const c = adapter.container(e.target);
        if (c) {
          clearTimeout(hideTimer);
          current = c;
          place();
        } else {
          clearTimeout(hideTimer);
          hideTimer = setTimeout(() => (btnHost.style.display = "none"), 500);
        }
      },
      true
    );
    btnHost.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    document.addEventListener("scroll", place, true);
    btnRoot.querySelector("button").addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (current) verifyInline(current);
    });
  }

  // Remember what was right-clicked so the context menu can verify that message.
  const anchors = new Map();
  let lastContextTarget = null;
  document.addEventListener("contextmenu", (e) => (lastContextTarget = e.target), true);

  // ── Messages from the service worker ──────────────────────────────
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    switch (msg.type) {
      case "NEMESIS_GET_SELECTION":
        sendResponse({ text: String(window.getSelection() || "") });
        return false;
      case "NEMESIS_GET_CONTEXT_TARGET": {
        const container = adapter && lastContextTarget ? adapter.container(lastContextTarget) : null;
        if (!container) {
          sendResponse(null);
          return false;
        }
        const anchor = `a${Date.now()}`;
        anchors.set(anchor, container);
        sendResponse({ text: cleanText(adapter.text(container)), anchor });
        return false;
      }
      case "NEMESIS_PENDING":
        if (msg.anchor && anchors.has(msg.anchor)) inlineChip(anchors.get(msg.anchor)).pending();
        else showPending();
        sendResponse(true);
        return false;
      case "NEMESIS_RESULT":
        if (msg.anchor && anchors.has(msg.anchor)) {
          inlineChip(anchors.get(msg.anchor)).result(msg.result);
          anchors.delete(msg.anchor);
        } else showResult(msg.result);
        sendResponse(true);
        return false;
      case "NEMESIS_ERROR":
        if (msg.anchor && anchors.has(msg.anchor)) {
          inlineChip(anchors.get(msg.anchor)).error(msg.message);
          anchors.delete(msg.anchor);
        } else showError(msg.message);
        sendResponse(true);
        return false;
      default:
        return false;
    }
  });
})();
