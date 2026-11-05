# Study pack for the technical walkthrough

Preparation material for the 45-minute walkthrough of the delivered version
(branch `delivery-freeze-2026-10-28`, commit `fc0c281`). The outputs are in
`deliverables/study_pack/`:

| File | What it is |
|---|---|
| `01_Study_Guide.pdf` | Every step from raw files to the LLM client: what, why, cost, evidence, weak spots; the ten questions; a question bank; the full decision and assumption registers |
| `01b_Study_Guide_School_Edition.pdf` | The same chapters 0–20 told as a school: pupils (clients), record books (accounts), topics (districts), tutors (bank staff) and a robot (the LLM); every chapter ends with an "In grown-up words" box that maps back to the real terms. Sources in `guide_kids/`, styles in `style_kids.css` |
| `02_Lessons_Learned_and_Self_Audit.pdf` | Every mistake, weak spot and sloppy detail found in the delivered version, verified against code, evidence or the database, with status and a way to say it |
| `03_Walkthrough_Deck.pptx` / `.pdf` | 26 slides (22 main, 4 backup) with speaker notes, sized for about 30 minutes |
| `04_Cheat_Sheet.pdf` | One page of figures and one-liners |

Figures come from the delivered evidence files, snapshotted in `sources/delivered/`
(taken from `fc0c281`), or from queries run on 2026-11-04; `notes/verified_findings.md`
records each check. Work done after delivery (D028, D029, A47–A49) is in
`sources/post_delivery/` and is labelled as such everywhere it appears.

## Rebuilding

```
python study_pack/build.py                 # the four PDFs (or: guide, kids, lessons, cheatsheet) (needs python-markdown, pypdf; fontTools optional)
cd study_pack/deck && npm install          # once: pptxgenjs
NODE_PATH=study_pack/deck/node_modules node study_pack/deck/build_deck.js
```

PDFs are printed by Chromium through Playwright (`render_pdf.mjs`); the deck's PDF
copy is converted with LibreOffice. `_build/` holds intermediate files.
