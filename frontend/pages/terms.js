import Head from "next/head";
import Link from "next/link";

/** Terms of use. Public page. */
export default function TermsPage() {
  const item = "mt-3 text-[15px] leading-relaxed text-secondary";
  return (
    <>
      <Head>
        <title>Terms of use — FactFlow</title>
      </Head>
      <article className="mx-auto max-w-3xl px-4 pb-24 pt-16">
        <div className="mono mb-4 text-[11px] tracking-[3px] text-red">TERMS OF USE</div>
        <h1 className="m-0 font-display text-[36px] font-bold leading-tight text-primary">Use it, question it, stay in charge.</h1>
        <p className={item}>
          FactFlow is a free student prototype built for HackWithAditya 2026 at Aditya University. By signing in you agree to
          these terms. Last updated 22 November 2026.
        </p>
        <ol className="mt-6 flex list-decimal flex-col gap-3 pl-5 text-[15px] leading-relaxed text-secondary">
          <li>
            <strong className="text-primary">Verdicts are guidance, not certainty.</strong> FactFlow shows its sources and
            says &quot;Unverified&quot; when evidence is missing. Check the sources before acting on anything important.
          </li>
          <li>
            <strong className="text-primary">You stay in charge of your mail.</strong> The agent only acts within the settings
            you choose, every message it sends can be undone for two minutes, and risky actions wait for your approval. You
            are responsible for what you approve.
          </li>
          <li>
            <strong className="text-primary">Use it fairly.</strong> Do not use FactFlow to harass anyone, to spread content
            you know is false, or to attack the service.
          </li>
          <li>
            <strong className="text-primary">It is a prototype.</strong> It is provided as is, may be unavailable at times, and
            may change. Do not rely on it as your only protection.
          </li>
          <li>
            <strong className="text-primary">Your data.</strong> How we handle it is described in the{" "}
            <Link href="/privacy" className="text-primary underline">privacy policy</Link>. You can delete your account at any
            time in Settings.
          </li>
        </ol>
      </article>
    </>
  );
}
