import { ArrowLeft, Eye } from "lucide-react";
import Head from "next/head";
import Link from "next/link";

import VerdictCard from "@/components/VerdictCard";
import { SERVER_API_URL, SITE_URL } from "@/lib/config";
import { formatDate } from "@/lib/theme";

/** Server-side fetch of the public verdict so link previews (OG / Twitter) carry the verdict and claim. */
export async function getServerSideProps({ params, req }) {
  let res;
  try {
    res = await fetch(`${SERVER_API_URL}/api/v/${encodeURIComponent(params.slug)}`);
  } catch {
    return { props: { record: null, error: "The verification service is unreachable right now." } };
  }
  if (res.status === 404) return { notFound: true };
  if (!res.ok) return { props: { record: null, error: `Could not load this verdict (${res.status}).` } };

  const record = await res.json();
  const proto = req.headers["x-forwarded-proto"] || "http";
  const origin = SITE_URL || `${proto}://${req.headers.host}`;
  return { props: { record, pageUrl: `${origin}/v/${params.slug}`, error: null } };
}

function clip(text, n) {
  const t = (text || "").trim();
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t;
}

/** Public, shareable verdict page for one registry record. */
export default function PublicVerdictPage({ record, pageUrl, error }) {
  if (!record) {
    return (
      <div className="mx-auto max-w-xl px-4 py-32 text-center">
        <Head>
          <title>Verdict unavailable — NemesisAI</title>
        </Head>
        <p className="text-secondary">{error}</p>
      </div>
    );
  }

  const title = `${record.verdict}: ${clip(record.claim, 90)}`;
  const description =
    record.verdict === "UNVERIFIED"
      ? `We could not verify this yet. ${clip(record.summary, 150)}`
      : clip(record.summary, 200);

  return (
    <>
      <Head>
        <title>{`${title} — NemesisAI`}</title>
        <meta name="description" content={description} />
        <link rel="canonical" href={pageUrl} />
        <meta property="og:type" content="article" />
        <meta property="og:site_name" content="NemesisAI" />
        <meta property="og:title" content={title} />
        <meta property="og:description" content={description} />
        <meta property="og:url" content={pageUrl} />
        <meta name="twitter:card" content="summary" />
        <meta name="twitter:title" content={title} />
        <meta name="twitter:description" content={description} />
      </Head>

      <div className="mx-auto max-w-[880px] px-4 pb-24 pt-10">
        <div className="mono mb-2 flex flex-wrap items-center justify-between gap-3 text-[11.5px] text-secondary">
          <Link href="/registry" className="flex items-center gap-1.5 hover:text-primary">
            <ArrowLeft size={13} /> PUBLIC VERDICT REGISTRY
          </Link>
          <span className="flex items-center gap-3">
            <span>Checked {formatDate(record.created_at)}</span>
            <span className="flex items-center gap-1">
              <Eye size={12} /> {record.view_count} views
            </span>
            {record.repeat_count > 0 && <span>Seen again {record.repeat_count}×</span>}
          </span>
        </div>

        <VerdictCard result={record} showRegistryLink={false} />

        {record.versions?.length > 0 && (
          <div className="mt-6 rounded-md border border-subtle bg-card p-4">
            <div className="mono mb-2 text-[10.5px] tracking-[2px] text-secondary">OTHER VERSIONS OF THIS CLAIM</div>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]">
              {record.versions.map((v) => (
                <li key={v.slug}>
                  <Link href={`/v/${v.slug}`} className="text-primary hover:text-red">
                    v{v.version} · {v.verdict} · {formatDate(v.created_at)}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-8 flex justify-center">
          <Link href="/" className="btn-red">
            CHECK ANOTHER CLAIM
          </Link>
        </div>
      </div>
    </>
  );
}
