# RAG v1 Semantic Retrieval Evaluation Report

## Executive Summary
This document reports the empirical evaluation of FactFlow's scoped, local, no-quota semantic retrieval layer (RAG v1). The evaluation was conducted on branch `shield-integration` on **November 4, 2026**, executing `backend/scripts/eval_retrieval.py` against the ingested knowledge base (40 documents total: 12 verified Indian government schemes, 11 scam templates, 1 helpline, 6 incidents, and 10 known patterns).

Retriever configuration:
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional dense vectors, pure CPU inference, zero network calls, zero LLM calls).
- **Similarity Metric**: In-memory NumPy cosine similarity over unit-normalized vectors.
- **Threshold**: `KB_SIMILARITY_THRESHOLD = 0.60` (conservative cut-off enforcing the hard constraint: *"never fabricate a citation — below threshold returns empty list"*).
- **Target Latency Requirement**: p95 retrieval under 200 ms against the full corpus.

---

## Evaluation Benchmark Dataset
The evaluation set contains **28 curated queries** spanning three categories:
1. **10 Government Scheme Queries**: natural-language queries asking about verified welfare programs (solar electricity, farmer DBT subsidies, health coverage, housing, micro loans, pensions, employment, and digital infrastructure).
2. **11 Scam Template Queries**: real-world phishing and scam messages (digital arrest, bank KYC deactivation, UPI collect fraud, KBC lottery, fake government freebies, YouTube like jobs, electricity disconnection threats, courier customs fees, crypto trading groups, remote access tools, and OTP theft).
3. **7 Distractor Queries (Adversarial Near-Misses and Unrelated)**:
   - 5 adversarial near-misses sharing lexical tokens with schemes or scams (solar technician engineering jobs, traffic police e-challan portals, refrigerator compressor wattage formulas, stock market closing indices, and coastal heavy rainfall advisories).
   - 2 completely unrelated queries (sci-fi movie review, sourdough bread baking recipe).
   - Expected match: `None` (must return empty list).

---

## Quantitative Results

| Metric | Measured Value | Target / Baseline |
| :--- | :--- | :--- |
| **Total Evaluation Queries** | **28** | $\ge 20$ required |
| **True Positives (TP)** | **10** | Correct document retrieved above threshold |
| **True Negatives (TN)** | **7** | Distractor/unrelated query cleanly returned empty list |
| **False Positives (FP)** | **0** | No wrong documents or leaked distractors |
| **False Negatives (FN)** | **11** | Expected document was ranked #1, but fell below 0.60 threshold |
| **Precision** | **100.00%** | When a document is cited, it is 100% relevant |
| **Recall** | **47.62%** | 10 of 21 legitimate queries cleared the 0.60 threshold |
| **F1 Score** | **64.52%** | Harmonic mean of precision and recall |
| **Overall Accuracy** | **60.71%** | $(TP + TN) / Total$ |
| **Distractor Rejection Rate** | **100.00%** | 7 of 7 distractors rejected (0% false alarms) |
| **Mean Retrieval Latency** | **15.44 ms** | In-memory cosine similarity |
| **Median Retrieval Latency (p50)** | **15.44 ms** | |
| **p95 Retrieval Latency** | **17.70 ms** | **< 200 ms required** (over 11× faster than target) |

---

## Query-by-Query Results Log

| # | Category | Query Text | Expected Document | Retrieved Document | Score | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Scheme | PM Surya Ghar rooftop solar 300 units free electricity subsidy | `scheme_pm_surya_ghar` | `scheme_pm_surya_ghar` | 0.621 | **TP** |
| 2 | Scheme | PM Kisan 2000 rupees 17th installment DBT payment status online | `scheme_pm_kisan` | None | 0.503 | **FN** |
| 3 | Scheme | Ayushman Bharat card 5 lakh free hospital treatment eligibility | `scheme_ayushman_bharat` | None | 0.518 | **FN** |
| 4 | Scheme | PMAY urban housing subsidy for pucca house home loan interest subsidy | `scheme_pmay_urban` | None | 0.584 | **FN** |
| 5 | Scheme | Pradhan Mantri Mudra Yojana business loan up to 10 lakh for micro enterprise | `scheme_pm_mudra` | `scheme_pm_mudra` | 0.755 | **TP** |
| 6 | Scheme | Pradhan Mantri Jan Dhan Yojana zero balance bank account opening overdraft RuPay card | `scheme_pmjdy` | None | 0.470 | **FN** |
| 7 | Scheme | Pradhan Mantri Ujjwala Yojana free LPG cooking gas cylinder connection BPL households | `scheme_pm_ujjwala` | `scheme_pm_ujjwala` | 0.679 | **TP** |
| 8 | Scheme | Atal Pension Yojana monthly guaranteed pension after 60 years | `scheme_atal_pension` | None | 0.548 | **FN** |
| 9 | Scheme | National Career Service NCS government portal job fair vacancies counselling | `scheme_national_career_service` | `scheme_national_career_service` | 0.708 | **TP** |
| 10 | Scheme | Digital India government initiative online digital public infrastructure electronic services | `scheme_digital_india` | `scheme_digital_india` | 0.801 | **TP** |
| 11 | Scam | CBI Police Skype video call digital arrest illegal narcotics parcel | `scam_digital_arrest` | `scam_digital_arrest` | 0.701 | **TP** |
| 12 | Scam | Bank account deactivated within 24 hours pending PAN KYC update verify | `scam_kyc_block` | `scam_kyc_block` | 0.630 | **TP** |
| 13 | Scam | Scan QR code and enter UPI MPIN to receive buyer payment refund Google Pay | `scam_upi_collect` | None | 0.483 | **FN** |
| 14 | Scam | Won 25 Lakh in KBC WhatsApp lucky draw call manager pay registration GST fee | `scam_lottery_kbc` | `scam_lottery_kbc` | 0.784 | **TP** |
| 15 | Scam | Free laptops and smartphones under new yojana forward to 10 WhatsApp groups | `scam_fake_scheme_freebie` | `scam_fake_scheme_freebie` | 0.703 | **TP** |
| 16 | Scam | Earn 3000 daily part time work from home liking YouTube videos Telegram | `scam_job_part_time_reviews` | `scam_job_part_time_reviews` | 0.676 | **TP** |
| 17 | Scam | Power bill unpaid electricity disconnected tonight 9:30 PM call officer | `scam_electricity_disconnection` | None | 0.568 | **FN** |
| 18 | Scam | International courier package from UK on hold customs clearance pay tax duty | `scam_courier_customs_fee` | None | 0.484 | **FN** |
| 19 | Scam | WhatsApp VIP stock trading group guaranteed 500% profits crypto institutional calls | `scam_crypto_stock_tips` | None | 0.550 | **FN** |
| 20 | Scam | Customer support install AnyDesk or TeamViewer fix bank app transfer problem | `scam_remote_access_anydesk` | None | 0.459 | **FN** |
| 21 | Scam | Share 6 digit OTP password sent to mobile prevent credit card cancellation | `scam_otp_cvv_theft` | None | 0.526 | **FN** |
| 22 | Distractor | Salary scale recruitment vacancy solar panel engineers Bangalore | None | None | 0.225 | **TN** |
| 23 | Distractor | Online traffic police e-challan receipt download fine payment portal | None | None | 0.364 | **TN** |
| 24 | Distractor | Review of Christopher Nolan sci-fi movie in IMAX 3D mind bending soundtrack | None | None | 0.096 | **TN** |
| 25 | Distractor | How to bake sourdough bread loaf with crispy crust and soft crumb at home | None | None | 0.082 | **TN** |
| 26 | Distractor | Electricity consumption formula calculate watts to kilowatt-hours refrigerator | None | None | 0.169 | **TN** |
| 27 | Distractor | Stock market closing report Nifty 50 Sensex finish higher IT banking shares | None | None | 0.270 | **TN** |
| 28 | Distractor | Government issues weather advisory heavy rainfall waterlogging coastal regions | None | None | 0.193 | **TN** |

---

## Honest Analysis of Misses and Trade-offs

### 1. Zero False Positives vs Moderate Recall
- **100% Precision**: Across all 28 queries, the retrieval system did not return a single incorrect document and did not leak a single distractor or unrelated query.
- **Why Recall is 47.62%**: In all 11 False Negatives, **the top retrieved document was the exact correct target document** (for example, Q#2 matched `scheme_pm_kisan` as #1 candidate, Q#4 matched `scheme_pmay_urban` as #1 candidate, Q#17 matched `scam_electricity_disconnection` as #1 candidate). However, their raw cosine similarity scores ranged from **0.459 to 0.584**, which fell just below the configured threshold of `0.60`.
- Because the system strictly enforces the hard constraint (*"never fabricate a citation — if below threshold, return empty list"*), these 11 queries returned `None`.

### 2. Threshold Safety Margin
- The highest-scoring adversarial distractor in the benchmark was Q#23 (*"traffic police e-challan fine payment"*), which scored **0.364** against the courier fee document.
- Setting the threshold at **0.60** provides a **0.236 safety margin** above the worst-case distractor, completely preventing false citations.
- Lowering the threshold to **0.50** would boost recall from 47.6% to 81.0% (recovering 7 of the 11 misses), but would narrow the safety margin against sophisticated adversarial near-misses. For v1, maintaining 100% precision with zero fabricated citations was prioritized.

### 3. Latency Verification
- **Target**: p95 retrieval latency under 200 ms.
- **Measured**: **15.44 ms (median)**, **17.70 ms (p95)**.
- Pure in-memory vector dot product via NumPy is over **11× faster** than the budget ceiling.
