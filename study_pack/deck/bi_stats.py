"""Compute the BI figures for the defence deck from the database, and check them.

    python study_pack/deck/bi_stats.py      ->  study_pack/deck/bi_stats.json

Every number on the deck's insight and question slides comes from this file.

* The ten answers are re-run with the delivered reference SQL (snapshotted from
  fc0c281 in study_pack/sources/delivered/reference_results.json) and must match
  the delivered rows exactly, or the script stops.
* Q9 is the exception: this database holds the post-delivery month-end table
  (D028), so the delivered rule (last posting on or before the month end,
  same-day ties to the highest trans_id) is rebuilt here, and must reproduce the
  delivered 43,808.94 / median / min / max / overdrawn count.
* Spread statistics: sample standard deviation, percentiles by linear
  interpolation (the same as PostgreSQL percentile_cont), outliers by Tukey's
  fences (below Q1 - 1.5 IQR or above Q3 + 1.5 IQR).
* Proportions get a 95% Wilson interval; Q10's top group is compared with the
  rest by a two-sided Fisher exact test.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psycopg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import config  # noqa: E402

REF = json.loads((ROOT / "study_pack" / "sources" / "delivered" / "reference_results.json").read_text())["results"]
OUT = HERE / "bi_stats.json"
PCTS = [1, 5, 25, 50, 75, 95, 99]

# The delivered month-end rule, for one date: each account's last posting on or before it,
# same-day ties broken by the highest trans_id (D019 / A14 as delivered).
DELIVERED_BALANCE_SQL = """
SELECT DISTINCT ON (account_id) account_id, balance_after AS closing_balance, trans_date
FROM core.fact_transaction
WHERE trans_date <= DATE '1998-12-31'
ORDER BY account_id, trans_date DESC, trans_id DESC
"""


def rows(cur, sql, *args):
    cur.execute(sql, args)
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def num(x):
    if x is None:
        return None
    if isinstance(x, (int, np.integer)):
        return int(x)
    return float(x)


def clean(r):
    return {k: num(v) if not isinstance(v, str) else v for k, v in r.items()}


def dist(values, weights_are_values=True):
    """Mean, sample SD, percentiles and Tukey outliers of a list of numbers."""
    a = np.asarray([float(v) for v in values if v is not None])
    p = {str(q): float(np.percentile(a, q)) for q in PCTS}
    q1, q3 = p["25"], p["75"]
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out_lo, out_hi = a[a < lo], a[a > hi]
    d = {
        "n": int(a.size), "mean": float(a.mean()), "sd": float(a.std(ddof=1)),
        "min": float(a.min()), "max": float(a.max()), "p": p, "iqr": iqr,
        "fence_lo": lo, "fence_hi": hi,
        "out_lo": int(out_lo.size), "out_hi": int(out_hi.size),
        "out_pct": 100.0 * (out_lo.size + out_hi.size) / a.size,
        "z3": int((np.abs(a - a.mean()) > 3 * a.std(ddof=1)).sum()),
        # whiskers drawn on the deck: the most extreme values still inside the fences
        "whisker_lo": float(a[a >= lo].min()), "whisker_hi": float(a[a <= hi].max()),
    }
    if weights_are_values and a.min() >= 0:
        d["out_hi_share_of_sum"] = 100.0 * float(out_hi.sum()) / float(a.sum())
        top = np.sort(a)[::-1]
        d["top1pct_share_of_sum"] = 100.0 * float(top[: max(1, a.size // 100)].sum()) / float(a.sum())
    return d


def wilson(k, n, z=1.959964):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [100 * (c - h), 100 * (c + h)]


def fisher_two_sided(a, b, c, d):
    """Two-sided Fisher exact p for [[a, b], [c, d]] (sum of tables as or less likely)."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d

    def prob(x):
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    p0 = prob(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p0 * (1 + 1e-9))


def mean_ci(sd, n, z=1.959964):
    return z * sd / math.sqrt(n)


def check(label, got, want):
    g = [clean(r) for r in got]
    w = [clean(r) for r in want]
    if g != w:
        raise SystemExit(f"{label}: database result differs from the delivered reference\n got  {g[:3]}\n want {w[:3]}")
    print(f"  {label}: matches the delivered reference ({len(g)} rows)")


def main():
    S = {"generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "command": "python study_pack/deck/bi_stats.py",
         "source": "PostgreSQL core schema; Q1-Q8 and Q10 re-run with the delivered reference SQL and checked "
                   "against study_pack/sources/delivered/reference_results.json; Q9 with the delivered highest-trans_id rule",
         "method": {"sd": "sample standard deviation (n - 1)", "percentiles": "linear interpolation (= percentile_cont)",
                    "outliers": "Tukey fences: below Q1 - 1.5 IQR or above Q3 + 1.5 IQR",
                    "ci": "95% Wilson interval for shares; mean +/- 1.96 SD / sqrt(n) for means",
                    "test": "two-sided Fisher exact test"}}
    with psycopg.connect(config.dsn()) as con, con.cursor() as cur:
        print("checking the ten answers against the delivered reference ...")
        q = {}
        for k in ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q10"]:
            got = rows(cur, REF[k]["sql"])
            check(k, got, REF[k]["rows"])
            q[k] = {"rows": [clean(r) for r in REF[k]["rows"]]}

        # Q9 with the delivered rule
        bal = rows(cur, DELIVERED_BALANCE_SQL)
        b = np.asarray([float(r["closing_balance"]) for r in bal])
        q9ref = REF["Q9"]["rows"][0]
        got9 = {"accounts_with_known_balance": int(b.size), "average_balance": round(float(b.mean()), 2),
                "median_balance": round(float(np.percentile(b, 50)), 2), "min_balance": float(b.min()),
                "max_balance": float(b.max()), "accounts_overdrawn": int((b < 0).sum()),
                "accounts_carried_forward": sum(1 for r in bal if r["trans_date"] < datetime(1998, 12, 1).date())}
        for key, val in got9.items():
            if abs(val - float(q9ref[key])) > 0.005:
                raise SystemExit(f"Q9 {key}: {val} differs from delivered {q9ref[key]}")
        print(f"  Q9: delivered rule reproduces {got9['average_balance']:,.2f} over {got9['accounts_with_known_balance']} accounts")
        bd = dist(b, weights_are_values=False)
        edges = [-30000, 0, 20000, 40000, 60000, 80000, 100000, 140000]
        names = ["< 0", "0–20", "20–40", "40–60", "60–80", "80–100", "≥ 100"]  # thousand CZK
        hist = [int(((b >= edges[i]) & (b < edges[i + 1])).sum()) for i in range(len(names))]
        q["Q9"] = {"rows": [clean(q9ref)], "dist": bd, "hist": {"labels": names, "values": hist}}

        # --- spread inside the answers
        L = rows(cur, "SELECT loan_year, amount, status_code, is_problematic, statement_frequency, "
                      "coalesce(owner_card_type, 'no card') AS card, owner_age_at_loan_start AS age, duration_months, "
                      "monthly_payment FROM core.v_loan_enriched")
        by = lambda key: {v: [r for r in L if r[key] == v] for v in sorted({r[key] for r in L})}
        q["Q2"]["sd_by_year"] = {str(y): float(np.std([float(r["amount"]) for r in rs], ddof=1)) for y, rs in by("loan_year").items()}
        q["Q4"]["by_card"] = {c: {"n": len(rs), "sd": float(np.std([float(r["amount"]) for r in rs], ddof=1)),
                                  "median": float(np.median([float(r["amount"]) for r in rs]))}
                              for c, rs in by("card").items()}
        for c, v in q["Q4"]["by_card"].items():
            v["ci95"] = mean_ci(v["sd"], v["n"])
        q["Q7"]["by_status"] = {}
        for s_, rs in by("status_code").items():
            ages = [float(r["age"]) for r in rs if r["age"] is not None]
            sd = float(np.std(ages, ddof=1))
            q["Q7"]["by_status"][s_] = {"n": len(ages), "sd": sd, "ci95": mean_ci(sd, len(ages)),
                                        "min": min(ages), "max": max(ages), "under_15": sum(1 for a in ages if a < 15)}
        q3 = REF["Q3"]["rows"][0]
        q["Q3"]["ci95"] = wilson(q3["problematic_loans"], q3["total_loans"])
        vol_bad = sum(float(r["amount"]) for r in L if r["is_problematic"])
        vol_all = sum(float(r["amount"]) for r in L)
        q["Q3"]["share_by_volume"] = 100 * vol_bad / vol_all
        q["Q3"]["by_status"] = {s_: len(rs) for s_, rs in by("status_code").items()}
        f = REF["Q10"]["rows"]
        for r in q["Q10"]["rows"]:
            r["ci95"] = wilson(r["problematic_loans"], r["loans"])
        top = f[0]
        rest_k = sum(r["problematic_loans"] for r in f[1:])
        rest_n = sum(r["loans"] for r in f[1:])
        q["Q10"]["fisher_p_top_vs_rest"] = fisher_two_sided(top["problematic_loans"], top["loans"] - top["problematic_loans"],
                                                             rest_k, rest_n - rest_k)
        q["Q10"]["overall_pct"] = 100 * q3["problematic_loans"] / q3["total_loans"]
        g = REF["Q8"]["rows"]
        male = next(r for r in g if r["gender"] == "male")
        q["Q8"]["male_ci95"] = wilson(male["gold_card_owners"], sum(r["gold_card_owners"] for r in g))
        own = rows(cur, "SELECT owner_gender AS g, count(*) AS n FROM core.v_account_owner GROUP BY 1")
        q["Q8"]["male_pct_all_owners"] = 100 * sum(r["n"] for r in own if r["g"] == "male") / sum(r["n"] for r in own)
        m6 = np.asarray([r["accounts_opened"] for r in REF["Q6"]["rows"]], dtype=float)
        q["Q6"]["mean"], q["Q6"]["sd"] = float(m6.mean()), float(m6.std(ddof=1))
        q["Q6"]["z_max"] = float((m6.max() - m6.mean()) / m6.std(ddof=1))
        inc = rows(cur, "SELECT sum(t.amount) AS total, count(DISTINCT t.account_id) AS accounts FROM core.fact_transaction t "
                        "WHERE t.direction = 'credit' AND t.trans_date BETWEEN DATE '1997-01-01' AND DATE '1997-12-31'")[0]
        q["Q5"]["total_incoming_1997"] = float(inc["total"])
        q["Q5"]["accounts_with_incoming_1997"] = int(inc["accounts"])
        q["Q5"]["per_account"] = {r["district_name"]: float(r["total_incoming_amount"]) / r["accounts"] for r in REF["Q5"]["rows"]}
        q1 = REF["Q1"]["rows"]
        S["q"] = q

        # --- found insights: clients
        C = rows(cur, "SELECT gender, (DATE '1998-12-31' - birth_date) / 365.25 AS age FROM core.dim_client")
        ages = [float(r["age"]) for r in C if r["age"] is not None]
        bands = [("< 20", 0, 20), ("20–29", 20, 30), ("30–39", 30, 40), ("40–49", 40, 50), ("50–59", 50, 60),
                 ("60–69", 60, 70), ("70+", 70, 200)]
        roles = rows(cur, "SELECT disposition_type AS role, count(*) AS n FROM core.bridge_disposition GROUP BY 1 ORDER BY 2 DESC")
        S["clients"] = {
            "n": len(C),
            "gender": {g_: sum(1 for r in C if r["gender"] == g_) for g_ in ("male", "female")},
            "age": dist(ages, weights_are_values=False),
            "age_bands": {"labels": [b_[0] for b_ in bands], "values": [sum(1 for a in ages if b_[1] <= a < b_[2]) for b_ in bands]},
            "under_18": sum(1 for a in ages if a < 18),
            "roles": [clean(r) for r in roles],
            "regions_top2_pct": q1[0]["pct_of_clients"] + q1[1]["pct_of_clients"],
        }

        # --- found insights: money flow
        T = rows(cur, "SELECT amount, direction FROM core.fact_transaction")
        amt = [float(r["amount"]) for r in T]
        S["money"] = {
            "n": len(T), "volume": float(sum(amt)),
            "amount": dist(amt),
            "by_direction": [clean(r) for r in rows(cur, "SELECT direction, count(*) AS n, sum(amount) AS volume "
                                                          "FROM core.fact_transaction GROUP BY 1 ORDER BY 1")],
            "by_year": [clean(r) for r in rows(cur, "SELECT extract(year FROM trans_date)::int AS year, count(*) AS n, "
                                                     "sum(amount) AS volume FROM core.fact_transaction GROUP BY 1 ORDER BY 1")],
            "by_operation": [clean(r) for r in rows(cur, "SELECT coalesce(operation, 'interest (no operation)') AS operation, "
                                                          "count(*) AS n, sum(amount) AS volume FROM core.fact_transaction "
                                                          "GROUP BY 1 ORDER BY 3 DESC")],
            "by_category": [clean(r) for r in rows(cur, "SELECT coalesce(category, '(no category)') AS category, count(*) AS n, "
                                                         "sum(amount) AS volume FROM core.fact_transaction GROUP BY 1 ORDER BY 3 DESC")],
        }

        # --- found insights: loans
        amounts = [float(r["amount"]) for r in L]
        dur = {}
        for r in L:
            d_ = dur.setdefault(int(r["duration_months"]), [0, 0])
            d_[0] += 1
            d_[1] += 1 if r["is_problematic"] else 0
        S["loans"] = {
            "n": len(L), "volume": vol_all,
            "amount": dist(amounts), "payment": dist([float(r["monthly_payment"]) for r in L]),
            "status": q["Q3"]["by_status"],
            "by_duration": [{"months": m, "loans": v[0], "problematic": v[1], "pct": 100 * v[1] / v[0], "ci95": wilson(v[1], v[0])}
                            for m, v in sorted(dur.items())],
            "avg_amount_problematic": float(np.mean([float(r["amount"]) for r in L if r["is_problematic"]])),
            "avg_amount_ok": float(np.mean([float(r["amount"]) for r in L if not r["is_problematic"]])),
            "share_by_volume": q["Q3"]["share_by_volume"],
        }

        # --- found insights: accounts and cards
        S["accounts"] = {
            "n": rows(cur, "SELECT count(*) AS n FROM core.dim_account")[0]["n"],
            "frequency": [clean(r) for r in rows(cur, "SELECT statement_frequency AS f, count(*) AS n FROM core.dim_account "
                                                       "GROUP BY 1 ORDER BY 2 DESC")],
            "opened_by_year": [clean(r) for r in rows(cur, "SELECT extract(year FROM open_date)::int AS year, count(*) AS n "
                                                            "FROM core.dim_account GROUP BY 1 ORDER BY 1")],
            "with_loan": rows(cur, "SELECT count(DISTINCT account_id) AS n FROM core.fact_loan")[0]["n"],
            "cards": [clean(r) for r in rows(cur, "SELECT card_type AS t, count(*) AS n FROM core.dim_card GROUP BY 1 ORDER BY 2 DESC")],
            "owners_with_card": rows(cur, "SELECT count(*) AS n FROM core.v_account_owner WHERE owner_card_id IS NOT NULL")[0]["n"],
            "card_owner_age": {r["t"]: clean({k_: v for k_, v in r.items() if k_ != "t"}) for r in rows(cur,
                "SELECT owner_card_type AS t, min((DATE '1998-12-31' - owner_birth_date) / 365.25) AS min, "
                "avg((DATE '1998-12-31' - owner_birth_date) / 365.25) AS mean, max((DATE '1998-12-31' - owner_birth_date) / 365.25) AS max, "
                "count(*) FILTER (WHERE (DATE '1998-12-31' - owner_birth_date) / 365.25 < 18) AS under_18 "
                "FROM core.v_account_owner WHERE owner_card_type IS NOT NULL GROUP BY 1")},
            "balance": bd,
        }
    OUT.write_text(json.dumps(S, indent=1, ensure_ascii=False, default=num) + "\n")
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
