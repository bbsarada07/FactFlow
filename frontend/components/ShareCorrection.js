import { Check, Copy, Facebook, Instagram, Linkedin, Twitter } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";

const WHATSAPP_PATH =
  "M17.47 14.38c-.3-.15-1.75-.86-2.02-.96-.27-.1-.47-.15-.67.15-.2.3-.77.96-.94 1.16-.17.2-.35.22-.64.07-.3-.15-1.25-.46-2.38-1.47-.88-.78-1.48-1.75-1.65-2.05-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.18.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.6-.92-2.2-.24-.58-.49-.5-.67-.5h-.57c-.2 0-.52.07-.8.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.07 2.88 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.27.49 1.7.63.72.23 1.37.2 1.88.12.58-.09 1.75-.72 2-1.41.25-.7.25-1.29.17-1.41-.07-.13-.27-.2-.57-.35M12.05 21.5h-.01a9.4 9.4 0 0 1-4.8-1.32l-.34-.2-3.56.94.95-3.48-.23-.36a9.4 9.4 0 0 1-1.44-5.02c0-5.2 4.24-9.44 9.45-9.44a9.4 9.4 0 0 1 6.68 2.77 9.38 9.38 0 0 1 2.76 6.68c0 5.21-4.23 9.44-9.44 9.44M20.08 3.9A11.3 11.3 0 0 0 12.05.58C5.79.58.69 5.68.69 11.94c0 2 .52 3.96 1.52 5.68L.6 23.5l6.02-1.58a11.33 11.33 0 0 0 5.43 1.38h.01c6.26 0 11.36-5.1 11.36-11.36 0-3.03-1.18-5.89-3.33-8.03";

/** Share URLs for each platform. Pure: no server calls. Instagram has no web share link. */
export function shareLinks(text, registryUrl) {
  const t = encodeURIComponent(text);
  const u = encodeURIComponent(registryUrl || "");
  return {
    whatsapp: `https://wa.me/?text=${t}`,
    x: `https://twitter.com/intent/tweet?text=${t}`,
    facebook: `https://www.facebook.com/sharer/sharer.php?u=${u}`,
    linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${u}`,
  };
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    toast.error("Clipboard access was blocked by the browser");
    return false;
  }
}

function ShareButton({ href, onClick, label, children, color }) {
  const cls =
    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-hover";
  const style = { borderColor: `${color}55`, color };
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cls} style={style} aria-label={label}>
      {children}
    </a>
  ) : (
    <button type="button" onClick={onClick} className={cls} style={style} aria-label={label}>
      {children}
    </button>
  );
}

/**
 * Correction in place: a short sourced reply (EN / HI / TE, plus the user's own language when
 * different) with one-tap share links. Facebook and LinkedIn share the registry page URL.
 */
export default function ShareCorrection({ correction, localReply, localLanguage, verdict }) {
  const tabs = useMemo(() => {
    const t = [];
    if (correction?.text_en) t.push({ key: "en", label: "English", text: correction.text_en });
    if (correction?.text_hi) t.push({ key: "hi", label: "हिन्दी", text: correction.text_hi });
    if (correction?.text_te) t.push({ key: "te", label: "తెలుగు", text: correction.text_te });
    if (localReply && localLanguage && !["English", "Hindi", "Telugu"].includes(localLanguage)) {
      t.push({ key: "local", label: localLanguage, text: localReply });
    }
    return t;
  }, [correction, localReply, localLanguage]);

  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);
  const [igHint, setIgHint] = useState(false);
  if (!tabs.length) return null;

  const current = tabs[Math.min(active, tabs.length - 1)];
  const links = shareLinks(current.text, correction?.registry_url);

  async function copy() {
    if (await copyText(current.text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  async function instagram() {
    if (await copyText(current.text)) {
      setIgHint(true);
      toast.success("Copied. Paste into your story or DM.");
    }
  }

  return (
    <section className="rounded-md p-5" style={{ background: "rgba(37,211,102,0.05)", border: "1px solid rgba(37,211,102,0.15)" }}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="#25D366" aria-hidden="true">
            <path d={WHATSAPP_PATH} />
          </svg>
          <span className="label !text-[#25D366]">
            {verdict === "UNVERIFIED" ? "Reply without spreading it" : "Ready to correct this forward?"}
          </span>
        </div>
        <div className="flex gap-1" role="tablist">
          {tabs.map((t, i) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={i === active}
              onClick={() => setActive(i)}
              className="rounded-full px-2.5 py-1 text-[11.5px] transition-colors"
              style={{
                background: i === active ? "rgba(37,211,102,0.16)" : "transparent",
                color: i === active ? "#25D366" : "var(--text-secondary)",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <p className="mono m-0 whitespace-pre-wrap break-words text-[13px] leading-relaxed text-primary">{current.text}</p>
      <div className="mono mt-2 flex flex-wrap justify-between gap-2 text-[10.5px] text-muted">
        <span>Source: {correction?.source_label || "—"}</span>
        <span>{current.text.length} / 280</span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <ShareButton href={links.whatsapp} label="Share on WhatsApp" color="#25D366">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d={WHATSAPP_PATH} />
          </svg>
          WhatsApp
        </ShareButton>
        <ShareButton href={links.x} label="Share on X" color="#F0F0F5">
          <Twitter size={13} /> X
        </ShareButton>
        {correction?.registry_url && (
          <>
            <ShareButton href={links.facebook} label="Share on Facebook" color="#6EA2FF">
              <Facebook size={13} /> Facebook
            </ShareButton>
            <ShareButton href={links.linkedin} label="Share on LinkedIn" color="#6EA2FF">
              <Linkedin size={13} /> LinkedIn
            </ShareButton>
          </>
        )}
        <ShareButton onClick={instagram} label="Copy for Instagram" color="#E1306C">
          <Instagram size={13} /> Instagram
        </ShareButton>
        <ShareButton onClick={copy} label="Copy correction" color={copied ? "#25D366" : "#F0F0F5"}>
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copied ✓" : "Copy"}
        </ShareButton>
      </div>
      {igHint && <p className="mb-0 mt-2 text-[12px] text-secondary">Paste into your story or DM.</p>}
    </section>
  );
}
