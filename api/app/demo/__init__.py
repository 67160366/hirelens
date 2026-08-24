"""The public demo's material: one synthetic document and one synthetic posting.

**Why it lives in `app/` rather than in `tests/fixtures/`.** The running
application serves it — `api/app/api/routes/demo.py` judges this document on
request so an anonymous visitor can watch the guardrail work — and a package that
ships in the image cannot reach into the test tree.

**Nobody in it exists, and that rule binds harder here than in a fixture.**
`CLAUDE.md` forbids a real person's resume anywhere in this repository; a demo is
opened by strangers, so it carries the wider audience a fixture never has. What is
borrowed from real documents is the *shape*: the section order, a skills line, a
Thai education line, and the way dates get written.

The requirement labels are chosen so the demo has something to show: three appear
in the document and one does not, which is what produces a `not_evidenced` verdict
beside the `met` ones — and, in fabricating mode, the requirement the invented
quote gets attached to. A demo where everything passes would be a demo of nothing.
"""

from __future__ import annotations

from app.schemas.judgment import RequirementSpec

DEMO_POSTING_TITLE = "Backend Engineer (Python) — ทีมแพลตฟอร์มเอกสาร"

DEMO_FILENAME = "resume-demo-th.pdf"

DEMO_DOCUMENT_TEXT = """สมชาย ใจดี
วิศวกรซอฟต์แวร์อาวุโส  |  somchai.j@example.com  |  กรุงเทพมหานคร

ประสบการณ์ทำงาน
บริษัท เอซีเอ็มอี โลจิสติกส์ — วิศวกรซอฟต์แวร์ (ม.ค. 2564 - มี.ค. 2567)
  ดูแลระบบกระทบยอดการชำระเงินด้วย Python และ PostgreSQL
  รองรับธุรกรรม 40,000 รายการต่อวัน
  ลดเวลาปิดยอดกลางคืนจาก 3 ชั่วโมงเหลือ 22 นาที

บริษัท สยามดิจิทัล — นักพัฒนาซอฟต์แวร์ (มิ.ย. 2562 - ธ.ค. 2563)
  ดูแลระบบภายในที่ 12 ทีมใช้งานร่วมกัน

ทักษะ
Python, FastAPI, PostgreSQL, Docker, การออกแบบระบบ

การศึกษา
จุฬาลงกรณ์มหาวิทยาลัย — วิศวกรรมศาสตรบัณฑิต สาขาวิศวกรรมคอมพิวเตอร์ (2558 - 2562)"""

DEMO_REQUIREMENTS: list[RequirementSpec] = [
    RequirementSpec(
        id="demo-1",
        label="PostgreSQL",
        kind="skill",
        detail="ใช้งานจริงในระบบที่มีคนใช้",
        must_have=True,
    ),
    RequirementSpec(id="demo-2", label="FastAPI", kind="skill"),
    RequirementSpec(id="demo-3", label="การออกแบบระบบ", kind="skill"),
    # Deliberately absent from the document. The verdict beside it is the sentence
    # this project exists to keep honest: nothing citable was found, which is not
    # the same as the candidate lacking it.
    RequirementSpec(id="demo-4", label="Kubernetes", kind="skill"),
]

__all__ = [
    "DEMO_DOCUMENT_TEXT",
    "DEMO_FILENAME",
    "DEMO_POSTING_TITLE",
    "DEMO_REQUIREMENTS",
]
