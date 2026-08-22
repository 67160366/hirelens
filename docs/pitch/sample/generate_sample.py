"""Generate the demo documents for the pitch: one posting's text and one resume.

    python docs/pitch/sample/generate_sample.py

**The person in this resume does not exist.** `CLAUDE.md` forbids a real person's
resume anywhere in this repository, and the rule holds for demo material as much as
for test fixtures — a slide is a wider audience than a test run, not a narrower one.
What is taken from the real world is the *shape*: the section order, the sidebar,
the way dates and metrics are written, and the two-column layout that Canva and Word
templates produce and that resume parsers are documented to read out of order.

The layout is deliberately the hard one: a full-width header band over two columns.
`api/tests/fixtures/generate.py` calls that "the shape almost every real two-column
resume has", and it is the shape the pitch uses to show what a plain text extractor
does with it.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent
PAGE_W, PAGE_H = A4

THAI_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/leelawui.ttf"),
    Path("C:/Windows/Fonts/tahoma.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"),
    Path("/Library/Fonts/Tahoma.ttf"),
)
BOLD_CANDIDATES = (
    Path("C:/Windows/Fonts/leelawub.ttf"),
    Path("C:/Windows/Fonts/tahomabd.ttf"),
)

BODY, BOLD = "SampleBody", "SampleBold"

INK = (0.09, 0.10, 0.12)
MUTED = (0.34, 0.33, 0.31)
RULE = (0.82, 0.81, 0.80)
BAND = (0.96, 0.96, 0.95)

# --- the header band ------------------------------------------------------
NAME = "ธนวัฒน์ ศรีอุดม"
TITLE = "Backend Engineer"
CONTACT = "thanawat.s@example.com  ·  08 1234 5678  ·  กรุงเทพฯ  ·  github.com/example"

# --- the narrow left column ----------------------------------------------
SIDEBAR: list[tuple[str, str]] = [
    ("H2", "ทักษะ"),
    ("BODY", "Python, FastAPI"),
    ("BODY", "PostgreSQL, Redis"),
    ("BODY", "Docker, GitHub Actions"),
    ("BODY", "Celery, RabbitMQ"),
    ("BODY", "pytest, Grafana"),
    ("GAP", ""),
    ("H2", "การศึกษา"),
    ("BODY", "มหาวิทยาลัยเกษตรศาสตร์"),
    ("BODY", "วิศวกรรมศาสตรบัณฑิต"),
    ("BODY", "สาขาวิศวกรรมคอมพิวเตอร์"),
    ("BODY", "2559 - 2563"),
    ("GAP", ""),
    ("H2", "ภาษา"),
    ("BODY", "ไทย - ภาษาแม่"),
    ("BODY", "อังกฤษ - ใช้งานได้"),
]

# --- the wide right column ------------------------------------------------
MAIN: list[tuple[str, str]] = [
    ("H2", "สรุปโดยย่อ"),
    ("BODY", "วิศวกรฝั่งหลังบ้าน ประสบการณ์ 4 ปี ดูแลบริการที่รับงาน"),
    ("BODY", "ประมวลผลเอกสารจำนวนมาก สนใจงานที่วัดผลได้และตรวจสอบย้อนกลับได้"),
    ("GAP", ""),
    ("H2", "ประสบการณ์ทำงาน"),
    ("BOLD", "บริษัท ไทยเพย์เมนต์ เกตเวย์ — Backend Engineer"),
    ("MUTED", "ก.ค. 2565 - ปัจจุบัน"),
    ("BODY", "· พัฒนา REST API ด้วย Python และ FastAPI ให้ทีมภายใน 6 ทีมใช้งาน"),
    ("BODY", "· ออกแบบสคีมาบน PostgreSQL รองรับรายการโอนเงิน 120,000 รายการต่อวัน"),
    ("BODY", "· ย้ายงานประมวลผลไฟล์ไปไว้บน Celery worker ทำให้เวลาตอบกลับของ API"),
    ("BODY", "  ลดจาก 4.2 วินาที เหลือ 380 มิลลิวินาที"),
    ("BODY", "· วางระบบ retry และ dead-letter queue สำหรับงานที่ล้มเหลว"),
    ("GAP", ""),
    ("BOLD", "บริษัท สยามดิจิทัล โซลูชันส์ — Junior Developer"),
    ("MUTED", "พ.ค. 2563 - มิ.ย. 2565"),
    ("BODY", "· ดูแลระบบหลังบ้านของเว็บ e-commerce ที่เขียนด้วย Django"),
    ("BODY", "· เขียน unit test ด้วย pytest จนความครอบคลุมขึ้นจาก 34% เป็น 71%"),
    ("BODY", "· ทำ CI/CD ด้วย GitHub Actions และ Docker"),
    ("GAP", ""),
    ("H2", "โครงการที่ภูมิใจ"),
    ("BODY", "· ระบบกระทบยอดอัตโนมัติ ลดงานตรวจสอบด้วยมือของทีมบัญชีลงราว 15 ชม./สัปดาห์"),
]


def register_fonts() -> None:
    body = next((p for p in THAI_FONT_CANDIDATES if p.exists()), None)
    if body is None:
        raise SystemExit(
            "No Thai-capable font found. Looked in: "
            + ", ".join(str(p) for p in THAI_FONT_CANDIDATES)
        )
    bold = next((p for p in BOLD_CANDIDATES if p.exists()), body)
    pdfmetrics.registerFont(TTFont(BODY, str(body)))
    pdfmetrics.registerFont(TTFont(BOLD, str(bold)))


def draw_column(c: canvas.Canvas, lines: list[tuple[str, str]], *, x: float, top: float) -> None:
    y = top
    for kind, text in lines:
        if kind == "GAP":
            y -= 12
            continue
        if kind == "H2":
            c.setFont(BOLD, 10.5)
            c.setFillColorRGB(*INK)
            c.drawString(x, y, text)
            y -= 5
            c.setStrokeColorRGB(*RULE)
            c.setLineWidth(0.6)
            c.line(x, y, x + (150 if x < 200 else 300), y)
            y -= 13
            continue
        if kind == "BOLD":
            c.setFont(BOLD, 10)
            c.setFillColorRGB(*INK)
        elif kind == "MUTED":
            c.setFont(BODY, 9)
            c.setFillColorRGB(*MUTED)
        else:
            c.setFont(BODY, 9.5)
            c.setFillColorRGB(*INK)
        c.drawString(x, y, text)
        y -= 14.5


def write_resume(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)

    # Header band, full width across both columns — the part that makes a naive
    # column profile find nothing.
    band_h = 84
    c.setFillColorRGB(*BAND)
    c.rect(0, PAGE_H - band_h, PAGE_W, band_h, stroke=0, fill=1)

    c.setFillColorRGB(*INK)
    c.setFont(BOLD, 20)
    c.drawString(50, PAGE_H - 38, NAME)
    c.setFont(BODY, 11.5)
    c.setFillColorRGB(*MUTED)
    c.drawString(50, PAGE_H - 56, TITLE)
    c.setFont(BODY, 8.5)
    c.drawString(50, PAGE_H - 72, CONTACT)

    top = PAGE_H - band_h - 26
    draw_column(c, SIDEBAR, x=50, top=top)
    draw_column(c, MAIN, x=225, top=top)

    # A thin full-width footer, the way a template puts a page number there.
    c.setFillColorRGB(*MUTED)
    c.setFont(BODY, 7.5)
    c.drawString(50, 34, "หน้า 1 จาก 1")
    c.save()


if __name__ == "__main__":
    register_fonts()
    out = HERE / "sample_resume_th.pdf"
    write_resume(out)
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
