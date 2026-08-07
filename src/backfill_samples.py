"""One-time backfill of the 8 seed reports, extracted by reading each PDF.

This is the "existing-plan" extraction: I (the model) read each report's text
and produced these structured records. The nightly job does the same for new
files via headless Claude Code. Run once:  python src/backfill_samples.py
"""
from __future__ import annotations
from db import init
from ingest import ingest_record

RECORDS = [
    # 1 — SBI Securities · JTL Industries (Initiating Coverage, BUY)
    ("SBI_Securities_Initiating_Coverage_on_JTL_Industries_Ltd_,_with.pdf", {
        "report_type": "analyst", "broker": "SBI Securities",
        "analyst": "Harsh N. Vasa", "report_date": "2026-08-04",
        "parse_status": "ok",
        "calls": [{
            "ticker": "JTLIND.NS", "company_raw": "JTL Industries",
            "sector": "Iron & Steel Products", "rating": "BUY",
            "rating_raw": "Buy", "rating_action": "initiate",
            "cmp": 75.7, "target_price": 127.0, "horizon_months": 12,
            "thesis": "Capacity set to double to 18.36 lakh MTPA by FY28E with a "
                      "decisive shift to high-margin value-added products (VAP share "
                      "21%->55%), driving a sharp step-up in earnings and return ratios. "
                      "Valued at 18x FY28E EPS of Rs6.5 via SOTP.",
            "drivers": ["Installed capacity doubling to 18.36 lakh MTPA by FY28E",
                        "VAP mix rising from ~21% (FY26) to ~55% (FY28E), lifting EBITDA/t",
                        "RoE/RoCE expanding from 6.6%/8.5% to 13.6%/15.1% by FY28E",
                        "Backward integration via Nabha Steels + JTL Defence entry"],
            "risks": ["Steel price cyclicality", "Execution risk on large capex ramp",
                      "Working-capital intensity during expansion"],
            "estimates": {"Rev CAGR FY26-28E": "44.1%", "EBITDA CAGR": "59.0%",
                          "PAT CAGR": "60.5%", "FY28E EPS": "Rs6.5", "Target P/E": "18x"},
        }],
    }),
    # 2 — 360 ONE Capital · Sanathan Textiles (Initiating Coverage, BUY)
    ("360_ONE_Capital_Initiating_Coverage_on_Sanathan_Textiles,_with_28.pdf", {
        "report_type": "analyst", "broker": "360 ONE Capital",
        "analyst": "Aradhana Jain", "report_date": "2026-08-01",
        "parse_status": "ok",
        "calls": [{
            "ticker": "SANATHAN.NS", "company_raw": "Sanathan Textiles",
            "sector": "Textiles", "rating": "BUY",
            "rating_raw": "Buy", "rating_action": "initiate",
            "cmp": 475.0, "target_price": 608.0, "horizon_months": 12,
            "thesis": "Entering its strongest earnings, return-ratio and cash-flow phase "
                      "as the ~Rs22bn Punjab capex monetises; sales/EBITDA/PAT CAGR of "
                      "23%/41%/72% over FY26-29E. Valued at 14x June-28 EPS.",
            "drivers": ["Punjab facility cost edge: EBITDA/t Rs13,000-13,500 vs Rs8,500-9,000 at Silvassa",
                        "Three growth engines: PFY, cotton and technical textiles",
                        "PFY market share rising ~8% -> ~12% post Phase II",
                        "RoE improving from ~4% (FY26) to ~14% (FY29E) as leverage falls"],
            "risks": ["Peak net debt ~Rs13bn in FY26", "Polyester/PFY commodity cyclicality",
                      "Execution across multiple simultaneous expansions"],
            "estimates": {"Sales CAGR FY26-29E": "23%", "EBITDA CAGR": "41%",
                          "PAT CAGR": "72%", "EBITDA margin": "7.5%->11%", "Target": "14x Jun-28 EPS"},
        }],
    }),
    # 3 — Equirus Securities · Lloyds Engineering Works (Initiating Coverage, BUY)
    ("Equirus_Securities_Initiating_Coverage_on_LLOYDS_ENGINEERING_WORKS (1).pdf", {
        "report_type": "analyst", "broker": "Equirus Securities",
        "analyst": "Pankaj Motwani", "report_date": "2026-08-03",
        "parse_status": "ok",
        "calls": [{
            "ticker": "LLOYDSENGG.NS", "company_raw": "Lloyds Engineering Works",
            "sector": "Industrial Products", "rating": "BUY",
            "rating_raw": "Buy", "rating_action": "initiate",
            "cmp": 89.0, "target_price": 125.0, "horizon_months": 13,
            "thesis": "Management-led turnaround under the returning Gupta family, riding "
                      "India's steel, infrastructure and defence capex cycles; acquisitions "
                      "and a proposed merger create a vertically integrated engineering "
                      "platform. Sep'27 SOTP TP implies 37x 1-yr forward P/E.",
            "drivers": ["Mining-to-Metal platform into India's 300MT-by-FY31 steel capex",
                        "Defence/naval franchise: per-ship opportunity 80-100mn -> 400-500mn",
                        "Acquisitions (SISCOL, Metalfab, Techno) broadening addressable market",
                        "Proposed LICL/Metalfab/Techno merger, EPS-accretive"],
            "risks": ["Rich valuation (44x/32x FY27E/FY28E P/E)",
                      "Execution on acquisitions and merger integration",
                      "Dependence on the industrial capex cycle"],
            "estimates": {"Rev CAGR FY26-29E": "62.7%", "EBITDA CAGR": "68.4%",
                          "PAT CAGR": "47.4%", "Target": "37x 1-yr fwd P/E (Sep'27)"},
        }],
    }),
    # 4 — Centrum · BSE (Result Update, Neutral, TP revised 3,902 -> 3,940)
    ("BSE_Q1FY27_Result_Update_Centrum_0508206.pdf", {
        "report_type": "analyst", "broker": "Centrum Broking",
        "analyst": "Mohit Mangal", "report_date": "2026-08-05",
        "parse_status": "ok",
        "calls": [{
            "ticker": "BSE.NS", "company_raw": "BSE Ltd",
            "sector": "Exchanges", "rating": "HOLD",
            "rating_raw": "Neutral", "rating_action": "reiterate",
            "cmp": 3618.0, "target_price": 3940.0, "prior_target": 3902.0,
            "horizon_months": 12,
            "thesis": "Healthy Q1 (revenue +63% YoY, PAT +66%) driven by a 93% jump in "
                      "equity derivatives, but the July-1 regulatory changes temper the "
                      "options-volume outlook. Valued at 42x Sep'28E EPS (cut from 44x). "
                      "Maintain Neutral.",
            "drivers": ["Equity derivatives revenue +93% YoY", "Continued market-share gains and FPI onboarding",
                        "Target of double-digit cash-market share by early CY2027"],
            "risks": ["July-1 regulatory changes weighing on options volumes",
                      "ADTO moderation (Rs297bn -> Rs254bn into July)",
                      "Cybersecurity threats"],
            "estimates": {"Rev CAGR FY26-29E": "19%", "PAT CAGR": "18%",
                          "Target multiple": "42x Sep'28E EPS"},
        }],
    }),
    # 5 — Motilal Oswal Morning India · Trent (Result Update, reiterate BUY)
    ("MORNING_INDIA-20260807-MOFSL-MI-PG072.pdf", {
        "report_type": "analyst", "broker": "Motilal Oswal",
        "analyst": "Motilal Oswal Research", "report_date": "2026-08-07",
        "parse_status": "ok",
        "calls": [{
            "ticker": "TRENT.NS", "company_raw": "Trent Ltd",
            "sector": "Retail", "rating": "BUY",
            "rating_raw": "Buy", "rating_action": "reiterate",
            "cmp": 3107.0, "target_price": 3775.0, "horizon_months": 12,
            "thesis": "Another quarter of strong margin performance despite muted LFL; "
                      "standalone pre-IND AS EBITDA/PAT +36%/+26% YoY. Reiterate BUY at "
                      "40x Sep'28E pre-IND AS EV/EBITDA even as valuations stay demanding "
                      "(62x FY28 EPS).",
            "drivers": ["Gross/EBITDA margin expansion of 150bp/195bp YoY",
                        "33% YoY store additions, Zudio scaling in tier 2/3",
                        "FY26-29E standalone rev/EBITDA/PAT CAGR ~21%/26%/19%"],
            "risks": ["Demanding valuation (62x FY28 EPS)", "Raw-material inflation and supply-chain risk",
                      "~10% YoY SPSF decline / soft like-for-like growth"],
            "estimates": {"Std rev CAGR FY26-29E": "21%", "EBITDA CAGR": "26%",
                          "PAT CAGR": "19%", "Target": "40x Sep'28E EV/EBITDA"},
        }],
    }),
    # 6 — Nuvama · Textiles sector report (market) + 3 initiating-coverage calls
    ("Nuvama Report on Textiles- The Loom Turns Toward India.pdf", {
        "report_type": "market", "broker": "Nuvama Institutional Equities",
        "analyst": "Ashish K. Vanwari", "report_date": "2026-07-15",
        "parse_status": "ok",
        "market": {
            "theme": "Indian Textiles — The Loom Turns Toward India",
            "sectors": ["Textiles", "Apparel", "Home Textiles", "Technical Textiles"],
            "summary": "The USD1.6tn global textile industry is mid the largest sourcing "
                       "reallocation in two decades: China's share of US apparel imports has "
                       "halved, and India — for the first time since the quota era — competes "
                       "without a structural handicap. India leads at the front of the chain "
                       "(cotton, spinning) but is under-built in man-made fibre and short on "
                       "apparel trade access.",
            "outlook": "Structural tailwinds now aligning: tariff parity for non-China "
                       "producers, UK CETA in force (Jul-15-2026) and an EU FTA in negotiation, "
                       "and a completed US inventory correction reviving orders. Top picks: "
                       "Arvind, Sanathan and Indo Count.",
            "key_points": ["China's US apparel-import share halved over 10 years",
                           "India's EU apparel share stuck ~3% vs Bangladesh 16.7% — access is the swing factor",
                           "US retail sales USD5.3tn (FY19) -> USD7.2tn (FY24); de-stocking done",
                           "Risks: US tariff reversal, EU FTA delay, cotton-price volatility, Chinese MMF overcapacity, capex execution"],
        },
        "calls": [
            {"ticker": "KPRMILL.NS", "company_raw": "KPR Mill", "sector": "Textiles",
             "rating": "BUY", "rating_raw": "Initiating (top pick space)",
             "rating_action": "initiate", "target_price": 1276.0, "horizon_months": 12,
             "thesis": "Initiated in Nuvama's textiles coverage as one of the sector's most "
                       "ambitious capacity expanders amid the India sourcing shift.",
             "drivers": ["Integrated model", "Garmenting expansion"], "risks": ["Cotton price volatility"]},
            {"ticker": "ICIL.NS", "company_raw": "Indo Count Industries", "sector": "Home Textiles",
             "rating": "BUY", "rating_raw": "Initiating (top pick)",
             "rating_action": "initiate", "target_price": 541.0, "horizon_months": 12,
             "thesis": "Top pick; home-textiles leader positioned for US sourcing shift away from China.",
             "drivers": ["US home-textiles share gains", "Capacity expansion"], "risks": ["US demand", "Cotton prices"]},
            {"ticker": "SANATHAN.NS", "company_raw": "Sanathan Textiles", "sector": "Textiles",
             "rating": "BUY", "rating_raw": "Initiating (top pick)",
             "rating_action": "initiate", "target_price": 585.0, "horizon_months": 12,
             "thesis": "Top pick; MMF/PFY expander well placed as India builds man-made-fibre capacity.",
             "drivers": ["Punjab PFY expansion", "MMF penetration"], "risks": ["PFY cyclicality", "Leverage"]},
        ],
    }),
    # 7 — Axis Direct · Monthly Quant Report (market/strategy)
    ("Axis-Direct-Monthly-Quant-Report-August-2026 (1).pdf", {
        "report_type": "market", "broker": "Axis Direct",
        "analyst": "Axis Direct Quant", "report_date": "2026-08-01",
        "parse_status": "ok",
        "market": {
            "theme": "August 2026 Quant Strategy — Value-Momentum Barbell",
            "sectors": ["Factor strategy", "Broad market"],
            "summary": "The quant macro dashboard confirms a shift into an 'Expansion' regime "
                       "on stronger domestic activity and stabilising liquidity, yet the "
                       "headline market stays choppy with risk-adjusted returns compressing "
                       "across factors. Classic defensives (Low Volatility, Quality) are "
                       "actively destroying capital.",
            "outlook": "Maintain a pro-cyclical stance via a Value 30% / Momentum 30% barbell "
                       "with Growth 20% as anchor; Value is the primary alpha engine (max "
                       "dispersion) and Momentum a deep-mispricing rebound play. Defensives "
                       "capped at 10% each.",
            "key_points": ["Allocation: Value 30 / Momentum 30 / Growth 20 / Quality 10 / Low Vol 10",
                           "Defensive 'safe' playbook broken — negative risk-adjusted returns",
                           "Model blends macro cycle, absolute trend, factor dispersion, prob-adjusted valuation"],
        },
    }),
    # 8 — Maybank Asset Management · 2026 Outlook (market/macro)
    ("Maybank Asset Management Follow the Earnings. Follow the Fed.pdf", {
        "report_type": "market", "broker": "Maybank Asset Management",
        "analyst": "MAMG", "report_date": "2026-01-01",
        "parse_status": "needs_review",
        "parse_note": "Annual outlook — exact publication date not stated in text; dated to Jan-2026.",
        "market": {
            "theme": "2026 Global Markets Outlook — Follow the Earnings, Follow the Fed",
            "sectors": ["Global equities", "Asian fixed income", "FX & rates", "Sukuk"],
            "summary": "2025 delivered strong returns across assets on resilient earnings, the "
                       "AI capex cycle and a shift to easing, with gold +60% and silver +120%. "
                       "With valuations elevated and the cycle mature, 2026 returns are likely "
                       "more modest and driven by earnings and Fed policy rather than valuation "
                       "rerating.",
            "outlook": "Positive but modest 2026; US GDP seen 2-3%. Earnings the primary equity "
                       "driver as valuations (US near historic highs) leave little room for "
                       "rerating. Follow the earnings, follow the Fed.",
            "key_points": ["Gold +60%, silver +120%, platinum +120% in 2025",
                           "2025 bond markets returned 6-12%",
                           "US budget deficit running 6-7% of GDP",
                           "Tech sector 2025 revenue/earnings growth ~15%/30%"],
        },
    }),
]


def main():
    init()
    n = 0
    for filename, rec in RECORDS:
        rid = ingest_record(filename, rec)
        status = "ingested" if rid != -1 else "already present"
        print(f"  [{status}] {filename}")
        if rid != -1:
            n += 1
    print(f"Backfilled {n} new reports.")


if __name__ == "__main__":
    main()
