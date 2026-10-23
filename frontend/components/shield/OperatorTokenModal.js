import { useState, useEffect } from "react";
import { KeyRound, Check, X, ShieldAlert, Eye, EyeOff } from "lucide-react";
import { getOperatorToken, setOperatorToken, clearOperatorToken } from "@/lib/shieldApi";

export default function OperatorTokenModal({ isOpen, onClose, onTokenSaved }) {
  const [tokenInput, setTokenInput] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setTokenInput(getOperatorToken() || "");
      setSavedSuccess(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSave = (e) => {
    e.preventDefault();
    const clean = tokenInput.trim();
    if (clean) {
      setOperatorToken(clean);
      setSavedSuccess(true);
      setTimeout(() => {
        onTokenSaved?.(clean);
        onClose();
      }, 600);
    } else {
      clearOperatorToken();
      onTokenSaved?.(null);
      onClose();
    }
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
      <div className="relative w-full max-w-md overflow-hidden rounded-lg border border-subtle bg-surface p-6 shadow-2xl">
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
              <span>Operator Routes Protection</span>
            </div>
            Shield operator routes (inbox management, approvals, benchmark, audit) require the backend secret{" "}
            <code className="text-red">OPERATOR_TOKEN</code>. It is stored securely in{" "}
            <span className="text-primary font-semibold">sessionStorage</span> and sent via{" "}
            <code className="text-secondary">X-Operator-Token</code>.
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
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Enter OPERATOR_TOKEN..."
                className="w-full rounded-md border border-subtle bg-card px-3 py-2.5 text-[13px] font-mono text-primary placeholder-muted outline-none focus:border-red"
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
          </div>

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={handleClear}
              className="text-[12px] text-secondary hover:text-red transition-colors"
            >
              Clear Token
            </button>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="btn-ghost"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn-red !py-2 !px-5 !text-[13px]"
              >
                {savedSuccess ? (
                  <>
                    <Check size={14} /> Saved
                  </>
                ) : (
                  "Save Token"
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
