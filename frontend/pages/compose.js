import { AlertTriangle, CheckCircle2, Paperclip, PenLine, Send, ShieldCheck } from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import OutgoingQueue from "@/components/agent/OutgoingQueue";
import { checkCompose, getMailStatus, listMyFiles, sendCompose } from "@/lib/api";

const KIND_LABEL = {
  financial: "Bank or ID number",
  secret: "Password or secret",
  lookalike_recipient: "Lookalike address",
  brand_lookalike: "Imitates a brand",
  false_claim: "Possibly false claim",
};

export default function ComposePage() {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [fileIds, setFileIds] = useState([]);
  const [files, setFiles] = useState([]);
  const [gmail, setGmail] = useState(null);
  const [check, setCheck] = useState(null); // {findings, ok} for the current text
  const [busy, setBusy] = useState(null);
  const [queuedAt, setQueuedAt] = useState(0);
  const [factCheck, setFactCheck] = useState(false);

  useEffect(() => {
    listMyFiles().then((r) => setFiles(r.items || [])).catch(() => {});
    getMailStatus().then((m) => setGmail(m.gmail)).catch(() => {});
  }, []);

  useEffect(() => setCheck(null), [to, subject, body, fileIds, factCheck]); // any edit needs a fresh check

  const message = { to, subject, body, file_ids: fileIds, fact_check: factCheck };

  const runCheck = async () => {
    setBusy("check");
    try {
      setCheck(await checkCompose(message));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(null);
    }
  };

  const send = async (confirm) => {
    setBusy("send");
    try {
      await sendCompose({ ...message, confirm });
      toast.success("Queued. It leaves your Gmail in a couple of minutes; you can undo it below.");
      setTo("");
      setSubject("");
      setBody("");
      setFileIds([]);
      setCheck(null);
      setQueuedAt(Date.now());
    } catch (err) {
      if (err.status === 409 && err.data?.findings) setCheck(err.data);
      else toast.error(err.message);
    } finally {
      setBusy(null);
    }
  };

  const canSend = gmail?.can_send;
  const ready = to.includes("@") && (subject.trim() || body.trim());

  return (
    <>
      <Head>
        <title>Write an email — FactFlow</title>
      </Head>
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="mono mb-2 text-[11px] tracking-[3px] text-red">MAIL</div>
        <h1 className="m-0 flex items-center gap-2 font-display text-[30px] font-bold text-primary">
          <PenLine size={24} className="text-red" /> Write an email
        </h1>
        <p className="mt-2 text-[15px] text-secondary">
          FactFlow checks it before it goes: bank and ID numbers, OTPs, passwords and keys, lookalike addresses and false
          claims. It is sent from your Gmail and can be undone for a couple of minutes.
        </p>

        {gmail && !canSend && (
          <div className="mt-5 rounded-md border p-4 text-[13.5px] text-secondary" style={{ borderColor: "rgba(255,107,0,0.45)" }}>
            {gmail.status === "connected"
              ? "Your Gmail is connected with read access only. "
              : "Your Gmail is not connected. "}
            <Link href="/settings" className="text-primary underline">Connect it in Settings</Link> to send from FactFlow. You can
            still check a message here.
          </div>
        )}

        <div key={queuedAt} className="mt-6 space-y-3 rounded-lg border border-subtle bg-card p-5">
          <label className="block">
            <span className="mono text-[11px] tracking-[1px] text-muted">TO</span>
            <input value={to} onChange={(e) => setTo(e.target.value)} type="email" autoComplete="email" placeholder="name@company.com"
              className="mt-1 w-full rounded-md border border-subtle bg-surface px-3 py-2 text-[14px] text-primary focus:border-active focus:outline-none" />
          </label>
          <label className="block">
            <span className="mono text-[11px] tracking-[1px] text-muted">SUBJECT</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)}
              className="mt-1 w-full rounded-md border border-subtle bg-surface px-3 py-2 text-[14px] text-primary focus:border-active focus:outline-none" />
          </label>
          <label className="block">
            <span className="mono text-[11px] tracking-[1px] text-muted">MESSAGE</span>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={9}
              className="mt-1 w-full resize-y rounded-md border border-subtle bg-surface px-3 py-2 text-[14px] leading-relaxed text-primary focus:border-active focus:outline-none" />
          </label>
          {files.length > 0 && (
            <div>
              <span className="mono text-[11px] tracking-[1px] text-muted">ATTACH FROM MY FILES</span>
              <div className="mt-1 flex flex-wrap gap-2">
                {files.map((f) => {
                  const on = fileIds.includes(f.id);
                  return (
                    <button key={f.id} type="button" aria-pressed={on}
                      onClick={() => setFileIds((ids) => (on ? ids.filter((x) => x !== f.id) : [...ids, f.id].slice(0, 5)))}
                      className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px]"
                      style={on ? { borderColor: "#FF2D2D", background: "rgba(255,45,45,0.1)", color: "#F0F0F5" } : { borderColor: "#2A2A3A", color: "#8888A0" }}>
                      <Paperclip size={12} /> {f.filename}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {check && (
            <div role="status" className="rounded-md border p-4"
              style={check.findings?.length ? { borderColor: "rgba(255,107,0,0.5)", background: "rgba(255,107,0,0.06)" } : { borderColor: "rgba(0,230,118,0.45)" }}>
              {check.findings?.length ? (
                <>
                  <div className="flex items-center gap-2 text-[14px] font-semibold text-primary">
                    <AlertTriangle size={16} className="text-orange" /> Check before sending
                  </div>
                  <ul className="mb-0 mt-2 space-y-1 pl-0">
                    {check.findings.map((f) => (
                      <li key={f.message} className="list-none text-[13.5px] text-secondary">
                        <span className="mono mr-2 text-[10.5px] text-orange">{KIND_LABEL[f.kind] || f.kind}</span>
                        {f.message}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <div className="flex items-center gap-2 text-[14px] text-primary">
                  <CheckCircle2 size={16} className="text-green" /> Nothing risky found.
                </div>
              )}
            </div>
          )}

          <label className="flex items-center gap-2 text-[13px] text-secondary">
            <input type="checkbox" checked={factCheck} onChange={(e) => setFactCheck(e.target.checked)} className="h-4 w-4 accent-[#FF2D2D]" />
            Also fact-check claims in this message (takes up to a minute)
          </label>
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="button" disabled={!ready || busy} onClick={runCheck} className="btn-ghost !py-2 !px-4 !text-[13px]">
              <ShieldCheck size={14} /> {busy === "check" ? "Checking…" : "Check"}
            </button>
            {check?.findings?.length ? (
              <button type="button" disabled={!canSend || busy} onClick={() => send(true)} className="btn-red !py-2 !px-4 !text-[13px]">
                <Send size={14} /> Send anyway
              </button>
            ) : (
              <button type="button" disabled={!canSend || !ready || busy} onClick={() => send(false)} className="btn-red !py-2 !px-4 !text-[13px]">
                <Send size={14} /> {busy === "send" ? "Checking…" : "Check and send"}
              </button>
            )}
          </div>
        </div>

        <div className="mt-6">
          <OutgoingQueue limit={6} />
        </div>
      </div>
    </>
  );
}
