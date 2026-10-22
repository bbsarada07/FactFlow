import Link from "next/link";
import { useRouter } from "next/router";

import Logo from "@/components/Logo";

const LINKS = [
  { href: "/", label: "Verify" },
  { href: "/tracker", label: "Tracker" },
  { href: "/incidents", label: "Incidents" },
  { href: "/about", label: "About" },
];

export default function Navbar() {
  const { pathname } = useRouter();

  return (
    <header
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-between gap-3 px-4 md:px-6"
      style={{
        height: "var(--nav-height)",
        background: "rgba(4,4,7,0.8)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <Link href="/" className="flex shrink-0 items-center gap-2.5" aria-label="FactFlow home">
        <Logo size={28} />
        <span className="hidden font-display text-[17px] font-bold tracking-tight sm:inline">FactFlow</span>
        <span className="ml-1 hidden items-center gap-1.5 sm:flex">
          <span className="live-dot" />
          <span className="mono text-[10px] font-medium tracking-[1.5px] text-red">LIVE</span>
        </span>
      </Link>

      <nav className="flex h-full items-stretch gap-1 sm:gap-2 md:gap-6">
        {LINKS.map((l) => {
          const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`relative flex items-center px-1.5 text-[11px] font-medium uppercase tracking-[1.5px] transition-colors duration-200 sm:px-2 sm:text-[12px] ${
                active ? "text-red" : "text-secondary hover:text-primary"
              }`}
            >
              {l.label}
              {active && (
                <span className="absolute inset-x-1 bottom-0 h-[2px] rounded-full bg-red" style={{ boxShadow: "0 0 12px #FF2D2D" }} />
              )}
            </Link>
          );
        })}
      </nav>

      <div className="hidden shrink-0 items-center gap-3 lg:flex">
        <span className="mono text-[11px] text-muted">GROQ × GPT-OSS</span>
      </div>
    </header>
  );
}
