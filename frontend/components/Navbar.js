import { LogIn, LogOut, Settings } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useRef, useState } from "react";

import Logo from "@/components/Logo";
import { getNeedsYou } from "@/lib/api";
import { signInUrl, signOut, useAuth, useSignIn } from "@/lib/auth";

const LINKS = [
  { href: "/", label: "Check" },
  { href: "/shield", label: "Mail", match: (p) => (p.startsWith("/shield") && p !== "/shield/approvals") || p === "/compose" },
  { href: "/shield/approvals", label: "Needs you", badge: true },
  { href: "/tracker", label: "Tracker" },
  { href: "/incidents", label: "Incidents" },
  { href: "/about", label: "About" },
];

/** How many things wait for the signed-in user (approvals + alerts), refreshed every minute. */
function useNeedsYouCount() {
  const { status } = useAuth();
  const { asPath } = useRouter();
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (status !== "signed_in") return undefined;
    let alive = true;
    const load = () => getNeedsYou().then((r) => alive && setCount(r.total || 0)).catch(() => {});
    load();
    const id = setInterval(load, 60000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [status, asPath]);
  return status === "signed_in" ? count : 0;
}

export default function Navbar() {
  const { pathname } = useRouter();
  const needsYou = useNeedsYouCount();

  return (
    <header
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-between gap-2 px-3 sm:px-6"
      style={{
        height: "var(--nav-height)",
        background: "rgba(4,4,7,0.85)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="FactFlow home">
        <Logo size={26} />
        <span className="hidden font-display text-[17px] font-bold tracking-tight sm:inline">FactFlow</span>
        <span className="ml-1 hidden items-center gap-1.5 md:flex">
          <span className="live-dot" />
          <span className="mono text-[10px] font-medium tracking-[1.5px] text-red">LIVE</span>
        </span>
      </Link>

      <nav className="flex h-full items-stretch gap-1 sm:gap-2 md:gap-5 overflow-x-auto no-scrollbar">
        {LINKS.map((l) => {
          const active = l.match ? l.match(pathname) : l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`relative flex items-center px-1.5 text-[10.5px] sm:text-[12px] font-medium uppercase tracking-[1px] sm:tracking-[1.5px] transition-colors duration-200 shrink-0 ${
                active ? "text-red" : "text-secondary hover:text-primary"
              }`}
            >
              {l.label}
              {l.badge && needsYou > 0 && (
                <span
                  className="mono ml-1.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-bold text-white"
                  style={{ background: "#FF2D2D" }}
                  aria-label={`${needsYou} waiting for you`}
                >
                  {needsYou > 99 ? "99+" : needsYou}
                </span>
              )}
              {active && (
                <span className="absolute inset-x-1 bottom-0 h-[2px] rounded-full bg-red" style={{ boxShadow: "0 0 12px #FF2D2D" }} />
              )}
            </Link>
          );
        })}
      </nav>

      <AccountMenu />
    </header>
  );
}

function initials(user) {
  const base = (user?.name || user?.email || "?").trim();
  return base
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join("");
}

/** Sign in, or the signed-in person's menu (settings, sign out). */
function AccountMenu() {
  const { status, user } = useAuth();
  const { asPath, pathname } = useRouter();
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const signIn = useSignIn(asPath);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  if (status === "loading") return <div className="h-8 w-8 shrink-0" />;
  if (status !== "signed_in") {
    if (pathname === "/login") return <div className="w-8 shrink-0" />;
    return (
      <a href={signInUrl(asPath)} onClick={signIn.go} className="btn-red shrink-0 !py-1.5 !px-3 !text-[12px]">
        <LogIn size={13} /> {signIn.phase === "waking" ? "Waking up…" : "Sign in"}
      </a>
    );
  }

  return (
    <div className="relative shrink-0" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full border border-subtle py-0.5 pl-0.5 pr-2 transition-colors hover:border-active"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Your account"
      >
        {user?.picture_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.picture_url} alt="" referrerPolicy="no-referrer" className="h-7 w-7 rounded-full" />
        ) : (
          <span
            className="mono flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold text-primary"
            style={{ background: "rgba(255,45,45,0.2)" }}
          >
            {initials(user)}
          </span>
        )}
        <span className="hidden max-w-[140px] truncate text-[12.5px] text-secondary lg:inline">{user?.name || user?.email}</span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-11 w-64 overflow-hidden rounded-md border border-subtle bg-card shadow-xl">
          <div className="border-b border-subtle px-4 py-3">
            <div className="truncate text-[13.5px] font-semibold text-primary">{user?.name || "Your account"}</div>
            <div className="truncate text-[12px] text-secondary">{user?.email}</div>
          </div>
          <Link href="/settings" role="menuitem" onClick={() => setOpen(false)} className="flex items-center gap-2 px-4 py-2.5 text-[13px] text-secondary hover:bg-hover hover:text-primary">
            <Settings size={14} /> Agent settings
          </Link>
          <button type="button" role="menuitem" onClick={signOut} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] text-secondary hover:bg-hover hover:text-primary">
            <LogOut size={14} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
