"""Evaluation script for RAG v1 semantic retrieval over FactFlow Knowledge Base.

Runs a curated, real test set (schemes, scam templates, and adversarial/unrelated distractors)
against the ingested database, reporting true metrics (precision, recall, false positive rate,
latency p50/p95, and exact misses).
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# Add backend directory to path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from database import connection
from shield.kb.ingest import ingest_all
from shield.kb.retrieve import retrieve

EVAL_QUERIES = [
    # --- Schemes (10) ---
    {
        "query": "How to apply for PM Surya Ghar rooftop solar 300 units free electricity subsidy",
        "expected_id": "scheme_pm_surya_ghar",
        "category": "scheme",
    },
    {
        "query": "PM Kisan 2000 rupees 17th installment DBT payment status online",
        "expected_id": "scheme_pm_kisan",
        "category": "scheme",
    },
    {
        "query": "Ayushman Bharat card 5 lakh free hospital treatment eligibility",
        "expected_id": "scheme_ayushman_bharat",
        "category": "scheme",
    },
    {
        "query": "PMAY urban housing subsidy for pucca house home loan interest subsidy",
        "expected_id": "scheme_pmay_urban",
        "category": "scheme",
    },
    {
        "query": "Pradhan Mantri Mudra Yojana business loan up to 10 lakh for micro enterprise",
        "expected_id": "scheme_pm_mudra",
        "category": "scheme",
    },
    {
        "query": "Pradhan Mantri Jan Dhan Yojana zero balance bank account opening overdraft and RuPay debit card",
        "expected_id": "scheme_pmjdy",
        "category": "scheme",
    },
    {
        "query": "Pradhan Mantri Ujjwala Yojana free LPG cooking gas cylinder connection for BPL households",
        "expected_id": "scheme_pm_ujjwala",
        "category": "scheme",
    },
    {
        "query": "Atal Pension Yojana monthly guaranteed pension after 60 years",
        "expected_id": "scheme_atal_pension",
        "category": "scheme",
    },
    {
        "query": "National Career Service NCS government portal job fair vacancies and career counselling",
        "expected_id": "scheme_national_career_service",
        "category": "scheme",
    },
    {
        "query": "Digital India government initiative online digital public infrastructure and electronic services",
        "expected_id": "scheme_digital_india",
        "category": "scheme",
    },

    # --- Scam Templates (11) ---
    {
        "query": "This is Deputy Commissioner from Cyber Crime CBI. You are under digital arrest on Skype video call for illegal narcotics parcel.",
        "expected_id": "scam_digital_arrest",
        "category": "scam",
    },
    {
        "query": "Your bank account will be deactivated within 24 hours due to pending PAN card and KYC update. Click here to verify.",
        "expected_id": "scam_kyc_block",
        "category": "scam",
    },
    {
        "query": "Scan this QR code and enter UPI MPIN to receive your buyer payment refund in Google Pay.",
        "expected_id": "scam_upi_collect",
        "category": "scam",
    },
    {
        "query": "Congratulations you won 25 Lakh in KBC WhatsApp lucky draw call manager to pay registration GST fee.",
        "expected_id": "scam_lottery_kbc",
        "category": "scam",
    },
    {
        "query": "Government is giving free laptops and smartphones under new yojana forward this message to 10 WhatsApp groups.",
        "expected_id": "scam_fake_scheme_freebie",
        "category": "scam",
    },
    {
        "query": "Earn 3000 daily part time work from home by liking YouTube videos and subscribing on Telegram.",
        "expected_id": "scam_job_part_time_reviews",
        "category": "scam",
    },
    {
        "query": "Power bill unpaid electricity will be disconnected tonight at 9:30 PM call electricity officer immediately.",
        "expected_id": "scam_electricity_disconnection",
        "category": "scam",
    },
    {
        "query": "Your international courier package from UK is on hold at customs clearance pay tax duty charges immediately.",
        "expected_id": "scam_courier_customs_fee",
        "category": "scam",
    },
    {
        "query": "Join exclusive WhatsApp VIP stock trading group with guaranteed 500% profits on cryptocurrency and institutional calls.",
        "expected_id": "scam_crypto_stock_tips",
        "category": "scam",
    },
    {
        "query": "Customer support representative asking you to install AnyDesk or TeamViewer to fix bank app transfer problem.",
        "expected_id": "scam_remote_access_anydesk",
        "category": "scam",
    },
    {
        "query": "Dear customer share the 6 digit OTP password sent to your mobile to prevent immediate credit card cancellation.",
        "expected_id": "scam_otp_cvv_theft",
        "category": "scam",
    },

    # --- Deliberately Unrelated / Adversarial Near-Miss Distractors (7) -> Expected: None ---
    {
        "query": "Salary scale and recruitment vacancy for solar panel installation engineers in Bangalore",
        "expected_id": None,
        "category": "adversarial",
    },
    {
        "query": "Online traffic police e-challan receipt download and fine payment portal",
        "expected_id": None,
        "category": "adversarial",
    },
    {
        "query": "Review of new Christopher Nolan sci-fi movie in IMAX 3D with mind bending soundtrack",
        "expected_id": None,
        "category": "unrelated",
    },
    {
        "query": "How to bake a sourdough bread loaf with crispy crust and soft crumb at home",
        "expected_id": None,
        "category": "unrelated",
    },
    {
        "query": "Electricity consumption formula: calculate watts to kilowatt-hours on home refrigerator compressor",
        "expected_id": None,
        "category": "adversarial",
    },
    {
        "query": "Stock market closing report: Nifty 50 and Sensex finish higher led by IT and banking shares",
        "expected_id": None,
        "category": "adversarial",
    },
    {
        "query": "Government issues weather advisory for heavy rainfall and waterlogging across coastal regions",
        "expected_id": None,
        "category": "adversarial",
    },
]


async def run_eval():
    await connection.init_db()
    async with connection.session_factory()() as session:
        # Ingest KB to ensure fresh, complete state
        stats = await ingest_all(session)
        print(f"Loaded Knowledge Base: {stats['total']} documents ({stats['schemes']} schemes, {stats['scam_templates']} scams, {stats['helpline']} helpline, {stats['incidents']} incidents, {stats['known_patterns']} known patterns)\n")

        tp = 0  # Expected a doc and got the right doc
        fp = 0  # Expected None but got a doc, OR expected Doc A but got Doc B
        tn = 0  # Expected None and got None
        fn = 0  # Expected a doc but got None (below threshold)

        latencies_ms = []
        detailed_results = []
        misses = []

        print(f"{'#':<3} | {'Cat':<11} | {'Status':<7} | {'Score':<6} | {'Top Match / Expected'}")
        print("-" * 85)

        for i, item in enumerate(EVAL_QUERIES, 1):
            q = item["query"]
            exp = item["expected_id"]
            cat = item["category"]

            t0 = time.perf_counter()
            hits = await retrieve(q, session)
            latency = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(latency)

            top_hit = hits[0] if hits else None
            top_id = top_hit.id if top_hit else None
            top_score = top_hit.score if top_hit else 0.0

            if exp is not None:
                if top_id == exp:
                    status = "TP"
                    tp += 1
                elif top_id is None:
                    status = "FN"
                    fn += 1
                    # Also fetch the score without threshold to know what it was
                    hits_all = await retrieve(q, session, threshold=0.0)
                    raw_score = hits_all[0].score if hits_all else 0.0
                    raw_id = hits_all[0].id if hits_all else None
                    misses.append({
                        "index": i,
                        "query": q,
                        "expected": exp,
                        "actual": f"None (top was '{raw_id}' at {raw_score:.3f}, below 0.60 threshold)",
                        "score": raw_score,
                    })
                else:
                    status = "FP_MISMATCH"
                    fp += 1
                    misses.append({
                        "index": i,
                        "query": q,
                        "expected": exp,
                        "actual": f"{top_id} ({top_score:.3f})",
                        "score": top_score,
                    })
            else:
                if top_id is None:
                    status = "TN"
                    tn += 1
                else:
                    status = "FP_LEAK"
                    fp += 1
                    misses.append({
                        "index": i,
                        "query": q,
                        "expected": "None",
                        "actual": f"{top_id} ({top_score:.3f})",
                        "score": top_score,
                    })

            match_label = f"{top_id or 'None'} (exp: {exp or 'None'})"
            print(f"{i:<3} | {cat:<11} | {status:<7} | {top_score:<6.3f} | {match_label}")

            detailed_results.append({
                "index": i,
                "query": q,
                "category": cat,
                "expected": exp,
                "top_hit_id": top_id,
                "top_hit_score": top_score,
                "status": status,
                "latency_ms": latency,
            })

        print("-" * 85)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = (tp + tn) / len(EVAL_QUERIES)

        latencies_ms.sort()
        p50 = latencies_ms[int(len(latencies_ms) * 0.50)]
        p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
        mean_lat = sum(latencies_ms) / len(latencies_ms)

        print("\n=== EVALUATION SUMMARY ===")
        print(f"Total Queries:      {len(EVAL_QUERIES)}")
        print(f"True Positives:     {tp}")
        print(f"True Negatives:     {tn}")
        print(f"False Positives:    {fp}")
        print(f"False Negatives:    {fn}")
        print(f"Precision:          {precision:.2%}")
        print(f"Recall:             {recall:.2%}")
        print(f"F1 Score:           {f1:.2%}")
        print(f"Overall Accuracy:   {accuracy:.2%}")
        print(f"Latency Mean:       {mean_lat:.2f} ms")
        print(f"Latency p50:        {p50:.2f} ms")
        print(f"Latency p95:        {p95:.2f} ms")

        if misses:
            print(f"\nExact Misses ({len(misses)}):")
            for m in misses:
                print(f"  - Q#{m['index']}: '{m['query']}'")
                print(f"    Expected: {m['expected']} | Actual: {m['actual']}")
        else:
            print("\nZero misses on the evaluation set.")

        return {
            "total": len(EVAL_QUERIES),
            "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "accuracy": accuracy,
            "p50_ms": p50, "p95_ms": p95, "mean_ms": mean_lat,
            "misses": misses,
            "detailed": detailed_results,
        }


if __name__ == "__main__":
    asyncio.run(run_eval())
