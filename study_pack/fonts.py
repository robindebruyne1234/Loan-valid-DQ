"""Convert the installed Inter OTF (CFF outlines) to TrueType for the PDFs.

Chromium embeds CFF-flavoured OpenType fonts as Type 3 fonts, which some PDF
viewers render without hinting. TrueType outlines embed as real fonts. This is
the standard fontTools otf2ttf conversion (cubic to quadratic curves).
"""

from __future__ import annotations

from pathlib import Path

SOURCE = Path("/usr/share/fonts/opentype/inter")
WEIGHTS = ["Inter-Regular", "Inter-Italic", "Inter-SemiBold", "Inter-SemiBoldItalic", "Inter-Bold"]


def _otf_to_ttf(src: Path, dst: Path) -> None:
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable

    font = TTFont(str(src))
    order = font.getGlyphOrder()
    glyphset = font.getGlyphSet()
    quad = {}
    for name in glyphset.keys():
        pen = TTGlyphPen(glyphset)
        glyphset[name].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
        quad[name] = pen.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = quad
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)
    hmtx = font["hmtx"]
    for name, glyph in glyf.glyphs.items():
        if hasattr(glyph, "xMin"):
            hmtx[name] = (hmtx[name][0], glyph.xMin)
    maxp = font["maxp"] = newTable("maxp")
    maxp.tableVersion = 0x00010000
    for attr in ("maxZones",):
        setattr(maxp, attr, 1)
    for attr in ("maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                 "maxStackElements", "maxSizeOfInstructions"):
        setattr(maxp, attr, 0)
    maxp.maxComponentElements = max(
        (len(g.components) for g in glyf.glyphs.values() if hasattr(g, "components")), default=0)
    maxp.compile(font)
    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order
    font.sfntVersion = "\000\001\000\000"
    font.save(str(dst))


def ensure(target: Path) -> str:
    """Write TrueType Inter into ``target``; return the @font-face CSS (empty if unavailable)."""
    try:
        import fontTools  # noqa: F401, PLC0415
    except ImportError:
        return ""
    target.mkdir(parents=True, exist_ok=True)
    faces = []
    spec = {"Inter-Regular": (400, "normal"), "Inter-Italic": (400, "italic"),
            "Inter-SemiBold": (600, "normal"), "Inter-SemiBoldItalic": (600, "italic"),
            "Inter-Bold": (700, "normal")}
    for name in WEIGHTS:
        src, dst = SOURCE / f"{name}.otf", target / f"{name}.ttf"
        if not src.exists():
            return ""
        if not dst.exists():
            _otf_to_ttf(src, dst)
        weight, style = spec[name]
        faces.append(f"@font-face {{ font-family: 'InterTT'; src: url('{dst.as_uri()}'); "
                     f"font-weight: {weight}; font-style: {style}; }}")
    return "\n".join(faces)
