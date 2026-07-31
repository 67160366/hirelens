"""Generate the PDF fixtures used by the parser tests.

Run this to (re)create the fixtures, then commit the results:

    python api/tests/fixtures/generate.py

The generated PDFs are committed rather than built during the test run, so CI does
not depend on a Thai-capable system font being installed. This script is the
reproducible record of how they were made.

All content is invented. No real person's resume appears anywhere in this repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FIXTURE_DIR = Path(__file__).parent
PAGE_W, PAGE_H = A4

# Fonts that ship with Windows and cover Thai. Only needed to *generate* fixtures.
THAI_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/tahoma.ttf"),
    Path("C:/Windows/Fonts/leelawui.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"),
    Path("/Library/Fonts/Tahoma.ttf"),
)

THAI_FONT_NAME = "ThaiBody"

RESUME_EN = [
    ("H1", "Somchai Jaidee"),
    ("BODY", "Senior Backend Engineer  |  somchai.j@example.com  |  Bangkok, Thailand"),
    ("GAP", ""),
    ("H2", "EXPERIENCE"),
    ("BODY", "Acme Logistics — Backend Engineer (Jan 2021 - Mar 2024)"),
    ("BODY", "  Built payment reconciliation services in Python and PostgreSQL,"),
    ("BODY", "  handling 40,000 transactions per day."),
    ("BODY", "  Cut nightly settlement runtime from 3 hours to 22 minutes."),
    ("GAP", ""),
    ("BODY", "Siam Digital — Junior Developer (Jun 2019 - Dec 2020)"),
    ("BODY", "  Maintained a Django monolith serving 12 internal teams."),
    ("GAP", ""),
    ("H2", "SKILLS"),
    ("BODY", "Python, FastAPI, PostgreSQL, Redis, Docker, pytest"),
    ("GAP", ""),
    ("H2", "EDUCATION"),
    ("BODY", "Chulalongkorn University — B.Eng Computer Engineering (2015 - 2019)"),
]

RESUME_TH = [
    ("H1", "สมชาย ใจดี"),
    ("BODY", "วิศวกรซอฟต์แวร์อาวุโส  |  somchai.j@example.com  |  กรุงเทพมหานคร"),
    ("GAP", ""),
    ("H2", "ประสบการณ์ทำงาน"),
    ("BODY", "บริษัท เอซีเอ็มอี โลจิสติกส์ — วิศวกรซอฟต์แวร์ (ม.ค. 2564 - มี.ค. 2567)"),
    ("BODY", "  ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL"),
    ("BODY", "  รองรับธุรกรรม 40,000 รายการต่อวัน"),
    ("GAP", ""),
    ("H2", "ทักษะ"),
    ("BODY", "Python, FastAPI, PostgreSQL, Docker, การออกแบบระบบ"),
    ("GAP", ""),
    ("H2", "การศึกษา"),
    ("BODY", "จุฬาลงกรณ์มหาวิทยาลัย — วิศวกรรมศาสตรบัณฑิต สาขาวิศวกรรมคอมพิวเตอร์"),
]


def find_thai_font() -> Path | None:
    return next((p for p in THAI_FONT_CANDIDATES if p.exists()), None)


def register_thai_font() -> str | None:
    font_path = find_thai_font()
    if font_path is None:
        return None
    pdfmetrics.registerFont(TTFont(THAI_FONT_NAME, str(font_path)))
    return THAI_FONT_NAME


def draw_lines(
    c: canvas.Canvas,
    lines: list[tuple[str, str]],
    *,
    body_font: str,
    bold_font: str,
    x: float = 60,
    top: float = PAGE_H - 70,
) -> None:
    y = top
    for kind, text in lines:
        if kind == "GAP":
            y -= 10
            continue
        size = {"H1": 18, "H2": 12, "BODY": 10}[kind]
        font = bold_font if kind in {"H1", "H2"} else body_font
        c.setFont(font, size)
        c.drawString(x, y, text)
        y -= size + 6


def write_single_page(path: Path, lines: list[tuple[str, str]], *, thai: bool) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    if thai:
        font = register_thai_font()
        if font is None:
            raise RuntimeError(
                "No Thai-capable font found; cannot regenerate the Thai fixture. "
                f"Looked in: {', '.join(str(p) for p in THAI_FONT_CANDIDATES)}"
            )
        body_font = bold_font = font
    else:
        body_font, bold_font = "Helvetica", "Helvetica-Bold"
    draw_lines(c, lines, body_font=body_font, bold_font=bold_font)
    c.save()


def write_two_column(path: Path) -> None:
    """Two-column layout — a classic case where naive extraction interleaves text."""
    c = canvas.Canvas(str(path), pagesize=A4)
    left = [
        ("H1", "Nadia Wong"),
        ("H2", "CONTACT"),
        ("BODY", "nadia.w@example.com"),
        ("BODY", "Chiang Mai, Thailand"),
        ("GAP", ""),
        ("H2", "SKILLS"),
        ("BODY", "Go, Kubernetes"),
        ("BODY", "Terraform, gRPC"),
    ]
    right = [
        ("H2", "EXPERIENCE"),
        ("BODY", "Northstar Cloud — SRE"),
        ("BODY", "(Feb 2022 - Present)"),
        ("BODY", "  Ran a 60-node Kubernetes"),
        ("BODY", "  platform for 9 product teams."),
        ("GAP", ""),
        ("BODY", "Highland Systems — DevOps"),
        ("BODY", "(Aug 2020 - Jan 2022)"),
    ]
    draw_lines(c, left, body_font="Helvetica", bold_font="Helvetica-Bold", x=50)
    draw_lines(c, right, body_font="Helvetica", bold_font="Helvetica-Bold", x=300)
    c.save()


def write_multipage(path: Path, pages: int = 3) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    for page in range(1, pages + 1):
        lines: list[tuple[str, str]] = [("H1", f"Project Portfolio — Page {page}")]
        for item in range(1, 6):
            marker = f"P{page}I{item}"
            lines.append(("BODY", f"Page {page} project {item}: distinctive marker {marker}."))
        draw_lines(c, lines, body_font="Helvetica", bold_font="Helvetica-Bold")
        c.showPage()
    c.save()


def _render_text_image(lines: list[str], *, width: int = 1240, height: int = 1754) -> Image.Image:
    """Rasterize text so the resulting PDF page has no text layer at all."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    font_path = find_thai_font()
    try:
        font = ImageFont.truetype(str(font_path), 28) if font_path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()

    y = 90
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 46

    # Faint speckle so it reads as a scan rather than a clean render.
    for offset in range(0, width, 37):
        draw.point((offset, (offset * 7) % height), fill="gray")
    return image


def write_scanned(path: Path) -> None:
    """A resume that exists only as an image — must raise NoTextLayerError in M1
    and is the OCR fixture for M2."""
    image = _render_text_image(
        [
            "Somchai Jaidee",
            "Senior Backend Engineer",
            "",
            "EXPERIENCE",
            "Acme Logistics - Backend Engineer (Jan 2021 - Mar 2024)",
            "Built payment reconciliation services in Python.",
            "",
            "ทักษะ: Python, FastAPI, PostgreSQL",
        ]
    )
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(ImageReader(image), 0, 0, width=PAGE_W, height=PAGE_H)
    c.save()


def write_mixed_scan(path: Path) -> None:
    """Page 1 has a text layer, page 2 does not — partial-scan handling."""
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_lines(
        c,
        [
            ("H1", "Preecha Boonmee"),
            ("H2", "SUMMARY"),
            ("BODY", "Data platform engineer with 6 years building ETL pipelines."),
        ],
        body_font="Helvetica",
        bold_font="Helvetica-Bold",
    )
    c.showPage()
    image = _render_text_image(["EXPERIENCE", "Riverbank Analytics - Data Engineer"])
    c.drawImage(ImageReader(image), 0, 0, width=PAGE_W, height=PAGE_H)
    c.save()


def write_empty(path: Path) -> None:
    """A structurally valid PDF with a blank page."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.showPage()
    c.save()


def write_not_a_pdf(path: Path) -> None:
    path.write_bytes(b"This is plainly not a PDF file.\n" * 4)


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    write_single_page(FIXTURE_DIR / "resume_en.pdf", RESUME_EN, thai=False)
    write_single_page(FIXTURE_DIR / "resume_th.pdf", RESUME_TH, thai=True)
    write_two_column(FIXTURE_DIR / "resume_two_column.pdf")
    write_multipage(FIXTURE_DIR / "resume_multipage.pdf")
    write_scanned(FIXTURE_DIR / "resume_scanned.pdf")
    write_mixed_scan(FIXTURE_DIR / "resume_mixed_scan.pdf")
    write_empty(FIXTURE_DIR / "empty.pdf")
    write_not_a_pdf(FIXTURE_DIR / "not_a_pdf.pdf")

    for pdf in sorted(FIXTURE_DIR.glob("*.pdf")):
        print(f"  {pdf.name:28} {pdf.stat().st_size:>8,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
