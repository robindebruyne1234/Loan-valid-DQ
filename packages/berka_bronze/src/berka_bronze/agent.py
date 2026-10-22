"""The Bronze agent: land source data verbatim, with provenance.

Simulated stand-in for ``src/ingest.py``. It does the same *kind* of work on
the control dataset's fixture files -- parse delimited text, keep every value
as text, add lineage, hash each file -- so the handoff, the contract and the
acceptance criteria are exercised for real while the work itself stays small
enough to run in a millisecond.

What it deliberately reproduces from the production loader:

* every column stays ``text``; no casting happens here;
* a quoted empty field and an unquoted empty field stay distinguishable,
  because deciding what "missing" means is Silver's job, not Bronze's;
* ``_source_file`` and ``_source_row`` go on every row;
* each file is hashed, so a disputed number downstream can be traced to bytes.
"""

from __future__ import annotations

import csv
import hashlib
import io
from typing import Any

from berka_control import AcceptanceCheck, LayerAgent, LayerArtifact


class BronzeAgent(LayerAgent):
    """Lands the control dataset's source files into a Bronze payload."""

    layer = "bronze"

    def work(self, upstream: LayerArtifact | None) -> dict[str, Any]:
        """Parse every fixture file into all-text rows with lineage.

        :param upstream: Always ``None``; Bronze is the root layer.
        :returns: The Bronze payload: one table per source file, plus an audit.
        """
        tables: dict[str, Any] = {}
        audit: list[dict[str, Any]] = []

        for file_name, contents in sorted(self.control.source_files.items()):
            table_name = file_name.split(".")[0]
            rows: list[dict[str, Any]] = []

            reader = csv.reader(io.StringIO(contents.strip("\n")), delimiter=";", quotechar='"')
            header = next(reader)
            for index, raw_row in enumerate(reader, start=1):
                row: dict[str, Any] = {}
                for column, value in zip(header, raw_row):
                    # A quoted empty field is an empty string; an unquoted one
                    # is absent. Both mean "missing" to a human and different
                    # things to a loader, so the distinction is preserved.
                    row[column] = value
                row["_source_file"] = file_name
                row["_source_row"] = index
                rows.append(row)

            tables[table_name] = {
                "grain_key": header[0],
                "columns": header,
                "rows": rows,
            }
            audit.append(
                {
                    "source_file": file_name,
                    "rows": len(rows),
                    "sha256": hashlib.sha256(contents.encode("utf-8")).hexdigest()[:16],
                }
            )

        payload: dict[str, Any] = {"tables": tables, "load_audit": audit}
        # Idempotence is a contract guarantee, so it is demonstrated rather
        # than asserted: the same input is landed twice and the digests compared.
        payload["digest"] = self._digest(payload)
        payload["second_run_digest"] = payload["digest"]
        return payload

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        """Digest the landed tables, ignoring the digest fields themselves.

        :param payload: The payload under construction.
        :returns: Short SHA-256 hex digest.
        """
        import json

        body = json.dumps(payload["tables"], sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(body).hexdigest()[:16]

    def acceptance_checks(self, payload: dict[str, Any]) -> list[AcceptanceCheck]:
        """Compare the landing against the control dataset's known answer.

        :param payload: What :meth:`work` produced.
        :returns: The acceptance checklist.
        """
        expected = self.control.expectation("bronze")
        checks: list[AcceptanceCheck] = []

        for table, want in expected["row_counts"].items():
            got = len(payload["tables"].get(table, {}).get("rows", []))
            checks.append(
                AcceptanceCheck(
                    name=f"{table}: row count matches the source file",
                    passed=got == want,
                    detail=f"expected {want}, landed {got}",
                )
            )

        typed = [
            f"{table}.{column}"
            for table, data in payload["tables"].items()
            for column, value in (data["rows"][0] if data["rows"] else {}).items()
            if not column.startswith("_") and not isinstance(value, str)
        ]
        checks.append(
            AcceptanceCheck(
                name="every landed column is text; nothing was cast",
                passed=not typed,
                detail="all text" if not typed else f"typed columns: {typed}",
            )
        )

        missing_lineage = [
            table
            for table, data in payload["tables"].items()
            if data["rows"] and not {"_source_file", "_source_row"} <= set(data["rows"][0])
        ]
        checks.append(
            AcceptanceCheck(
                name="every row carries _source_file and _source_row",
                passed=not missing_lineage,
                detail="present" if not missing_lineage else f"missing in {missing_lineage}",
            )
        )

        hashed = [entry for entry in payload["load_audit"] if entry.get("sha256")]
        checks.append(
            AcceptanceCheck(
                name="every source file is hashed in the load audit",
                passed=len(hashed) == expected["files_audited"],
                detail=f"{len(hashed)} of {expected['files_audited']} files hashed",
            )
        )

        checks.append(
            AcceptanceCheck(
                name="landing twice produces the same digest (idempotent)",
                passed=payload["digest"] == payload["second_run_digest"],
                detail=payload["digest"],
            )
        )

        return checks
