// FactFlow service worker: context menus, keyboard shortcut, API calls and history.

const API_URL = "http://localhost:8000";
const POLL_MS = 2000;
const TIMEOUT_MS = 180000;
const SOCIAL_PATTERNS = [
  "https://web.whatsapp.com/*",
  "https://x.com/*",
  "https://twitter.com/*",
  "https://www.instagram.com/*",
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "factflow-verify",
      title: "🔍 Verify with FactFlow",
      contexts: ["selection", "image"],
    });
    chrome.contextMenus.create({
      id: "factflow-verify-message",
      title: "🔍 Verify this message with FactFlow",
      contexts: ["page", "link"],
      documentUrlPatterns: SOCIAL_PATTERNS,
    });
  });
});

function platformFor(url) {
  try {
    const host = new URL(url).hostname;
    if (host === "web.whatsapp.com") return "whatsapp";
    if (host === "x.com" || host === "twitter.com" || host.endsWith(".twitter.com")) return "twitter";
    if (host.endsWith("instagram.com")) return "instagram";
    if (host.endsWith("facebook.com")) return "facebook";
    if (host.endsWith("youtube.com")) return "youtube";
  } catch (_) {
    /* non-http page */
  }
  return "extension";
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function verify(payload) {
  const res = await fetch(`${API_URL}/api/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);

  const started = Date.now();
  while (Date.now() - started < TIMEOUT_MS) {
    await sleep(POLL_MS);
    const r = await fetch(`${API_URL}/api/result/${body.request_id}`);
    if (r.status === 200) {
      const result = await r.json();
      if (result.status === "failed") throw new Error(result.error || "Verification failed");
      return result;
    }
    if (r.status !== 202) throw new Error(`Result lookup failed (${r.status})`);
  }
  throw new Error("Verification timed out");
}

function compact(result) {
  return {
    request_id: result.request_id,
    verdict: result.verdict,
    confidence: result.confidence,
    claim: result.claim,
    summary: result.summary,
    fact: result.fact,
    whatsapp_reply: result.whatsapp_reply,
    harm_type: result.harm_type,
    harm_level: result.harm_level,
    at: Date.now(),
  };
}

async function remember(item) {
  const { history = [] } = await chrome.storage.local.get("history");
  await chrome.storage.local.set({ history: [item, ...history].slice(0, 5) });
}

async function sendToTab(tabId, message) {
  try {
    await chrome.tabs.sendMessage(tabId, message);
    return true;
  } catch (_) {
    return false; // no content script (chrome:// pages, Web Store, PDF viewer)
  }
}

function notify(title, message) {
  chrome.notifications.create({ type: "basic", iconUrl: "icon128.png", title, message: message.slice(0, 250) });
}

/** Verify and show the floating badge (or an OS notification when the page can't host one). */
async function verifyForTab(tab, payload, anchor = null) {
  const shown = await sendToTab(tab.id, { type: "FACTFLOW_PENDING", anchor });
  try {
    const result = compact(await verify({ ...payload, platform: platformFor(tab.url) }));
    await remember(result);
    if (!(await sendToTab(tab.id, { type: "FACTFLOW_RESULT", result, anchor })) || !shown) {
      notify(`FactFlow: ${result.verdict} (${Math.round((result.confidence || 0) * 100)}%)`, result.summary || result.claim);
    }
  } catch (err) {
    if (!(await sendToTab(tab.id, { type: "FACTFLOW_ERROR", message: err.message, anchor }))) {
      notify("FactFlow could not verify this", err.message);
    }
  }
}

async function verifySelectionInTab(tab) {
  let text = "";
  try {
    const r = await chrome.tabs.sendMessage(tab.id, { type: "FACTFLOW_GET_SELECTION" });
    text = (r && r.text) || "";
  } catch (_) {
    /* page without content script */
  }
  if (text.trim().length < 8) {
    await sendToTab(tab.id, { type: "FACTFLOW_ERROR", message: "Select some text to verify first." });
    return;
  }
  await verifyForTab(tab, { text: text.trim().slice(0, 5000) });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!tab || tab.id == null) return;

  if (info.menuItemId === "factflow-verify") {
    if (info.mediaType === "image" && info.srcUrl && /^https?:/.test(info.srcUrl)) {
      await verifyForTab(tab, { image_url: info.srcUrl, text: (info.selectionText || "").slice(0, 5000) });
    } else if (info.selectionText) {
      await verifyForTab(tab, { text: info.selectionText.slice(0, 5000) });
    }
    return;
  }

  if (info.menuItemId === "factflow-verify-message") {
    // Ask the content script for the message/post under the cursor when the menu opened.
    let target = null;
    try {
      target = await chrome.tabs.sendMessage(tab.id, { type: "FACTFLOW_GET_CONTEXT_TARGET" });
    } catch (_) {
      /* ignore */
    }
    if (!target || !target.text) {
      await sendToTab(tab.id, { type: "FACTFLOW_ERROR", message: "Couldn't find a message here. Select its text and try again." });
      return;
    }
    await verifyForTab(tab, { text: target.text }, target.anchor);
  }
});

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command !== "verify-selection") return;
  const active = tab || (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
  if (active) await verifySelectionInTab(active);
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // Inline hover button on WhatsApp / X / Instagram.
  if (msg.type === "FACTFLOW_VERIFY_TEXT") {
    verify({ text: msg.text.slice(0, 5000), platform: msg.platform || platformFor(sender.tab && sender.tab.url) })
      .then(async (r) => {
        const result = compact(r);
        await remember(result);
        sendResponse({ ok: true, result });
      })
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }

  // Popup "Verify Selected Text".
  if (msg.type === "FACTFLOW_VERIFY_ACTIVE_SELECTION") {
    chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
      if (tab) verifySelectionInTab(tab);
      sendResponse({ ok: !!tab });
    });
    return true;
  }
  return false;
});
