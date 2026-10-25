"""Build the walkthrough deck: deliverables/Walkthrough_Deck.pptx.

Generated rather than hand-built, for the same reason every other figure in
this project is: a deck that is typed by hand goes stale the moment a number
changes, and this one carries a lot of numbers. Re-run it after `make all` and
it is true again.

Design rules followed here:

* **Plain language on the slide, detail in the notes.** Every slide has
  speaker notes carrying what to actually say, so the deck can be presented
  from cold.
* **One idea per slide.** If a slide needs two sentences to state its point,
  it is two slides.
* **The figures do the explaining.** Ten diagrams already exist; the deck
  embeds them rather than re-describing them in bullets.

Usage: python scripts/make_pitch_deck.py
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = PROJECT_ROOT / "docs" / "diagrams"
TARGET = PROJECT_ROOT / "deliverables" / "Walkthrough_Deck.pptx"

NAVY = RGBColor(0x1F, 0x38, 0x64)
INK = RGBColor(0x1F, 0x2A, 0x44)
GREY = RGBColor(0x5B, 0x64, 0x72)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RED = RGBColor(0x99, 0x1B, 0x1B)
AMBER = RGBColor(0xB4, 0x53, 0x09)
GREEN = RGBColor(0x15, 0x80, 0x3D)
PALE = RGBColor(0xF7, 0xF9, 0xFC)

FONT = "Calibri"
W, H = Inches(13.333), Inches(7.5)


def new_deck() -> Presentation:
    """Create an empty 16:9 presentation.

    :returns: The presentation, sized for a modern projector.
    """
    deck = Presentation()
    deck.slide_width, deck.slide_height = W, H
    return deck


def blank(deck: Presentation):
    """Add a blank slide.

    :param deck: The presentation.
    :returns: The new slide.
    """
    return deck.slides.add_slide(deck.slide_layouts[6])


def notes(slide, text: str) -> None:
    """Attach speaker notes.

    :param slide: Target slide.
    :param text: What to say when presenting this slide.
    :returns: ``None``.
    """
    slide.notes_slide.notes_text_frame.text = text.strip()


def box(slide, left, top, width, height, fill=None, line=None, line_w=1.25):
    """Draw a rectangle.

    :param slide: Target slide.
    :param left: Left position.
    :param top: Top position.
    :param width: Width.
    :param height: Height.
    :param fill: Optional fill colour.
    :param line: Optional outline colour.
    :param line_w: Outline width in points.
    :returns: The shape.
    """
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.adjustments[0] = 0.04
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(line_w)
    shape.shadow.inherit = False
    return shape


def text(slide, left, top, width, height, runs, align=PP_ALIGN.LEFT, spacing=6):
    """Add a text box built from (string, size, bold, colour) tuples.

    :param slide: Target slide.
    :param left: Left position.
    :param top: Top position.
    :param width: Width.
    :param height: Height.
    :param runs: Sequence of ``(text, point_size, bold, colour)``.
    :param align: Paragraph alignment.
    :param spacing: Space after each paragraph, in points.
    :returns: The text frame.
    """
    shape = slide.shapes.add_textbox(left, top, width, height)
    frame = shape.text_frame
    frame.word_wrap = True
    for index, (body, size, bold, colour) in enumerate(runs):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.alignment = align
        para.space_after = Pt(spacing)
        run = para.add_run()
        run.text = body
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = colour
        run.font.name = FONT
    return frame


def heading(slide, title: str, kicker: str | None = None) -> None:
    """Put a standard title (and optional kicker) at the top of a slide.

    :param slide: Target slide.
    :param title: The slide's one idea.
    :param kicker: Optional small label above the title.
    :returns: ``None``.
    """
    top = Inches(0.42)
    if kicker:
        text(slide, Inches(0.6), Inches(0.3), Inches(12), Inches(0.3),
             [(kicker.upper(), 11, True, GREY)], spacing=2)
        top = Inches(0.62)
    text(slide, Inches(0.6), top, Inches(12.2), Inches(0.9),
         [(title, 30, True, NAVY)], spacing=2)


def picture(slide, name: str, top=Inches(1.45), bottom_margin=Inches(0.45)) -> None:
    """Place a diagram, scaled to fit the available area.

    :param slide: Target slide.
    :param name: File name inside docs/diagrams.
    :param top: Top of the available area.
    :param bottom_margin: Space to leave below the image.
    :returns: ``None``.
    """
    from PIL import Image  # noqa: PLC0415

    path = DIAGRAMS / name
    with Image.open(path) as image:
        iw, ih = image.size
    avail_w = W - Inches(1.2)
    avail_h = H - top - bottom_margin
    scale = min(avail_w / iw, avail_h / ih)
    width, height = Emu(int(iw * scale)), Emu(int(ih * scale))
    slide.shapes.add_picture(str(path), int((W - width) / 2), int(top), width, height)


def bullets(slide, items, left=Inches(0.7), top=Inches(1.6), width=Inches(12), size=18):
    """Add a simple bulleted list with generous spacing.

    :param slide: Target slide.
    :param items: Sequence of ``(text, bold)`` or plain strings.
    :param left: Left position.
    :param top: Top position.
    :param width: Width.
    :param size: Font size in points.
    :returns: ``None``.
    """
    runs = []
    for item in items:
        body, bold = (item, False) if isinstance(item, str) else item
        runs.append((("     " + body) if not body.startswith(" ") else body, size, bold,
                     INK if bold else GREY))
    text(slide, left, top, width, H - top - Inches(0.5), runs, spacing=12)


def stat_row(slide, stats, top=Inches(5.3), colour=NAVY):
    """Draw a row of headline numbers.

    :param slide: Target slide.
    :param stats: Sequence of ``(big_number, caption)``.
    :param top: Top position of the row.
    :param colour: Colour for the numbers.
    :returns: ``None``.
    """
    count = len(stats)
    gap = Inches(0.25)
    width = (W - Inches(1.2) - gap * (count - 1)) / count
    left = Inches(0.6)
    for number, caption in stats:
        box(slide, int(left), int(top), int(width), Inches(1.35), fill=PALE, line=colour, line_w=1)
        text(slide, int(left), int(top) + Inches(0.14), int(width), Inches(0.6),
             [(number, 26, True, colour)], align=PP_ALIGN.CENTER, spacing=0)
        text(slide, int(left) + Inches(0.1), int(top) + Inches(0.72), int(width) - Inches(0.2),
             Inches(0.5), [(caption, 11, False, GREY)], align=PP_ALIGN.CENTER, spacing=0)
        left += width + gap


def divider(deck, number: str, title: str, subtitle: str):
    """Add a section divider slide.

    :param deck: The presentation.
    :param number: Section number.
    :param title: Section title.
    :param subtitle: One line on what the section covers.
    :returns: The slide.
    """
    slide = blank(deck)
    box(slide, 0, 0, W, H, fill=NAVY)
    text(slide, Inches(1.1), Inches(2.6), Inches(11), Inches(0.5),
         [(f"PART {number}", 14, True, RGBColor(0x9A, 0xB2, 0xD8))], spacing=6)
    text(slide, Inches(1.1), Inches(3.0), Inches(11), Inches(1.2),
         [(title, 40, True, WHITE)], spacing=8)
    text(slide, Inches(1.1), Inches(4.3), Inches(10), Inches(0.8),
         [(subtitle, 17, False, RGBColor(0xC9, 0xD6, 0xEA))], spacing=0)
    return slide


def build() -> Presentation:
    """Build the full deck.

    :returns: The populated presentation.
    """
    deck = new_deck()

    # ---------------------------------------------------------------- title
    s = blank(deck)
    box(s, 0, 0, W, H, fill=NAVY)
    box(s, 0, Inches(4.55), W, Inches(0.06), fill=RGBColor(0x15, 0x80, 0x3D))
    text(s, Inches(1.1), Inches(2.3), Inches(11), Inches(1.0),
         [("The Governed Data Product for AI", 44, True, WHITE)], spacing=4)
    text(s, Inches(1.1), Inches(3.35), Inches(11), Inches(0.6),
         [("Making a bank's data safe for an AI assistant to answer questions from", 19, False,
           RGBColor(0xC9, 0xD6, 0xEA))], spacing=0)
    text(s, Inches(1.1), Inches(4.9), Inches(11), Inches(1.2),
         [("Berka (PKDD'99) dataset  ·  1,079,680 rows  ·  one database, one language", 14, False,
           RGBColor(0x9A, 0xB2, 0xD8)),
          ("Built and verified end to end in 4 minutes 28 seconds, from an empty database", 14,
           False, RGBColor(0x9A, 0xB2, 0xD8))], spacing=5)
    notes(s, """
Opening line: "I'll show you three things - that the data is trustworthy, that
the meaning is pinned down, and that people only see their own customers. Each
one is backed by something that runs, not by a description."

Set expectations: about 20 minutes of walkthrough, and I'd rather be
interrupted than talk for 20 minutes straight.
""")

    # --------------------------------------------------------- the problem
    s = blank(deck)
    heading(s, "A bank wants to ask its data questions in plain English", "the problem")
    text(s, Inches(0.7), Inches(1.6), Inches(12), Inches(1.0),
         [("Eight lists: people, accounts, loans, cards, who may use which account, "
           "every payment, standing orders, towns.", 18, False, GREY)], spacing=10)
    text(s, Inches(0.7), Inches(2.4), Inches(12), Inches(0.6),
         [("An AI assistant can only answer correctly if three things are true. "
           "All three.", 20, True, INK)], spacing=0)
    cards = [
        ("1. The data is tidy", "If one payment is written down twice, every total that\nincludes it is too big - and nothing shows an error.", NAVY),
        ("2. The words mean one thing", "If \"a bad loan\" means something different to you and to me,\nwe will both be confident, and we will disagree.", AMBER),
        ("3. People see only their own", "A bank is not allowed to let everyone see everything.\nAnd the AI must not be the thing deciding that.", GREEN),
    ]
    left = Inches(0.7)
    width = Inches(3.9)
    for title, body, colour in cards:
        box(s, int(left), Inches(3.3), int(width), Inches(2.0), fill=PALE, line=colour, line_w=1.5)
        text(s, int(left) + Inches(0.25), Inches(3.55), int(width) - Inches(0.5), Inches(0.5),
             [(title, 17, True, colour)], spacing=6)
        text(s, int(left) + Inches(0.25), Inches(4.15), int(width) - Inches(0.5), Inches(1.2),
             [(body, 13, False, GREY)], spacing=0)
        left += width + Inches(0.35)
    text(s, Inches(0.7), Inches(5.6), Inches(12), Inches(0.6),
         [("Miss any one of them and the assistant gives an answer that looks right and is wrong "
           "- which is worse than no answer.", 16, True, RED)], spacing=0)
    notes(s, """
The key sentence is the red one. A wrong-but-confident answer is worse than a
refusal, because nobody checks it.

If asked why not just point an AI at the database: because all three of these
fail at once. That is the whole project.
""")

    # --------------------------------------------------------- way of working
    s = blank(deck)
    heading(s, "Four steps. Like cooking from a messy box of shopping.", "the way of working")
    steps = [
        ("1  BRONZE", "Photocopy everything.\nChange nothing.", "So we can always say what\nactually arrived.", NAVY),
        ("2  SILVER", "Tidy up. Check everything.\nGrade what is broken.", "123 checks. Three grades:\nred, orange, green.", AMBER),
        ("3  GOLD", "Build the shelves.\nAgree what words mean.", "Decide once, write it down,\nso nobody redefines it.", GREEN),
        ("4  SERVE", "Let the AI ask -\nwith three safeguards.", "A dictionary, a bouncer,\nand a lock on the shelf.", RED),
    ]
    left = Inches(0.6)
    width = Inches(2.95)
    for title, what, why, colour in steps:
        box(s, int(left), Inches(1.75), int(width), Inches(3.4), fill=WHITE, line=colour, line_w=2)
        box(s, int(left), Inches(1.75), int(width), Inches(0.52), fill=colour)
        text(s, int(left) + Inches(0.2), Inches(1.84), int(width), Inches(0.4),
             [(title, 15, True, WHITE)], spacing=0)
        text(s, int(left) + Inches(0.22), Inches(2.5), int(width) - Inches(0.44), Inches(1.0),
             [(what, 15, True, INK)], spacing=0)
        text(s, int(left) + Inches(0.22), Inches(3.75), int(width) - Inches(0.44), Inches(1.2),
             [(why, 12.5, False, GREY)], spacing=0)
        left += width + Inches(0.22)
    text(s, Inches(0.6), Inches(5.5), Inches(12.2), Inches(0.8),
         [("The names are standard: bronze, silver, gold. What matters is that each step is "
           "allowed to do one job and not the next one's.", 15, False, GREY)], spacing=0)
    notes(s, """
This is the spine of the whole talk. Everything else hangs off these four.

The discipline point: Bronze is not allowed to clean, Silver is not allowed to
delete, Gold is not allowed to reach back past Silver. Each boundary stops a
specific class of mistake.
""")

    # --------------------------------------------------------- bronze
    s = blank(deck)
    heading(s, "Step 1 — copy it exactly, and prove you did", "bronze")
    bullets(s, [
        ("Every column arrives as plain text. Nothing is converted, nothing is fixed, nothing is dropped.", True),
        "A squashed tomato stays a squashed tomato. Fixing it here would hide it from the checks.",
        ("Each file gets a fingerprint - a code that changes if a single letter changes.", True),
        "So when somebody argues about a number six months later, we can prove the file never moved.",
        ("Running it twice gives exactly the same result.", True),
        "Nothing to repair if it is interrupted - just run it again.",
    ], top=Inches(1.7))
    stat_row(s, [("1,079,680", "rows landed"), ("< 4 sec", "to load all eight files"),
                 ("8 of 8", "row counts match the published figures"),
                 ("SHA-256", "fingerprint recorded per file")], top=Inches(5.25))
    notes(s, """
The temptation at this step is to be helpful - trim a space, fix a date. Do not.
Every repair here is a defect you can no longer find.

The row counts matching the published reference exactly is the first piece of
evidence that the pipeline is sound: we did not get a different dataset.
""")

    # --------------------------------------------------------- severity
    s = blank(deck)
    heading(s, "Step 2 — tidy up, and grade everything that is broken", "silver")
    picture(s, "03_severity.png", top=Inches(1.5), bottom_margin=Inches(1.25))
    text(s, Inches(0.6), H - Inches(1.1), Inches(12.2), Inches(0.8),
         [("We never throw a row away quietly. Red is removed and counted. Orange stays, with a "
           "warning that reaches the final answer. Green is tidied and logged.", 15, False, GREY)],
         spacing=0)
    notes(s, """
Walk the three lanes left to right. The point is that each colour has a
MECHANICAL consequence, not just a label in a report.

Orange is the one people miss: the warning travels with the row all the way
into the answer the AI gives, so the caveat cannot get lost in a document
nobody opens.
""")

    # --------------------------------------------------------- the hard part
    s = blank(deck)
    heading(s, "The grading is the hard part. The check is the easy half.", "the decision that matters")
    box(s, Inches(0.6), Inches(1.55), Inches(6.0), Inches(2.5), fill=RGBColor(0xF4, 0xFA, 0xF6), line=GREEN, line_w=1.5)
    text(s, Inches(0.85), Inches(1.75), Inches(5.5), Inches(0.4),
         [("14 payments of exactly zero", 19, True, GREEN)], spacing=6)
    text(s, Inches(0.85), Inches(2.25), Inches(5.5), Inches(1.6),
         [("A rule saying \"every payment must be more than zero\" sounds obviously right.",
           14, False, GREY),
          ("At RED it would delete 14 real interest payments and break 14 customers' running "
           "balances — to fix nothing at all.", 14, True, INK),
          ("So it is GREEN.", 15, True, GREEN)], spacing=6)
    box(s, Inches(6.95), Inches(1.55), Inches(5.8), Inches(2.5), fill=RGBColor(0xFD, 0xF4, 0xF4), line=RED, line_w=1.5)
    text(s, Inches(7.2), Inches(1.75), Inches(5.3), Inches(0.4),
         [("A payment of minus 500", 19, True, RED)], spacing=6)
    text(s, Inches(7.2), Inches(2.25), Inches(5.3), Inches(1.6),
         [("Same column, same kind of rule.", 14, False, GREY),
          ("But a minus sign has been applied twice, so money would move the wrong way. There is "
           "no reading of this row that is correct.", 14, True, INK),
          ("So it is RED.", 15, True, RED)], spacing=6)
    text(s, Inches(0.6), Inches(4.45), Inches(12.2), Inches(1.4),
         [("Same column. Opposite decision. And we can say why for each one.", 20, True, NAVY),
          ("That is what the brief is really testing. A rule without a justified grade scores the "
           "same as no rule — because the grade is where the judgement lives.", 15, False, GREY)],
         spacing=10)
    notes(s, """
This is the slide to spend time on. If they remember one thing, make it this.

The general principle: before setting a severity, ask what ACTING on it would
cost. A defensible rule with the wrong grade does more damage than the defect.

Expect the question "isn't zero always wrong?" - answer with the interest run:
the bank charged interest, it worked out to nothing, the posting is real.
""")

    # --------------------------------------------------------- gold / model
    s = blank(deck)
    heading(s, "Step 3 — build the shelves, and pin down the words", "gold")
    picture(s, "04_star_schema.png", top=Inches(1.4), bottom_margin=Inches(1.3))
    text(s, Inches(0.6), H - Inches(1.15), Inches(12.2), Inches(0.9),
         [("One shelf per kind of thing, and a rule about what one row means. Customers do not "
           "connect to accounts directly — they connect through a record that says in what "
           "capacity, which is what makes \"the account owner\" a phrase with one meaning.", 14,
           False, GREY)], spacing=0)
    notes(s, """
Point at bridge_disposition. That is the shape that matters: a husband may be
allowed to use an account he does not own, and his gold card must not make the
owner look like a gold card holder.

If the grain is wrong - say the customer shelf has someone twice - every count
is wrong and NOTHING errors. So we check it on every build, not by eye.
""")

    # --------------------------------------------------------- serve
    s = blank(deck)
    heading(s, "Step 4 — let the AI in, with three safeguards", "serving")
    picture(s, "02_query_path.png", top=Inches(1.5), bottom_margin=Inches(1.9))
    items = [
        ("A dictionary", "it sees the meaning of the data, never the data", NAVY),
        ("A bouncer", "reads the AI's instruction properly before it runs", AMBER),
        ("A lock on the shelf", "the shelf itself hands over only your rows", GREEN),
    ]
    left = Inches(0.7)
    width = Inches(3.95)
    for title, body, colour in items:
        box(s, int(left), H - Inches(1.75), int(width), Inches(1.15), fill=PALE, line=colour, line_w=1.4)
        text(s, int(left) + Inches(0.2), H - Inches(1.62), int(width), Inches(0.4),
             [(title, 15, True, colour)], spacing=2)
        text(s, int(left) + Inches(0.2), H - Inches(1.2), int(width) - Inches(0.3), Inches(0.6),
             [(body, 12, False, GREY)], spacing=0)
        left += width + Inches(0.25)
    notes(s, """
The lock is the one to dwell on. You could ask the AI nicely to only show
someone their own customers - that is not a lock, it is a REQUEST. You are
asking the thing you are limiting to limit itself.

Instead the lock is on the shelf. The AI writes text; the predicate that limits
the rows is never in that text, so no rewriting of the text can remove it.
""")
    _results(deck)
    _decisions(deck)
    _readiness(deck)
    return deck


def _results(deck: Presentation) -> None:
    """Add the results act: what the three tasks produced.

    :param deck: The presentation.
    :returns: ``None``.
    """
    notes(divider(deck, "2", "What it found, and what it answered",
                  "The three tasks the brief sets, and the evidence behind each"), """
Part 1 was how it works. Part 2 is what it actually found and answered.

Everything from here is a number that came out of a run, not a capability
being described. If a figure on a slide cannot be traced to the database or
the run log, it does not belong on the slide.
""")

    # ------------------------------------------------------- task 1 defects
    s = blank(deck)
    heading(s, "Task 1 — every defect found, and how to solve it", "data quality")
    picture(s, "08_defect_catalogue.png", top=Inches(1.4), bottom_margin=Inches(1.1))
    text(s, Inches(0.6), H - Inches(1.0), Inches(12.2), Inches(0.8),
         [("Volume is not harm. One row in the red band changes two answers; 2.5 million rows in "
           "the green band change none. Nine of the fourteen need no fix at all.", 15, True, NAVY)],
         spacing=0)
    notes(s, """
Do not read the list. Point at the shape: the bars get longer as the colour
gets safer.

Nine of fourteen need no fix, and they are reported precisely so nobody
"cleans" them later. Clipping overdrafts would bias the Q9 average upwards.
That is a real risk - it is the obvious thing a well-meaning person does.
""")

    # ----------------------------------------------------- the three finds
    s = blank(deck)
    heading(s, "Three things we found that the documentation does not mention", "data quality")
    finds = [
        ("The balance chain does not add up",
         "Testing order-independently: 3,869 of 4,500 accounts differ between the sum of their "
         "payments and their last stated balance. Most is rounding — every amount carries one "
         "decimal. But 55 accounts are out by more than 100, and one by exactly 1,200 with only "
         "55 payments. That is a missing or duplicated posting, not rounding.", AMBER),
        ("Same-day order is simply not recorded",
         "Payment IDs are not in time order within a day. For 183 accounts that uncertainty lands "
         "on their very last active day — so \"the closing balance\" is a documented choice we "
         "made, not a fact the data contains. That is exactly what Q9 asks for.", AMBER),
        ("One duplicate no primary key could catch",
         "Same account, same date, same type, same amount, same resulting balance — different ID. "
         "A genuinely separate payment would have moved the balance. This is the single row that "
         "gets removed, and the product reports 1,056,319 where the file has 1,056,320.", RED),
    ]
    top = Inches(1.65)
    for title, body, colour in finds:
        box(s, Inches(0.6), int(top), Inches(12.2), Inches(1.6), fill=PALE, line=colour, line_w=1.4)
        text(s, Inches(0.85), int(top) + Inches(0.14), Inches(11.7), Inches(0.4),
             [(title, 17, True, colour)], spacing=4)
        text(s, Inches(0.85), int(top) + Inches(0.58), Inches(11.7), Inches(1.0),
             [(body, 13, False, GREY)], spacing=0)
        top += Inches(1.78)
    notes(s, """
These are the slides that show we actually looked, rather than running the
rules the dataset documentation suggests.

The 1,200 one is worth naming specifically: 55 payments on that account, and a
gap of exactly 1,200.00. That is not rounding, that is a posting.
""")

    # ----------------------------------------------------- defect lifecycle
    s = blank(deck)
    heading(s, "And what \"solving\" one actually means", "data quality")
    picture(s, "07_defect_lifecycle.png", top=Inches(1.4), bottom_margin=Inches(0.9))
    text(s, Inches(0.6), H - Inches(0.8), Inches(12.2), Inches(0.6),
         [("Red: fix at source and reload — nothing was destroyed. Orange: correct it, or accept "
           "it is reality and keep the caveat. Green: usually nothing, and the rule waits.", 14,
           False, GREY)], spacing=0)
    notes(s, """
The orange column is the honest one. Sometimes the right permanent answer is
"this is reality, and the caveat stays forever" - intra-day ordering is not
recorded anywhere, so no amount of work makes that uncertainty go away.

Saying so is better than pretending a cleanup will fix it.
""")

    # ----------------------------------------------------------- task 2
    s = blank(deck)
    heading(s, "Task 2 — the AI answered all ten, first time", "model and semantic layer")
    text(s, Inches(0.7), Inches(1.55), Inches(12), Inches(0.6),
         [("It never saw the database. It got the dictionary and the question, and nothing else.",
           18, True, INK)], spacing=12)
    rows = [
        ("Q1  clients per region", "south Moravia 937, north Moravia 920, + 6 more"),
        ("Q2  loans granted per year", "1993: 2.6m · 1994: 13.4m · 1995: 13.3m · 1996: 18.3m · +2"),
        ("Q3  problematic loans", "76 of 682 = 11.14%  (matches the published figure exactly)"),
        ("Q4  average loan by owner's card", "junior 221,970 · gold 161,881 · no card 148,865 · classic 148,809"),
        ("Q5  top districts, 1997", "Prague 115.1m · Karvina 28.5m · Ostrava 27.7m · +7"),
        ("Q6  new accounts per month 1996", "all twelve months present — Jan 106, Feb 104, Mar 124 …"),
        ("Q7  owner age at loan start", "paid 37.1 · unpaid 39.6 · running 38.7 · in debt 37.0"),
        ("Q8  gender split, gold cards", "53 men (60.2%) · 35 women (39.8%)"),
        ("Q9  average balance Dec 1998", "43,808.94 over 4,500 accounts  (+ 2 caveats attached)"),
        ("Q10 frequency with worst share", "after each transaction 18.75% — but only 6 of 32 loans"),
    ]
    top = Inches(2.25)
    for index, (question, answer) in enumerate(rows):
        if index % 2 == 0:
            box(s, Inches(0.6), int(top) - Inches(0.03), Inches(12.2), Inches(0.42), fill=PALE)
        text(s, Inches(0.75), int(top), Inches(4.4), Inches(0.38), [(question, 12.5, True, INK)], spacing=0)
        text(s, Inches(5.2), int(top), Inches(7.6), Inches(0.38), [(answer, 12.5, False, GREY)], spacing=0)
        top += Inches(0.42)
    text(s, Inches(0.6), Inches(6.65), Inches(12.2), Inches(0.5),
         [("10 of 10 matched the answers a person had worked out by hand beforehand. No retries. "
           "No SQL corrected by hand.", 15, True, GREEN)], spacing=0)
    notes(s, """
The marking scheme was written first, by hand, before the model saw anything.
That is what makes 10/10 mean something.

If asked about Q3 matching 11.14% exactly: that figure is published with the
dataset, so it is an independent check on the whole pipeline, not just on the
query.
""")

    # ----------------------------------------------------------- task 3
    s = blank(deck)
    heading(s, "Task 3 — four people, four different answers to the same question", "entitlements")
    text(s, Inches(0.7), Inches(1.5), Inches(12), Inches(0.5),
         [("Measured by logging in as each one and counting — not by reading the settings.", 17,
           False, GREY)], spacing=10)
    users = [
        ("cro_global", "group risk", "5,369", GREEN),
        ("rm_north", "northern book", "1,481", NAVY),
        ("rm_south", "southern book", "1,386", NAVY),
        ("rm_unassigned", "brand new, no book yet", "0", RED),
    ]
    left = Inches(0.6)
    width = Inches(2.98)
    for role, who, clients, colour in users:
        box(s, int(left), Inches(2.25), int(width), Inches(1.9), fill=WHITE, line=colour, line_w=2)
        text(s, int(left) + Inches(0.2), Inches(2.42), int(width), Inches(0.4),
             [(role, 14, True, colour)], spacing=2)
        text(s, int(left) + Inches(0.2), Inches(2.8), int(width), Inches(0.3),
             [(who, 11, False, GREY)], spacing=0)
        text(s, int(left) + Inches(0.2), Inches(3.2), int(width) - Inches(0.3), Inches(0.7),
             [(clients, 32, True, colour)], spacing=0)
        text(s, int(left) + Inches(0.2), Inches(3.78), int(width), Inches(0.3),
             [("clients visible", 11, False, GREY)], spacing=0)
        left += width + Inches(0.2)
    text(s, Inches(0.6), Inches(4.45), Inches(12.2), Inches(1.5),
         [("The zero is the important one. A badly built system defaults to showing everything.",
           18, True, RED),
          ("And \"sees everything\" is not an exemption — the risk manager holds a portfolio "
           "containing every client and goes through exactly the same lock as everyone else.",
           15, False, GREY)], spacing=10)
    stat_row(s, [("9", "ways we tried to break in"), ("9", "that failed"),
                 ("4 inserts", "to onboard a new person"), ("0", "code changes to do it")],
             top=Inches(5.75), colour=GREEN)
    notes(s, """
Nine bypass attempts: pretending to be another user, going round the back of
the views straight to the base tables, reading the raw layer, setting a
session variable to someone else's name, editing the permission tables,
turning the lock off, dropping it, writing, and joining outwards to widen the
result. All nine refused.

Onboarding is four inserts and one credential. No policy, view or query
changes - that was an explicit requirement in the brief.
""")


def _decision_slide(deck, number, question, options, chosen, why, cost, note):
    """Add one design-decision slide in a fixed, comparable shape.

    Every decision is presented the same way -- what was asked, what the
    options were, what was chosen, why, and what it cost -- so a reviewer can
    compare them instead of re-learning a layout each time.

    :param deck: The presentation.
    :param number: Decision number.
    :param question: The question the decision answers.
    :param options: Sequence of ``(option, verdict, is_chosen)``.
    :param chosen: One line naming the choice.
    :param why: The reason, in one or two sentences.
    :param cost: What the choice costs.
    :param note: Speaker notes.
    :returns: The slide.
    """
    s = blank(deck)
    heading(s, question, f"design decision {number}")
    top = Inches(1.6)
    for option, verdict, is_chosen in options:
        colour = GREEN if is_chosen else GREY
        fill = RGBColor(0xF1, 0xF8, 0xF3) if is_chosen else PALE
        box(s, Inches(0.6), int(top), Inches(12.2), Inches(0.85), fill=fill, line=colour,
            line_w=1.8 if is_chosen else 1.0)
        text(s, Inches(0.85), int(top) + Inches(0.1), Inches(4.0), Inches(0.5),
             [(option, 15, True, colour if is_chosen else INK)], spacing=0)
        text(s, Inches(4.95), int(top) + Inches(0.14), Inches(7.6), Inches(0.6),
             [(verdict, 13, False, GREY)], spacing=0)
        if is_chosen:
            text(s, Inches(11.6), int(top) + Inches(0.1), Inches(1.1), Inches(0.4),
                 [("CHOSEN", 11, True, GREEN)], spacing=0)
        top += Inches(0.98)
    top += Inches(0.15)
    box(s, Inches(0.6), int(top), Inches(7.6), Inches(1.5), fill=WHITE, line=NAVY, line_w=1.4)
    text(s, Inches(0.85), int(top) + Inches(0.12), Inches(7.1), Inches(0.35),
         [("WHY", 11, True, NAVY)], spacing=4)
    text(s, Inches(0.85), int(top) + Inches(0.46), Inches(7.1), Inches(1.0),
         [(why, 13.5, False, INK)], spacing=0)
    box(s, Inches(8.4), int(top), Inches(4.4), Inches(1.5), fill=WHITE, line=AMBER, line_w=1.4)
    text(s, Inches(8.65), int(top) + Inches(0.12), Inches(3.9), Inches(0.35),
         [("WHAT IT COSTS", 11, True, AMBER)], spacing=4)
    text(s, Inches(8.65), int(top) + Inches(0.46), Inches(3.9), Inches(1.0),
         [(cost, 13.5, False, INK)], spacing=0)
    notes(s, note)
    return s


def _decisions(deck: Presentation) -> None:
    """Add the design-decision act -- the pitch.

    :param deck: The presentation.
    :returns: ``None``.
    """
    notes(divider(deck, "3", "Why it is built this way",
                  "Six decisions, each with the options considered and what the choice cost"), """
Every slide in this part has the same four parts: the options that were real,
the one chosen, why, and what it cost. The cost box is not modesty - a decision
with no stated cost usually means the alternatives were never priced.

All six are in the Design Decision Record, with six more that did not need a
slide.
""")

    _decision_slide(
        deck, 1, "Where should the entitlement filter sit?",
        [("In the prompt", "Ask the AI to filter itself. Defeated by the model simply omitting it.", False),
         ("In the application", "A gateway rewrites every query. Real, but one unanticipated query shape defeats it — and the blast radius is every user.", False),
         ("In the database", "A rule attached to the shelf itself, applied inside every single statement.", True)],
        "In the database",
        "The AI only ever writes text. The thing that limits the rows is not in that text, so "
        "no rewriting of the text can remove it. Nine bypass attempts, nine failures.",
        "One login per person, which complicates connection pooling. The answer is a pool per "
        "role, or a trusted gateway that picks the role.",
        """
This is the strongest slide in the deck. The one-liner: asking the model to
filter itself is a REQUEST, not a control - you are asking the thing being
limited to limit itself.

Also note the identity choice: we use the logged-in database user, not a
setting the connection can change. A setting can be changed by anything that
can send SQL. There is a test that tries exactly that.
""")

    s = blank(deck)
    heading(s, "The same request, three places the lock could sit", "design decision 1")
    picture(s, "05_where_the_filter_sits.png", top=Inches(1.4), bottom_margin=Inches(0.5))
    notes(s, """
Point at the dark lozenge moving down the three rows. Everything else is held
constant, so the choice is the only thing changing.
""")

    _decision_slide(
        deck, 2, "One big table, or a proper model?",
        [("One big table", "Flatten everything onto the payment. No joins — which is why many AI tools prefer it.", False),
         ("Data Vault", "Right for integrating many sources with history. There is one source and a single extract.", False),
         ("Star schema with a bridge", "One table per kind of thing, joined through a record that says in what capacity.", True)],
        "Star schema with a bridge",
        "The ten questions have four different grains — customer, account, loan, payment. One "
        "table can only have one of them, so every other count becomes a DISTINCT the query "
        "author has to remember, and gets wrong with no error.",
        "Joins, and a month-end balance table that has to be rebuilt. The curated views give the "
        "AI a join-free surface anyway.",
        """
The killer detail: in one big table, a customer with 300 payments is counted
300 times unless someone remembers DISTINCT. Nothing errors. That is exactly
the failure mode we are trying to design out.

Second reason, less obvious: the entitlement filter. On a customer table it is
one check against 5,369 rows. Flattened, it is evaluated per payment -
1,056,319 times.
""")

    s = blank(deck)
    heading(s, "The same two tasks, priced against both shapes", "design decision 2")
    picture(s, "06_model_shape.png", top=Inches(1.4), bottom_margin=Inches(0.5))
    notes(s, "Left is what we built. Right is what we would have paid for removing the joins.")

    _decision_slide(
        deck, 3, "What should happen to a broken row?",
        [("Reject everything broken", "Clean data, but 2.5 million rows deleted for cosmetic reasons, and the answers change.", False),
         ("Repair it quietly", "Looks tidy. Hides the incident, and nobody can audit what was changed.", False),
         ("Grade it: red, orange, green", "Each grade has a mechanical consequence, and the reason is written down.", True)],
        "Three grades, each with a consequence",
        "A grade without a consequence is a comment. Red removes and counts; orange keeps and "
        "attaches a warning that reaches the answer; green standardises and logs.",
        "Three code paths instead of one, and a quarantine table to keep. In exchange every "
        "exclusion is reversible, countable and attributable to a named rule.",
        """
Link back to the zero-amount slide. The grade is where the judgement lives,
and the brief says explicitly that an ungraded rule scores the same as no rule.

If pushed on "why not just reject everything broken": 2.5 million rows are in
the green band and change no answer. Rejecting them would be deleting most of
the dataset to improve nothing.
""")

    _decision_slide(
        deck, 4, "How does the AI learn what the data means?",
        [("Describe it in the prompt", "Fast to write. Drifts silently the moment the schema changes.", False),
         ("A BI tool's metrics layer", "Mature, but another product to buy, run and keep on-premises.", False),
         ("A written file the build checks", "Meanings, grains and caveats in one file, verified against the live database.", True)],
        "A semantic layer the build verifies",
        "A dictionary that has drifted is worse than none, because it gives the model confident "
        "wrong information and the model cannot check it. A described column that does not "
        "exist, or a column nobody described, fails the build.",
        "The file has to be maintained alongside the model. The verification is what makes that "
        "safe rather than a liability.",
        """
This is the piece that produced the 10/10. The model had no database access -
only this file and the question.

The verification matters more than the file: 100 columns described, and the
build fails if any of them stops matching reality.
""")

    _decision_slide(
        deck, 5, "How much should we trust the AI?",
        [("Trust it; give it the database", "It would answer by looking at the data, which tests the agent and not the data product.", False),
         ("Trust it; check the answer", "Too late. By then the query has already run against production.", False),
         ("Treat it as an untrusted author", "No tools, no filesystem, no connection. Its SQL is parsed before anything runs.", True)],
        "Untrusted, and sandboxed",
        "We are testing whether the semantic layer is good enough for a model to be right — not "
        "whether a model can go digging. And a query author you do not control should not be "
        "able to reach anything you have not deliberately published.",
        "A parser dependency, and legitimate queries are occasionally stricter than necessary.",
        """
Twenty bypass attempts were put through the parser - comment-hidden second
statements, writes buried in a WITH clause, reading internal schemas, file
functions. All rejected.

Important honesty point: the parser is NOT the security boundary. The three
attempts that got past it were then refused by the database itself, because
the account is unprivileged. Two independent controls, and we tested both.
""")

    _decision_slide(
        deck, 6, "PostgreSQL, or something lighter?",
        [("DuckDB, in-process", "Fastest to set up. Has no row-level security — so Task 3 becomes prose and untested SQL.", False),
         ("A cloud warehouse", "Powerful. Contradicts the bank's own direction of travel, which is back on-premises.", False),
         ("PostgreSQL 16", "One database. Row-level security that we can connect to and prove.", True)],
        "PostgreSQL 16, run locally",
        "Task 3 is about enforcement, and the only honest way to show a query cannot bypass a "
        "filter is to put the filter in the engine and prove it by logging in as a restricted "
        "user and counting rows.",
        "No built-in lineage or scheduling, and a single node. Neither is on the critical path "
        "of this brief, and both are named in the scaling section.",
        """
If asked why not DuckDB, which would have been faster: the one task that is
purely about control would have had no evidence behind it.

The brief warns in bold about spending the time on infrastructure. Total
infrastructure cost here: one 50-line shell script that starts Postgres.
""")

    # ------------------------------------------------------------ scaling
    s = blank(deck)
    heading(s, "What breaks at 100,000 times the data", "scaling honestly")
    text(s, Inches(0.7), Inches(1.5), Inches(12), Inches(0.5),
         [("100 billion payments. 450 million accounts. Around 10 terabytes. Four things break, "
           "in this order.", 17, False, GREY)], spacing=12)
    breaks = [
        ("1", "The full rebuild", "Everything is rebuilt from scratch each run. At 10 TB that is hours of rewriting data that did not change. It becomes an incremental load, month by month."),
        ("2", "The quality checks", "123 rules, each reading everything. They have to check only what arrived, and the running-balance check needs to remember where it got to."),
        ("3", "The month-end balance table", "450 million accounts times 72 months is 32 billion pre-computed rows. It becomes one new slice per month instead of a rebuild."),
        ("4", "The entitlement lookup", "Cheap over 4,500 accounts, expensive when one portfolio holds millions. It becomes a stored, indexed list sitting next to the data."),
    ]
    top = Inches(2.2)
    for number, title, body in breaks:
        box(s, Inches(0.6), int(top), Inches(0.55), Inches(0.9), fill=AMBER)
        text(s, Inches(0.6), int(top) + Inches(0.22), Inches(0.55), Inches(0.5),
             [(number, 20, True, WHITE)], align=PP_ALIGN.CENTER, spacing=0)
        box(s, Inches(1.15), int(top), Inches(11.65), Inches(0.9), fill=PALE)
        text(s, Inches(1.4), int(top) + Inches(0.1), Inches(3.0), Inches(0.4),
             [(title, 15, True, INK)], spacing=0)
        text(s, Inches(4.5), int(top) + Inches(0.12), Inches(8.1), Inches(0.7),
             [(body, 12.5, False, GREY)], spacing=0)
        top += Inches(1.02)
    text(s, Inches(0.6), Inches(6.5), Inches(12.2), Inches(0.7),
         [("Two things do not break, and they are the parts worth keeping: the dictionary (a few "
           "thousand words, whatever the volume) and where the lock sits.", 15, True, GREEN)],
         spacing=0)
    notes(s, """
Being specific here is the point. "It would need more hardware" is not an
answer; "the month-end balance table becomes 32 billion pre-computed rows" is.

The design does not change for the entitlement one - it is still a rule on the
table, and onboarding is still an insert. Only the lookup's shape changes.
""")


# --------------------------------------------------------------------------
# part 4: readiness and completeness
# --------------------------------------------------------------------------


def _two_columns(slide, left_title, left_items, right_title, right_items,
                 left_colour=GREEN, right_colour=AMBER):
    """Draw two headed lists side by side.

    :param slide: Target slide.
    :param left_title: Heading of the left column.
    :param left_items: Sequence of ``(lead, detail)`` for the left column.
    :param right_title: Heading of the right column.
    :param right_items: Sequence of ``(lead, detail)`` for the right column.
    :param left_colour: Accent colour of the left column.
    :param right_colour: Accent colour of the right column.
    :returns: ``None``.
    """
    columns = (
        (Inches(0.6), left_title, left_items, left_colour),
        (Inches(6.95), right_title, right_items, right_colour),
    )
    for left, title, items, colour in columns:
        box(slide, int(left), Inches(1.45), Inches(5.78), Inches(0.5), fill=colour)
        text(slide, int(left) + Inches(0.2), Inches(1.52), Inches(5.4), Inches(0.4),
             [(title.upper(), 13, True, WHITE)], spacing=0)
        top = Inches(2.1)
        for lead, detail in items:
            box(slide, int(left), int(top), Inches(5.78), Inches(1.0), fill=PALE)
            text(slide, int(left) + Inches(0.2), int(top) + Inches(0.08), Inches(5.4),
                 Inches(0.3), [(lead, 13.5, True, INK)], spacing=0)
            text(slide, int(left) + Inches(0.2), int(top) + Inches(0.38), Inches(5.4),
                 Inches(0.6), [(detail, 11.5, False, GREY)], spacing=0)
            top += Inches(1.12)


def _matrix(slide, rows, top=Inches(1.95), widths=(4.3, 4.3, 3.8), row_h=Inches(0.62)):
    """Draw a three-column requirement / delivered / evidence table.

    :param slide: Target slide.
    :param rows: Sequence of ``(requirement, delivered, evidence)``; the first
        row is treated as the header.
    :param top: Top of the table.
    :param widths: Column widths in inches.
    :param row_h: Height of each body row.
    :returns: ``None``.
    """
    for index, cells in enumerate(rows):
        header = index == 0
        height = Inches(0.42) if header else row_h
        left = Inches(0.6)
        for cell, width_in in zip(cells, widths):
            width = Inches(width_in)
            box(slide, int(left), int(top), int(width), int(height),
                fill=NAVY if header else (PALE if index % 2 else WHITE),
                line=None if header else RGBColor(0xDD, 0xE3, 0xED), line_w=0.75)
            text(slide, int(left) + Inches(0.14), int(top) + Inches(0.08),
                 int(width) - Inches(0.24), int(height) - Inches(0.1),
                 [(cell, 11.5 if header else 11, header, WHITE if header else INK)],
                 spacing=0)
            left += width
        top += height


def _readiness(deck: Presentation) -> None:
    """Add part 4: what is ready, what is thin, and the completeness check.

    :param deck: The presentation.
    :returns: ``None``.
    """
    notes(divider(deck, "4", "Is it ready?",
                  "What was built, what it is worth, and what is still thin - said out loud "
                  "rather than left for a reviewer to find."), """
This part answers three different questions that tend to get merged: is it
complete against the brief, is it trustworthy, and what would happen next.

Completeness is a checklist and it is on two slides. Trustworthiness is the two
bugs the build found in itself, and the thin column. Next steps are in
dependency order.
""")

    # --------------------------------------------------- what exists, in numbers
    s = blank(deck)
    heading(s, "What exists", "the whole build, in one picture")
    text(s, Inches(0.7), Inches(1.4), Inches(12), Inches(0.5),
         [("One command - make clean all - builds every number in every deliverable from the "
           "four source files. It takes four and a half minutes.", 16, False, GREY)], spacing=10)
    stat_row(s, [
        ("12 of 12", "pipeline steps green"),
        ("4m 28s", "empty database to deliverables"),
        ("137", "tests passing"),
        ("123", "quality rules executed"),
        ("1.06 m", "rows checked"),
    ], top=Inches(2.1))
    stat_row(s, [
        ("10 of 10", "LLM answers correct"),
        ("9 of 9", "bypass attempts refused"),
        ("20 of 20", "seeded defects caught"),
        ("135", "files in the submitted ZIP"),
        ("0", "numbers typed by hand"),
    ], top=Inches(3.7))
    text(s, Inches(0.6), Inches(5.5), Inches(12.2), Inches(1.3),
         [("Why the last one matters most: a deck or a spreadsheet goes stale the moment a "
           "number changes. Every figure on these slides is read out of the database or the "
           "run log by a script. If the pipeline changes, the deck is wrong until it is "
           "re-run - and re-running it is one command.", 15, False, INK)], spacing=0)
    notes(s, """
Lead with the reproducibility, not the counts. The counts are only credible
because of it.

The "0 numbers typed by hand" claim is not free, and section 2.1 of the review
is the honest footnote: one hard-coded test count had gone stale in the
workbook's Overview tab. It was found by grepping the generators for literals
and is now derived by collecting the suite. The lesson stated in the review is
the one to say here: the honesty rule only works where it is mechanised.
""")

    # ---------------------------------------------------------- the system map
    s = blank(deck)
    heading(s, "Everything that was set up", "one map of the whole thing")
    picture(s, "09_system_map.png", top=Inches(1.25))
    notes(s, """
This is the slide to leave up during questions.

Seven schemas, four roles, eleven consumer views, one guard, one LLM call per
question. Nothing on this map is a product that had to be bought or a service
that had to be configured: it is one PostgreSQL database, a YAML file of rules,
a YAML file of meaning, and about 3,900 lines of Python.

Total infrastructure setup: a 50-line shell script that starts Postgres. The
brief warns in bold about spending the time on tooling; this is the evidence
that the warning was heeded.
""")

    # ------------------------------------------------------- build sequence
    s = blank(deck)
    heading(s, "The order it runs in", "and why the order is a control, not a habit")
    picture(s, "10_build_sequence.png", top=Inches(1.25))
    notes(s, """
Two orderings on this map are load-bearing and were both learned the hard way.

Security is built BEFORE the consumer views, because a consumer view reads the
entitlement list; building it the other way round fails. And the model is
rebuilt whenever the consumer views are, because dropping them cascades.

Both of those are in DECISIONS as D008 and D012. They are in the diagram so
that nobody has to rediscover them.
""")

    # ------------------------------------------- the two bugs we caught ourselves
    s = blank(deck)
    heading(s, "Two bugs this build found in itself", "the part worth trusting")
    text(s, Inches(0.7), Inches(1.35), Inches(12), Inches(0.45),
         [("Both would have been invisible to a reviewer. Both were caught by a check that "
           "runs every time, not by someone reading the code.", 16, False, GREY)], spacing=8)
    bugs = [
        ("1", "The quarantine list was not told which room to look in",
         "Testing the rules means planting known defects in a copy of the data. But the list of "
         "rows to throw away did not say which copy, so a planted defect deleted a REAL row: 76 "
         "districts instead of 77, and 11,024 payments left pointing at nothing.",
         "Caught by the model build, which counts every parent before it accepts a child. Fixed "
         "by scoping the list to one schema. Written up as D008."),
        ("2", "A view politely dropped the lock",
         "The rule that hides other people's clients sits on the table. A view on top of that "
         "table normally runs as its owner - so it read the table as the owner and handed back "
         "all 682 loans to a user entitled to none.",
         "Caught by logging in as that restricted user and counting, which is the only test that "
         "would have found it. Fixed with one setting per view, plus a test that reads the "
         "setting back. Written up as D010."),
    ]
    top = Inches(2.05)
    for number, title, what, how in bugs:
        box(s, Inches(0.6), int(top), Inches(0.6), Inches(2.15), fill=RED)
        text(s, Inches(0.6), int(top) + Inches(0.75), Inches(0.6), Inches(0.5),
             [(number, 24, True, WHITE)], align=PP_ALIGN.CENTER, spacing=0)
        box(s, Inches(1.2), int(top), Inches(11.55), Inches(2.15), fill=PALE)
        text(s, Inches(1.45), int(top) + Inches(0.12), Inches(11.1), Inches(0.35),
             [(title, 16, True, INK)], spacing=0)
        text(s, Inches(1.45), int(top) + Inches(0.52), Inches(11.1), Inches(0.75),
             [(what, 12.5, False, GREY)], spacing=0)
        text(s, Inches(1.45), int(top) + Inches(1.42), Inches(11.1), Inches(0.65),
             [(how, 12.5, False, GREEN)], spacing=0)
        top += Inches(2.35)
    notes(s, """
Offer these before being asked. A build with no bugs found in it either had no
checks or is not being honest about them.

The second one is the one to dwell on for Task 3: it is exactly the failure
mode that reading the policies would have passed. The policy was correct the
whole time. The view in front of it was not.

Say the consequence plainly: this is why the entitlement claim is made by
authenticating as four roles and counting rows, and not by quoting SQL.
""")

    # ---------------------------------------------------- strong and thin
    s = blank(deck)
    heading(s, "Strong here, thin there", "said before anyone has to ask")
    _two_columns(
        s,
        "Strong",
        [
            ("Severities have consequences, not labels",
             "block quarantines and the exclusion is counted and reversible; warn flags the row "
             "and the flag travels into the answer; info changes no number."),
            ("Three findings not in the dataset's own documentation",
             "55 accounts whose balance chain does not reconcile; intra-day order undefined for "
             "183 accounts; one duplicate payment no primary key can catch."),
            ("The entitlement claim is tested by logging in",
             "Four roles, 5,369 / 1,481 / 1,386 / 0 clients. That is what caught bug 2."),
            ("Rules proven on clean data",
             "20 seeded defects in a separate schema, one per rule family, each caught by the "
             "rule meant to catch it."),
        ],
        "Thin",
        [
            ("Bronze has no dedicated tests",
             "Its guarantees are assertions inside the ingest module and are never re-checked. "
             "Largest hole in the suite, and first item of next-step work."),
            ("Four modules are over 500 lines",
             "dq_runner in particular mixes execution, quarantine, flagging, reconciliation and "
             "two report writers. Coherent, but due a split."),
            ("The rule engine pulls violations into Python",
             "Fine at 1.06 m rows; named in the Design Decision Record as one of the four things "
             "that break at 100,000 times the volume."),
            ("No CI, and the page count is checked by regex",
             "Everything is reproducible by one command; nothing runs it automatically. The DDR "
             "two-page check reads the PDF bytes."),
        ],
    )
    notes(s, """
Read the right-hand column out loud. Volunteering the thin parts is cheaper
than having them found, and it is the difference between a demo and an
engineering review.

Each one has a next step attached in REVIEW_AND_NEXT_STEPS section 4, in
dependency order: the six Bronze tests come first because nothing else in the
layered plan can be verified until they exist.
""")

    # -------------------------------------------------- completeness: the asks
    s = blank(deck)
    heading(s, "Completeness: every ask in the brief", "1 of 2 - the three tasks")
    _matrix(s, [
        ("What the brief asks for", "Where it is delivered", "Evidence it is real"),
        ("Rules for completeness, uniqueness,\nreferential integrity, validity,\ncross-table consistency",
         "dq/dq_rules.yaml - 88 written rules\nplus a sweep, 123 executed over\nsix dimensions",
         "dq.results, one row per rule\nper run; DQ rules tab"),
        ("Each defect type with the rule it\nbreaks and a severity",
         "Defect types tab and defects.csv -\nrule id, dimension, severity,\nrationale, handling",
         "Generated from the run, not\ntyped; 08_defect_catalogue"),
        ("A justified severity for every rule\n(\"a rule without one scores as\nno rule\")",
         "severity_rationale on all 88 rules,\neach stated in terms of which of\nthe ten questions it would move",
         "Rendered into the workbook;\ntest asserts no rule lacks one"),
        ("AI-ready data product with a\nsemantic layer",
         "core star schema + ai consumer\nviews + semantic/semantic.yaml,\nvalidated against the live database",
         "Model tab; grain, key and FK\nchecks; core = stg - quarantine"),
        ("An LLM answering ten questions\nwith generated SQL and result",
         "Questions and Q detail tabs - prompt,\nmodel, raw response, guarded SQL,\nresult, reference answer",
         "10 of 10 correct first attempt;\nevery call logged to disk"),
        ("Entitlements: each user sees only\ntheir own clients, and an LLM query\ncannot bypass it",
         "Row level security on the base tables\n+ security_invoker views; onboarding\nis two inserts, no code change",
         "Entitlements tab: 5,369 / 1,481 /\n1,386 / 0; nine bypass attempts\nrefused"),
    ], top=Inches(1.35), row_h=Inches(0.82))
    notes(s, """
This slide exists because "completeness" is a grading criterion, not a feeling.
Read it as a checklist; every row has an artefact and a piece of evidence, and
nothing is marked done on the strength of prose.

The row to point at is the third. The brief says a rule without a justified
severity scores the same as no rule, so the justification is a required field
on every rule and a test fails if one is missing.
""")

    # ------------------------------------------- completeness: the deliverables
    s = blank(deck)
    heading(s, "Completeness: every deliverable", "2 of 2 - the artefacts and the disclosure")
    _matrix(s, [
        ("What the brief asks for", "What was handed over", "State"),
        ("Excel: defect types, model\nexplanation, questions",
         "Berka_TakeHome_Submission.xlsx -\nnine tabs; the three required plus\nQ detail, DQ rules, Assumptions,\nEntitlements, Run log, Overview",
         "Complete; every cell\ngenerated"),
        ("A ZIP of the semantic solution\nand the code",
         "semantic_solution.zip - 135 files,\nwith a manifest that says which part\nis the assessed pipeline and which\nis next-step work",
         "Complete"),
        ("Design Decision Record, max two\npages: options, choice, why, cost,\nand what breaks at 100,000x",
         "DDR.pdf and DDR.docx - twelve\ndecisions in options / chosen / why /\ncost form, plus the four things that\nbreak, named specifically",
         "Complete; two pages,\nchecked"),
        ("Full AI-tooling disclosure",
         "AI_DISCLOSURE.md - which model, for\nwhat, with what access, and what was\nhand-written: the reference answers\nand all 88 rules",
         "Complete"),
        ("Assumptions stated explicitly",
         "ASSUMPTIONS.md - A1 to A24, each\nwith what was assumed, why, and what\nwould change if it were wrong",
         "Complete; rendered\ninto the workbook"),
        ("Plain-language walkthrough\n(asked for in this session)",
         "HOW_WE_WORKED_SIMPLY.md, VISUAL_GUIDE\nwith ten figures, and this deck",
         "Complete"),
    ], top=Inches(1.3), widths=(4.1, 5.2, 3.1), row_h=Inches(0.92))
    notes(s, """
The disclosure row is the one not to skip past. The split is the point: the
model wrote code and answered the ten questions; the reference answers it was
graded against and all 88 quality rules were hand-written first, before the
model saw them.

That ordering is what makes "10 of 10 correct" mean anything. Grading against
answers the same model produced would mean nothing at all.
""")

    # ------------------------------------------------------------- next steps
    s = blank(deck)
    heading(s, "What would be done next", "in dependency order, not by appeal")
    text(s, Inches(0.7), Inches(1.35), Inches(12), Inches(0.4),
         [("Nothing below is needed for the brief. It is the order the work would continue in, "
           "and each item unblocks the next.", 15.5, False, GREY)], spacing=8)
    steps = [
        ("1", "Write the six Bronze tests",
         "Nothing else in the layered plan can be verified until they exist.", RED),
        ("2", "Split the test suite by layer",
         "tests/bronze | silver | gold, and make bronze | silver | gold. An hour, "
         "no production code moves, and the agents' acceptance criteria become runnable.", AMBER),
        ("3", "Add a session-start hook so the database comes up by itself",
         "The cluster stopped three times during the build and needed a manual restart. "
         "Fifteen minutes.", AMBER),
        ("4", "Then move the layers into isolated Python packages",
         "Bronze first - 250 lines, one consumer. Silver last, because that is where a mistake "
         "costs most. Simulated already: four packages, five gates, 21 tests, four faults "
         "injected and all four refused.", NAVY),
        ("5", "Freeze the control dataset only once the boundaries stop moving",
         "Freezing a surface that is still shifting turns every change into a proposal.", NAVY),
    ]
    top = Inches(1.95)
    for number, title, body, colour in steps:
        box(s, Inches(0.6), int(top), Inches(0.52), Inches(0.92), fill=colour)
        text(s, Inches(0.6), int(top) + Inches(0.24), Inches(0.52), Inches(0.45),
             [(number, 19, True, WHITE)], align=PP_ALIGN.CENTER, spacing=0)
        box(s, Inches(1.12), int(top), Inches(11.65), Inches(0.92), fill=PALE)
        text(s, Inches(1.35), int(top) + Inches(0.09), Inches(11.2), Inches(0.32),
             [(title, 14.5, True, INK)], spacing=0)
        text(s, Inches(1.35), int(top) + Inches(0.42), Inches(11.2), Inches(0.45),
             [(body, 12, False, GREY)], spacing=0)
        top += Inches(1.02)
    text(s, Inches(0.6), Inches(6.98), Inches(12.2), Inches(0.4),
         [("Deliberately not doing: renaming the schemas to bronze / silver / gold, and one "
           "container per layer - right for a platform, wrong for this brief.",
           12.5, True, NAVY)], spacing=0)
    notes(s, """
Three deliberate omissions are as much a part of the answer as the five steps.
Saying what was decided against, and why, is what separates a plan from a wish
list.

If asked whether the package migration is in scope: it is not, and the
simulation is the deliberate answer to "what would you do next" - dummy code
that proves the boundary is checkable, not production code refactored on a
guess.
""")

    # ----------------------------------------------------------------- close
    s = blank(deck)
    box(s, 0, 0, W, H, fill=NAVY)
    text(s, Inches(1.1), Inches(1.5), Inches(11.2), Inches(0.9),
         [("Three claims, and how each one is proved", 34, True, WHITE)], spacing=10)
    closes = [
        ("The data is graded, not just checked",
         "123 rules, each with a severity and a reason for it, proven by 20 planted defects."),
        ("The model can be asked questions in English",
         "A semantic layer validated against the live database; 10 of 10 answers correct, "
         "first attempt, every call logged."),
        ("The lock is in the engine, not in the question",
         "Row level security on the base tables; four roles counted; nine bypass attempts "
         "refused. Onboarding a portfolio is two inserts."),
    ]
    top = Inches(2.75)
    for title, body in closes:
        box(s, Inches(1.1), int(top), Inches(11.2), Inches(1.15),
            fill=RGBColor(0x2C, 0x4C, 0x80))
        text(s, Inches(1.4), int(top) + Inches(0.12), Inches(10.6), Inches(0.35),
             [(title, 17, True, WHITE)], spacing=0)
        text(s, Inches(1.4), int(top) + Inches(0.52), Inches(10.6), Inches(0.5),
             [(body, 13, False, RGBColor(0xC9, 0xD6, 0xEA))], spacing=0)
        top += Inches(1.3)
    text(s, Inches(1.1), Inches(6.8), Inches(11.2), Inches(0.4),
         [("make clean all - four and a half minutes, 12 of 12 steps, 137 tests. "
           "Every number on these slides came out of that run.", 14, True,
           RGBColor(0x9A, 0xB2, 0xD8))], spacing=0)
    notes(s, """
Close on the three claims, then stop. Do not re-summarise the deck.

If there is one sentence to leave behind: the hard part of this brief was never
writing rules or writing SQL - it was deciding what each defect costs, and
making the entitlement something the question cannot argue with.
""")


if __name__ == "__main__":
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    presentation = build()
    presentation.save(TARGET)
    print(f"wrote {TARGET.relative_to(PROJECT_ROOT)} -- "
          f"{len(presentation.slides)} slides")
