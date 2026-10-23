import { AlertTriangle } from "lucide-react";
import { USE_MOCKS } from "@/lib/shieldApi";

/** Full-width warning shown on every Shield page while mock mode is on (NEXT_PUBLIC_USE_MOCKS=true). */
export default function MockBanner() {
  if (!USE_MOCKS) return null;
  return (
    <div
      role="alert"
      className="mb-4 flex items-start gap-2 rounded-md border border-orange/40 bg-orange/10 px-3 py-2 text-[12.5px] text-orange"
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>
        <strong>MOCK DATA:</strong> nothing on this page comes from the backend. Numbers, verdicts and approvals are
        made-up examples, not results. Set <code>NEXT_PUBLIC_USE_MOCKS=false</code> (the default) to use the real API.
      </span>
    </div>
  );
}
