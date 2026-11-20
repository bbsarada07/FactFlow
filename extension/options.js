// Options page: shows whether this browser's extension is connected to a FactFlow account, and disconnects it.
// Connecting happens on the FactFlow website (Settings -> Browser extension -> Connect), never by pasting a token.
const DEFAULT_SITE = "https://factflow-2.onrender.com";

async function render() {
  const [{ token }, { siteUrl }] = await Promise.all([
    chrome.storage.local.get("token"),
    chrome.storage.sync.get({ siteUrl: DEFAULT_SITE }),
  ]);
  document.getElementById("dot").className = `dot ${token ? "on" : ""}`;
  document.getElementById("state").textContent = token ? `Connected to your account on ${siteUrl}` : "Not connected";
  document.getElementById("help").textContent = token
    ? "Checks you start from this browser are saved in your FactFlow account. Disconnecting here removes the token from this browser; to revoke it everywhere, use Settings on the website."
    : "Open FactFlow, sign in, go to Settings and click Connect under Browser extension.";
  document.getElementById("open").href = `${siteUrl}/settings`;
  document.getElementById("disconnect").hidden = !token;
}

document.getElementById("disconnect").addEventListener("click", async () => {
  await chrome.storage.local.remove("token");
  render();
});
chrome.storage.onChanged.addListener(render);
render();
