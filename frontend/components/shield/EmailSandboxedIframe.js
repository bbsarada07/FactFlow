import { useState, useId } from "react";
import { Shield, Code, Eye } from "lucide-react";
import { escapeSuspiciousCharacters } from "@/lib/shieldApi";

/**
 * Renders untrusted email HTML safely.
 * HARD RULE:
 * - NEVER use dangerouslySetInnerHTML.
 * - Email HTML only inside <iframe sandbox="" srcDoc={...} referrerPolicy="no-referrer">
 * - Empty sandbox attribute completely disables scripts, popups, and same-origin privileges.
 */
export default function EmailSandboxedIframe({ htmlContent, fallbackText }) {
  const [viewMode, setViewMode] = useState("rendered"); // 'rendered' | 'plain'
  const iframeTitle = useId();

  // Inject a default dark-mode styling into the iframe's srcDoc so rendered emails match FactFlow
  const safeSrcDoc = htmlContent
    ? `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      margin: 0;
      padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: #E2E8F0;
      background-color: #0d0d12;
      word-break: break-word;
    }
    a { color: #6EA2FF; pointer-events: none; text-decoration: underline; }
    img { max-width: 100%; height: auto; }
  </style>
</head>
<body>
  ${htmlContent}
</body>
</html>`
    : null;

  return (
    <div className="rounded-md border border-subtle bg-surface overflow-hidden">
      <div className="flex items-center justify-between border-b border-subtle px-3 py-2 bg-card text-[11px] font-mono">
        <div className="flex items-center gap-1.5 text-secondary">
          <Shield size={12} className="text-green" />
          <span>ISOLATED SANDBOX IFRAME</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setViewMode("rendered")}
            className={`px-2 py-0.5 rounded text-[10.5px] transition-colors ${
              viewMode === "rendered"
                ? "bg-hover text-primary font-bold border border-active"
                : "text-muted hover:text-secondary"
            }`}
          >
            <Eye size={11} className="inline mr-1" /> Rendered
          </button>
          <button
            type="button"
            onClick={() => setViewMode("plain")}
            className={`px-2 py-0.5 rounded text-[10.5px] transition-colors ${
              viewMode === "plain"
                ? "bg-hover text-primary font-bold border border-active"
                : "text-muted hover:text-secondary"
            }`}
          >
            <Code size={11} className="inline mr-1" /> Plain Text
          </button>
        </div>
      </div>

      <div className="p-3">
        {viewMode === "rendered" && safeSrcDoc ? (
          <iframe
            title={`Sandboxed Email Content ${iframeTitle}`}
            sandbox=""
            srcDoc={safeSrcDoc}
            referrerPolicy="no-referrer"
            className="w-full h-64 rounded border border-subtle bg-base"
          />
        ) : (
          <div className="w-full h-64 overflow-y-auto rounded border border-subtle bg-base p-3 text-[13px] font-mono text-secondary whitespace-pre-wrap leading-relaxed">
            {escapeSuspiciousCharacters(fallbackText || "No body content available")}
          </div>
        )}
      </div>
    </div>
  );
}
