"""The Silver agent: conform the data and grade what is wrong with it.

Simulated stand-in for ``sql/10_stg.sql`` plus ``src/dq_runner.py``. It casts
the Bronze text, keeps the original where a cast changed something, and runs a
small rule set that reproduces the production severity framework: ``block``
quarantines, ``warn`` flags, ``info`` records.

Two production lessons are built in rather than described:

* **Silver never filters.** Row counts must equal Bronze's. Deciding a row is
  unusable is a graded verdict that Gold acts on, not a deletion here.
* **A flag must resolve.** A warn finding identified by ``account_id`` but
  recorded against the transaction table reaches nobody. Every rule therefore
  declares which table its business key belongs to.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from berka_control import AcceptanceCheck, LayerAgent, LayerArtifact


class SilverAgent(LayerAgent):
    """Types the Bronze landing and applies the data quality rule set."""

    layer = "silver"

    def work(self, upstream: LayerArtifact | None) -> dict[str, Any]:
        """Cast, decode and grade.

        :param upstream: The Bronze artefact.
        :returns: The Silver payload: conformed tables plus the control plane.
        """
        assert upstream is not None  # guaranteed by the runtime's input gate
        bronze = upstream.payload["tables"]

        tables: dict[str, Any] = {}
        for name, data in bronze.items():
            tables[name] = {
                "grain_key": data["grain_key"],
                "rows": [self._conform(name, row) for row in data["rows"]],
            }

        blocked, flags, info = self._run_rules(tables)

        return {
            "tables": tables,
            "blocked": blocked,
            "flags": flags,
            "info_findings": info,
            "upstream_row_counts": {n: len(d["rows"]) for n, d in bronze.items()},
            "upstream_amount_sums": self._amount_sums(bronze, text=True),
            "amount_sums": self._amount_sums(tables, text=False),
        }

    # -- conforming ---------------------------------------------------------

    def _conform(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """Cast one Bronze row, keeping the original where a cast changed it.

        :param table: Source table name.
        :param row: The all-text Bronze row.
        :returns: A typed row with lineage and a conversion audit.
        """
        out: dict[str, Any] = {"_source_file": row["_source_file"],
                               "_source_row": row["_source_row"],
                               "_conversion_notes": []}
        for column, value in row.items():
            if column.startswith("_"):
                continue
            if column.endswith("_id") or column in {"duration"}:
                out[column] = int(value) if value not in ("", None) else None
            elif column in {"amount", "payments", "balance"}:
                out[column] = float(value) if value not in ("", None) else None
            elif column == "date":
                parsed = self._parse_yymmdd(value)
                out[column] = parsed
                if parsed is None and value:
                    out["_conversion_notes"].append(f"date: unparsable {value}")
                    out["date_raw"] = value
            elif column == "birth_number":
                out[column] = value
                out["birth_date"], out["gender"] = self._decode_birth_number(value)
            else:
                # A quoted empty string and an absent value both become NULL
                # here. This is the layer that is allowed to make that call.
                out[column] = value if value not in ("", None) else None
        return out

    def _parse_yymmdd(self, value: str) -> dt.date | None:
        """Parse a six-digit source date into the century the surface declares.

        :param value: The raw text.
        :returns: The date, or ``None`` when it is not a real calendar date.
        """
        text = (value or "").strip()
        if len(text) != 6 or not text.isdigit():
            return None
        century = int(self.control.constant("century_prefix"))
        try:
            return dt.date(century + int(text[:2]), int(text[2:4]), int(text[4:6]))
        except ValueError:
            return None

    @staticmethod
    def _decode_birth_number(value: str) -> tuple[dt.date | None, str | None]:
        """Decode a Czech birth number into a date and a gender.

        Women carry month + 50.

        :param value: The six-digit birth number.
        :returns: Tuple of (birth date or ``None``, gender or ``None``).
        """
        text = (value or "").strip()
        if len(text) != 6 or not text.isdigit():
            return None, None
        year, month, day = int(text[:2]), int(text[2:4]), int(text[4:6])
        gender = "female" if month > 50 else "male"
        if month > 50:
            month -= 50
        try:
            return dt.date(1900 + year, month, day), gender
        except ValueError:
            return None, gender

    @staticmethod
    def _amount_sums(tables: dict[str, Any], text: bool) -> dict[str, float]:
        """Total the amount column of each table that has one.

        :param tables: Tables to total.
        :param text: Whether the values are still text (Bronze) or cast.
        :returns: Mapping of table name to rounded total.
        """
        sums: dict[str, float] = {}
        for name, data in tables.items():
            values = [row.get("amount") for row in data["rows"] if row.get("amount") not in (None, "")]
            if values:
                sums[name] = round(sum(float(value) for value in values), 2)
        return sums

    # -- the rule set -------------------------------------------------------

    def _run_rules(
        self, tables: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Run the rule set and return the three severities separately.

        A miniature of ``dq/dq_rules.yaml``: one rule per severity, each
        carrying the justification, because the production rule loader refuses
        a rule that has none.

        :param tables: The conformed tables.
        :returns: Tuple of (blocked, flags, info findings).
        """
        blocked: list[dict[str, Any]] = []
        flags: list[dict[str, Any]] = []
        info: list[dict[str, Any]] = []

        # block -- duplicate transaction by business key. The primary key
        # cannot catch it, and it double counts a flow.
        seen: dict[tuple, int] = {}
        for row in tables["trans"]["rows"]:
            key = (row["account_id"], row["date"], row["type"], row["amount"], row["balance"])
            if key in seen:
                blocked.append({
                    "table": "trans",
                    "business_key": str(row["trans_id"]),
                    "rule": "UNQ_TRANS_BUSINESS_KEY",
                    "reason": f"identical in content to trans_id {seen[key]}",
                })
            else:
                seen[key] = row["trans_id"]

        # block -- orphan foreign key. An inner join silently drops it, so the
        # loan would vanish from the answers that reach the account.
        accounts = {row["account_id"] for row in tables["account"]["rows"]}
        for row in tables["loan"]["rows"]:
            if row["account_id"] not in accounts:
                blocked.append({
                    "table": "loan",
                    "business_key": str(row["loan_id"]),
                    "rule": "RI_LOAN_ACCOUNT",
                    "reason": f"account_id {row['account_id']} does not exist",
                })

        # warn -- implausible age. The row stays, because the account and its
        # postings are sound; the flag travels into Gold so a metric can say so.
        min_age = int(self.control.constant("min_age_at_event"))
        by_client = {row["client_id"]: row for row in tables["client"]["rows"]}
        for account in tables["account"]["rows"]:
            owner = by_client.get(account["account_id"])
            if not owner or not owner.get("birth_date") or not account.get("date"):
                continue
            age = (account["date"] - owner["birth_date"]).days / 365.25
            if age < min_age:
                flags.append({
                    # The finding is about an account opening, and the business
                    # key is a client_id, so the flag is recorded against the
                    # CLIENT table. Recording it against 'account' would make it
                    # unresolvable -- the production bug this guards against.
                    "table": "client",
                    "business_key": str(owner["client_id"]),
                    "flag": "val_owner_age_at_account_open",
                    "reason": f"owner was {age:.1f} years old at account opening",
                })

        # info -- zero amount. Blocking these would remove valid postings and
        # break a balance chain to fix nothing, which is the worked example for
        # why severity is about consequence.
        for row in tables["trans"]["rows"]:
            if row.get("amount") == 0:
                info.append({
                    "table": "trans",
                    "business_key": str(row["trans_id"]),
                    "rule": "VAL_TRANS_AMOUNT_POSITIVE",
                    "reason": "amount is exactly zero (interest run that accrued nothing)",
                })

        return blocked, flags, info

    def acceptance_checks(self, payload: dict[str, Any]) -> list[AcceptanceCheck]:
        """Compare the conformed output and the verdicts against the known answer.

        :param payload: What :meth:`work` produced.
        :returns: The acceptance checklist.
        """
        expected = self.control.expectation("silver")
        checks: list[AcceptanceCheck] = []

        for table, want in expected["row_counts"].items():
            got = len(payload["tables"].get(table, {}).get("rows", []))
            checks.append(AcceptanceCheck(
                name=f"{table}: row count unchanged from Bronze (this layer never filters)",
                passed=got == want,
                detail=f"expected {want}, have {got}",
            ))

        for table, want in expected["amount_sums"].items():
            got = payload["amount_sums"].get(table)
            checks.append(AcceptanceCheck(
                name=f"{table}: amount sum survives the cast",
                passed=got is not None and round(got, 2) == round(float(want), 2),
                detail=f"expected {want}, have {got}",
            ))

        got_blocked = {(item["table"], item["business_key"]) for item in payload["blocked"]}
        want_blocked = {(item["table"], str(item["business_key"])) for item in expected["blocked"]}
        checks.append(AcceptanceCheck(
            name="the right rows are blocked, and only those",
            passed=got_blocked == want_blocked,
            detail=f"expected {sorted(want_blocked)}, found {sorted(got_blocked)}",
        ))

        got_flags = {(item["table"], item["business_key"], item["flag"]) for item in payload["flags"]}
        want_flags = {
            (item["table"], str(item["business_key"]), item["flag"]) for item in expected["flags"]
        }
        checks.append(AcceptanceCheck(
            name="the right rows are flagged, and only those",
            passed=got_flags == want_flags,
            detail=f"expected {sorted(want_flags)}, found {sorted(got_flags)}",
        ))

        unresolved = [
            f"{item['table']}.{item['business_key']}"
            for item in payload["flags"]
            if str(item["business_key"]) not in {
                str(row.get(payload["tables"][item["table"]]["grain_key"]))
                for row in payload["tables"][item["table"]]["rows"]
            }
        ]
        checks.append(AcceptanceCheck(
            name="every flag resolves to a real row",
            passed=not unresolved,
            detail="all resolve" if not unresolved else f"dangling: {unresolved}",
        ))

        got_info = {(item["table"], item["business_key"]) for item in payload["info_findings"]}
        want_info = {(item["table"], str(item["business_key"])) for item in expected["info_only"]}
        checks.append(AcceptanceCheck(
            name="zero-amount postings are recorded as info, not blocked",
            passed=got_info == want_info and not (got_info & got_blocked),
            detail=f"info {sorted(got_info)}; none of them blocked",
        ))

        return checks
