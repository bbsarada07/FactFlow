// Runs only on the FactFlow website (see "matches" in manifest.json), never on other pages.
// Settings → Browser extension → Connect posts a personal token to this page; we hand it to the service worker,
// which stores it. Because this script exists only on the FactFlow site, no other website can connect the
// extension to a different account.
(() => {
  document.documentElement.dataset.factflowExtension = "1";

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.type !== "FACTFLOW_CONNECT_EXTENSION" || typeof data.token !== "string" || !data.token.startsWith("ffx_")) return;
    chrome.runtime.sendMessage({ type: "FACTFLOW_SET_TOKEN", token: data.token }, (reply) => {
      if (reply && reply.ok) window.postMessage({ type: "FACTFLOW_EXTENSION_CONNECTED" }, window.location.origin);
    });
  });
})();
