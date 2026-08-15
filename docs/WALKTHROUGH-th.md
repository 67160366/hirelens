# HireLens — คู่มือทำความเข้าใจโปรเจค (ภาษาไทย)

> **เอกสารนี้ไม่ใช่แหล่งอ้างอิงที่เป็นทางการ** — เป็นคำอธิบายสำหรับเจ้าของโปรเจค
> เขียนขึ้น 2026-08-15 ปรับปรุง 2026-08-16 ตอนปิด **M5** (จากสภาพ repo ณ commit `a7bc967`)
>
> เอกสารที่ถือเป็นความจริง (และเซสชันใหม่ต้องอ่านตามลำดับที่ `CLAUDE.md` กำหนด) คือ
> `docs/HANDOFF.md` → `docs/PLAN.md` → `docs/NOTES.md` → `docs/llm-providers.md`
> **สถานะรายข้อที่ถูกต้องอยู่ในตารางของ `docs/PLAN.md` เท่านั้น** ไฟล์นี้เป็นภาพนิ่ง
> ที่จะเก่าลงเรื่อย ๆ — ถ้าขัดกัน ให้เชื่อสี่ไฟล์ข้างบน

สารบัญ

1. [โปรเจคนี้คืออะไร](#1-โปรเจคนี้คืออะไร)
2. [ไอเดียแกนกลาง](#2-ไอเดียแกนกลาง-the-one-idea)
3. [Tech stack และเหตุผลที่เลือก](#3-tech-stack-และเหตุผลที่เลือก)
4. [สถาปัตยกรรมและการไหลของข้อมูล](#4-สถาปัตยกรรมและการไหลของข้อมูล)
5. [เดินโค้ดทีละโมดูล](#5-เดินโค้ดทีละโมดูล)
6. [เลเยอร์ธุรกิจ](#6-เลเยอร์ธุรกิจ)
7. [งานเบื้องหลังและ retry policy](#7-งานเบื้องหลังและ-retry-policy)
8. [Frontend](#8-frontend)
9. [Observability](#9-observability)
10. [Test / CI / คุณภาพ](#10-test--ci--คุณภาพ)
11. [ตอนนี้โปรเจคถึงไหนแล้ว](#11-ตอนนี้โปรเจคถึงไหนแล้ว)
12. [กฎที่ห้ามพัง](#12-กฎที่ห้ามพัง)
13. [เริ่มเล่นเองยังไง](#13-เริ่มเล่นเองยังไง)

---

## 1. โปรเจคนี้คืออะไร

**HireLens** — ระบบคัดกรองเรซูเม่ (resume screening) ที่ **ทุกคำกล่าวอ้างต้องอ้างอิง
ข้อความจริงในเอกสารต้นฉบับได้เสมอ** และสิ่งที่อ้างอิงไม่ได้จะถูกทิ้งพร้อมรายงาน
ไม่ใช่เอามาแสดง

ที่มา: user journey #19 (HR Tech) ในเอกสาร `userjourneysthailand.md.pdf` ซึ่งเก็บ
ไว้นอก repo (อาจมีเนื้อหาของบุคคลที่สาม) pain point เขียนไว้ตรง ๆ ว่า

> *"เรซูเม่ไม่ผ่านการคัดกรองอัตโนมัติ (ATS) โดยไม่รู้สาเหตุ"*

ปัญหาคือ ATS ปฏิเสธคนโดยอธิบายไม่ได้ HireLens ตอบด้วยการบังคับให้ทุกข้อสรุป
"ชี้นิ้ว" กลับไปที่บรรทัดในเรซูเม่ที่เป็นที่มาของมัน รองรับทั้งไทยและอังกฤษ

---

## 2. ไอเดียแกนกลาง (The one idea)

อ่านข้อนี้ข้อเดียวก็เข้าใจครึ่งโปรเจค

> **โมเดลนับตัวอักษรไม่ได้ เพราะฉะนั้นจึงไม่เคยถามมันเลย**

```
parse (เก็บ char offset) → ถามโมเดลเอาแค่ "quote" → หา quote นั้นในเอกสารเอง → เก็บเฉพาะที่หาเจอ
```

- โมเดลคืนมาแค่ **ข้อความที่ยกมา (quote)** — ห้ามคืนเลขหน้า ห้ามคืน character offset
- แอปพลิเคชันเป็นคนไปหาเองว่า quote นั้นอยู่ตรงไหนใน `document_text`
  (`api/app/pipeline/evidence.py`)
- **quote ที่หาไม่เจอ = การกุ (fabrication)** → ถูกทิ้ง ใส่ไว้ใน `dropped` และรายงานออกมา

กฎเดียวนี้ให้ผลลัพธ์ 3 อย่างพร้อมกัน

| ได้อะไร | ยังไง |
|---|---|
| **Guardrail** | claim ที่ verify ไม่ได้ ไม่มีทางไปถึงตาคนอ่าน |
| **Explainability** | ทุก field มี page + char range → UI เอาไป highlight ได้ทันที |
| **Metric ฟรี ๆ** | นับ quote ที่ถูกปฏิเสธ = hallucination rate โดยไม่ต้องมี labelled dataset |

### ไอเดียเดียวกันถูกใช้ซ้ำอีกสามครั้ง

นี่คือสิ่งที่ทำให้โปรเจคนี้มีเอกลักษณ์ — ทุกมิลสโตนหลังจากนั้นเป็นรูปแบบเดิมในเสื้อผ้าใหม่

| มิลสโตน | รูปแบบเดียวกัน |
|---|---|
| M1 | **claim หนึ่ง ๆ มาจาก quote ที่หาเจอ** ไม่ใช่จากที่โมเดลบอก |
| M3 | **verdict (met / not_evidenced) อนุมานจากหลักฐานที่หาเจอ** ไม่เคยรับ verdict จากโมเดล |
| M4 | **state ของใบสมัคร เป็น projection ของ append-only event log** ไม่ใช่คอลัมน์ที่ใครก็เซ็ตได้ |
| M5 | **ทุกตัวเลขบน dashboard คือ query จากแถวที่ระบบเขียนไว้แล้ว** และบอกได้ว่ามาจากแถวไหน |

หลักคิดร่วมกันคือ: *อะไรก็ตามที่เป็นคำกล่าวอ้างเกี่ยวกับ "ตัวคน" ต้องอนุมานจากสิ่งที่
ตรวจสอบได้ ไม่ใช่ประกาศออกมาเฉย ๆ*

---

## 3. Tech stack และเหตุผลที่เลือก

### Backend (`api/`)

| ของ | ใช้ทำอะไร |
|---|---|
| Python 3.11 + **FastAPI** | REST API, OpenAPI ที่ `/docs` |
| **SQLAlchemy 2 (async) + Alembic** | ORM + migration (ปัจจุบันถึง `0010`) |
| **PostgreSQL 17** (pgvector image) | DB ของ dev/prod — ใช้ JSONB |
| **SQLite** | fallback และ **test suite ทั้งชุดรันบนนี้** |
| **Redis + ARQ** | job queue สำหรับงานเบื้องหลัง |
| **MinIO / S3 หรือ local filesystem** | เก็บไฟล์ที่อัปโหลด |
| **pdfplumber / python-docx** | อ่าน PDF/DOCX พร้อม offset |
| **Tesseract** (ทางเลือก) | OCR หน้าที่เป็นภาพสแกน (ไทย + อังกฤษ) |
| **google-genai** (Gemini free tier) | LLM provider จริง |
| pytest / ruff / mypy strict | gate ทั้งหมดบังคับใน CI |

### Frontend (`web/`)

Next.js 16 (App Router) + TypeScript + Tailwind + **vitest แบบไม่มี DOM** (จงใจ)

### Infra

Docker Compose 8 services: `postgres`, `redis`, `minio`, `createbucket` (one-shot),
`migrate` (one-shot), `api`, `worker`, `web`

- `api` กับ `worker` เป็น **image เดียวกัน คนละคำสั่ง** — เพราะ `worker.py` เป็นแค่
  adapter บาง ๆ ของ `jobs.py` ถ้าแยก image dependency จะ drift กันโดยไม่มีใครรู้
- migration รันเป็น service ของตัวเอง ไม่ใช่ใน entrypoint ของ API — เพื่อไม่ให้
  replica สองตัวแย่งกัน apply

### หลักการที่สองที่กำหนดรูปร่าง stack

> **ทุก dependency ต้องมี default ที่ไม่ต้องมี server**

```
git clone && pytest -q   →  ผ่านทันที  (ไม่ต้องมี API key, DB, Redis, Tesseract, ไม่เสียเงิน)
```

ทำได้เพราะสามอย่าง

1. **`fake` LLM provider** (`api/app/llm/fake.py`) — **ไม่ใช่ stub** มันอ่านเอกสารจริง
   แล้วยก quote จริงมา ทำให้ evidence verification ทำงานเหมือนของจริงเป๊ะ ๆ
   และมี `FAKE_MODE=hallucinating` ที่แกล้งกุ quote เพื่อทดสอบเส้นทาง dropped
   (ถือเป็น **load-bearing infrastructure** อ่านก่อนแตะ provider seam)
2. **`JSON_VARIANT`** ใน `models/base.py` — เรนเดอร์เป็น JSONB บน Postgres, JSON บน SQLite
3. **`QUEUE_BACKEND=inline`** — request ทำงานเองไม่ต้องมี Redis

> ⚠️ การเปลี่ยนแปลงที่ทำให้ test suite ต้องมี server = การเปลี่ยนแปลงที่ผิด
> ให้เพิ่มเป็น opt-in module แทน (เช่น `tests/test_postgres.py`)

---

## 4. สถาปัตยกรรมและการไหลของข้อมูล

```
Next.js (App Router, TS, Tailwind)
   │  REST + SSE
   ▼
FastAPI ──► PostgreSQL          (rows)
   │        Redis               (job queue)
   │        MinIO / filesystem  (ไฟล์ต้นฉบับ)
   │
   └─ enqueue ─► ARQ worker
                    ▼
        parse → extract → verify evidence      (หนึ่งเรซูเม่)
        judge requirements → verify evidence   (หนึ่ง screening)
                             │
                             └─► LLM provider (fake | gemini)

        rank · retrieve   ← pure function ไม่เสีย model call เลย
```

### 4.1 การอัปโหลดหนึ่งครั้งไหลยังไง

สำคัญ เพราะ **request ไม่ได้เป็นคนทำงานเอง**

1. `POST /resumes` — เช็ค `Content-Length`, นามสกุล และ **magic bytes `%PDF-`**
   *ก่อน* จะเก็บหรือคิดเงินอะไรทั้งนั้น และต้องมี `consent=true` (ขาดไป = 422 จาก
   schema เลย ไม่มี default)
2. `resume_service.ingest_resume` แฮชไบต์ → ถ้าบัญชีนี้เคยอัปโหลดไฟล์เดิม จะได้ row
   เดิม ไม่ extract ซ้ำ → เขียน blob → insert row `status=pending` → **commit**
3. **แล้วค่อย enqueue** — ถ้า enqueue ก่อน commit, worker ที่เร็วจะหา row ไม่เจอ
4. ตอบ `pending` **เสมอ** ไม่ว่า queue backend เป็นอะไร (client contract เดียว
   ไม่ใช่หนึ่งอันต่อรูปแบบการ deploy)
5. `jobs.run_resume_job` เคลม row (`processing`, `attempts += 1`, `last_attempt_at`,
   `SELECT … FOR UPDATE`) แล้ว **commit การเคลม** เพื่อให้ delivery ซ้ำเห็นแล้วข้าม
6. `resume_service.process_resume` parse → เขียน `document_text` + page spans ลง row
   → extract → verify (ไม่ commit เอง; job เป็นเจ้าของ transaction)
7. สำเร็จ → `extracted`, reset `failed_attempts`, commit ทีเดียวทั้ง profile +
   usage log + status

### 4.2 ฝั่ง client ตามงานยังไง

- `GET /resumes/{id}/events` = **SSE stream** จนกว่า status จะนิ่ง
  (ไม่ใช่ `pending` และไม่ใช่ `processing`)
- ถ้า stream จบโดยยังไม่มีคำตอบ → fallback ไป **polling** `GET /resumes/{id}`
- ฝั่ง client ใช้ **`fetch` ไม่ใช่ `EventSource`** เพราะ `EventSource` ตั้ง
  `Authorization` header ไม่ได้ → token จะต้องไปอยู่ใน query string → ไหลเข้า
  proxy log และ browser history ซึ่งผิดกฎ "ห้าม log ข้อมูลส่วนบุคคล"
  ราคาที่จ่ายคือต้อง parse SSE frame เองใน `web/lib/api.ts` (`readFrames`)
- ฝั่ง server SSE **re-read row ทุก ๆ ครึ่งวินาทีแล้ว emit เมื่อเปลี่ยน** ไม่ใช่
  pub/sub — เพราะ pub/sub จะทำให้ Redis กลายเป็น critical path ของ API และพัง
  "no-server default" กลไกเปลี่ยนทีหลังได้โดย client ไม่รู้สึกอะไร

---

## 5. เดินโค้ดทีละโมดูล

### 5.1 `pipeline/parse.py` — สัญญาเรื่อง offset

`ParsedDocument.text` คือ **coordinate space เดียว** ที่หลักฐานทุกชิ้นชี้เข้าไป

- NFC normalize + **ตัด `U+0000` ทิ้ง** ก่อนวัด page span — Postgres ไม่ยอมรับ NUL
  ในคอลัมน์ text แต่ SQLite ยอม ทำให้ทั้ง suite ตาบอดมาก่อน (ดู `HANDOFF.md` §11)
- **OCR ถูกแทนที่เข้าไปใน page list *ก่อน* `_assemble` วัด span** — ทำให้หน้าที่กู้มา
  จากภาพมี offset ธรรมดาเหมือนหน้าอื่น ถ้าทำ OCR เป็น pass ที่สองหลังประกอบเอกสารแล้ว
  offset ทุกตัวหลังหน้านั้นจะเลื่อนหมด
- `document_text` **เก็บแบบ verbatim** ห้าม re-parse / re-normalize ของที่เก็บแล้ว
  เพราะจะทำให้ citation ที่เคยแสดงต่อผู้ใช้ไปแล้วชี้ผิดที่

### 5.2 `pipeline/layout.py` — สองคอลัมน์

XY-cut แบบมีขอบเขต

- **ตัดแนวนอนก่อนแนวตั้ง** เพราะ header เต็มความกว้างจะพาดข้าม gutter ทำให้
  column profile ทั้งหน้าหาอะไรไม่เจอเลยในเรซูเม่สองคอลัมน์จริง ๆ เกือบทุกใบ
- จัดลำดับใหม่ด้วยการ **crop เป็นภูมิภาคแล้วให้ pdfplumber ประกอบข้อความเอง** —
  ถ้าประกอบบรรทัดจาก word box เองจะต้องตัดสินใจว่าเว้นวรรคตรงไหน ซึ่งภาษาไทย
  ไม่มีเว้นวรรคระหว่างคำ
- **ถ้าไม่มั่นใจ → คืน `None` = เส้นทางโค้ดเดิมก่อน M2** ทำให้เอกสารคอลัมน์เดียว
  parse ออกมา **byte-identical** เป๊ะ (มี 4 guard ที่ผลิต `None` และ
  `tests/test_layout.py` pin ทีละอันแยกกัน)

### 5.3 `pipeline/evidence.py` ★ หัวใจ

252 บรรทัด อ่านคุ้มที่สุดในโปรเจค จับคู่ **3 ชั้น** จากเข้มไปหลวม

| Tier | วิธี | เหตุผล |
|---|---|---|
| 1 `exact` | หาตรงตัว | quote ดี ๆ ส่วนใหญ่ลงที่นี่ |
| 2 `whitespace_collapsed` | ยุบ whitespace run เหลือช่องเดียว | โมเดล reflow ข้อความที่ข้ามบรรทัดใน PDF |
| 3 `whitespace_stripped` | ลบ whitespace ทิ้งหมด | **ส่วนใหญ่ไว้กู้ภาษาไทย** ที่ PDF ชอบแทรกช่องว่างกลางคำ |

รายละเอียดที่ฉลาด

- `_IndexedText` เก็บ `offsets[i]` = ตำแหน่งใน**ต้นฉบับ**ที่ผลิตตัวอักษร `text[i]`
  → match ในเวอร์ชันที่แปลงแล้ว แต่ map กลับไปยัง offset จริงได้
- `MIN_QUOTE_CHARS = 4` และ tier 3 ต้องยาว ≥ 8 — ยิ่งหลวมยิ่งต้องยาว ไม่งั้น
  `"go"` จะไปแมตช์ข้างใน `"django"`
- `occurrences > 1` → **`is_ambiguous`** รายงานว่ากำกวม ไม่เดา
- คืน **ข้อความจากต้นฉบับ** ไม่ใช่ที่โมเดลพิมพ์มา (`self._source[start:end]`)
- `match_kind` ถูกบันทึกไว้ — ถ้ารันหนึ่งเต็มไปด้วย match ชั้น 3 แปลว่า
  **parser มีปัญหา** ไม่ใช่ matcher มีปัญหา

### 5.4 `pipeline/extract.py` — re-ask loop

```python
for attempt in 1..max_attempts:
    ถามโมเดล                       # รอบ 2 ส่ง quote ที่ถูกปฏิเสธกลับไปด้วย
    verify ทุก field
    เก็บ candidate ที่ dropped น้อยที่สุด
    ถ้า dropped == 0 → หยุด
best.stats.attempts = len(usages)  # นับ "จำนวนครั้งที่เรียกโมเดลจริง" ไม่ใช่รอบที่ชนะ
```

จุดละเอียด: **`seniority` เป็น field ที่โมเดลอยากเดาที่สุด** ถ้าหา quote รองรับไม่ได้
จะถูกลดเป็น `unknown` แทนที่จะเก็บไว้แบบไม่มีหลักฐาน

### 5.5 `pipeline/judge.py` (M3) — verdict ต้องอนุมาน ห้ามรับ

```python
verdict = Verdict.MET if evidence else Verdict.NOT_EVIDENCED
# บรรทัดเดียวที่เป็นเหตุผลของทั้งมิลสโตน
```

- **ไม่มี `not_met` โดยเจตนา** — "การไม่มี" อ้างอิงไม่ได้ (ยกข้อความที่ไม่มีในเอกสาร
  มาไม่ได้) และระบบแยกไม่ออกระหว่าง "ผู้สมัครไม่มีทักษะนี้" กับ "เรซูเม่ไม่ได้เขียนถึง"
  ซึ่งอันแรกเป็นคำกล่าวอ้างเกี่ยวกับตัวคน
- โมเดลอ้างถึง requirement ด้วย **เลขลำดับ (1-based)** ไม่ใช่ UUID — ถูกกว่าใน token
  และเลขนอกช่วงคือสิ่งที่ verifier จับได้ (UUID ที่เพี้ยนจับไม่ได้) → กลายเป็น
  `RejectReason.UNKNOWN_REQUIREMENT` นับรวมใน hallucination rate
  ส่วนเลขซ้ำ **merge** ไม่ทับกัน เพราะโมเดลที่ตอบข้อเดียวแยกเป็นสองรายการก็ยังตอบแล้ว
- retry rule **ต่างจาก extract**: judging เก็บอันที่ `met` มากที่สุด ไม่ใช่ dropped
  น้อยที่สุด เพราะ prompt รอบสองบอกให้ "ตัดทิ้งไปเลยถ้าอ้างไม่ได้" → คำตอบว่างเปล่า
  จะได้ dropped = 0 แล้วชนะ ทั้งที่ทิ้งหลักฐานจริงของรอบแรกไป
- รายการ requirement วางไว้ **นอก** `<resume>` block ใน prompt — ไม่ใช่เรื่องความสวยงาม:
  `fake.py` หาเอกสารจาก block นั้นพอดี ถ้าเอาไปไว้ข้างในโมเดลจะยก requirement มาเป็น
  หลักฐานแล้ว verify ตกทุกอัน
- **judging ไม่เคยเห็น `must_have` หรือ `weight`** — สองอันนี้เดินทางไปกับ
  `RequirementSpec` และกลับมาบน `RequirementJudgment` โดยไม่ถูกแตะ เพื่อให้ ranking
  อ่าน "ข้อนี้มีหลักฐานไหม" เป็นคำถามเกี่ยวกับเอกสาร ส่วน "ข้อนี้สำคัญแค่ไหน" เป็น
  คำถามเกี่ยวกับตำแหน่งงาน

### 5.6 `pipeline/ranking.py` (M3) — ไม่เสีย model call เลย

```
score = ผลรวม weight ของข้อที่ met / ผลรวม weight ทั้งหมด
gate  = must_have ทุกข้อต้อง met  (ถ้าไม่มี must_have เลย = ผ่าน)
sort  = (ไม่ผ่าน gate ทีหลัง, score มาก→น้อย, met มาก→น้อย, screening_id)
```

สองกฎที่พลาดง่ายมาก

- **weight / must_have อ่านจาก job ปัจจุบัน ไม่ใช่จาก judgment ที่เก็บไว้** —
  `requirements_fingerprint` จงใจไม่รวมสองอันนี้ ดังนั้นแก้ weight แล้ว screening ยัง
  "current" อยู่ แต่ JSON ที่เก็บไว้ยังถือเลขเก่าตลอดกาล ถ้าอ่านจาก stored result
  การแก้ weight จะไม่มีผลอะไรเลยแบบเงียบ ๆ
  (mutation-test: ทำผิดแล้ว `test_ranking.py` ตก 5 เคส)
- **join ด้วยตำแหน่ง ไม่ใช่ id** เพราะ fingerprint ไม่รวม id ด้วย และถ้าความยาว
  ไม่ตรง → `excluded: malformed` ไม่ใช่ join มั่ว

อื่น ๆ

- `screening_id` ท้าย sort key ทำให้ order เป็น **total order** — ไม่งั้นคนคะแนน
  เท่ากันจะสลับที่กันทุกครั้งที่ refresh
- must-have **นับรวมในคะแนนด้วย ไม่ใช่แค่เป็นประตู** — ในกลุ่มที่ผ่าน gate มันเป็น
  ค่าคงที่ไม่เปลี่ยนลำดับ แต่ในกลุ่มที่ไม่ผ่านมันคือสิ่งที่แยก "ขาดหนึ่งข้อ" ออกจาก
  "ขาดทุกข้อ" และทำให้ตัวหารไม่เป็นศูนย์เมื่อทุกข้อเป็น must-have
- ผลพลอยได้ที่สำคัญ: **recruiter ลาก weight แล้วอันดับเรียงใหม่ทันทีโดยไม่เสียเงินสักบาท**
- screening ที่ stale ถูก **excluded พร้อมเหตุผล** ไม่ใช่รันใหม่อัตโนมัติ —
  สัญชาตญาณเดียวกับ `dropped`

### 5.7 `pipeline/retrieval.py` — โมดูลเดียวที่อนุญาตให้ "ประมาณ" ได้

เพราะมัน **ไม่ได้กล่าวอ้างอะไรเกี่ยวกับใครเลย** — แค่เรียงว่าเรซูเม่ไหนคุ้มที่จะจ่ายเงิน
ให้โมเดลตัดสิน ลบทิ้งทั้งโมดูลก็ไม่มี verdict ไหนเปลี่ยน

- **คืนทุกเอกสารเสมอ เรียงลำดับ ไม่เคยกรองทิ้ง** — retriever ที่กรองจะคัดคนออกก่อนที่
  จะมีใครได้ดู และไม่มีใครเห็นว่ามันเกิดขึ้น (mutation-test: กรอง 0 คะแนนออก → ตก 9 เคส)
- **ภาษาไทย tokenize ด้วย character n-gram (n=3), ละตินด้วยคำ** — นี่คือ *การวัด*
  ไม่ใช่รสนิยม: `resume_th.pdf` มี run ยาว 31 ตัวอักษรติดกัน
  `ดูแลระบบกระทบยอดการชำระเงินด้วย` และคำจริงอย่าง `ชำระเงิน` กับ `วิศวกรรม` อยู่
  **ข้างใน** ซึ่ง whitespace tokenizer หาไม่เจอทั้งคู่
  (n=2 ชนกันข้ามคำ, n=4 เริ่มพลาดคำสั้น)
- **ไม่ match กับ `job.description`** เด็ดขาด — จะเป็นการเอา free text กลับมาให้คะแนน
  ทางประตูหลัง พิสูจน์สดแล้ว: เรซูเม่ที่มี *ทุกคำ* ใน description ยังได้ 0.0
- ยังไม่มีการวัดคุณภาพของลำดับ และนั่นจงใจ — เดิมเป็น M6 แต่ **review แล้วปิดโดยไม่สร้าง**
  (2026-08-16) เพราะสร้างตามที่เขียนไม่ได้อย่างซื่อสัตย์: หัวข้อคือ "วัด **ranking** เทียบ
  BM25" แต่ BM25 เป็น **retrieval** scorer และ docstring ของ `retrieval.py` เองห้ามเอา
  สองอย่างนี้มาเทียบกันไว้ตั้งแต่ M3 — *"a retrieval score is not a ranking score…
  must not be shown as though they were comparable"* บวกกับ retriever ตัวนี้**เป็น BM25
  อยู่แล้ว** (มี IDF จริง), embedding ติดกฎ paid-provider, และ gold set บน fixture
  สังเคราะห์ 9 ใบที่เราเขียนเอง = ให้คะแนนข้อสอบตัวเอง เหตุผลเต็มอยู่ใน `docs/PLAN.md`

---

## 6. เลเยอร์ธุรกิจ

### 6.1 Jobs & Requirements (M3)

requirement เป็น **row** มี `kind` (skill / experience / education / language / other),
`label`, `detail`, `must_have`, `weight`

- พิมพ์เข้ามาผ่าน CRUD **ไม่ใช่ให้โมเดลแตกออกมาจาก job description** — เพราะ
  requirement คือ *input* ไม่ใช่ *claim* ไม่มีอะไรให้ guardrail ตรวจ และการเอาโมเดล
  มาวางตรงนี้คือการเพิ่มจุดพังโดยไม่เพิ่มการรับประกันอะไรเลย
- `description` เก็บไว้เป็นบริบทและ audit แต่ **ไม่ใช่สิ่งที่ใครถูกตัดสินด้วย** —
  ถ้าตัดสินจาก free text จะบอกไม่ได้ว่า verdict ตอบส่วนไหนของประกาศ
- route ของ requirement **nest อยู่ใต้ `/jobs/{id}`** เพื่อให้เรื่อง ownership จบในที่เดียว

### 6.2 Screening (M3)

`POST /jobs/{id}/screenings` → **202 เมื่อ queue งานใหม่ / 200 เมื่อผลเดิมตอบได้อยู่แล้ว**

ตัวตัดสินคือ `requirements_fingerprint` = hash ของ **(kind, label, detail) และลำดับ**
เท่านั้น

- ไม่รวม `weight` / `must_have` — ไม่เคยไปถึง prompt รวมแล้วจะเผาเงินได้คำตอบเดิม
- ไม่รวม id — ลบ requirement แล้วพิมพ์อันเดิมกลับมา = คำถามเดิม
- `prompt_version` เก็บ **ข้าง ๆ** hash ไม่ยุบรวม เพื่อให้แยกออกว่า "stale เพราะ
  requirement เปลี่ยน" กับ "stale เพราะ prompt เปลี่ยน"
- **screening ที่ complete แล้วรันซ้ำได้ แต่ resume ที่ extract แล้วรันซ้ำไม่ได้** —
  requirement เปลี่ยนได้ แต่เอกสารเปลี่ยนไม่ได้ การ extract ซ้ำคือจ่ายเงินรอบสอง
  เพื่อ profile ที่มีอยู่แล้ว
- ค่าใช้จ่ายของ judging ลงบัญชีที่ **screening ไม่ใช่ resume** — `LLMCallLog` มีทั้ง
  `resume_id` และ `screening_id` และเซ็ตอันเดียว ถ้าแขวน judging ไว้กับ resume
  ตัวเลข "เอกสารนี้ extract ไปเท่าไหร่" จะเพี้ยน

### 6.3 Applications + state machine (M4)

```
applied → screening → screened → shortlisted / rejected / withdrawn
```

- **`application_events` คือของจริง, `Application.state` เป็นแค่ projection** —
  replay log ต้องได้ค่าเดิมเสมอ
- `services/application_service.py` เป็น **ผู้เขียนเพียงคนเดียว** ของทั้งสองอย่าง
  และไม่เคยเขียน state โดยไม่เขียน event ที่ทำให้เกิด — การจับคู่นี้แหละคือดีไซน์
- กฎที่หล่นออกมาเอง (บังคับใน `app/applications.py` ซึ่งเป็น pure function)
  - **shortlist ได้จาก `screened` เท่านั้น และต้องบันทึก screening id ที่มันอิงอยู่**
    → *"คุณ shortlist คนที่ยังไม่ถูกคัดกรองไม่ได้ เพราะจะไม่มีหลักฐานที่อ้างอิงได้
    อยู่เบื้องหลังการตัดสินใจ"*
  - **reject ต้องมีเหตุผล**
  - ท่าที่ผิดกฎตอบ **409 พร้อมเหตุผล** ไม่ใช่เงียบ ๆ ไม่ทำอะไร — state machine ที่
    เมินท่าที่ไม่ชอบ จะทำให้แยกไม่ออกว่าอะไรคือการตัดสินใจและอะไรคือบั๊ก
- **เรียงด้วย `position` ที่เก็บไว้ ไม่ใช่ `created_at`** — SQLite timestamp ละเอียด
  แค่ 1 วินาที journey ที่ใช้เวลาไม่กี่ ms จะได้เวลาเท่ากันหมด แล้ว tiebreak ไปตกที่
  **UUID สุ่ม** (log เคยกลับมาสลับกันจริงในเทสต์)
- `Actor` ถือ **account id** ไม่ใช่อนุมานเอา — เวอร์ชันแรกอนุมานจากผู้ย้าย ทำให้
  **การตัดสินใจของ recruiter ทุกครั้งถูกบันทึกว่า "ระบบทำ"** เทสต์ที่ควรจับได้ดันเช็ค
  แค่ `actor_role` (ซึ่งถูก) ไม่ได้เช็ค `actor_id` → เจอตอนอ่าน audit log จริง
  ไม่ใช่จาก suite. `actor_id` เป็น null ได้เฉพาะกับระบบเท่านั้น
- **recruiter อ่านเรซูเม่ของคนที่สมัครงานตัวเองได้ แต่สั่งการไม่ได้** — `_owned_resume`
  ขยายเฉพาะการอ่าน ส่วน `POST /retry` ยังต้องเป็นเจ้าของ เพราะการ replay ใช้เงินและ
  เป็นของคนที่อัปโหลด "การได้ดู CV ไม่เท่ากับการได้รับปุ่มควบคุมมันมา"

### 6.4 RBAC (M4) — **403 กับ 404 ห้ามปนกัน**

| กรณี | ตอบ | เหตุผล |
|---|---|---|
| role ผิดสำหรับ route | **403** | route อยู่ใน `/docs` อยู่แล้ว บอกไปไม่รั่วอะไร |
| ไม่ใช่ทรัพยากรของคุณ | **404** | 403 บน id หนึ่ง = ยืนยันว่า id นั้นมีอยู่จริง → เป็น oracle ให้เดา account |

- `require_role` ใน `api/deps.py` เป็นที่เดียวที่ 403 ควรอยู่ และรันเป็น dependency
  **ก่อน** อ่าน row ใด ๆ เพื่อให้ candidate ที่ยิง id จริงกับ id มั่วได้คำตอบเหมือนกันเป๊ะ
  (mutation-test: ตอบ 403 ตรงจุด ownership → ตก 7 เคส)
- `require_role` ให้สิทธิ์ `ADMIN` โดยปริยาย — role system ที่ทุก route ต้องจำว่าต้อง
  ใส่ superuser เอง จะมีรูตั้งแต่ครั้งแรกที่มีคนลืม
- **role อ่านจาก row ไม่เคยฝังใน token** — ถ้าฝังใน JWT การถอดสิทธิ์จะไม่มีผลจนกว่า
  access token จะหมดอายุ คือช่วงเวลาที่สิทธิ์ซึ่งถูกถอดไปแล้วยังใช้ได้อยู่
- ข้อยกเว้นเดียว (เพิ่ม 2026-08-13): **job posting อ่านได้สาธารณะ** เพราะมันคือ
  ประกาศรับสมัคร แต่ทุก write และทุกอย่างที่ posting ผลิตออกมา (ranking, screening,
  รายชื่อผู้สมัคร) ยังคง 404 ตามเดิม เพราะมันมี verdict เกี่ยวกับคนจริง ๆ

### 6.5 PDPA (M4)

- **consent ไม่มี default** — `POST /resumes` ไม่มีค่าตั้งต้น ขาดไป = 422 จาก schema
  ก่อนที่จะเก็บ byte เดียวหรือเรียกโมเดล และเก็บ `consent_version` คู่กับ `consented_at`
  เพราะ "เขายินยอม" กับ "เขายินยอมกับ*ถ้อยคำนี้*" คือคนละคำกล่าวอ้าง
  `GET /resumes/consent` เสิร์ฟข้อความให้ client แสดง จะได้ไม่แต่งเอง
- `GET /auth/me/export` — คืน **ของจริง** รวม `document_text` และ profile ที่ verify แล้ว
  ถ้าคืนแค่สรุป สิทธิ์ในการขอสำเนาก็เป็นแค่ของประดับ
- `DELETE /auth/me` — **ลบไฟล์ก่อน แล้วค่อยลบ row และถ้าไฟล์ลบไม่ได้ ยกเลิกทั้งหมด**
  สลับลำดับ = row หายแต่ object ค้างใน bucket โดยไม่มีอะไรชี้ถึงมัน → หาไม่เจอ =
  ลบไม่ได้ตลอดกาล ส่วน "row ที่ไฟล์หาย" เป็นสถานะที่ pipeline จัดการได้อยู่แล้ว
- `PRAGMA foreign_keys=ON` ใน `db.py` เป็น load-bearing — SQLite เมิน `ON DELETE`
  ทุกตัวถ้าไม่สั่ง และ **test suite ทั้งชุดรันบน SQLite**

---

## 7. งานเบื้องหลังและ retry policy

`api/app/jobs.py` (649 บรรทัด) เป็นส่วนที่ใหม่และซับซ้อนที่สุด

### Status ของ resume

| Status | ความหมาย |
|---|---|
| `pending` | อยู่ในคิว หรือกำลังรอ backoff |
| `processing` | worker เคลมไปแล้ว ค้างเกิน `JOB_VISIBILITY_TIMEOUT_SECONDS` แปลว่า worker ตาย |
| `parsed` | เหลือไว้เพื่อ row เก่าก่อน M2 เท่านั้น ไม่ใช่สถานะพักอีกต่อไป |
| `extracted` | มี profile ที่ verify แล้ว — terminal และปฏิเสธ retry |
| `failed` | **เอกสารนี้ประมวลผลไม่ได้** — ไฟล์เสีย/ว่าง/ไม่มี key/สแกนที่ OCR ปิดอยู่ retry ไม่ช่วย *เว้นแต่เปลี่ยน config* |
| `dead_lettered` | **ความล้มเหลวชั่วคราวใช้โควตา retry หมด** คุ้มที่จะเล่นซ้ำ |

การแยก `failed` / `dead_lettered` คือหัวใจของ M2 #2 — status เดียวพูดพร้อมกันไม่ได้ว่า
"หยุดถามได้แล้ว" กับ "ลองใหม่ทีหลังนะ"

### นโยบาย

- `is_retryable` เป็น **whitelist ของ error ที่ถาวร** (`ParseError`,
  `ObjectNotFoundError`, `LLMConfigError`) ที่เหลือทั้งหมดรวมถึง exception ที่ไม่รู้จัก
  นับเป็นชั่วคราว ทิศทางนี้จงใจ: ความล้มเหลวที่ไม่คุ้นเคยมักเป็นอาการชั่วคราวมากกว่า
  ข้อเท็จจริงเกี่ยวกับเอกสาร และ **retry ผิดเสียแค่วินาที แต่ยอมแพ้ผิดคือเสียงานทั้งชิ้น**
- backoff = `5s → 10s → 20s` สูงสุด 3 ครั้งติด แล้ว dead-letter
  (`arq` ตั้ง `max_tries = job_max_attempts + 2` เพื่อไม่ให้มันยอมแพ้ก่อน — การยอมแพ้
  เป็นการตัดสินใจของ job และถูกเขียนลงบน row)
- `decide_retry` เป็น **pure function** คืน `PERMANENT` / `RETRY` / `EXHAUSTED`
  ไม่คืน status ทำให้ resume กับ screening ใช้ policy ร่วมกันได้โดยไม่ต้องใช้ enum
  ร่วมกัน (screening ไม่มีวันเป็น `parsed` หรือ `extracted`) และเทสต์ได้โดยไม่ต้องมี Redis
- job **คืน `JobOutcome` ไม่ raise `Retry` ของ arq** → `jobs.py` ไม่รู้จัก arq เลย
  มีแต่ `worker.py` ที่รู้
- **สอง counter**: `failed_attempts` = งบ retry (รีเซ็ตเมื่อสำเร็จหรือ retry มือ),
  `attempts` = ยอดจริงไม่เคยรีเซ็ต และเป็นตัวทำให้ job id ไม่ซ้ำ — arq ปฏิเสธ job id
  ที่เพิ่งเห็น ดังนั้น replay ที่ใช้ id เดิมจะถูกทิ้งเงียบ ๆ

### Reclaim — งานที่ worker ตายกลางทาง (M4 slice 1)

งานที่ *fail* จัดการได้ด้วย retry แต่งานที่ **process ดับไปเฉย ๆ** (ไฟดับ, OOM,
`docker kill`) ไม่เคยได้ *fail* — row ค้างที่ `processing` ที่ซึ่งทุกทางออกถูกปิด:
delivery ซ้ำก็ข้าม, `POST /retry` ตอบ 409, อัปโหลดไฟล์เดิมก็ dedupe มาลงที่ row เดิม

`jobs.reclaim_stalled` เป็น arq cron ทุกนาที (และตอน startup) กวาด row ที่ค้างเกิน
timeout สามอย่างที่จงใจ

- **ใช้ `decide_retry` ซ้ำ ไม่ใช่รีเซ็ต status** — การ reclaim นับเข้า
  `failed_attempts` ด้วย ทำให้เอกสารที่ฆ่า worker ทุกครั้ง dead-letter ในที่สุด
  แทนที่จะวนลูป reap → requeue → die ตลอดกาล (mutation-test: รีเซ็ต status เฉย ๆ → ตก 3 เคส)
- **การ list กับการ reclaim แยกเป็นคนละฟังก์ชัน** เพราะ `_record_failure` commit
  ซึ่งปล่อย lock ทิ้ง → รายการที่ list มาเชื่อไม่ได้ ต้องอ่าน row ใหม่ `with_for_update`
  แล้วทดสอบเงื่อนไขซ้ำ
- **row ที่ `processing` แต่ไม่มี `last_attempt_at` นับว่า stalled** เพราะการเคลม
  เขียนทั้งสองอย่างใน commit เดียว การรวมกันแบบนั้นจึงเป็นไปไม่ได้ถ้ามีอะไรกำลังรันอยู่

ครึ่งที่ทำด้วยมือ: `POST /resumes/{id}/retry` และ `POST /screenings/{id}/retry` รับ row
ที่ค้างเกิน timeout ด้วย และนี่คือ **ครึ่งเดียวที่มีอยู่ภายใต้ `QUEUE_BACKEND=inline`**
เพราะไม่มี process ให้ตั้ง cron

### `InlineQueue` ทำอะไรไม่ได้

เลื่อนงานไม่ได้ และการนอนรอ backoff จะค้าง request ทิ้งไว้ทั้งนั้น มันจึง **ไม่ retry
เลย** — ความล้มเหลวชั่วคราวทิ้ง resume ไว้ที่ `pending` พร้อมเหตุผล แล้วอัปโหลดไฟล์เดิม
ซ้ำจะหยิบมันขึ้นมาใหม่ และมันไม่รัน reaper ด้วยเหตุผลเดียวกัน นี่เป็นคุณสมบัติของการ
รันโดยไม่มีคิว ไม่ใช่บั๊ก

---

## 8. Frontend

```
app/page.tsx            auth + upload + progress สด + ผลลัพธ์ + retry
app/jobs/page.tsx       รายการ job + สร้าง job พร้อม requirement ในคำขอเดียว
app/jobs/[id]/page.tsx  requirement editor + screening + ranking + verdict ข้างเอกสาร
app/applications/       ฝั่งผู้สมัคร — สมัคร ติดตาม ถอน
app/metrics/            dashboard การใช้งานและคุณภาพ (M5 slice 2)
```

หลักการฝั่ง client

- **`lib/` ถือ logic บริสุทธิ์ทั้งหมด** (`screening.ts`, `applications.ts`,
  `evidence.ts`, `metrics.ts`, `requirements.ts`, `api.ts`, `auth.ts`) เพื่อให้
  `npm test` **ไม่ต้องมี DOM และไม่ต้องมี React testing library** — สัญชาตญาณเดียวกับ
  ที่ Python suite ไม่ต้องมี server
- `lib/applications.ts` ตัดสินว่าจะ **เสนอ** ท่าไหนให้กด แต่ **จงใจไม่ตัดสินว่าอะไร
  ทำได้** — server เป็นคนตัดสิน สำเนาชุดที่สองของกฎคือชุดที่จะ drift โดยไม่มีใครสังเกต
- `DocumentPane` รับ `references: EvidenceRef[]` **ไม่ใช่ profile** — นี่คือสิ่งที่ทำให้
  citation ของ screening ไป highlight ผ่าน component ที่ M1 เขียนไว้สำหรับ extraction
  ได้ เพราะ offset ชี้เข้า `document_text` เดียวกัน
- `createScreening` คืน `queued` เพราะ **202 vs 200 เป็นการตัดสินใจเชิงออกแบบที่ UI
  ต้องรายงานได้** ไม่ใช่รายละเอียดที่ซ่อนไว้
- **session เป็น external store ไม่ใช่ component state** (`useSyncExternalStore` เหนือ
  `localStorage`) — `lib/auth.ts` เป็นที่เดียวที่แตะ `localStorage`, component สองตัวบน
  หน้าเดียวกันจึงเห็น token ตรงกันเสมอ และ **sign out แท็บนึงแล้วแท็บอื่นออกตาม**
  ผ่าน `storage` event
- token เก็บใน `localStorage` (อ่านได้ด้วย XSS) — ยอมรับได้สำหรับ dev สองต้นทาง
  คำตอบของ production คือ httpOnly cookie ซึ่ง **ยัง defer อยู่ (ข้อเดียวที่เหลือ)**
- **refresh-token denylist ทำแล้ว** (2026-08-16, migration `0011`) — `POST /auth/logout`
  มีจริงแล้ว และ refresh token ที่ใช้ไปแล้วถูกเพิกถอนจริง ก่อนหน้านี้ `README` เขียนว่า
  "single-use" แต่**ไม่จริง**: ออก pair ใหม่แล้วปล่อยตัวเก่าใช้ได้ต่ออีก 14 วัน
  กฎที่ต้องจำ: **`decode_token` กับ `token_service.assert_live` ต้องเรียกคู่กันเสมอ**
  (verify อย่างเดียว = รับ token ที่ถูก sign out ไปแล้ว)
  สิ่งที่ยังทำไม่ได้: เปลี่ยนรหัสผ่านแล้ว**ไล่เครื่องอื่นออกไม่ได้** เพราะ denylist เก็บแค่
  token ที่ตายแล้ว ไม่เก็บที่ยังมีชีวิต — มี test pin ไว้ให้พังวันที่มีคนแก้

---

## 9. Observability (M5 slice 2)

`GET /metrics/usage` = aggregate จาก `llm_call_logs` + `extracted_profiles`
**ไม่มี table ใหม่ ไม่มี migration**

schema ถูกออกแบบรองรับมาตั้งแต่ M1 — `claims_verified`, `claims_dropped`,
`hallucination_rate` ถูกยกออกมาเป็นคอลัมน์จริง *เพื่อการนี้โดยเฉพาะ* query จึงเป็น
`GROUP BY` ไม่ใช่การเดิน JSON

**หมายเหตุที่สำคัญ:** slice นี้ถูก **respecify ก่อนสร้าง** — เดิม scope ไว้เป็น *cost*
dashboard แต่ไม่มี cost เลย เพราะ `app/llm/gemini.py` map ทุกโมเดลเป็น `FREE_TIER`
ทำให้ทั้ง 22 call เก็บ `cost_usd = 0.0` และไม่มีสักแถวที่เป็น NULL — สร้างตามที่เขียนไว้
จะได้หน้าจอที่มีแต่เลขศูนย์ซึ่งอ่านเหมือนบั๊ก กฎเรื่อง cost ยังอยู่ครบ (ราคาที่ไม่รู้
ต้องขึ้น "unknown" ไม่ใช่ `$0.00` และบอกด้วยว่ากี่แถวที่ไม่มีราคา) แต่สิ่งที่หน้าจอนำ
เสนอคือ token, latency, prompt family และตัวเลขคุณภาพ ซึ่งเป็นของจริงวันนี้

4 การตัดสินใจที่ mutation-test พิสูจน์แล้วว่า load-bearing (ผิดอันไหนก็ตก 1 เคส)

1. **cost ของกลุ่มเป็น `unknown` เว้นแต่ทุก call ในกลุ่มมีราคา** — `SUM` ข้าม null
   ทำให้รายงานยอดบางส่วนเหมือนยอดเต็ม ยอดที่หายไปมองเห็นได้ ยอดที่ขาดบางส่วนมองไม่เห็น
2. **hallucination rate คำนวณใหม่จากยอดรวม ไม่ใช่เฉลี่ยจากค่าที่เก็บไว้รายเอกสาร** —
   บนข้อมูลทดสอบสองสูตรต่างกัน **25 เท่า**
3. **owner scoping มีสองแขน** เพราะ `llm_call_logs` ไม่มีคอลัมน์เจ้าของเลย:
   `resume_id → resumes.candidate_id` (extraction) และ
   `screening_id → screenings → jobs.owner_id` (judging) ตัดแขนไหนออกครึ่งหนึ่งของ
   call จะรายงานเป็นศูนย์เงียบ ๆ
4. **แบ่งเป็น 4 bucket** รวมถึง `unattributed` — row ที่ไม่มีทั้งสอง id ถูกกฎหมาย
   อยู่ (invariant นั้นเป็น docstring ไม่ใช่ constraint) จึงต้องรายงานว่ามี ไม่ใช่หายเงียบ

**ADMIN เห็นทุก row โดยอ่าน role ใน WHERE clause** ไม่ใช่ gate ที่ route —
`require_role` ไม่รัน query เลย ถ้าใช้มันจะ 403 ใส่บัญชีที่เป็นเจ้าของ row พอดี

---

## 10. Test / CI / คุณภาพ

- `pytest -q` → **651 ผ่าน / 38 skip** (skip คือ opt-in: Postgres 4 + Tesseract 12 +
  MinIO 9 + live-LLM 12)
- `npm test` → **137 เคส** (vitest ไม่มี DOM)
- gate ที่บังคับใน CI: `ruff check`, `ruff format --check`, `mypy app` (strict),
  `pytest -q`, แล้ว `npm ci` / `typecheck` / `lint` / `build`
  \+ **migration up/down round-trip บน SQLite**

### บทเรียนเรื่องเครื่องมือที่โกหก

มีบันทึกไว้ 8 ตัวใน `HANDOFF.md` §10 อันที่สำคัญที่สุด

- **การตรวจที่ผลลัพธ์คือ "ความว่างเปล่า" ต้องมี positive control ก่อน** —
  `read_console_messages` เริ่มจับตอนถูกเรียกครั้งแรก หน้าที่โหลดก่อนหน้าจะคืน
  "ไม่มี message" ไม่ว่าจะสะอาดหรือไม่ ต้องยิง probe `console.log`/`console.error`
  ให้เห็นก่อน แล้วค่อยเชื่อว่าไม่มี error
- **คำสั่งที่ทำสองอย่าง รายงานแค่อย่างเดียว** — `docker compose up -d --build`
  build สำเร็จ, recreate ล้มเหลว, exit 0 → container เสิร์ฟโค้ดเก่าอายุ 9 ชั่วโมง
  ขณะที่คำสั่งบอกว่าสำเร็จ สาเหตุรากคือ `C:` เต็ม (ทำให้ containerd metadata store
  เป็น read-only) **เช็คพื้นที่ว่างก่อนเซสชันที่จะ rebuild**
- **suite แบบ opt-in ที่เงียบ หน้าตาเหมือน suite ที่ผ่าน** — `test_postgres.py` มี
  2 ใน 5 เคสพังมา 3 วันโดยไม่มีใครเห็น เพราะ `pytest -q` ข้ามและ CI ไม่มี DB
  ต้องรันทุก opt-in module ด้วยมือเป็นระยะ
- **ก่อนเชื่อการทดสอบสด ต้องพิสูจน์ว่ากำลังทดสอบสิ่งที่เพิ่งสร้าง** — เคยเจอ zombie
  server บน port เก่า, ARQ worker ตัวที่สองจากเซสชันก่อนแอบรับงาน, และ dev server
  บน port ที่ไม่อยู่ใน CORS list เช็คด้วย `/openapi.json` และถ้าการเปลี่ยนแปลงไม่ได้
  เพิ่ม route ให้ถาม container ตรง ๆ ว่ามันถืออะไรอยู่

### กฎที่แพงที่สุดที่โปรเจคนี้ซื้อมา

> **slice จะ "เสร็จ" เมื่อมีคนใช้มันแล้ว ไม่ใช่เมื่อ API call ทุกตัวถูก verify แล้ว**

2026-08-13 การเปิด browser ดู M4 slice 5 ครั้งแรกเจอ **7 ข้อบกพร่อง 4 อันบล็อกงาน**
ในโค้ดที่ทุก gate เขียวหมด

- candidate มองไม่เห็นประกาศงานเลย (`GET /jobs` กรองตามเจ้าของ → `200 []`)
- ปุ่ม Create job กดไม่ได้ เพราะ `min=0.1 step=0.5` ทำให้ค่า default ของตัวเอง (1) ไม่ valid
- recruiter คัดกรองผู้สมัครไม่ได้ เพราะ picker สร้างจาก `GET /resumes` ซึ่งคืนแค่ของตัวเอง
- transition ทุกอันตอบ 422 เพราะ `moveApplication` / `applyToJob` ข้าม helper `json()`
  แล้วไม่ได้ส่ง `Content-Type`

ไม่มีอันไหนที่เทสต์ logic บริสุทธิ์จะเห็นได้เลย ตอนนี้ทุก slice จึงต้อง
**ขับ browser ข้างใน slice ไม่ใช่หลัง slice** (และ 2026-08-15 slice 1 ผ่านฉลุย —
กฎไม่ได้บอกว่า browser check จะเจอบั๊กเสมอ แต่บอกว่าไม่มีอย่างอื่นบอกคุณได้)

---

## 11. ตอนนี้โปรเจคถึงไหนแล้ว

*(ข้อมูล ณ 2026-08-16 — ดู `docs/PLAN.md` สำหรับสถานะที่เป็นทางการ)*

| Milestone | ขอบเขต | สถานะ |
|---|---|---|
| **M1** | parse (PDF, offsets, ไทย), extract, verify evidence, retry, auth, upload API, web UI | ✅ 2026-07-30 |
| **M2** | async worker + queue, OCR, DOCX, two-column, MinIO, evidence viewer | ✅ 2026-08-08 |
| **M3** | job requirements, judging ระดับ requirement, ranking, retrieval, screening UI | ✅ 2026-08-12 |
| **M4** | visibility timeout, RBAC, application state machine, PDPA | ✅ 2026-08-12 |
| **M5** | dropped-claims view, dashboard, geometry, pdf.js overlay, production compose | ✅ **2026-08-16 (5/5)** |
| **M6** | ประเมิน ranking เทียบ BM25/embedding baseline | ⛔ **review แล้ว ปิดโดยไม่สร้าง** (2026-08-16) |

### M5 รายละเอียด

| # | slice | สถานะ |
|---|---|---|
| 1 | **dropped-claims audit view** | ✅ ดูใน browser แล้ว ใช้โควตา Gemini **0** — เห็น `Excluded — could not be traced to the document (1)` พร้อม quote ที่ถูกกุขีดฆ่า และ **quote ที่กุไม่ได้ผลิต verdict** |
| 2 | **usage & quality dashboard** | ✅ respecify ก่อนสร้าง (ดู §9) |
| 3 | **character geometry ตอน parse** | ✅ **แก้ scope จาก per-word เป็น per-character runs** |
| 4 | **pdf.js overlay** | ✅ citation ถูกวาดกล่องทับ PDF ต้นฉบับแล้ว — browser เจอบั๊กที่ gate มองไม่เห็น (span เดียวถูกวาดซ้ำสองครั้ง) |
| 5 | **production compose + runbook** | ✅ `docker-compose.prod.yml` + `docs/RUNBOOK.md` ซ้อมขึ้นจริงแบบ cold start แล้ว |

**เรื่อง slice 3 ที่น่าสนใจ:** แผนเดิมเขียนว่าเก็บ bounding box **ต่อคำ** ซึ่งผิดสำหรับ
ภาษาที่โปรเจคนี้แคร์ที่สุด เพราะไทยไม่มีเว้นวรรค "คำ" หนึ่งคำใน `resume_th.pdf` คือ
run ยาว 31 ตัวอักษร ตอนนี้เก็บเป็น **run ระดับตัวอักษรที่อยู่บรรทัดเดียวกัน** ทำให้
quote `ชำระเงิน` ที่อยู่ตัวที่ 180 *ข้างใน* run นั้นได้ **8 กล่องสำหรับ 8 ตัวอักษร**
(แบบ per-word จะ highlight ทั้ง 31 ตัว) และไม่ได้ใช้การ *ค้นหา* ข้อความเลย — ใช้
textmap ของ pdfplumber ที่จับคู่ตัวอักษรกับกล่องมาให้โดยโครงสร้าง เพราะ `find()`
วัดแล้วพังสามทาง: 8 ใน 11 คำใน `resume_broken_tounicode.pdf` มี NUL, มันคืนตำแหน่งแรก
ขณะที่ 105 จาก 120 คำใน `resume_multipage.pdf` ซ้ำกัน, และหน้าสองคอลัมน์ถูกเรียงใหม่
ทำให้เกิด offset inversion 11 จุด

**คุณสมบัติที่ slice 3 ต้องรักษาไว้ และวัดแล้วจริง ๆ:** `document_text`, page spans,
`pages_without_text` และ `pages_from_ocr` **byte-identical ทั้ง 13 fixture** ก่อนและ
หลัง — นั่นคือสิ่งที่ทำให้ citation ที่เคยแสดงต่อผู้ใช้ไปแล้วยังชี้ที่เดิม

**M5 ปิดครบแล้ว (2026-08-16)** — ทั้ง 5 slice ถูกขับใน browser *ข้างใน* slice ทุกอัน

เรื่องที่น่าสนใจของ **slice 5 (production compose)**: กลไก compose ถูก**วัดก่อนสร้าง**
เพราะ 4 เซสชันติดกันที่แผนระบุกลไกที่ไม่เคยลอง แล้วปรากฏว่าใช้ไม่ได้ วัดบน Compose
v5.3.1 ได้ผลว่า

| กลไก | ผล |
|---|---|
| `env_file:` ใน override | **แพ้** `environment:` ของไฟล์ฐาน — key ที่ฐานตั้งไว้จะคงค่า dev เดิมโดยไม่มีอะไรบอก (scope เดิมสั่งให้ใช้อันนี้) |
| `--env-file` / `COMPOSE_ENV_FILES` | **ใช้ได้** เพราะไปป้อน `${VAR:-default}` ของ compose เอง → เป็นอันที่เลือกใช้ |
| `ports: !reset []` / `!override` | **ใช้ได้ทั้งคู่** |
| `ports:` merge เฉย ๆ | **ต่อท้าย** — ได้ port ทั้ง dev และ prod เผยแพร่พร้อมกัน |
| `profiles:` | ใช้ไม่ได้เลย — พอ profile ไม่ทำงาน project **โหลดไม่ขึ้น** เพราะทุก infra service เป็นเป้า `depends_on` |

สองอย่างที่เจอตอนสร้างจริงและไม่มีในแผน: **`migrate` รันภายใต้ `APP_ENV=prod`** เพราะ
`migrations/env.py` เรียก `get_settings()` → ลืม `JWT_SECRET` แล้วพังที่ service **แรก**
ไม่ใช่ที่สาม (ดูจริงแล้ว api/worker/web ไม่ได้สตาร์ทเลย) และ **ทุก service ที่ build ต้องมี
image tag ของตัวเอง** ไม่งั้น build ของ prod จะทับ `hirelens-web:local` แล้ว dev ครั้งถัดไป
จะหยิบ bundle ที่ชี้ API ผิด URL ไปใช้เงียบ ๆ

ซ้อมจริงแบบ cold start (`-p hirelens-prod` volume ของตัวเอง) พิสูจน์ได้ว่า: migration
ทั้ง 10 ตัวรันบน DB เปล่า, data service ทั้งสาม**ไม่เผยแพร่ port เลย** (ทดสอบโดยมี positive
control คือ Redis ของ dev ที่ตอบ `+PONG`), อัปโหลด `resume_th.pdf` ผ่าน browser ได้
**10/10 claims verified, 0 model call ที่เป็น Gemini**, และลบบัญชีแล้วเหลือ 0 row 0 ไฟล์

### สถานะ repo

- gate ล่าสุด (รันเอง ไม่ได้อ้าง): pytest **651/38 skip**, vitest **137**,
  ruff / mypy (57 ไฟล์) / typecheck / lint / build clean
- opt-in ที่รันด้วยมือแล้ว: `test_postgres.py` 5 ผ่าน, `test_minio.py` 9 ผ่าน
- จำนวน commit ที่ยังไม่ push **ให้ดูด้วย `git rev-list --count origin/main..main`**
  อย่าเชื่อบรรทัดนี้ — เอกสารในโปรเจคนี้เคยบอกเลขผิดมาแล้วสองครั้ง

---

## 12. กฎที่ห้ามพัง

1. **ห้ามให้ claim ที่ยัง verify ไม่ได้เข้าไปใน response** — ใส่ `dropped` แทน
2. **ห้ามให้โมเดลผลิต character offset หรือเลขหน้า** — นี่คือความผิดพลาดที่ทั้งดีไซน์นี้
   มีอยู่เพื่อหลีกเลี่ยง
3. **ห้ามทำให้ test suite ต้องมี server** — ใช้ opt-in module แทน
4. **ห้าม log หรือ print document text** — เรซูเม่คือ PII (รวมถึง storage key ที่ฝัง
   candidate id + content hash)
5. **`document_text` เก็บ verbatim** ห้าม re-parse / re-normalize ของที่เก็บแล้ว
6. **403 คือ route, 404 คือ row** ห้ามยุบรวม
7. **path ของโปรเจคต้องเป็น ASCII** — codepage เครื่องนี้คือ cp874 (ไทย) เคยทำ venv
   พังมาแล้วผ่านไฟล์ `.pth`
8. **`LLM_PROVIDER=anthropic` raise โดยเจตนา** — adapter ที่ไม่เคยรันกับ API จริง
   แย่กว่า error ที่ซื่อสัตย์ และ provider ที่คิดเงินต้องมาพร้อมตารางราคาที่อัปเดต
   \+ การทดสอบสดที่บันทึกไว้ใน `docs/llm-providers.md`
9. **test data สังเคราะห์เท่านั้น** — เรซูเม่คนจริงห้ามเข้า repo
10. **fixture ไบนารีต้องอยู่ใน `.gitattributes`** — `core.autocrlf=true` เคยเขียนทับ
    `0x0A` ข้างใน compressed stream ของ PDF ทำให้ไฟล์เสียบนเครื่อง Windows ทุกเครื่อง
    (ถ้าสงสัยว่าเกิดขึ้น ให้ **เทียบขนาดไฟล์ ไม่ใช่ hash** เพราะ `git hash-object`
    normalize ระหว่างแฮช)
11. **`test_columns_should_read_one_after_the_other` ใน `test_parse.py` ต้องอยู่ต่อ**
12. **OCR ต้องถูกแทนเข้า page list ก่อน `_assemble` วัด span**
13. **erasure ลบไฟล์ก่อน row และไม่ลบอะไรเลยถ้าไฟล์ลบไม่ได้**
14. **`PRAGMA foreign_keys=ON` ใน `db.py` เป็น load-bearing**

---

## 13. เริ่มเล่นเองยังไง

```bash
# เร็วที่สุด ไม่ต้องมี server ไม่ต้องมี DB ไม่ต้องมี API key
cd api && python -m app.cli tests/fixtures/resume_th.pdf
cd api && python -m app.cli tests/fixtures/resume_th.pdf --requirement skill:Python

# ทั้งระบบในคอนเทนเนอร์
docker compose up -d --build   # api :8000 (/docs), web :3000, minio console :9001
docker compose logs -f worker
```

- อยากเห็นเส้นทาง **dropped-claims**: ตั้ง `FAKE_MODE=hallucinating` ใน `.env`
  รีสตาร์ท api + worker แล้วอัปโหลดใหม่
- อยากเห็นเส้นทาง **dead-letter**: `FAKE_MODE=unavailable` แล้วดู log ของ worker
- **ไม่มี worker รัน = อัปโหลดค้างที่ `pending` ตลอดไป** (อัปโหลดไฟล์เดิมซ้ำจะ
  re-queue ให้ เริ่ม worker ช้าก็ยังทันงาน)

### ลำดับการอ่านโค้ด

ประมาณ 30 นาทีก็เข้าใจ pipeline (ลำดับเต็มอยู่ใน `HANDOFF.md` §3)

1. `README.md`
2. **`api/app/pipeline/evidence.py`** ← หัวใจ
3. `api/tests/test_evidence.py` ← สเปคที่ชัดที่สุด รวมเคสภาษาไทย
4. `api/app/pipeline/parse.py` (+ `layout.py` ดูว่าทำไมมันตอบ `None` บ่อย)
5. `api/app/pipeline/extract.py`
6. `api/app/schemas/extraction.py` + `profile.py` ← การแยกสองชั้น: โมเดลคืนอะไร vs เราเก็บอะไร
7. `api/app/llm/fake.py`
8. `api/app/services/resume_service.py`
9. **`api/app/jobs.py`** ← ครึ่งเบื้องหลังทั้งหมดและ retry policy
10. `api/app/queue.py`
11. **`api/app/applications.py`** ← หัวใจของ M4 และสั้นมาก
12. `api/app/services/application_service.py`, `privacy_service.py`
13. `docs/PLAN.md`

### คำสั่งที่ใช้บ่อย

รันจาก `api/` ใน venv (`.venv\Scripts\activate`) หรือใส่ prefix
`.venv/Scripts/python.exe -m`

```bash
pytest -q                        # ทั้ง suite ไม่ต้องมี DB / API key / Tesseract
ruff check app tests migrations  # บังคับใน CI
ruff format app tests migrations
mypy app                         # strict บังคับใน CI
alembic upgrade head
uvicorn app.main:app --reload    # :8000
arq app.worker.WorkerSettings    # ต้องมี QUEUE_BACKEND=arq + Redis
```

จาก `web/`: `npm run dev` (:3000), `npm run typecheck`, `npm run lint`, `npm test`,
`npm run build`
