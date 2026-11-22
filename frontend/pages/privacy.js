import Head from "next/head";
import Link from "next/link";

const CONTACT = process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "";
const UPDATED = "22 November 2026";

function Section({ title, children }) {
  return (
    <section className="mt-10">
      <h2 className="m-0 font-display text-[20px] font-semibold text-primary">{title}</h2>
      <div className="mt-3 flex flex-col gap-3 text-[15px] leading-relaxed text-secondary">{children}</div>
    </section>
  );
}

/** Privacy policy: what FactFlow stores, why, who processes it, and how to delete it. Public page. */
export default function PrivacyPage() {
  return (
    <>
      <Head>
        <title>Privacy policy — FactFlow</title>
        <meta name="description" content="What FactFlow stores, why, who processes it, and how to delete it." />
      </Head>
      <article className="mx-auto max-w-3xl px-4 pb-24 pt-16">
        <div className="mono mb-4 text-[11px] tracking-[3px] text-red">PRIVACY POLICY</div>
        <h1 className="m-0 font-display text-[36px] font-bold leading-tight text-primary">Your data stays yours.</h1>
        <p className="mt-4 text-[15px] text-secondary">
          FactFlow is a student project built for HackWithAditya 2026 at Aditya University. This page explains exactly
          what it stores, why, and how you remove it. Last updated {UPDATED}.
        </p>

        <Section title="What we collect">
          <ul className="m-0 flex list-disc flex-col gap-2 pl-5">
            <li>
              <strong className="text-primary">Your Google account basics</strong> when you sign in: your Google account ID,
              email address, name and profile picture.
            </li>
            <li>
              <strong className="text-primary">What you ask FactFlow to check</strong>: the claim text (with phone numbers,
              Aadhaar and card numbers removed), links and screenshots, and the verdict.
            </li>
            <li>
              <strong className="text-primary">If you connect Gmail</strong>: an access token, stored encrypted, and for each
              message the agent checks, its analysis (the verdict, and the visible and hidden text it found). The raw email is
              not stored. Messages the agent sends for you, the files you upload to My files, and your agent settings are also
              stored.
            </li>
            <li>
              <strong className="text-primary">A security audit log</strong> of actions the agent took or was stopped from
              taking, with personal numbers removed.
            </li>
          </ul>
        </Section>

        <Section title="How we use it">
          <p>
            Only to provide FactFlow&apos;s features to you: checking claims and emails, running your mail agent, and
            showing you your own history. We do not sell your data, show you ads, or use your data to train AI models.
          </p>
          <p>
            Everything you check or connect is private to your account. A verdict page becomes visible to others only if
            you press Share, and you can stop sharing at any time.
          </p>
        </Section>

        <Section title="Google user data (Gmail)">
          <p>
            FactFlow&apos;s use and transfer of information received from Google APIs adheres to the{" "}
            <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer"
              className="text-primary underline">Google API Services User Data Policy</a>, including the Limited Use requirements.
          </p>
          <p>
            Gmail access is used only to check your incoming and sent mail for scams and hidden instructions, label and
            archive risky mail, and send the replies and files you allow. FactFlow never deletes your mail, and every message
            it sends waits two minutes so you can undo it. No person reads your mail unless you ask us to, it is needed for
            security, or the law requires it.
          </p>
        </Section>

        <Section title="Services that process data for us">
          <ul className="m-0 flex list-disc flex-col gap-2 pl-5">
            <li><strong className="text-primary">Groq</strong> runs the AI models. It receives the text being checked, with personal numbers removed.</li>
            <li><strong className="text-primary">Google Gemini</strong> reads the text in screenshots you upload.</li>
            <li><strong className="text-primary">Google Fact Check Tools, Bing News, Google News, NewsAPI and GDELT</strong> receive search words taken from a claim, never your email address or your emails.</li>
            <li><strong className="text-primary">Render</strong> hosts the website and database.</li>
          </ul>
        </Section>

        <Section title="Keeping it safe">
          <p>
            All traffic uses HTTPS. Gmail tokens are encrypted, sign-in sessions are stored only as one-way hashes, and every
            account can see only its own data.
          </p>
        </Section>

        <Section title="Deleting your data">
          <p>
            In <Link href="/settings" className="text-primary underline">Settings</Link>, Disconnect Gmail revokes FactFlow&apos;s
            access at Google. &quot;Delete my account and data&quot; removes everything your account owns. Audit-log entries are
            kept for the integrity of the log but are detached from you. You can also remove FactFlow&apos;s access at any time at{" "}
            <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer" className="text-primary underline">
              myaccount.google.com/permissions
            </a>.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            {CONTACT ? (
              <>Questions or requests: <a href={`mailto:${CONTACT}`} className="text-primary underline">{CONTACT}</a>.</>
            ) : (
              <>Questions or requests: write to the support email shown on FactFlow&apos;s Google sign-in screen.</>
            )}{" "}
            If this policy changes, the date at the top changes with it.
          </p>
        </Section>
      </article>
    </>
  );
}
