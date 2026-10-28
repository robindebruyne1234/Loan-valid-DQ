"""Draw the defect catalogue as an SVG, from deliverables/defects.csv.

Generated rather than hand-drawn so the picture cannot drift from the data:
re-run `make dq` and then this, and the figure is true again. The only thing
held here is the *remedy* per defect type, which is a judgement and belongs
with a person, not in the pipeline.

The figure makes one claim: on this dataset, defect volume and defect harm run
in opposite directions. The green band holds 2.5 million rows and changes no
reported number; the red band holds one row and changes two answers.

Usage: python scripts/make_defect_catalogue.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "deliverables" / "defects.csv"
TARGET = PROJECT_ROOT / "docs" / "diagrams" / "08_defect_catalogue.svg"

#: What would actually make each defect go away. Keyed by the opening words of
#: the defect type, so a reworded description still matches. A defect with no
#: entry renders with a visible gap rather than a silent blank.
REMEDIES: dict[str, str] = {
    "Duplicate transaction": "Delete the twin in the source system. Quarantine names both ids, the account and the date.",
    "Closing balance": "Have the source record posting order within a day (a sequence or a timestamp).",
    "Running balance": "Find the missing or extra posting. 14 accounts are material, not rounding; the largest is out by 488.30.",
    "Implausible age": "Correct the birth number, or the owner flag, in the customer system.",
    "Counterparty missing on a transfer": "A transfer has two sides. Fix the feed that dropped one.",
    "Missing values in columns": "Nothing today. The rule stays so the grade can be promoted the day a metric reads the column.",
    "Counterparty bank and account absent": "Nothing. Cash operations have no counterparty; this is structural and documented.",
    "The same column encodes": "Collapsed to one NULL in staging. Ask the source to settle on a single spelling.",
    "Transaction operation absent": "Nothing. These are the bank's own interest runs, which have no customer operation.",
    "Balance after the transaction is negative": "Nothing. Overdraft is real banking. Clipping it at zero would bias the Q9 average upwards.",
    "Owner's own district differs": "Nothing. People move. Both readings are published and each question states which it uses.",
    "Two clients share birth number": "Candidate duplicate people. A master-data process should review the 26 pairs.",
    "Transaction amount is zero": "Nothing. Interest that accrued nothing. Blocking would break 14 balance chains to fix nothing.",
    "Placeholder '?'": "Ask the source for the two missing figures. Promote to warn if a metric ever reads the 1995 series.",
}

SEVERITY_STYLE = {
    "block": {"colour": "#991b1b", "band": "#fdf4f4", "label": "BLOCK"},
    "warn": {"colour": "#b45309", "band": "#fffaf0", "label": "WARN"},
    "info": {"colour": "#15803d", "band": "#f4faf6", "label": "INFO"},
}

SEVERITY_MEANING = {
    "block": "removed from the product, and the removal is counted",
    "warn": "kept, flagged, and the caveat reaches the answer",
    "info": "standardised and logged; no reported number moves",
}

WIDTH = 1340
NAME_X, BAR_X, BAR_W, Q_X, FIX_X = 20, 352, 228, 668, 760
ROW_H, BAND_PAD, HEADER_H = 34, 10, 30


def escape(text: str) -> str:
    """Escape text for inclusion in SVG.

    :param text: Raw text.
    :returns: Text safe to place between SVG tags.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def remedy_for(defect_type: str) -> str:
    """Find the recorded remedy for a defect type.

    :param defect_type: The defect type as written in defects.csv.
    :returns: The remedy, or a visible placeholder when none is recorded.
    """
    for prefix, remedy in REMEDIES.items():
        if defect_type.startswith(prefix):
            return remedy
    return "NO REMEDY RECORDED -- add one to scripts/make_defect_catalogue.py"


def wrap(text: str, width: int) -> list[str]:
    """Wrap text to a character width.

    :param text: Text to wrap.
    :param width: Maximum characters per line.
    :returns: The lines.
    """
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def main() -> int:
    """Render the catalogue.

    :returns: Process exit code.
    """
    with SOURCE.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    grouped: dict[str, list[dict]] = {"block": [], "warn": [], "info": []}
    for row in rows:
        grouped[row["Severity"]].append(row)
    for members in grouped.values():
        members.sort(key=lambda r: -int(r["Rows affected"]))

    biggest = max(int(row["Rows affected"]) for row in rows)
    decades = math.log10(biggest) or 1.0

    def bar_width(count: int) -> float:
        """Scale a count to a bar width on a log axis.

        :param count: Rows affected.
        :returns: Width in pixels, with a visible minimum.
        """
        return max(4.0, (math.log10(count) / decades) * BAR_W) if count > 0 else 4.0

    height = 150 + sum(HEADER_H + BAND_PAD * 2 + len(m) * ROW_H + 12 for m in grouped.values()) + 56
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" role="img" aria-label="Every defect type found, '
        'grouped by severity, with the rows affected on a logarithmic scale, the questions each '
        'one touches, and what would permanently solve it. The one block-severity defect affects '
        'a single row and two answers; the info band holds over two and a half million rows and '
        'changes no reported number.">',
        f'<rect width="{WIDTH}" height="{height}" fill="#ffffff"/>',
        '<g font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        f'<text x="{NAME_X}" y="32" font-size="17" font-weight="600" fill="#1f3864">'
        f'Every defect found: {len(rows)} types, and what would solve each one</text>',
        f'<text x="{NAME_X}" y="52" font-size="11.5" fill="#5b6472">'
        'Bars are logarithmic. Read the shape, not the length: the band that removes data holds '
        'one row, and the band holding 2.5 million rows removes nothing and changes no answer.</text>',
        f'<text x="{NAME_X}" y="68" font-size="11.5" fill="#5b6472">'
        'Volume is not harm. Grading each defect by what it would cost to act on it is the whole '
        'job -- the rule that finds it is the easy half.</text>',
        f'<text x="{NAME_X}" y="104" font-size="10.5" fill="#5b6472">defect type</text>',
        f'<text x="{BAR_X}" y="104" font-size="10.5" fill="#5b6472">rows affected (log scale)</text>',
        f'<text x="{Q_X}" y="104" font-size="10.5" fill="#5b6472">answers</text>',
        f'<text x="{FIX_X}" y="104" font-size="10.5" fill="#5b6472">what would permanently solve it</text>',
        f'<line x1="16" y1="112" x2="{WIDTH - 16}" y2="112" stroke="#e3e7ed" stroke-width="1"/>',
    ]

    y = 124
    for severity in ("block", "warn", "info"):
        members = grouped[severity]
        style = SEVERITY_STYLE[severity]
        band_h = HEADER_H + BAND_PAD + len(members) * ROW_H + 6
        out.append(
            f'<rect x="16" y="{y}" width="{WIDTH - 32}" height="{band_h}" rx="6" fill="{style["band"]}"/>'
        )
        out.append(f'<rect x="16" y="{y}" width="5" height="{band_h}" rx="2" fill="{style["colour"]}"/>')
        out.append(
            f'<rect x="{NAME_X + 12}" y="{y + 9}" width="58" height="18" rx="9" fill="{style["colour"]}"/>'
        )
        out.append(
            f'<text x="{NAME_X + 41}" y="{y + 22}" font-size="10" font-weight="600" fill="#ffffff" '
            f'text-anchor="middle">{style["label"]}</text>'
        )
        total = sum(int(r["Rows affected"]) for r in members)
        out.append(
            f'<text x="{NAME_X + 82}" y="{y + 22}" font-size="11.5" fill="#1f2a44">'
            f'{len(members)} type(s), {total:,} rows -- {escape(SEVERITY_MEANING[severity])}</text>'
        )

        row_y = y + HEADER_H + BAND_PAD
        for row in members:
            count = int(row["Rows affected"])
            name = row["Defect type"]
            if len(name) > 52:
                name = name[:49] + "..."
            questions = row["Questions affected"]
            questions = "-" if questions == "none" else questions

            out.append(
                f'<text x="{NAME_X + 12}" y="{row_y + 14}" font-size="11.5" fill="#1f2a44">'
                f'{escape(name)}</text>'
            )
            out.append(
                f'<text x="{NAME_X + 12}" y="{row_y + 27}" font-size="9.5" fill="#8a93a0">'
                f'{escape(row["Dimension"])}</text>'
            )
            out.append(
                f'<rect x="{BAR_X}" y="{row_y + 5}" width="{bar_width(count):.1f}" height="13" '
                f'rx="2" fill="{style["colour"]}" opacity="0.75"/>'
            )
            out.append(
                f'<text x="{BAR_X + BAR_W + 10}" y="{row_y + 16}" font-size="10.5" '
                f'fill="#1f2a44">{count:,}</text>'
            )
            out.append(
                f'<text x="{Q_X}" y="{row_y + 16}" font-size="10.5" '
                f'fill="{"#1f3864" if questions != "-" else "#aab2bd"}">{escape(questions)}</text>'
            )
            for index, line in enumerate(wrap(remedy_for(row["Defect type"]), 78)[:2]):
                out.append(
                    f'<text x="{FIX_X}" y="{row_y + 13 + index * 13}" font-size="10.5" '
                    f'fill="#5b6472">{escape(line)}</text>'
                )
            row_y += ROW_H

        y += band_h + 12

    out.append(
        f'<text x="{NAME_X}" y="{y + 24}" font-size="11.5" fill="#1f2a44">'
        'Nine of the fourteen need no fix at all. They are reported so that nobody "cleans" them '
        'later and breaks something: clipping overdrafts would bias the Q9 average,</text>'
    )
    out.append(
        f'<text x="{NAME_X}" y="{y + 40}" font-size="11.5" fill="#1f2a44">'
        'and blocking the 14 zero-value postings would break 14 balance chains to fix nothing. '
        'Writing down why not to act is as much of the job as acting.</text>'
    )
    out += ["</g>", "</svg>"]

    TARGET.write_text("\n".join(out), encoding="utf-8")
    print(f"make_defect_catalogue | wrote {TARGET.relative_to(PROJECT_ROOT)} "
          f"({len(rows)} defect types, {height}px tall)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
