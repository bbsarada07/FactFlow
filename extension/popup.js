const API_URL = "http://localhost:8000";
const DASHBOARD_URL = "http://localhost:3000";
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
    li.addEventListener("click", () => chrome.tabs.create({ url: `${DASHBOARD_URL}/tracker` }));
    list.appendChild(li);
  }
}

async function checkBackend() {
  const dot = document.getElementById("dot");
  const label = document.getElementById("status");
  try {
    const r = await fetch(`${API_URL}/health`, { cache: "no-store" });
    const ok = r.ok;
    dot.className = `dot ${ok ? "on" : "off"}`;
    label.textContent = ok ? "ONLINE" : "DEGRADED";
  } catch {
    dot.className = "dot off";
    label.textContent = "OFFLINE";
  }
}

document.getElementById("verify").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "NEMESIS_VERIFY_ACTIVE_SELECTION" });
  window.close();
});

document.getElementById("dashboard").addEventListener("click", () => {
  chrome.tabs.create({ url: DASHBOARD_URL });
});

chrome.storage.onChanged.addListener((changes) => changes.history && renderHistory());
renderHistory();
checkBackend();
