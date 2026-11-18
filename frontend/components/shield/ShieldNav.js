import Link from "next/link";
import { useRouter } from "next/router";
import { useState, useEffect } from "react";
import { Mail, CheckSquare, BarChart3, ShieldCheck, KeyRound, Sparkles } from "lucide-react";
import MockBanner from "@/components/shield/MockBanner";
import OperatorTokenModal from "@/components/shield/OperatorTokenModal";
import { hasOperatorToken, USE_MOCKS } from "@/lib/shieldApi";

const NAV_ITEMS = [
  { href: "/shield", label: "Inbox", icon: Mail },
  { href: "/shield/approvals", label: "Approvals", icon: CheckSquare },
  { href: "/shield/advanced/benchmark", label: "Benchmark", icon: BarChart3 },
  { href: "/shield/advanced/audit", label: "Audit Log", icon: ShieldCheck },
];

export default function ShieldNav() {
  const { pathname } = useRouter();
  const [tokenModalOpen, setTokenModalOpen] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    setHasToken(hasOperatorToken());
  }, []);

  return (
    <>
      <MockBanner />
      <div className="mb-6 border-b border-subtle pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-red/10 border border-red/40 text-red">
              <ShieldCheck size={16} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-display text-[17px] font-bold tracking-tight text-primary">
                  Shield Control Panel
                </span>
                {USE_MOCKS ? (
                  <span className="pill text-[9.5px] bg-orange/10 border border-orange/40 text-orange">
                    <Sparkles size={10} /> MOCK DATA
                  </span>
                ) : (
                  <span className="pill text-[9.5px] bg-green/10 border border-green/40 text-green">
                    ● REAL API
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setTokenModalOpen(true)}
              className={`pill transition-all ${
                hasToken
                  ? "border-green/40 text-green bg-green/10 hover:bg-green/20"
                  : "border-subtle text-secondary hover:text-primary hover:bg-hover"
              }`}
              title="Configure operator authentication token in sessionStorage"
            >
              <KeyRound size={12} className={hasToken ? "text-green" : "text-secondary"} />
              <span className="text-[10.5px]">
                {hasToken ? "OPERATOR AUTH OK" : "SET OPERATOR TOKEN"}
              </span>
            </button>
          </div>
        </div>

        {/* Tab Links */}
        <nav className="mt-4 flex flex-wrap gap-1.5 sm:gap-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active =
              item.href === "/shield"
                ? pathname === "/shield" || pathname.startsWith("/shield/report")
                : pathname === item.href;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-[12.5px] font-medium transition-colors ${
                  active
                    ? "bg-card text-primary border border-active shadow-sm"
                    : "text-secondary hover:bg-hover hover:text-primary border border-transparent"
                }`}
              >
                <Icon size={14} className={active ? "text-red" : "text-muted"} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      <OperatorTokenModal
        isOpen={tokenModalOpen}
        onClose={() => setTokenModalOpen(false)}
        onTokenSaved={(token) => setHasToken(Boolean(token))}
      />
    </>
  );
}
