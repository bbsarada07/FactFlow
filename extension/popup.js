const DEFAULT_SITE = "https://factflow-2.onrender.com";

async function site() {
  const { siteUrl } = await chrome.storage.sync.get({ siteUrl: DEFAULT_SITE });
  return siteUrl;
}
const COLORS = { FALSE: "#FF2D2D", TRUE: "#00E676", MISLEADING: "#FF6B00", UNVERIFIED: "#8888A0", SATIRE: "#B04FD0" };

function ago(ts) {
  const s = (Date.now() - ts) / 1000;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

async function renderHistory() {
  const { history = [] } = await chrome.storage.local.get("history");
  const list = document.getElementById("history");
  list.textContent = "";
  if (!history.length) {
    const li = document.createElement("div");
    li.className = "empty";
    li.textContent = "No verifications yet. Select text on any page and right-click.";
    list.appendChild(li);
    return;
  }
  for (const h of history) {
    const li = document.createElement("li");
    li.title = h.summary || h.claim;
    const badge = document.createElement("span");
    badge.className = "verdict";
    badge.textContent = h.verdict;
    badge.style.background = COLORS[h.verdict] || COLORS.UNVERIFIED;
    if (h.verdict === "TRUE") badge.style.color = "#04140b";
    const claim = document.createElement("span");
    claim.className = "claim";
    claim.textContent = h.claim;
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = ago(h.at);
    li.append(badge, claim, time);
    li.addEventListener("click", async () => chrome.tabs.create({ url: `${await site()}/tracker` }));
    list.appendChild(li);
  }
}

async function checkBackend() {
  const dot = document.getElementById("dot");
  const label = document.getElementById("status");
  const { token } = await chrome.storage.local.get("token");
  if (!token) {
    dot.className = "dot off";
    label.textContent = "NOT CONNECTED";
    label.title = "Open FactFlow, go to Settings, and click Connect under Browser extension.";
    return;
  }
  try {
    const r = await fetch(`${await site()}/health`, { cache: "no-store" });
    const ok = r.ok;
    dot.className = `dot ${ok ? "on" : "off"}`;
    label.textContent = ok ? "CONNECTED" : "DEGRADED";
  } catch {
    dot.className = "dot off";
    label.textContent = "OFFLINE";
  }
}

document.getElementById("verify").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "FACTFLOW_VERIFY_ACTIVE_SELECTION" });
  window.close();
});

document.getElementById("dashboard").addEventListener("click", async () => {
  const { token } = await chrome.storage.local.get("token");
  chrome.tabs.create({ url: `${await site()}${token ? "/" : "/settings"}` });
});

chrome.storage.onChanged.addListener((changes) => changes.history && renderHistory());
renderHistory();
checkBackend();
