// Options page: stores the FactFlow API base URL in chrome.storage.sync under "apiBase".
const DEFAULT_API_BASE = "http://localhost:8000";

const input = document.getElementById("apiBase");
const status = document.getElementById("status");

/** Load the saved API base URL (or the dev default) into the input. */
async function load() {
  const { apiBase } = await chrome.storage.sync.get({ apiBase: DEFAULT_API_BASE });
  input.value = apiBase;
}

/** Validate and save the API base URL. */
async function save() {
  const value = input.value.trim().replace(/\/+$/, "") || DEFAULT_API_BASE;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error();
  } catch {
    status.textContent = "Enter a valid http(s) URL, e.g. http://localhost:8000";
    status.style.color = "#FF6B6B";
    return;
  }
  await chrome.storage.sync.set({ apiBase: value });
  input.value = value;
  status.textContent = `Saved: ${value}`;
  status.style.color = "#00E676";
}

document.getElementById("save").addEventListener("click", save);
input.addEventListener("keydown", (e) => e.key === "Enter" && save());
load();
