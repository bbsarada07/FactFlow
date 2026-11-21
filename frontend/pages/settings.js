import {
  Bot, CheckCircle2, Chrome, FileText, Inbox, LogOut, Mail, MessageCircle, RefreshCw, Shield, Trash2, Upload, UserRound,
} from "lucide-react";
import Head from "next/head";
import { useRouter } from "next/router";
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import {
  connectGmail,
  createExtensionToken,
  deleteAccount,
  deleteMyFile,
  disconnectGmail,
  getAgentSettings,
  listMyFiles,
  setAgentSettings,
  updateMyFile,
  uploadMyFile,
  getMailStatus,
  getPolicy,
  getWhatsAppLink,
  listExtensionTokens,
  newWhatsAppCode,
  revokeExtensionToken,
  setMailProvider,
  setPolicyMode,
  signOutEverywhere,
  syncMail,
  unlinkWhatsApp,
} from "@/lib/api";
import { signOut, useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/theme";

const GMAIL_ERRORS = {
  denied: "You cancelled the Google consent screen.",
  missing_code: "Google did not send a code back. Try again.",
  scope_not_allowed: "Google granted more access than FactFlow accepts, so it was refused and revoked.",
  address_taken: "That Gmail address is already connected to another FactFlow account.",
  not_configured: "Gmail is not set up on the server yet.",
  google_unreachable: "Google could not be reached. Try again in a moment.",
  auth_failed: "The connection request expired or was already used. Start again.",
};

function Section({ icon: Icon, title, children, aside }) {
  return (
    <section className="rounded-lg border border-subtle bg-card p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="m-0 flex items-center gap-2 font-display text-[18px] font-semibold text-primary">
          <Icon size={18} className="text-red" /> {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Status({ ok, children }) {
  return (
    <span
      className="mono inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]"
      style={{ borderColor: ok ? "rgba(0,230,118,0.45)" : "#2A2A3A", color: ok ? "#00E676" : "#8888A0" }}
    >
      {ok && <CheckCircle2 size={11} />} {children}
    </span>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [mail, setMail] = useState(null);
  const [policy, setPolicy] = useState(null);
  const [tokens, setTokens] = useState([]);
  const [whatsapp, setWhatsapp] = useState(null);
  const [code, setCode] = useState(null);
  const [extensionPresent, setExtensionPresent] = useState(false);
  const [busy, setBusy] = useState(null);
  const [agent, setAgent] = useState(null);
  const [myFiles, setMyFiles] = useState([]);

  const load = useCallback(async () => {
    const results = await Promise.allSettled([getMailStatus(), getPolicy(), listExtensionTokens(), getWhatsAppLink(),
      getAgentSettings(), listMyFiles()]);
    const [m, p, t, w, a, f] = results.map((r) => (r.status === "fulfilled" ? r.value : null));
    setMail(m);
    setPolicy(p);
    setTokens(t?.items || []);
    setWhatsapp(w);
    setAgent(a);
    setMyFiles(f?.items || []);
    const failed = results.find((r) => r.status === "rejected");
    if (failed) toast.error(failed.reason?.message || "Some settings could not be loaded.");
  }, []);

  useEffect(() => {
    load();
    setExtensionPresent(document.documentElement.dataset.factflowExtension === "1");
    const onConnected = (e) => {
      if (e.source === window && e.data?.type === "FACTFLOW_EXTENSION_CONNECTED") toast.success("Browser extension connected.");
    };
    window.addEventListener("message", onConnected);
    return () => window.removeEventListener("message", onConnected);
  }, [load]);

  // Coming back from Google's Gmail consent screen
  useEffect(() => {
    const { gmail, reason } = router.query;
    if (!gmail) return;
    if (gmail === "connected") toast.success("Gmail connected. Your agent will check new mail automatically.");
    else toast.error(GMAIL_ERRORS[reason] || "Gmail could not be connected.");
    router.replace("/settings", undefined, { shallow: true });
  }, [router]);

  const run = async (key, fn, success) => {
    setBusy(key);
    try {
      const out = await fn();
      if (success) toast.success(success);
      await load();
      return out;
    } catch (err) {
      toast.error(err.message);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const startGmail = async () => {
    setBusy("gmail");
    try {
      const { auth_url: url } = await connectGmail();
      window.location.assign(url);
    } catch (err) {
      toast.error(err.message);
      setBusy(null);
    }
  };

  const changeMode = (mode) => {
    if (mode === policy?.mode) return;
    if (mode === "balanced" && !window.confirm("Balanced mode lets your agent do more on its own. Switch to balanced?")) return;
    run("policy", () => setPolicyMode(mode, mode === "balanced"), `Policy set to ${mode}.`);
  };

  const connectExtension = () =>
    run("extension", async () => {
      const made = await createExtensionToken("Browser extension");
      // Handed straight to the FactFlow extension's content script on this page; never shown or copied.
      window.postMessage({ type: "FACTFLOW_CONNECT_EXTENSION", token: made.token, site: window.location.origin }, window.location.origin);
      return made;
    });

  const onUpload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      toast.error("Files can be at most 10 MB.");
      return;
    }
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    await run("upload", () => uploadMyFile({ filename: file.name, content_type: file.type || "application/octet-stream",
      data_base64: data, shareable: false }), `${file.name} added. Mark it "OK to send" if your agent may send it.`);
  };

  const removeAccount = async () => {
    if (!window.confirm("Delete your FactFlow account? Gmail access is revoked and all your checks, mail history, files and settings are deleted. This cannot be undone.")) return;
    try {
      await deleteAccount();
      window.location.assign("/login?signed_out=1");
    } catch (err) {
      toast.error(err.message);
    }
  };

  const gmail = mail?.gmail;
  const gmailConnected = gmail?.status === "connected";

  return (
    <>
      <Head>
        <title>Agent settings — FactFlow</title>
      </Head>
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-8">
          <div className="mono mb-2 text-[11px] tracking-[3px] text-red">YOUR AGENT</div>
          <h1 className="m-0 font-display text-[32px] font-bold tracking-tight text-primary">Settings</h1>
          <p className="mt-2 text-[15px] text-secondary">
            Everything here belongs to your account only. Nobody else can see your checks, your mail or your settings.
          </p>
        </div>

        <div className="space-y-5">
          <Section icon={UserRound} title="Account">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                {user?.picture_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={user.picture_url} alt="" referrerPolicy="no-referrer" className="h-11 w-11 rounded-full" />
                )}
                <div>
                  <div className="text-[15px] font-semibold text-primary">{user?.name || user?.email}</div>
                  <div className="text-[13px] text-secondary">
                    {user?.email} {user?.role === "admin" && <Status ok>ADMIN</Status>}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={signOut} className="btn-ghost !py-2 !text-[13px]">
                  <LogOut size={14} /> Sign out
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!window.confirm("Sign out on every device and browser?")) return;
                    await run("everywhere", signOutEverywhere);
                    window.location.assign("/login?signed_out=1");
                  }}
                  className="btn-ghost !py-2 !text-[13px]"
                >
                  Sign out everywhere
                </button>
              </div>
            </div>
          </Section>

          <Section
            icon={Mail}
            title="Gmail"
            aside={gmail ? <Status ok={gmailConnected}>{gmailConnected ? "CONNECTED" : gmail.status.replace("_", " ").toUpperCase()}</Status> : null}
          >
            {gmailConnected ? (
              <>
                <p className="m-0 text-[14px] text-secondary">
                  Your agent reads <span className="text-primary">{gmail.email_address}</span> and checks each new email
                  {mail?.poll_enabled ? ` about every ${Math.round(mail.poll_seconds)} seconds` : ""}.
                  {gmail.last_sync_at ? ` Last checked ${timeAgo(gmail.last_sync_at)}.` : ""}
                </p>
                {gmail.last_error && <p className="mt-2 text-[13px] text-orange">Last problem: {gmail.last_error}</p>}
                {gmail.needs_upgrade && (
                  <div className="mt-3 rounded-md border p-3 text-[13px] text-secondary" style={{ borderColor: "rgba(255,107,0,0.45)" }}>
                    Gmail is connected with read access only, so your agent cannot reply, send files or quarantine yet.
                    <button type="button" onClick={startGmail} className="btn-red ml-2 mt-2 !py-1.5 !px-3 !text-[12px] sm:mt-0">
                      Reconnect to allow replies and labels
                    </button>
                  </div>
                )}
                <p className="mt-3 text-[12.5px] text-muted">
                  FactFlow can read, label, archive and send from this Gmail. It never deletes mail.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button type="button" disabled={busy === "sync"} onClick={() => run("sync", syncMail, "Checked for new mail.")} className="btn-ghost !py-2 !text-[13px]">
                    <RefreshCw size={14} className={busy === "sync" ? "animate-spin" : ""} /> Check now
                  </button>
                  <button
                    type="button"
                    disabled={busy === "gmail-off"}
                    onClick={() => window.confirm("Disconnect Gmail? FactFlow revokes its access at Google and deletes the stored token.") && run("gmail-off", disconnectGmail, "Gmail disconnected.")}
                    className="btn-ghost !py-2 !text-[13px]"
                  >
                    Disconnect
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="m-0 text-[14px] text-secondary">
                  {gmail?.reconnect_required
                    ? "Google ended FactFlow's access (in testing mode this happens about once a week). Reconnect to keep your agent working."
                    : "Connect your Gmail and your agent checks every new email for hidden instructions, scams, spoofed senders and false claims. Anything risky waits for you."}
                </p>
                <button type="button" disabled={busy === "gmail" || gmail?.configured === false} onClick={startGmail} className="btn-red mt-4 !py-2 !px-5 !text-[13px]">
                  <Mail size={14} /> {gmail?.reconnect_required ? "Reconnect Gmail" : "Connect Gmail"}
                </button>
                {gmail?.configured === false && <p className="mt-2 text-[12.5px] text-muted">Gmail is not set up on this server yet.</p>}
              </>
            )}
            {mail && (
              <div className="mt-5 border-t border-subtle pt-4">
                <div className="mb-2 flex items-center gap-2 text-[13px] text-secondary">
                  <Inbox size={14} /> Which inbox your agent reads
                </div>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Inbox">
                  {[
                    ["auto", "Gmail when connected"],
                    ["gmail", "Gmail only"],
                    ["eml", "Demo inbox"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={mail.provider_setting === value}
                      onClick={() => mail.provider_setting !== value && run("provider", () => setMailProvider(value))}
                      className="rounded-full border px-3.5 py-1.5 text-[12.5px] transition-colors"
                      style={mail.provider_setting === value ? { borderColor: "#FF2D2D", background: "rgba(255,45,45,0.1)", color: "#F0F0F5" } : { borderColor: "#2A2A3A", color: "#8888A0" }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Section>

          <Section icon={Bot} title="What your agent does on its own" aside={agent ? <Status ok>{agent.autonomy.toUpperCase()}</Status> : null}>
            {agent && (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    ["auto", "Automatic", "Answers routine mail from people you write to and sends files you marked OK, with a couple of minutes to undo. Everything else asks you."],
                    ["drafts", "Drafts only", "Writes the replies but never sends one until you approve it."],
                    ["off", "Off", "Only reads, checks, labels and quarantines. Never writes back."],
                  ].map(([value, label, text]) => (
                    <button key={value} type="button" disabled={busy === "agent"} aria-pressed={agent.autonomy === value}
                      onClick={() => agent.autonomy !== value && run("agent", () => setAgentSettings({ autonomy: value }), `Your agent is now: ${label}.`)}
                      className="rounded-md border p-4 text-left transition-colors"
                      style={agent.autonomy === value ? { borderColor: "#FF2D2D", background: "rgba(255,45,45,0.08)" } : { borderColor: "#2A2A3A" }}>
                      <div className="font-display text-[15px] font-semibold text-primary">{label}</div>
                      <div className="mt-1 text-[12.5px] leading-relaxed text-secondary">{text}</div>
                    </button>
                  ))}
                </div>
                <label className="mt-4 flex items-center gap-3 text-[13.5px] text-secondary">
                  <input type="checkbox" checked={agent.digest_enabled} disabled={busy === "agent"}
                    onChange={(e) => run("agent", () => setAgentSettings({ digest_enabled: e.target.checked }))} className="h-4 w-4 accent-[#FF2D2D]" />
                  Email me a daily digest of what my agent did
                </label>
                <p className="mt-3 text-[12.5px] text-muted">
                  Money, passwords, ID numbers, unknown senders, hidden instructions and anything unusual always wait for you,
                  whatever you choose here.
                </p>
              </>
            )}
          </Section>

          <Section icon={FileText} title="My files" aside={<Status ok={myFiles.some((f) => f.shareable)}>{myFiles.length} FILE{myFiles.length === 1 ? "" : "S"}</Status>}>
            <p className="m-0 text-[14px] text-secondary">
              When a teammate asks for one of these by email, your agent can send it, but only if you marked it OK to send, the
              sender is verified and exactly one file matches. Otherwise it asks you. Up to 10 MB each.
            </p>
            <label className="btn-ghost mt-4 inline-flex cursor-pointer !py-2 !text-[13px]">
              <Upload size={14} /> {busy === "upload" ? "Uploading…" : "Add a file"}
              <input type="file" className="sr-only" onChange={onUpload} disabled={busy === "upload"} />
            </label>
            {myFiles.length > 0 && (
              <ul className="mt-4 divide-y divide-subtle rounded-md border border-subtle">
                {myFiles.map((f) => (
                  <li key={f.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5 text-[13px]">
                    <span className="min-w-0 truncate text-primary">{f.filename} <span className="text-muted">· {Math.max(1, Math.round(f.size / 1024))} KB</span></span>
                    <span className="flex items-center gap-3">
                      <label className="flex items-center gap-2 text-secondary">
                        <input type="checkbox" checked={f.shareable} onChange={(e) => run(`f-${f.id}`, () => updateMyFile(f.id, { shareable: e.target.checked }))}
                          className="h-4 w-4 accent-[#FF2D2D]" />
                        OK to send
                      </label>
                      <button type="button" onClick={() => window.confirm(`Delete ${f.filename}?`) && run(`fd-${f.id}`, () => deleteMyFile(f.id), "File deleted.")}
                        className="rounded p-1.5 text-secondary hover:bg-hover hover:text-primary" aria-label={`Delete ${f.filename}`}>
                        <Trash2 size={14} />
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section icon={Shield} title="Safety rules" aside={policy ? <Status ok>{policy.mode.toUpperCase()}</Status> : null}>
            {policy && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  {[
                    ["strict", "Strict", "Anything with a warning sign waits for you. Only reading, notes and protective steps run on their own."],
                    ["balanced", "Balanced", "Routine steps on safe mail run on their own. Money, new recipients and suspicious mail still wait for you."],
                  ].map(([value, label, text]) => (
                    <button
                      key={value}
                      type="button"
                      disabled={busy === "policy"}
                      onClick={() => changeMode(value)}
                      className="rounded-md border p-4 text-left transition-colors"
                      style={policy.mode === value ? { borderColor: "#FF2D2D", background: "rgba(255,45,45,0.08)" } : { borderColor: "#2A2A3A" }}
                      aria-pressed={policy.mode === value}
                    >
                      <div className="font-display text-[15px] font-semibold text-primary">{label}</div>
                      <div className="mt-1 text-[13px] leading-relaxed text-secondary">{text}</div>
                    </button>
                  ))}
                </div>
                <p className="mt-3 text-[12.5px] text-muted">
                  In both modes, instructions hidden inside an email are never carried out, and data never leaves for unknown sites.
                  {policy.allowed_domains?.length ? ` Trusted recipient domains: ${policy.allowed_domains.join(", ")}.` : ""}
                </p>
              </>
            )}
          </Section>

          <Section icon={Chrome} title="Browser extension" aside={<Status ok={tokens.length > 0}>{tokens.length ? "CONNECTED" : "NOT CONNECTED"}</Status>}>
            <p className="m-0 text-[14px] text-secondary">
              Select text on any page, including WhatsApp Web, right-click <span className="text-primary">Verify with FactFlow</span>, and the
              check lands in your account.
            </p>
            {extensionPresent ? (
              <button type="button" disabled={busy === "extension"} onClick={connectExtension} className="btn-red mt-4 !py-2 !px-5 !text-[13px]">
                <Chrome size={14} /> {tokens.length ? "Connect again" : "Connect this browser's extension"}
              </button>
            ) : (
              <p className="mt-3 rounded-md border border-subtle bg-surface p-3 text-[13px] text-secondary">
                The FactFlow extension is not installed in this browser. Load the <span className="mono">extension</span> folder from the
                FactFlow repository (chrome://extensions → Developer mode → Load unpacked), then reload this page.
              </p>
            )}
            {tokens.length > 0 && (
              <ul className="mt-4 divide-y divide-subtle rounded-md border border-subtle">
                {tokens.map((t) => (
                  <li key={t.id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-[13px]">
                    <span className="text-secondary">
                      <span className="mono text-primary">{t.prefix}…</span> · connected {timeAgo(t.created_at)}
                      {t.last_used_at ? ` · last used ${timeAgo(t.last_used_at)}` : ""}
                    </span>
                    <button type="button" onClick={() => run(`rev-${t.id}`, () => revokeExtensionToken(t.id), "Extension disconnected.")} className="rounded p-1.5 text-secondary hover:bg-hover hover:text-primary" aria-label="Disconnect this extension">
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section icon={MessageCircle} title="WhatsApp" aside={whatsapp ? <Status ok={whatsapp.linked_numbers > 0}>{whatsapp.linked_numbers ? "LINKED" : "NOT LINKED"}</Status> : null}>
            <p className="m-0 text-[14px] text-secondary">
              Forward any message to the FactFlow WhatsApp number and the verdict comes back in the chat. Link your number once so
              the checks are yours.
            </p>
            {code ? (
              <div className="mt-4 rounded-md border border-subtle bg-surface p-4">
                <div className="text-[13px] text-secondary">Send this message from your WhatsApp to the FactFlow number within 10 minutes:</div>
                <div className="mono mt-2 text-[24px] font-semibold tracking-[3px] text-primary">{code.message}</div>
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy === "wa"}
                onClick={async () => setCode(await run("wa", newWhatsAppCode))}
                className="btn-red !py-2 !px-5 !text-[13px]"
              >
                <MessageCircle size={14} /> {code ? "New code" : "Link WhatsApp"}
              </button>
              {whatsapp?.linked_numbers > 0 && (
                <button type="button" onClick={() => window.confirm("Unlink your WhatsApp number?") && run("wa-off", unlinkWhatsApp, "WhatsApp unlinked.")} className="btn-ghost !py-2 !text-[13px]">
                  Unlink
                </button>
              )}
            </div>
          </Section>

          <section className="rounded-lg border p-5 sm:p-6" style={{ borderColor: "rgba(255,45,45,0.35)" }}>
            <h2 className="m-0 font-display text-[16px] font-semibold text-primary">Delete my account and data</h2>
            <p className="mt-2 text-[13.5px] text-secondary">
              Revokes FactFlow&apos;s access to your Gmail and deletes your checks, mail history, files, contacts and settings.
            </p>
            <button type="button" onClick={removeAccount} className="btn-ghost mt-3 !py-2 !text-[13px]" style={{ borderColor: "rgba(255,45,45,0.5)", color: "#FF6B6B" }}>
              <Trash2 size={14} /> Delete my account
            </button>
          </section>
        </div>
      </div>
    </>
  );
}
