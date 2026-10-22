"""Render the Design Decision Record as a Word document and a PDF.

The text lives in ``deliverables/DDR_source.md`` so it can be reviewed and
edited as text; this module only renders it. The brief caps the document at two
pages, so the renderer converts to PDF with LibreOffice and **asserts the page
count**: a document that runs to three pages fails the build rather than being
submitted over length.

Markdown understood (deliberately a small subset -- this is a document, not a
site): ``#``/``##``/``###`` headings, ``**bold**`` and ``*italic*`` inline,
``1.`` ordered and ``-`` unordered lists, and blank-line separated paragraphs.

Run with ``make ddr``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from src import config, db

LOGGER = db.setup_logging("ddr")

#: Page and type setup. Tight but readable: the content has to fit two pages.
MARGIN_CM = 1.6
BODY_POINTS = 9.0
HEADING_COLOUR = RGBColor(0x1F, 0x38, 0x64)

#: Maximum pages the brief allows.
MAX_PAGES = 2


def add_runs(paragraph: Any, text: str) -> None:
    """Add text to a paragraph, honouring ``**bold**`` and ``*italic*``.

    :param paragraph: The python-docx paragraph to append to.
    :param text: Inline markdown text.
    :returns: ``None``.
    """
    for piece in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)", text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            run = paragraph.add_run(piece[2:-2])
            run.bold = True
        elif piece.startswith("*") and piece.endswith("*"):
            run = paragraph.add_run(piece[1:-1])
            run.italic = True
        elif piece.startswith("`") and piece.endswith("`"):
            run = paragraph.add_run(piece[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(BODY_POINTS - 0.5)
        else:
            paragraph.add_run(piece)


def build_document() -> Document:
    """Build the Word document from the markdown source.

    :returns: The populated :class:`docx.Document`.
    """
    source = (config.DELIVERABLES_DIR / "DDR_source.md").read_text(encoding="utf-8")
    document = Document()

    section = document.sections[0]
    section.top_margin = Cm(MARGIN_CM)
    section.bottom_margin = Cm(MARGIN_CM)
    section.left_margin = Cm(MARGIN_CM)
    section.right_margin = Cm(MARGIN_CM)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(BODY_POINTS)
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.0

    # Markdown is parsed line by line, with blank lines joining into paragraphs.
    buffer: list[str] = []

    def flush(style: str | None = None) -> None:
        """Emit the buffered lines as one paragraph.

        :param style: Optional paragraph style name.
        :returns: ``None``.
        """
        if not buffer:
            return
        text = " ".join(buffer).strip()
        buffer.clear()
        if not text:
            return
        paragraph = document.add_paragraph(style=style)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.space_after = Pt(3)
        add_runs(paragraph, text)

    for raw_line in source.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue

        if line.startswith("### "):
            flush()
            heading = document.add_paragraph()
            heading.paragraph_format.space_before = Pt(6)
            heading.paragraph_format.space_after = Pt(2)
            run = heading.add_run(line[4:])
            run.bold = True
            run.font.size = Pt(BODY_POINTS + 1.5)
            run.font.color.rgb = HEADING_COLOUR
        elif line.startswith("## "):
            flush()
            heading = document.add_paragraph()
            heading.paragraph_format.space_after = Pt(4)
            run = heading.add_run(line[3:])
            run.bold = True
            run.font.size = Pt(BODY_POINTS + 2)
            run.font.color.rgb = HEADING_COLOUR
        elif line.startswith("# "):
            flush()
            heading = document.add_paragraph()
            heading.paragraph_format.space_after = Pt(1)
            run = heading.add_run(line[2:])
            run.bold = True
            run.font.size = Pt(BODY_POINTS + 5)
            run.font.color.rgb = HEADING_COLOUR
        elif re.match(r"^\d+\.\s", line):
            flush()
            buffer.append(re.sub(r"^\d+\.\s", "", line))
            flush(style="List Number")
        elif line.startswith("- "):
            flush()
            buffer.append(line[2:])
            flush(style="List Bullet")
        elif line.startswith(("   ", "\t")) and buffer:
            buffer.append(line.strip())
        else:
            buffer.append(line.strip())
    flush()

    footer = document.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = footer.add_run(
        f"Generated by `make ddr` at {db.utc_now_iso()} (git {db.git_commit()}). "
        f"Source text: deliverables/DDR_source.md"
    )
    run.italic = True
    run.font.size = Pt(6.5)
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    return document


def convert_to_pdf() -> int | None:
    """Convert the Word document to PDF with LibreOffice and count the pages.

    :returns: The PDF's page count, or ``None`` when LibreOffice is unavailable
        or the page count cannot be read.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        LOGGER.warning("LibreOffice not found -> cannot produce a PDF or verify the page count")
        return None

    result = subprocess.run(
        [
            soffice, "--headless", "--norestore", "--convert-to", "pdf",
            "--outdir", str(config.DELIVERABLES_DIR), str(config.DDR_DOCX),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if not config.DDR_PDF.exists():
        LOGGER.error("PDF conversion failed -> %s", (result.stderr or result.stdout)[:300])
        return None

    # Count pages without a PDF library: /Type /Page objects in the raw file.
    data = config.DDR_PDF.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    return pages or None


def main() -> int:
    """Render the Design Decision Record and verify its length.

    :returns: Process exit code: ``0`` when the document is within the page
        limit, ``1`` when it is over or the page count could not be verified.
    """
    config.DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    document = build_document()
    document.save(config.DDR_DOCX)

    words = len(
        (config.DELIVERABLES_DIR / "DDR_source.md").read_text(encoding="utf-8").split()
    )
    LOGGER.info(
        "wrote %s -> %d paragraphs, %d source words",
        config.DDR_DOCX.relative_to(config.PROJECT_ROOT),
        len(document.paragraphs),
        words,
    )

    pages = convert_to_pdf()
    if pages is None:
        LOGGER.warning("page count NOT VERIFIED")
        db.record_run("ddr", "make ddr", {"words": words, "pages": "not verified"})
        return 1

    LOGGER.info("wrote %s -> %d page(s)", config.DDR_PDF.relative_to(config.PROJECT_ROOT), pages)
    db.record_run("ddr", "make ddr", {"words": words, "pages": pages})

    if pages > MAX_PAGES:
        LOGGER.error(
            "the brief allows %d pages and this is %d -> shorten "
            "deliverables/DDR_source.md and re-run 'make ddr'",
            MAX_PAGES, pages,
        )
        return 1
    LOGGER.info("page count within the %d-page limit set by the brief", MAX_PAGES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
