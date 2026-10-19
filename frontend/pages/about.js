import { motion } from "framer-motion";
import { Building2, Cpu, Landmark, Newspaper, Repeat, Server, Users, Zap } from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { useEffect, useState } from "react";

import ArchitectureDiagram from "@/components/ArchitectureDiagram";
import InViewCount from "@/components/InViewCount";
import { api } from "@/lib/api";
import { EASE } from "@/lib/theme";

const reveal = {
  hidden: { opacity: 0, y: 30 },
  show: (i = 0) => ({ opacity: 1, y: 0, transition: { duration: 0.6, delay: i * 0.1, ease: EASE } }),
};

function SectionHeader({ kicker, title, children }) {
  return (
    <motion.div variants={reveal} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} className="mb-12 max-w-2xl">
      <div className="mono mb-4 text-[11px] tracking-[3px] text-red">{kicker}</div>
      <h2 className="m-0 font-display font-semibold leading-tight tracking-[-0.02em]" style={{ fontSize: "clamp(30px, 5vw, 46px)" }}>
        {title}
      </h2>
      {children && <p className="mt-4 text-[16px] leading-relaxed text-secondary">{children}</p>}
    </motion.div>
  );
}

const PIPELINE_FACTS = [
  ["6", "specialised agents"],
  ["3", "live evidence sources"],
  ["12", "output languages"],
  ["1", "verdict you can forward"],
];

const REVENUE = [
  {
    icon: Users,
    color: "#00E676",
    title: "Citizens",
    price: "Free · ₹99/yr Family Shield",
    body: "Verification, the Chrome extension and WhatsApp replies stay free. A family plan adds priority checks and alerts for elderly relatives.",
  },
  {
    icon: Newspaper,
    color: "#2979FF",
    title: "Newsrooms & fact-checkers",
    price: "Usage-based API",
    body: "A triage queue that surfaces viral, harm-scored claims first, with evidence already gathered — hours saved per debunk.",
  },
  {
    icon: Building2,
    color: "#FF6B00",
    title: "Platforms & telcos",
    price: "Annual T&S licence",
    body: "Trust & safety dashboards with rumour alerts by region, language and harm type, before content goes viral.",
  },
  {
    icon: Landmark,
    color: "#B04FD0",
    title: "Government & NGOs",
    price: "Programme contracts",
    body: "Election-integrity and public-health early warning, with priority on violence- and communal-risk rumours.",
  },
];

const MARKET = [
  { tag: "TAM", value: 3960, label: "₹ crore / year", basis: "400M Indian WhatsApp users × ₹99/yr" },
  { tag: "SAM", value: 396, label: "₹ crore / year", basis: "10% who regularly share news forwards" },
  { tag: "SOM", value: 7.9, decimals: 1, label: "₹ crore / year", basis: "2% of SAM within three years" },
];

export default function AboutPage() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    api("/health")
      .then((r) => setHealth(r.data))
      .catch(() => {});
  }, []);

  const models = health?.models || { nano: "openai/gpt-oss-20b", ultra: "openai/gpt-oss-120b" };

  const STACK = [
    {
      icon: Cpu,
      color: "#2979FF",
      title: "Fast tier · Nano",
      model: models.nano,
      body: "Runs Intake, Source Tracer, Explainer and Harm Assessor. Structured JSON in about a second per call keeps the full pipeline under a minute.",
    },
    {
      icon: Zap,
      color: "#FF2D2D",
      title: "Deep tier · Ultra",
      model: models.ultra,
      body: "Escalated only when confidence drops below 85% or a claim is CRITICAL. Breaks the claim into sub-claims and hunts for contradictions.",
    },
    {
      icon: Server,
      color: "#00E676",
      title: "Groq inference",
      model: "OpenAI-compatible API",
      body: "Low-latency LPU inference behind a standard chat-completions API. The explainer and harm agents run in parallel to cut wall-clock time.",
    },
    {
      icon: Repeat,
      color: "#FF6B00",
      title: "Provider-agnostic",
      model: "Swap via .env",
      body: "Point the base URL and model names at any OpenAI-compatible endpoint, such as NVIDIA Nemotron on Nebius, without touching agent code.",
    },
  ];

  return (
    <>
      <Head>
        <title>How it works — NemesisAI</title>
      </Head>

      {/* 1 — The problem */}
      <section
        className="relative flex min-h-[calc(100vh-var(--nav-height))] items-center justify-center overflow-hidden px-4 text-center"
        style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(255,45,45,0.07), transparent 70%)" }}
      >
        <div>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mono mb-6 text-[11px] tracking-[3px] text-red">
            THE PROBLEM
          </motion.div>
          <div className="font-display font-bold leading-none tracking-[-0.04em] text-primary" style={{ fontSize: "clamp(44px, 11vw, 132px)", textShadow: "0 0 60px rgba(255,45,45,0.25)" }}>
            <InViewCount end={400000000} duration={2.6} />
            <span className="text-red">+</span>
          </div>
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.8, duration: 0.6 }}
            className="mx-auto mt-8 max-w-xl text-[18px] leading-relaxed text-secondary sm:text-[20px]"
          >
            WhatsApp users in India who could be reached by a single false forward — long before a fact-check is published.
          </motion.p>
        </div>
      </section>

      {/* 2 — Architecture */}
      <section className="mx-auto max-w-6xl px-4 py-24">
        <SectionHeader kicker="ARCHITECTURE" title="Six agents. One forensic verdict.">
          An orchestrator routes every claim through triage, live evidence search, conditional deep reasoning, explanation and
          harm scoring, streaming each step to your screen as it happens.
        </SectionHeader>
        <motion.div
          variants={reveal}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
          className="rounded-lg border border-subtle bg-surface p-4 sm:p-8"
        >
          <ArchitectureDiagram />
        </motion.div>
        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {PIPELINE_FACTS.map(([n, label], i) => (
            <motion.div
              key={label}
              custom={i}
              variants={reveal}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true }}
              className="rounded-md border border-subtle bg-card p-4"
            >
              <div className="font-display text-[28px] font-bold text-primary">{n}</div>
              <div className="mono text-[11px] tracking-[1px] text-secondary">{label}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* 3 — Inference stack */}
      <section className="mx-auto max-w-6xl px-4 py-24">
        <SectionHeader kicker="INFERENCE STACK" title="Fast where it can be. Deep where it must be.">
          Two model tiers on Groq. The small model handles most of the work; the large one is only called when it can change the
          outcome.
        </SectionHeader>
        <div className="grid gap-4 md:grid-cols-2">
          {STACK.map((c, i) => (
            <motion.div
              key={c.title}
              custom={i}
              variants={reveal}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-60px" }}
              whileHover={{ scale: 1.01 }}
              className="glass rounded-lg p-6"
            >
              <div className="mb-5 flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-md" style={{ background: `${c.color}18`, border: `1px solid ${c.color}44` }}>
                  <c.icon size={20} style={{ color: c.color }} />
                </span>
                <div>
                  <div className="font-display text-[18px] font-semibold">{c.title}</div>
                  <div className="mono text-[11.5px]" style={{ color: c.color }}>
                    {c.model}
                  </div>
                </div>
              </div>
              <p className="m-0 text-[14.5px] leading-relaxed text-secondary">{c.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* 4 — Business model */}
      <section className="mx-auto max-w-6xl px-4 pb-28 pt-24">
        <SectionHeader kicker="BUSINESS MODEL" title="Free for citizens. Paid by those who need scale.">
          Four revenue streams fund a public-good verification layer.
        </SectionHeader>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {REVENUE.map((r, i) => (
            <motion.div
              key={r.title}
              custom={i}
              variants={reveal}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-60px" }}
              whileHover={{ scale: 1.01 }}
              className="rounded-lg border border-subtle bg-card p-6"
              style={{ borderTop: `2px solid ${r.color}` }}
            >
              <r.icon size={22} style={{ color: r.color }} />
              <div className="mt-4 font-display text-[18px] font-semibold">{r.title}</div>
              <div className="mono mt-1 text-[11.5px]" style={{ color: r.color }}>
                {r.price}
              </div>
              <p className="mb-0 mt-3 text-[14px] leading-relaxed text-secondary">{r.body}</p>
            </motion.div>
          ))}
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {MARKET.map((m, i) => (
            <motion.div
              key={m.tag}
              custom={i}
              variants={reveal}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true }}
              className="glass rounded-lg p-6"
            >
              <div className="mono text-[11px] tracking-[3px] text-red">{m.tag}</div>
              <div className="mt-2 font-display text-[40px] font-bold leading-none">
                ₹<InViewCount end={m.value} decimals={m.decimals || 0} />
                <span className="ml-1 text-[16px] font-medium text-secondary">Cr</span>
              </div>
              <div className="mono mt-1 text-[11px] text-muted">{m.label}</div>
              <p className="mb-0 mt-4 text-[13px] text-secondary">{m.basis}</p>
            </motion.div>
          ))}
        </div>
        <p className="mono mt-4 text-[11px] text-muted">Market sizes are team planning estimates derived from the stated assumptions.</p>

        <div className="mt-20 flex flex-col items-center gap-5 text-center">
          <h3 className="m-0 font-display text-[28px] font-semibold">See it work on a real forward.</h3>
          <div className="flex flex-wrap justify-center gap-3">
            <Link href="/" className="btn-red">
              VERIFY A CLAIM
            </Link>
            <Link href="/incidents" className="btn-ghost !px-6 !py-3">
              Browse incidents
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
