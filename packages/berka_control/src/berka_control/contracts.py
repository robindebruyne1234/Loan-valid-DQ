"""The contract one layer publishes to the next, and its verification.

A layered build only holds together if each layer publishes something the next
one can *test*, rather than a module the next one reads. These are those
tests, expressed against the declarations in the control dataset, so a
contract change is a change to governed data rather than to three codebases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ContractViolation(AssertionError):
    """Raised when a layer's output does not satisfy the contract it declared.

    This is the failure that must be loud. A silent contract breach is how a
    downstream layer ends up debugging someone else's bug.
    """


@dataclass
class Contract:
    """One layer's published contract, as declared in the control dataset.

    :ivar name: Contract name, for example ``silver_conformed``.
    :ivar declaration: The raw ``publishes`` block from the control dataset.
    """

    name: str
    declaration: dict[str, Any] = field(default_factory=dict)

    @property
    def tables(self) -> tuple[str, ...]:
        """Tables or entities the contract promises.

        :returns: Names, empty when the contract declares none.
        """
        return tuple(self.declaration.get("tables") or self.declaration.get("entities") or ())

    @property
    def guarantees(self) -> dict[str, Any]:
        """The row-level guarantees the contract makes.

        :returns: The ``row_guarantees`` block, or an empty mapping.
        """
        return dict(self.declaration.get("row_guarantees") or {})


def verify_contract(contract: Contract, payload: dict[str, Any]) -> list[str]:
    """Check one layer's output against the contract it declared.

    Each guarantee in the control dataset maps to a check here. A guarantee
    with no check is reported as unverifiable rather than silently passed:
    a contract nobody tests is documentation.

    :param contract: The contract the producing layer declared.
    :param payload: The producing layer's output, as a plain dictionary.
    :returns: List of human-readable violations; empty means the contract holds.
    """
    problems: list[str] = []
    tables: dict[str, Any] = payload.get("tables", {})

    for table in contract.tables:
        if table not in tables:
            problems.append(f"{contract.name}: promised table '{table}' is absent")

    guarantees = contract.guarantees

    if guarantees.get("all_columns_text"):
        for name, table in tables.items():
            offenders = [
                column
                for row in table.get("rows", [])[:1]
                for column, value in row.items()
                if not column.startswith("_") and not isinstance(value, str)
            ]
            if offenders:
                problems.append(
                    f"{contract.name}: table '{name}' promised all-text columns "
                    f"but {offenders} are typed"
                )

    for column in guarantees.get("lineage_columns") or ():
        for name, table in tables.items():
            rows = table.get("rows", [])
            if rows and column not in rows[0]:
                problems.append(
                    f"{contract.name}: table '{name}' is missing lineage column "
                    f"'{column}'"
                )

    if guarantees.get("preserves_empty_string_vs_null"):
        collapsed = [
            name for name, table in tables.items()
            if table.get("empty_string_collapsed_to_null")
        ]
        if collapsed:
            problems.append(
                f"{contract.name}: tables {collapsed} collapsed the source's "
                "empty-string / NULL distinction, which is Silver's decision to make"
            )

    if guarantees.get("row_count_equals_bronze"):
        upstream = payload.get("upstream_row_counts") or {}
        for name, table in tables.items():
            if name in upstream and len(table.get("rows", [])) != upstream[name]:
                problems.append(
                    f"{contract.name}: table '{name}' has "
                    f"{len(table.get('rows', []))} rows against {upstream[name]} "
                    "upstream -- this layer casts, it must not filter"
                )

    if guarantees.get("preserves_amount_sums"):
        for name, expected in (payload.get("upstream_amount_sums") or {}).items():
            actual = payload.get("amount_sums", {}).get(name)
            if actual is not None and round(float(actual), 2) != round(float(expected), 2):
                problems.append(
                    f"{contract.name}: '{name}' amount sum moved from {expected} "
                    f"to {actual} -- the money must survive the cast"
                )

    if guarantees.get("equals_silver_minus_blocked"):
        upstream = payload.get("upstream_row_counts") or {}
        blocked = payload.get("blocked_counts") or {}
        for name, table in tables.items():
            if name not in upstream:
                continue
            expected = upstream[name] - blocked.get(name, 0)
            if len(table.get("rows", [])) != expected:
                problems.append(
                    f"{contract.name}: '{name}' has {len(table.get('rows', []))} rows, "
                    f"expected {expected} = {upstream[name]} conformed - "
                    f"{blocked.get(name, 0)} blocked"
                )

    if guarantees.get("declared_grain_holds"):
        for name, table in tables.items():
            key = table.get("grain_key")
            if not key:
                problems.append(f"{contract.name}: '{name}' declares no grain key")
                continue
            values = [row.get(key) for row in table.get("rows", [])]
            if len(values) != len(set(values)):
                problems.append(
                    f"{contract.name}: '{name}' declares one row per {key} and "
                    "does not have it -- a false grain makes a correct query double count"
                )

    if guarantees.get("flag_keys_must_resolve") or (
        payload.get("flags") and guarantees.get("conversion_audit")
    ):
        for flag in payload.get("flags", []):
            table = tables.get(flag["table"], {})
            key = table.get("grain_key")
            known = {str(row.get(key)) for row in table.get("rows", [])}
            if str(flag["business_key"]) not in known:
                problems.append(
                    f"{contract.name}: flag '{flag['flag']}' points at "
                    f"{flag['table']}.{flag['business_key']}, which does not exist "
                    "-- a flag that resolves to nothing reaches nobody"
                )

    if guarantees.get("warn_flags_visible"):
        for name, table in tables.items():
            rows = table.get("rows", [])
            if rows and "_dq_flags" not in rows[0]:
                problems.append(
                    f"{contract.name}: '{name}' does not expose _dq_flags, so a "
                    "consumer cannot repeat the caveat"
                )

    if guarantees.get("idempotent") and payload.get("second_run_digest") is not None:
        if payload["second_run_digest"] != payload.get("digest"):
            problems.append(
                f"{contract.name}: re-running produced a different digest; "
                "this layer is not idempotent"
            )

    return problems
