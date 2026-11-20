import { useState, useEffect } from "react";
import { KeyRound, Check, X, ShieldAlert, Eye, EyeOff, RotateCw, AlertTriangle, ChevronDown } from "lucide-react";
import {
  getOperatorToken,
  setOperatorToken,
  clearOperatorToken,
  verifyOperatorToken,
} from "@/lib/shieldApi";

export default function OperatorTokenModal({ isOpen, onClose, onTokenSaved }) {
  const [tokenInput, setTokenInput] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState(null); // { status, message }
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setTokenInput(getOperatorToken() || "");
      setSavedSuccess(false);
      setProblem(null);
      setChecking(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const finish = (token) => {
    setSavedSuccess(true);
    setTimeout(() => {
      onTokenSaved?.(token);
      onClose();
    }, 500);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    const clean = tokenInput.trim();
    if (!clean) {
      clearOperatorToken();
      onTokenSaved?.(null);
      onClose();
      return;
    }
    setChecking(true);
    setProblem(null);
    const check = await verifyOperatorToken(clean);
    setChecking(false);
    if (check.ok) {
      setOperatorToken(clean);
      finish(clean);
      return;
    }
    if (check.status === 0) {
      // Backend unreachable: keep the token so it is used once the server is back.
      setOperatorToken(clean);
      setProblem({ status: 0, message: `${check.message} The token was saved but could not be checked.` });
      return;
    }
    setProblem(check);
    if (check.status === 503) setShowHelp(true);
  };

  const handleClear = () => {
    clearOperatorToken();
    setTokenInput("");
    onTokenSaved?.(null);
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="operator-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
    >
      <div className="relative w-full max-w-md max-h-[90vh] overflow-y-auto rounded-lg border border-subtle bg-surface p-6 shadow-2xl">
        <div className="flex items-center justify-between pb-3 border-b border-subtle">
          <div className="flex items-center gap-2">
            <KeyRound className="text-red" size={20} />
            <h3 id="operator-modal-title" className="font-display text-[16px] font-bold text-primary">Operator Authentication</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-secondary hover:text-primary hover:bg-hover"
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSave} className="mt-4 flex flex-col gap-4">
          <div className="rounded-md border border-subtle bg-card p-3 text-[12.5px] text-secondary leading-relaxed">
            <div className="flex items-start gap-2 text-primary font-medium mb-1">
              <ShieldAlert size={15} className="text-orange shrink-0 mt-0.5" />
              <span>Only needed for operator pages</span>
            </div>
            Running demo emails and checking your own email work <span className="text-primary font-semibold">without</span> a
            token. The token unlocks the full inbox, approvals, benchmark and audit log. It must equal the{" "}
            <code className="text-red">OPERATOR_TOKEN</code> set on the backend server; it is kept in this tab&apos;s{" "}
            <span className="text-primary font-semibold">sessionStorage</span> only.
          </div>

          <div>
            <label htmlFor="operator-token-input" className="mono block text-[11px] tracking-[1.5px] uppercase text-secondary mb-1.5">
              Operator Token
            </label>
            <div className="relative flex items-center">
              <input
                id="operator-token-input"
                type={showPassword ? "text" : "password"}
                value={tokenInput}
                onChange={(e) => {
                  setTokenInput(e.target.value);
                  setProblem(null);
                }}
                placeholder="Paste OPERATOR_TOKEN..."
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-md border border-subtle bg-card px-3 py-2.5 pr-10 text-[13px] font-mono text-primary placeholder-muted outline-none focus:border-red"
              />
              <button
                type="button"
                onClick={() => setShowPassword((p) => !p)}
                className="absolute right-3 text-secondary hover:text-primary"
                aria-label={showPassword ? "Hide token" : "Show token"}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {problem && (
              <p role="alert" className="mt-2 flex items-start gap-1.5 text-[12px] text-orange">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>{problem.message}</span>
              </p>
            )}
          </div>

          <div className="rounded-md border border-subtle bg-card text-[12px] text-secondary">
            <button
              type="button"
              onClick={() => setShowHelp((s) => !s)}
              aria-expanded={showHelp}
              className="flex w-full items-center justify-between px-3 py-2 text-left text-primary font-medium"
            >
              <span>Where do I get the token?</span>
              <ChevronDown size={14} className={`transition-transform ${showHelp ? "rotate-180" : ""}`} />
            </button>
            {showHelp && (
              <ol className="list-decimal pl-8 pr-3 pb-3 flex flex-col gap-1.5 leading-relaxed">
                <li>
                  You create it yourself; there is no account to sign up for. Generate one:
                  <code className="block mt-1 rounded bg-surface px-2 py-1 text-[11px] text-primary break-all">
                    python -c &quot;import secrets; print(secrets.token_urlsafe(32))&quot;
                  </code>
                </li>
                <li>
                  Local backend: put it in <code className="text-red">backend/.env</code> as{" "}
                  <code className="text-primary">OPERATOR_TOKEN=...</code> and restart the server.
                </li>
                <li>
                  Hosted backend (Render): Service, then <span className="text-primary">Environment</span>, add{" "}
                  <code className="text-primary">OPERATOR_TOKEN</code>, then save and let it redeploy.
                </li>
                <li>Paste the same value here. Never put it in a NEXT_PUBLIC_ variable or commit it.</li>
              </ol>
            )}
          </div>

          <div className="flex items-center justify-between pt-1">
            <button
              type="button"
              onClick={handleClear}
              className="text-[12px] text-secondary hover:text-red transition-colors"
            >
              Clear Token
            </button>
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="btn-ghost">
                {problem?.status === 0 ? "Close" : "Cancel"}
              </button>
              <button type="submit" disabled={checking} className="btn-red !py-2 !px-5 !text-[13px]">
                {checking ? (
                  <>
                    <RotateCw size={14} className="animate-spin" /> Checking...
                  </>
                ) : savedSuccess ? (
                  <>
                    <Check size={14} /> Verified
                  </>
                ) : (
                  "Verify & Save"
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
