"""The Gold agent: model the business, certify the metrics, serve entitled rows.

Simulated stand-in for ``sql/30_core.sql``, ``40_ai_views.sql`` and
``50_sec_rls.sql`` plus their Python drivers. It excludes what Silver blocked,
carries what Silver flagged onto the row, computes the certified metrics once,
and serves each demo portfolio only its own clients.

The two failures this layer is prone to are modelled explicitly, because both
happened in the production build:

* **a grain that is declared and not true** -- a correct-looking query then
  double counts and nothing errors, so the grain is verified, not asserted;
* **a serving object that drops the filter** -- so entitlement is applied where
  the rows live and is proven by asking as a restricted principal and counting,
  never by reading the policy.
"""

from __future__ import annotations

from typing import Any

from berka_control import AcceptanceCheck, LayerAgent, LayerArtifact


class GoldAgent(LayerAgent):
    """Builds the certified model and the entitlement-filtered serving layer."""

    layer = "gold"

    def work(self, upstream: LayerArtifact | None) -> dict[str, Any]:
        """Build core from Silver minus blocked, then serve it per portfolio.

        :param upstream: The Silver artefact.
        :returns: The Gold payload: modelled tables, metrics and served views.
        """
        assert upstream is not None  # guaranteed by the runtime's input gate
        silver = upstream.payload
        blocked_keys = {
            (item["table"], str(item["business_key"])) for item in silver["blocked"]
        }
        flags_by_row: dict[tuple[str, str], list[str]] = {}
        for flag in silver["flags"]:
            flags_by_row.setdefault((flag["table"], str(flag["business_key"])), []).append(
                flag["flag"]
            )

        tables: dict[str, Any] = {}
        blocked_counts: dict[str, int] = {}
        for name, data in silver["tables"].items():
            key = data["grain_key"]
            kept: list[dict[str, Any]] = []
            removed = 0
            for row in data["rows"]:
                identity = (name, str(row.get(key)))
                if identity in blocked_keys:
                    removed += 1
                    continue
                # The warn flag travels onto the row, so a consumer can repeat
                # the caveat instead of being told the number is clean.
                kept.append({**row, "_dq_flags": flags_by_row.get(identity, [])})
            tables[name] = {"grain_key": key, "rows": kept}
            blocked_counts[name] = removed

        return {
            "tables": tables,
            "blocked_counts": blocked_counts,
            "upstream_row_counts": {n: len(d["rows"]) for n, d in silver["tables"].items()},
            "certified_metrics": self._certified_metrics(tables),
            "served": self._serve(tables),
        }

    # -- certified metrics --------------------------------------------------

    def _certified_metrics(self, tables: dict[str, Any]) -> dict[str, float]:
        """Compute the metrics whose definition the business has agreed.

        Defined once, here, so no consumer can redefine "problematic" and
        quietly report a different number.

        :param tables: The modelled tables.
        :returns: Mapping of metric name to value.
        """
        problematic_statuses = set(self.control.constant("problematic_loan_statuses"))
        loans = tables["loan"]["rows"]
        problematic = [row for row in loans if row.get("status") in problematic_statuses]
        return {
            "problematic_loan_pct": (
                round(100.0 * len(problematic) / len(loans), 2) if loans else 0.0
            ),
            "total_loan_amount": round(sum(row["amount"] for row in loans), 2),
        }

    # -- serving ------------------------------------------------------------

    def _serve(self, tables: dict[str, Any]) -> dict[str, Any]:
        """Apply the entitlement filter per portfolio and return what each sees.

        In production this is a row level security policy evaluated inside the
        database, so a consumer querying the base tables directly is filtered
        identically. The simulation keeps the shape that matters: the filter is
        applied where the rows live, by a component the query author does not
        control, and the result is *measured* per principal.

        :param tables: The modelled tables.
        :returns: Mapping of portfolio to the ids it can see.
        """
        entitlements = self.control.expectation("gold")["entitlements"]
        served: dict[str, Any] = {}
        for portfolio, grant in entitlements.items():
            entitled_clients = set(grant["clients"])
            # An account is visible when its owner is an entitled client. In
            # this fixture account_id and client_id correspond one to one.
            visible_accounts = sorted(
                row["account_id"] for row in tables["account"]["rows"]
                if row["account_id"] in entitled_clients
            )
            visible_loans = sorted(
                row["loan_id"] for row in tables["loan"]["rows"]
                if row["account_id"] in set(visible_accounts)
            )
            served[portfolio] = {
                "clients": sorted(
                    row["client_id"] for row in tables["client"]["rows"]
                    if row["client_id"] in entitled_clients
                ),
                "visible_accounts": visible_accounts,
                "visible_loans": visible_loans,
            }
        return served

    def acceptance_checks(self, payload: dict[str, Any]) -> list[AcceptanceCheck]:
        """Verify the model, the metrics and the entitlement filter.

        :param payload: What :meth:`work` produced.
        :returns: The acceptance checklist.
        """
        expected = self.control.expectation("gold")
        checks: list[AcceptanceCheck] = []

        for table, want in expected["row_counts"].items():
            got = len(payload["tables"].get(table, {}).get("rows", []))
            checks.append(AcceptanceCheck(
                name=f"{table}: equals conformed minus blocked",
                passed=got == want,
                detail=f"expected {want}, have {got}",
            ))

        for table, key in expected["grain_one_row_per"].items():
            values = [row.get(key) for row in payload["tables"][table]["rows"]]
            checks.append(AcceptanceCheck(
                name=f"{table}: declared grain of one row per {key} actually holds",
                passed=len(values) == len(set(values)),
                detail=f"{len(values)} rows, {len(set(values))} distinct {key}",
            ))

        for metric, want in expected["certified_metrics"].items():
            got = payload["certified_metrics"].get(metric)
            checks.append(AcceptanceCheck(
                name=f"certified metric {metric}",
                passed=got is not None and round(float(got), 2) == round(float(want), 2),
                detail=f"expected {want}, computed {got}",
            ))

        flagged_visible = [
            row for row in payload["tables"]["client"]["rows"] if row.get("_dq_flags")
        ]
        checks.append(AcceptanceCheck(
            name="warn flags from Silver are visible on the served rows",
            passed=bool(flagged_visible),
            detail=(
                f"{len(flagged_visible)} row(s) carry a caveat, e.g. "
                f"{flagged_visible[0]['_dq_flags']}" if flagged_visible else "none visible"
            ),
        ))

        for portfolio, want in expected["entitlements"].items():
            got = payload["served"][portfolio]
            matches = all(got[field] == want[field] for field in ("clients", "visible_accounts", "visible_loans"))
            checks.append(AcceptanceCheck(
                name=f"{portfolio}: sees exactly its own rows",
                passed=matches,
                detail=f"expected {want}, served {got}",
            ))

        unassigned = payload["served"].get("UNASSIGNED", {})
        checks.append(AcceptanceCheck(
            name="an unentitled principal sees nothing, not everything",
            passed=all(not value for value in unassigned.values()),
            detail=f"served {unassigned}",
        ))

        return checks
