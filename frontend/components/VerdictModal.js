import { AnimatePresence, motion } from "framer-motion";
import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import VerdictCard from "@/components/VerdictCard";
import { getResult } from "@/lib/api";

export default function VerdictModal({ requestId, onClose }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!requestId) return;
    setResult(null);
    setError(null);
    getResult(requestId)
      .then(({ data }) => setResult(data))
      .catch((e) => setError(e.message));
  }, [requestId]);

  useEffect(() => {
    if (!requestId) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [requestId, onClose]);

  return (
    <AnimatePresence>
      {requestId && (
        <motion.div
          className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto px-3 py-16 sm:px-6"
          style={{ background: "rgba(4,4,7,0.78)", backdropFilter: "blur(10px)" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          role="dialog"
          aria-modal="true"
        >
          <motion.div
            className="relative w-full max-w-[820px]"
            initial={{ y: 30, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 30, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={onClose}
              className="absolute -top-11 right-0 flex items-center gap-1.5 rounded-full border border-active bg-card px-3 py-1.5 text-[12px] text-secondary hover:text-primary"
            >
              <X size={14} /> CLOSE
            </button>
            {error ? (
              <div className="rounded-lg border border-subtle bg-card p-8 text-center text-secondary">{error}</div>
            ) : !result ? (
              <div className="flex justify-center rounded-lg border border-subtle bg-card p-16">
                <Loader2 className="text-red" style={{ animation: "spin 1s linear infinite" }} />
              </div>
            ) : (
              <VerdictCard result={result} compact />
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
