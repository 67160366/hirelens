# HireLens — คู่มือทำความเข้าใจโปรเจค (ภาษาไทย)

> **เอกสารนี้ไม่ใช่แหล่งอ้างอิงที่เป็นทางการ** — เป็นคำอธิบายสำหรับเจ้าของโปรเจค
> เขียน 2026-08-15 · ปรับปรุงใหญ่ **2026-08-22** จากสภาพ repo ณ commit `a431d60`
>
> ลำดับที่ `CLAUDE.md` กำหนดให้เซสชันใหม่อ่านคือ `CLAUDE.md` → `docs/HANDOFF.md` §3 →
> `docs/PLAN.md` **สถานะรายข้อที่ถูกต้องอยู่ในตารางของ `docs/PLAN.md` เท่านั้น**
> ไฟล์นี้เป็นภาพนิ่งที่จะเก่าลงเรื่อย ๆ — ถ้าขัดกัน ให้เชื่อสามไฟล์ข้างบน
>
> เอกสารนี้เน้น **backend และการไหลของข้อมูล** ส่วนเรื่องดีไซน์/CSS อยู่ใน `docs/DESIGN.md`

สารบัญ

0. [พื้นฐานที่ต้องรู้ก่อน](#0-พื้นฐานที่ต้องรู้ก่อน)
1. [โปรเจคนี้คืออะไร](#1-โปรเจคนี้คืออะไร)
2. [ไอเดียแกนกลาง](#2-ไอเดียแกนกลาง-the-one-idea)
3. [Tech stack และเหตุผลที่เลือก](#3-tech-stack-และเหตุผลที่เลือก)
4. [สถาปัตยกรรมและการไหลของข้อมูล](#4-สถาปัตยกรรมและการไหลของข้อมูล)
5. [หนึ่ง request เดินทางยังไง](#5-หนึ่ง-request-เดินทางยังไง)
6. [เดินโค้ดทีละโมดูล (pipeline)](#6-เดินโค้ดทีละโมดูล-pipeline)
7. [เลเยอร์ธุรกิจ](#7-เลเยอร์ธุรกิจ)
8. [งานเบื้องหลังและ retry policy](#8-งานเบื้องหลังและ-retry-policy)
9. [Frontend — route และการส่งข้อมูล](#9-frontend--route-และการส่งข้อมูล)
10. [Observability](#10-observability)
11. [Test / CI / คุณภาพ](#11-test--ci--คุณภาพ)
12. [ตอนนี้โปรเจคถึงไหนแล้ว](#12-ตอนนี้โปรเจคถึงไหนแล้ว)
13. [กฎที่ห้ามพัง](#13-กฎที่ห้ามพัง)
14. [เริ่มเล่นเองยังไง](#14-เริ่มเล่นเองยังไง)

---

## 0. พื้นฐานที่ต้องรู้ก่อน

หัวข้อนี้เพิ่มมาสำหรับคนที่ยังไม่คุ้นกับศัพท์ฝั่ง backend อธิบายสั้น ๆ **พร้อมชี้ว่าของจริง
ในโปรเจคนี้อยู่ตรงไหน** ถ้าคุ้นอยู่แล้วข้ามไปข้อ 1 ได้เลย

### 0.1 คำที่โผล่ตลอดทั้งเอกสาร

| คำ | ความหมายสั้นที่สุด | ของจริงในโปรเจคนี้ |
|---|---|---|
| **API / REST** | โปรแกรมคุยกันด้วย HTTP โดยมี "ที่อยู่" (path) และ "กริยา" (GET/POST/PATCH/DELETE) | `api/app/api/routes/` ทั้ง 7 ไฟล์ ดูรายการเต็มที่ `http://localhost:8000/docs` |
| **Status code** | ตัวเลขที่บอกว่าเกิดอะไรขึ้น | 200 สำเร็จ · 201 สร้างแล้ว · 202 รับเข้าคิว · 204 สำเร็จแต่ไม่มีเนื้อ · 401 ยังไม่ล็อกอิน · **403 บทบาทไม่ถึง** · **404 ไม่ใช่ของคุณ (หรือไม่มีจริง)** · 409 ท่านี้ทำไม่ได้ตอนนี้ · 422 ข้อมูลที่ส่งมาผิดรูป |
| **Router** | กลุ่ม route ที่รวมไว้ด้วยกัน | `auth` · `resumes` · `jobs` · `screenings` · `applications` · `metrics` · `careers` |
| **Dependency injection** | บอกว่า "ฟังก์ชันนี้ต้องการ X" แล้วเฟรมเวิร์กหามาให้ก่อนเข้าฟังก์ชัน | `SessionDep` (session ของ DB), `CandidateDep` (บัญชีที่ล็อกอินอยู่), `RecruiterDep` — ทั้งหมดใน `api/app/api/deps.py` |
| **ORM** | เขียน Python แล้วได้ SQL | SQLAlchemy 2 แบบ async ใน `api/app/models/` |
| **Migration** | สคริปต์เปลี่ยนโครงตารางทีละขั้น ย้อนได้ | `api/migrations/versions/` — ตอนนี้ `0001` → **`0013`** |
| **Transaction / commit** | กลุ่มการเขียนที่สำเร็จพร้อมกันหรือล้มพร้อมกัน | ลำดับ commit ในข้อ 4.1 เป็นเรื่องเป็นเรื่องตาย ไม่ใช่รายละเอียด |
| **Queue / worker** | ฝากงานหนักให้อีก process ทำ ผู้ใช้จะได้ไม่ต้องรอ | `app/queue.py` เป็นรอยต่อ, `app/worker.py` เป็น entrypoint ของ arq, `app/jobs.py` คือตัวงานจริง |
| **SSE (Server-Sent Events)** | เซิร์ฟเวอร์ push ข้อความมาเรื่อย ๆ บน HTTP เส้นเดียว | `GET /resumes/{id}/events` |
| **JWT** | token ที่เซ็นชื่อไว้ ปลอมไม่ได้ แต่ **อ่านได้** จึงห้ามใส่ความลับ | `api/app/security.py` |
| **httpOnly cookie** | cookie ที่ JavaScript บนหน้าเว็บอ่านไม่ได้เลย | `api/app/cookies.py` — เบราเซอร์ถือ session ไว้ สคริปต์ขโมยไม่ได้ |
| **RBAC** | สิทธิ์ตามบทบาท | `candidate` / `recruiter` / `admin` ใน `api/app/models/core.py` |
| **Append-only log** | เขียนต่อท้ายอย่างเดียว ห้ามแก้ ห้ามลบ | ตาราง `application_events` |
| **Projection** | คอลัมน์ที่ "คำนวณได้" จาก log | `Application.state` — เล่น log ซ้ำต้องได้ค่าเดิมเสมอ |
| **Pure function** | ใส่ค่าเข้า ได้ค่าออก ไม่แตะ DB ไม่แตะเวลา ไม่แตะเครือข่าย → เทสต์ง่ายมาก | `app/applications.py`, `app/publication.py`, `pipeline/ranking.py`, `jobs.decide_retry` |
| **Fixture** | ไฟล์ตัวอย่างที่ commit ไว้ใช้เทสต์ | `api/tests/fixtures/*.pdf` — **สังเคราะห์ทั้งหมด ไม่มีเรซูเม่คนจริง** |

### 0.2 กับดักเล็ก ๆ ที่กัดจริง

- **enum ถูกเก็บใน DB เป็น "ชื่อ" ตัวใหญ่** ไม่ใช่ค่าตัวเล็ก — `PUBLISHED`, `DEAD_LETTERED`,
  `RECRUITER` เขียน SQL ดิบแล้วใส่ `'published'` จะไม่เจอแถวไหนเลย และไม่มี error บอก
- **`PRAGMA foreign_keys=ON` ใน `api/app/db.py` เป็นของจำเป็น** — SQLite เมิน `ON DELETE`
  ทุกตัวถ้าไม่สั่งเปิด และ **test suite ทั้งชุดรันบน SQLite**
- **path ของโปรเจคต้องเป็น ASCII** — codepage ของเครื่องนี้คือ cp874 (ไทย) เคยทำ venv พังมาแล้ว
- **`localhost:3000` เท่านั้น ห้าม `127.0.0.1:3000`** — cookie ไม่สนใจ port แต่สนใจ host
  เปิดผิดตัวจะ login ผ่าน แล้วทุก request หลังจากนั้น 401 (เหตุผลเต็มในข้อ 5.4)

---

## 1. โปรเจคนี้คืออะไร

**HireLens** — ระบบคัดกรองเรซูเม่ที่ **ทุกคำกล่าวอ้างต้องอ้างอิงข้อความจริงในเอกสารต้นฉบับได้
เสมอ** และสิ่งที่อ้างอิงไม่ได้จะถูกทิ้งพร้อมรายงาน ไม่ใช่เอามาแสดง

ที่มา: user journey #19 (HR Tech) ในเอกสาร `userjourneysthailand.md.pdf` ซึ่งเก็บไว้นอก repo
(อาจมีเนื้อหาของบุคคลที่สาม) pain point เขียนไว้ตรง ๆ ว่า

> *"เรซูเม่ไม่ผ่านการคัดกรองอัตโนมัติ (ATS) โดยไม่รู้สาเหตุ"*

ปัญหาคือ ATS ปฏิเสธคนโดยอธิบายไม่ได้ HireLens ตอบด้วยการบังคับให้ทุกข้อสรุป "ชี้นิ้ว" กลับไปที่
บรรทัดในเรซูเม่ที่เป็นที่มาของมัน รองรับทั้งไทยและอังกฤษ

**และตั้งแต่ 2026-08-22 คำตอบนั้นถึงมือผู้สมัครจริงแล้ว** — `GET /applications/{id}/screening`
(ข้อ 7.6) ทำให้ผู้สมัครเปิดอ่าน verdict ชุดเดียวกับที่ recruiter อ่าน บนเอกสารของตัวเอง
ที่ตำแหน่งตัวอักษรเดียวกัน ก่อนหน้านั้นทุกหน้าจอในระบบนี้รับใช้ฝั่งที่เป็นคนปฏิเสธเท่านั้น

รูปร่างปัจจุบันคือ **careers site ของนายจ้างรายเดียว** ที่นายจ้างคือ HireLens เอง และระบบคัดกรอง
เป็น **ฟีเจอร์ที่ประกาศออกมา** ไม่ใช่หลังบ้านที่ซ่อนไว้ — จงใจไม่ใช่เว็บขายซอฟต์แวร์ให้ HR
และจงใจไม่ใช่ careers site ที่การคัดกรองมองไม่เห็น (อย่างหลังคือ ATS ที่โปรเจคนี้เกิดมาเถียงด้วย)

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

### ไอเดียเดียวกันถูกใช้ซ้ำอีกหลายครั้ง

นี่คือสิ่งที่ทำให้โปรเจคนี้มีเอกลักษณ์ — ทุกมิลสโตนหลังจากนั้นคือเรื่องเดิม เปลี่ยนแค่บริบท

| มิลสโตน | รูปแบบเดียวกัน |
|---|---|
| M1 | **claim หนึ่ง ๆ มาจาก quote ที่หาเจอ** ไม่ใช่จากที่โมเดลบอก |
| M3 | **verdict (met / not_evidenced) อนุมานจากหลักฐานที่หาเจอ** ไม่เคยรับ verdict จากโมเดล |
| M4 | **state ของใบสมัคร เป็น projection ของ append-only event log** ไม่ใช่คอลัมน์ที่ใครก็เซ็ตได้ |
| M5 | **ทุกตัวเลขบน dashboard คือ query จากแถวที่ระบบเขียนไว้แล้ว** และบอกได้ว่ามาจากแถวไหน |
| careers | **สิ่งที่ผู้สมัครเห็นคือ judgment ที่เก็บไว้** ไม่ใช่การ join ประกาศงานฉบับปัจจุบันมาเล่าใหม่ |

หลักคิดร่วมกันคือ: *อะไรก็ตามที่เป็นคำกล่าวอ้างเกี่ยวกับ "ตัวคน" ต้องอนุมานจากสิ่งที่ตรวจสอบได้
ไม่ใช่ประกาศออกมาเฉย ๆ*

**ข้อยกเว้นที่จงใจมีข้อเดียว** — สถานะของ *ประกาศงาน* (`api/app/publication.py`) ไม่ใช่คำกล่าวอ้าง
เกี่ยวกับใคร มันคือข้อเท็จจริงเชิงบรรณาธิการเกี่ยวกับเอกสารที่บริษัทเขียนเอง จึงย้อนกลับได้และ
ไม่เก็บประวัติ (ข้อ 7.4)

---

## 3. Tech stack และเหตุผลที่เลือก

### Backend (`api/`)

| ของ | ใช้ทำอะไร |
|---|---|
| Python 3.11 + **FastAPI** | REST API, OpenAPI ที่ `/docs` (ตอนนี้ 34 path) |
| **SQLAlchemy 2 (async) + Alembic** | ORM + migration (ปัจจุบันถึง **`0013`**) |
| **PostgreSQL 17** (pgvector image) | DB ของ dev/prod — ใช้ JSONB |
| **SQLite** | fallback และ **test suite ทั้งชุดรันบนนี้** |
| **Redis + ARQ** | job queue สำหรับงานเบื้องหลัง |
| **MinIO / S3 หรือ local filesystem** | เก็บไฟล์ที่อัปโหลด |
| **pdfplumber / python-docx** | อ่าน PDF/DOCX พร้อม offset |
| **Tesseract** (ทางเลือก) | OCR หน้าที่เป็นภาพสแกน (ไทย + อังกฤษ) |
| **google-genai** (Gemini free tier) | LLM provider จริง |
| pytest / ruff / mypy strict | gate ทั้งหมดบังคับใน CI |

**โครงไดเรกทอรีของ `api/app/` เปลี่ยนไปแล้ว** — route ไม่ได้อยู่ที่ root ของ `app/` อีกต่อไป
เอกสารรุ่นก่อนหน้ายังอ้างที่อยู่เก่า

```
api/app/
├── api/
│   ├── deps.py              ← dependency ทั้งหมด: session, บัญชี, require_role, CSRF guard
│   └── routes/              ← 7 router
│       ├── auth.py          ← ลงทะเบียน/ล็อกอิน/refresh/logout/เปลี่ยนรหัส/export/ลบบัญชี
│       ├── resumes.py       ← อัปโหลด, สถานะ, SSE, ไฟล์ต้นฉบับ, geometry, retry
│       ├── jobs.py          ← ประกาศงาน + requirement + publication
│       ├── screenings.py    ← สั่งคัดกรอง, ranking, รายชื่อผู้สมัครที่คัดได้
│       ├── applications.py  ← สมัคร, state machine, **receipt ของผู้สมัคร**
│       ├── metrics.py       ← dashboard
│       └── careers.py       ← **route สาธารณะ ไม่ต้องมีบัญชี**
├── pipeline/                ← parse → extract → judge → evidence → rank → retrieve
├── services/                ← ตรรกะที่แตะ DB (resume, screening, application, privacy, token)
├── models/                  ← ตาราง
├── schemas/                 ← รูปข้อมูลของ pydantic (โมเดลคืนอะไร vs เราเก็บอะไร)
├── llm/                     ← seam ของ provider: fake (ค่าตั้งต้น) / gemini / anthropic (raise)
├── applications.py          ← pure: state machine ของใบสมัคร
├── publication.py           ← pure: state machine ของประกาศงาน
├── jobs.py                  ← งานเบื้องหลังทั้งหมด + retry policy
└── queue.py · worker.py · storage.py · security.py · cookies.py · db.py · config.py
```

### Frontend (`web/`)

Next.js 16 (App Router) + TypeScript + Tailwind + **vitest แบบไม่มี DOM** (จงใจ)

> `web/AGENTS.md` เตือนไว้ว่า Next เวอร์ชันนี้ **ไม่ใช่ Next ที่จำได้** — API และโครงไฟล์เปลี่ยน
> ให้อ่าน `node_modules/next/dist/docs/` ก่อนเขียนโค้ด

### Infra

Docker Compose: `postgres`, `redis`, `minio`, `createbucket` (one-shot), `migrate` (one-shot),
`api`, `worker`, `web`

- `api` กับ `worker` เป็น **image เดียวกัน คนละคำสั่ง** — เพราะ `worker.py` เป็นแค่ adapter บาง ๆ
  ของ `jobs.py` ถ้าแยก image dependency จะ drift กันโดยไม่มีใครรู้
- migration รันเป็น service ของตัวเอง ไม่ใช่ใน entrypoint ของ API — เพื่อไม่ให้ replica สองตัว
  แย่งกัน apply

### หลักการที่สองที่กำหนดรูปร่าง stack

> **ทุก dependency ต้องมี default ที่ไม่ต้องมี server**

```
git clone && pytest -q   →  ผ่านทันที  (ไม่ต้องมี API key, DB, Redis, Tesseract, ไม่เสียเงิน)
```

ทำได้เพราะสามอย่าง

1. **`fake` LLM provider** (`api/app/llm/fake.py`) — **ไม่ใช่ stub** มันอ่านเอกสารจริงแล้วยก quote
   จริงมา ทำให้ evidence verification ทำงานเหมือนของจริงเป๊ะ ๆ และมี `FAKE_MODE=hallucinating`
   ที่แกล้งกุ quote เพื่อทดสอบเส้นทาง dropped (ถือเป็น **load-bearing infrastructure**
   อ่านก่อนแตะ provider seam)
2. **`JSON_VARIANT`** ใน `models/base.py` — เรนเดอร์เป็น JSONB บน Postgres, JSON บน SQLite
3. **`QUEUE_BACKEND=inline`** — request ทำงานเองไม่ต้องมี Redis

> การเปลี่ยนแปลงที่ทำให้ test suite ต้องมี server = การเปลี่ยนแปลงที่ผิด
> ให้เพิ่มเป็น opt-in module แทน (เช่น `tests/test_postgres.py`)

---

## 4. สถาปัตยกรรมและการไหลของข้อมูล

```
                    ┌────────────────────────────────────────────┐
   ไม่มีบัญชี  ─────►│ Next.js  /  /careers  /careers/{id}         │
                    │          (shell สาธารณะ)                    │
   มีบัญชี   ─────►│          /me  /me/documents  /hire  /usage  │
                    └───────────────┬────────────────────────────┘
                                    │  REST (fetch, credentials: include) + SSE
                                    ▼
                    ┌────────────────────────────────────────────┐
                    │ FastAPI                                     │
                    │  · CORS + CSRF guard (เฉพาะ cookie write)   │
                    │  · get_current_candidate → require_role     │
                    └───┬──────────────┬──────────────┬───────────┘
                        │              │              │
                PostgreSQL          Redis        MinIO / filesystem
                  (rows)          (job queue)     (ไฟล์ต้นฉบับ)
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

1. `POST /resumes` — เช็ค `Content-Length`, นามสกุล และ **magic bytes `%PDF-`** *ก่อน* จะเก็บ
   หรือคิดเงินอะไรทั้งนั้น และต้องมี `consent=true` (ขาดไป = 422 จาก schema เลย ไม่มี default)
2. `resume_service.ingest_resume` แฮชไบต์ → ถ้าบัญชีนี้เคยอัปโหลดไฟล์เดิม จะได้ row เดิม
   ไม่ extract ซ้ำ → เขียน blob → insert row `status=pending` → **commit**
3. **แล้วค่อย enqueue** — ถ้า enqueue ก่อน commit, worker ที่เร็วจะหา row ไม่เจอ
4. ตอบ `pending` **เสมอ** ไม่ว่า queue backend เป็นอะไร (client contract เดียว ไม่ใช่หนึ่งอัน
   ต่อรูปแบบการ deploy)
5. `jobs.run_resume_job` เคลม row (`processing`, `attempts += 1`, `last_attempt_at`,
   `SELECT … FOR UPDATE`) แล้ว **commit การเคลม** เพื่อให้ delivery ซ้ำเห็นแล้วข้าม
6. `resume_service.process_resume` parse → เขียน `document_text` + page spans ลง row → extract
   → verify (ไม่ commit เอง; job เป็นเจ้าของ transaction)
7. สำเร็จ → `extracted`, reset `failed_attempts`, commit ทีเดียวทั้ง profile + usage log + status

### 4.2 ฝั่ง client ตามงานยังไง

- `GET /resumes/{id}/events` = **SSE stream** จนกว่า status จะนิ่ง (ไม่ใช่ `pending` และ
  ไม่ใช่ `processing`)
- ถ้า stream จบโดยยังไม่มีคำตอบ → fallback ไป **polling** `GET /resumes/{id}` ทุก 700 ms
  (`POLL_INTERVAL_MS`, ยอมแพ้ที่ `POLL_TIMEOUT_MS` = 120 วินาที)
- ฝั่ง client ใช้ **`fetch` ไม่ใช่ `EventSource`** เพราะ `EventSource` ตั้ง `Authorization`
  header ไม่ได้ → token จะต้องไปอยู่ใน query string → ไหลเข้า proxy log และ browser history
  ซึ่งผิดกฎ "ห้าม log ข้อมูลส่วนบุคคล" สิ่งที่ต้องแลกคือเราต้องแกะ SSE frame เองใน
  `web/lib/api.ts` (`readFrames`)
- ฝั่ง server SSE **re-read row ทุก ๆ ครึ่งวินาทีแล้ว emit เมื่อเปลี่ยน**
  (`sse_poll_seconds` ค่าตั้งต้น 0.5) ไม่ใช่ pub/sub —
  เพราะ pub/sub จะทำให้ Redis กลายเป็น critical path ของ API และพัง "no-server default"
  กลไกเปลี่ยนทีหลังได้โดย client ไม่รู้สึกอะไร

### 4.3 endpoint ทั้งหมด และใครเรียกได้

| Router | Endpoint | ใครเรียกได้ |
|---|---|---|
| **careers** | `GET /careers/postings` | **ทุกคน ไม่ต้องมีบัญชี** |
| | `GET /careers/postings/{id}` | **ทุกคน** (draft = 404) |
| **auth** | `POST /auth/register` · `/login` · `/refresh` · `/logout` | ทุกคน |
| | `POST /auth/change-password` | เจ้าของบัญชี (ล้างทุก session ทุกเครื่อง) |
| | `GET /auth/me` · `GET /auth/me/export` · `DELETE /auth/me` | เจ้าของบัญชี (PDPA) |
| **resumes** | `GET /resumes/consent` | ทุกคน — ข้อความยินยอมต้องแสดงก่อนมีบัญชี |
| | `POST /resumes` · `GET /resumes` | เจ้าของเอกสาร |
| | `GET /resumes/{id}` · `/file` · `/geometry` · `/events` | เจ้าของ **+ recruiter ที่มีคนสมัครงานตัวเองด้วยเอกสารนี้** |
| | `POST /resumes/{id}/retry` | เจ้าของเท่านั้น — replay ใช้เงิน |
| **jobs** | `POST /jobs` · `PATCH` · `DELETE` · requirement CRUD | recruiter (เจ้าของประกาศ) |
| | `GET /jobs` | ผู้ที่ล็อกอิน — **แต่คนละลิสต์ตาม role**: candidate เห็นเฉพาะ `published`, recruiter เห็นของตัวเองรวม draft |
| | `GET /jobs/{id}` | ผู้ที่ล็อกอิน — published อ่านได้ทุกคน, draft เป็น 404 (`_readable_job`) |
| | `POST /jobs/{id}/publication` | **admin เท่านั้นสำหรับการ publish** — owner ถอนลงเองได้ |
| **screenings** | `POST /jobs/{id}/screenings` | recruiter เจ้าของประกาศ — **202 งานใหม่ / 200 ผลเดิมยังใช้ได้** |
| | `GET /jobs/{id}/screenings` · `/ranking` · `/candidates` | recruiter เจ้าของประกาศ |
| | `GET /screenings/{id}` · `POST /screenings/{id}/retry` | recruiter เจ้าของประกาศ |
| **applications** | `POST /jobs/{id}/applications` | candidate (ประกาศต้อง published) |
| | `GET /me/applications` · `GET /applications/{id}` | ผู้สมัคร หรือเจ้าของประกาศ |
| | `POST /applications/{id}/transitions` | ตาม state machine — ดูข้อ 7.5 |
| | **`GET /applications/{id}/screening`** | **สองฝ่ายของใบสมัครนั้น** — receipt (ข้อ 7.6) |
| | `GET /applications/{id}/events` | สองฝ่ายของใบสมัครนั้น |
| **metrics** | `GET /metrics/usage` | ผู้ที่ล็อกอินทุกคน — **ไม่มี role gate** แต่ scope แถวใน WHERE |

---

## 5. หนึ่ง request เดินทางยังไง

หัวข้อนี้ตอบคำถาม "การส่งข้อมูลของเว็บทำงานยังไง" แบบไล่ทีละชั้นจริง ๆ

### 5.1 เส้นทางที่ต้องมีบัญชี — ตัวอย่าง `POST /jobs/{id}/screenings`

```
[1] ผู้ใช้กดปุ่มใน React
      └─ components/... เรียก api.createScreening(jobId, resumeId)

[2] web/lib/api.ts — fetch เดียวของทั้งแอป
      fetch(`${API_BASE}${path}`, { ...init, credentials: "include" })
      · credentials: "include" คือ "การยืนยันตัวตน" ทั้งหมด — ไม่มี token ในหน้าเว็บให้แนบ
      · ต้องเขียนทุกครั้งเพราะค่าตั้งต้นคือ same-origin และ API อยู่คนละ port
      · helper json() ตั้ง Content-Type: application/json ให้
        ── เคยลืมมาแล้ว ผลคือ **ทุก transition ตอบ 422** (บทเรียน M4 slice 5)

[3] เบราเซอร์แนบ cookie ให้เอง (httpOnly — สคริปต์อ่านไม่ได้)

[4] FastAPI: CORSMiddleware ตรวจ Origin

[5] deps.get_current_candidate
      ├─ _present_credential  → เอา token จาก Authorization ก่อน แล้วค่อยดู cookie
      │                         **bearer ชนะเมื่อส่งมาทั้งคู่** → curl ทุกคำสั่งใน RUNBOOK
      │                         ยังทำงานเหมือนเดิม
      ├─ ถ้า token มาจาก cookie → _refuse_cross_site_write  (CSRF, ข้อ 5.3)
      ├─ decode_token          → ลายเซ็นถูกไหม หมดอายุยัง ชนิดถูกไหม
      ├─ session.get(Candidate) → โหลดแถวบัญชี **ก่อน** ยอมรับ token
      └─ token_service.assert_live(session, claims, candidate)
              · อยู่ใน denylist ไหม (logout แล้วหรือยัง)
              · epoch ตรงกับแถวไหม (เปลี่ยนรหัสผ่านแล้วหรือยัง)

[6] require_role(Role.RECRUITER) → ไม่ผ่าน = **403**

[7] _owned_job(session, job_id, candidate) → ไม่ใช่ของคุณ = **404** (ไม่ใช่ 403)

[8] screening_service … → เขียน DB → commit → enqueue

[9] response_model=ScreeningOut → pydantic คัดว่าอะไรออกไปได้บ้าง

[10] กลับถึง React → setState → หน้าจอเปลี่ยน
```

**สองอย่างในนี้ที่พลาดง่ายที่สุด**

- **`decode_token` กับ `assert_live` ต้องเรียกคู่กันเสมอ** — verify อย่างเดียวคือรับ token ที่
  ถูก sign out ไปแล้ว และ `assert_live` **บังคับ** ให้ส่งแถวบัญชีเข้าไปด้วย (mypy ฟ้องถ้าไม่โหลด)
  เพื่อให้กฎ "เรียกคู่กัน" ยังเป็นสองอย่าง ไม่กลายเป็นสาม
- **403 คุม route, 404 คุม row** — 403 บน id หนึ่ง = ยืนยันว่า id นั้นมีอยู่จริง กลายเป็น
  oracle ให้ไล่เดาบัญชีคนอื่น `require_role` ใน `deps.py` เป็นที่เดียวที่ 403 ควรอยู่

### 5.2 เส้นทางที่ไม่ต้องมีบัญชีเลย

`GET /careers/postings` เป็น **route แรกในระบบนี้ที่ไม่ resolve `Candidate` เลย** ทุก route
ก่อนหน้านี้หาเจ้าของก่อนเสมอ ซึ่งถูกต้องตอนที่ทุกหน้าจอเป็นของใครสักคน แต่ careers board
ไม่เป็นของใคร — คนที่กำลังตัดสินใจว่าจะสมัครดีไหมยังไม่ได้ลงทะเบียน และการบังคับให้ลงทะเบียน
ก่อนอ่านประกาศคือรูปแบบที่โปรเจคนี้ตั้งใจจะเถียงด้วย

**read-only เป็นขอบเขต ไม่ใช่เฟส** — การสมัคร การอัปโหลด และทุกการเปลี่ยนสถานะยังอยู่หลัง
`CandidateDep` ทั้งหมด คนแปลกหน้าอ่านสิ่งที่บริษัทประกาศได้ และไม่ได้อะไรอย่างอื่นเลย

### 5.3 CSRF ตอบเฉพาะจุดที่ cookie เป็น credential

`_refuse_cross_site_write` ทำงานเมื่อ **(ก) token มาจาก cookie และ (ข) เป็น method ที่เขียนข้อมูล**
เท่านั้น ถ้า `Origin` ไม่อยู่ใน `CORS_ORIGINS` → **403**

- write ที่ auth ด้วย **bearer ไม่ถูกเช็ค** เพราะหน้าเว็บของคนอื่นตั้ง `Authorization` header
  ข้ามโดเมนไม่ได้อยู่แล้ว
- **`Origin` ที่หายไป = อนุญาต** และนี่คือส่วนที่จงใจ — เบราเซอร์แนบ `Origin` ทุก unsafe method
  ดังนั้นการไม่มีแปลว่าเป็น client ที่ไม่ใช่เบราเซอร์ (`curl`, สคริปต์, RUNBOOK) ซึ่งไม่ใช่ CSRF
- ปกติ `SameSite=lax` กันให้อยู่แล้ว guard นี้มีไว้สำหรับ `COOKIE_SAMESITE=none` ที่ deploy
  ข้ามโดเมนต้องใช้ — **คุณสมบัติความปลอดภัยที่หายไปเมื่อเปลี่ยน config ไม่นับว่ามี**

เป็นความละเอียดแบบเดียวกับ "role คุม route (403) / ownership คุม row (404)"

### 5.4 กับดัก same-site ที่เสียเวลามาแล้ว

cookie ไม่สนใจ port แต่สนใจ host ดังนั้น

| เปิดหน้าเว็บที่ | API ที่ | ผล |
|---|---|---|
| `localhost:3000` | `localhost:8000` | same-site → cookie ถูกส่ง → ใช้ได้ |
| `127.0.0.1:3000` | `localhost:8000` | **คนละ site → cookie ถูกกลืนเงียบ ๆ** |

อาการคือ **login สำเร็จ 200 แล้วทุกอย่างหลังจากนั้น 401** ทั้งที่ทั้งสอง origin อยู่ใน
`CORS_ORIGINS` และ request ถึง API จริง — งงที่สุดในบรรดาอาการทั้งหมด `establishSession` ใน
`web/lib/auth.ts` จึงยิง `GET /auth/me` ต่อทันทีหลัง login เพื่อจับกรณีนี้แล้วบอกสาเหตุตรง ๆ
(วัดในเบราเซอร์จริง ไม่ได้เดา)

---

## 6. เดินโค้ดทีละโมดูล (pipeline)

### 6.1 `pipeline/parse.py` — สัญญาเรื่อง offset

`ParsedDocument.text` คือ **coordinate space เดียว** ที่หลักฐานทุกชิ้นชี้เข้าไป

- NFC normalize + **ตัด `U+0000` ทิ้ง** ก่อนวัด page span — Postgres ไม่ยอมรับ NUL ในคอลัมน์
  text แต่ SQLite ยอม ทำให้ทั้ง suite ตาบอดมาก่อน (ดู `HANDOFF.md` §11)
- **OCR ถูกแทนที่เข้าไปใน page list *ก่อน* `_assemble` วัด span** — ทำให้หน้าที่กู้มาจากภาพมี
  offset ธรรมดาเหมือนหน้าอื่น ถ้าทำ OCR เป็น pass ที่สองหลังประกอบเอกสารแล้ว offset ทุกตัว
  หลังหน้านั้นจะเลื่อนหมด
- `document_text` **เก็บแบบ verbatim** ห้าม re-parse / re-normalize ของที่เก็บแล้ว เพราะจะทำให้
  citation ที่เคยแสดงต่อผู้ใช้ไปแล้วชี้ผิดที่

### 6.2 `pipeline/layout.py` — สองคอลัมน์

XY-cut แบบมีขอบเขต

- **ตัดแนวนอนก่อนแนวตั้ง** เพราะ header เต็มความกว้างจะพาดข้าม gutter ทำให้ column profile
  ทั้งหน้าหาอะไรไม่เจอเลยในเรซูเม่สองคอลัมน์จริง ๆ เกือบทุกใบ
- จัดลำดับใหม่ด้วยการ **crop เป็นภูมิภาคแล้วให้ pdfplumber ประกอบข้อความเอง** — ถ้าประกอบ
  บรรทัดจาก word box เองจะต้องตัดสินใจว่าเว้นวรรคตรงไหน ซึ่งภาษาไทยไม่มีเว้นวรรคระหว่างคำ
- **ถ้าไม่มั่นใจ → คืน `None` = เส้นทางโค้ดเดิมก่อน M2** ทำให้เอกสารคอลัมน์เดียว parse ออกมา
  **byte-identical** เป๊ะ (มี 4 guard ที่ผลิต `None` และ `tests/test_layout.py` pin ทีละอันแยกกัน)

### 6.3 `pipeline/evidence.py` ★ หัวใจ

อ่านคุ้มที่สุดในโปรเจค จับคู่ **3 ชั้น** จากเข้มไปหลวม

| Tier | วิธี | เหตุผล |
|---|---|---|
| 1 `exact` | หาตรงตัว | quote ดี ๆ ส่วนใหญ่ลงที่นี่ |
| 2 `whitespace_collapsed` | ยุบ whitespace run เหลือช่องเดียว | โมเดล reflow ข้อความที่ข้ามบรรทัดใน PDF |
| 3 `whitespace_stripped` | ลบ whitespace ทิ้งหมด | **ส่วนใหญ่ไว้กู้ภาษาไทย** ที่ PDF ชอบแทรกช่องว่างกลางคำ |

รายละเอียดที่ฉลาด

- `_IndexedText` เก็บ `offsets[i]` = ตำแหน่งใน**ต้นฉบับ**ที่ผลิตตัวอักษร `text[i]` → match ใน
  เวอร์ชันที่แปลงแล้ว แต่ map กลับไปยัง offset จริงได้
- `MIN_QUOTE_CHARS = 4` และ tier 3 ต้องยาว ≥ 8 — ยิ่งหลวมยิ่งต้องยาว ไม่งั้น `"go"` จะไปแมตช์
  ข้างใน `"django"`
- `occurrences > 1` → **`is_ambiguous`** รายงานว่ากำกวม ไม่เดา
- คืน **ข้อความจากต้นฉบับ** ไม่ใช่ที่โมเดลพิมพ์มา (`self._source[start:end]`)
- `match_kind` ถูกบันทึกไว้ — ถ้ารันหนึ่งเต็มไปด้วย match ชั้น 3 แปลว่า **parser มีปัญหา**
  ไม่ใช่ matcher มีปัญหา

### 6.4 `pipeline/extract.py` — re-ask loop

```python
for attempt in 1..max_attempts:
    ถามโมเดล                       # รอบ 2 ส่ง quote ที่ถูกปฏิเสธกลับไปด้วย
    verify ทุก field
    เก็บ candidate ที่ dropped น้อยที่สุด
    ถ้า dropped == 0 → หยุด
best.stats.attempts = len(usages)  # นับ "จำนวนครั้งที่เรียกโมเดลจริง" ไม่ใช่รอบที่ชนะ
```

จุดละเอียด: **`seniority` เป็น field ที่โมเดลอยากเดาที่สุด** ถ้าหา quote รองรับไม่ได้จะถูกลดเป็น
`unknown` แทนที่จะเก็บไว้แบบไม่มีหลักฐาน

### 6.5 `pipeline/judge.py` — verdict ต้องอนุมาน ห้ามรับ

```python
verdict = Verdict.MET if evidence else Verdict.NOT_EVIDENCED
# บรรทัดเดียวที่เป็นเหตุผลของทั้งมิลสโตน
```

- **ไม่มี `not_met` โดยเจตนา** — "การไม่มี" อ้างอิงไม่ได้ (ยกข้อความที่ไม่มีในเอกสารมาไม่ได้)
  และระบบแยกไม่ออกระหว่าง "ผู้สมัครไม่มีทักษะนี้" กับ "เรซูเม่ไม่ได้เขียนถึง" ซึ่งอันแรกเป็น
  คำกล่าวอ้างเกี่ยวกับตัวคน — บนหน้าจอจึงเขียนว่า *"Nothing in this resume could be quoted to
  show it. That is not the same as the candidate lacking it."*
- โมเดลอ้างถึง requirement ด้วย **เลขลำดับ (1-based)** ไม่ใช่ UUID — ถูกกว่าใน token และเลข
  นอกช่วงคือสิ่งที่ verifier จับได้ (UUID ที่เพี้ยนจับไม่ได้) → กลายเป็น
  `RejectReason.UNKNOWN_REQUIREMENT` นับรวมใน hallucination rate ส่วนเลขซ้ำ **merge** ไม่ทับกัน
- retry rule **ต่างจาก extract**: judging เก็บอันที่ `met` มากที่สุด ไม่ใช่ dropped น้อยที่สุด
  เพราะ prompt รอบสองบอกให้ "ตัดทิ้งไปเลยถ้าอ้างไม่ได้" → คำตอบว่างเปล่าจะได้ dropped = 0
  แล้วชนะ ทั้งที่ทิ้งหลักฐานจริงของรอบแรกไป
- รายการ requirement วางไว้ **นอก** `<resume>` block ใน prompt — ไม่ใช่เรื่องความสวยงาม:
  `fake.py` หาเอกสารจาก block นั้นพอดี ถ้าเอาไปไว้ข้างในโมเดลจะยก requirement มาเป็นหลักฐาน
  แล้ว verify ตกทุกอัน
- **judging ไม่เคยเห็น `must_have` หรือ `weight`** — สองอันนี้เดินทางไปกับ `RequirementSpec`
  และกลับมาบน `RequirementJudgment` โดยไม่ถูกแตะ เพื่อให้ ranking อ่าน "ข้อนี้มีหลักฐานไหม"
  เป็นคำถามเกี่ยวกับเอกสาร ส่วน "ข้อนี้สำคัญแค่ไหน" เป็นคำถามเกี่ยวกับตำแหน่งงาน

### 6.6 `pipeline/ranking.py` — ไม่เสีย model call เลย

```
score = ผลรวม weight ของข้อที่ met / ผลรวม weight ทั้งหมด
gate  = must_have ทุกข้อต้อง met  (ถ้าไม่มี must_have เลย = ผ่าน)
sort  = (ไม่ผ่าน gate ทีหลัง, score มาก→น้อย, met มาก→น้อย, screening_id)
```

สองกฎที่พลาดง่ายมาก

- **weight / must_have อ่านจาก job ปัจจุบัน ไม่ใช่จาก judgment ที่เก็บไว้** —
  `requirements_fingerprint` จงใจไม่รวมสองอันนี้ ดังนั้นแก้ weight แล้ว screening ยัง "current"
  อยู่ แต่ JSON ที่เก็บไว้ยังถือเลขเก่าตลอดกาล ถ้าอ่านจาก stored result การแก้ weight จะไม่มีผล
  อะไรเลยแบบเงียบ ๆ (mutation-test: ทำผิดแล้ว `test_ranking.py` ตก 5 เคส)
- **join ด้วยตำแหน่ง ไม่ใช่ id** เพราะ fingerprint ไม่รวม id ด้วย และถ้าความยาวไม่ตรง →
  `excluded: malformed` ไม่ใช่ join มั่ว

อื่น ๆ

- `screening_id` ท้าย sort key ทำให้ order เป็น **total order** — ไม่งั้นคนคะแนนเท่ากันจะสลับที่
  กันทุกครั้งที่ refresh
- must-have **นับรวมในคะแนนด้วย ไม่ใช่แค่เป็นด่านผ่าน/ไม่ผ่าน** — ในกลุ่มที่ผ่าน gate มันเป็นค่าคงที่
  ไม่เปลี่ยนลำดับ แต่ในกลุ่มที่ไม่ผ่านมันคือสิ่งที่แยก "ขาดหนึ่งข้อ" ออกจาก "ขาดทุกข้อ"
- ผลพลอยได้ที่สำคัญ: **recruiter ลาก weight แล้วอันดับเรียงใหม่ทันทีโดยไม่เสียเงินสักบาท**
  (หน้าจอเขียนไว้ตรง ๆ ว่า *"Costs one query — adjusting a weight reorders this without
  re-judging anyone"*)
- screening ที่ stale ถูก **excluded พร้อมเหตุผล** ไม่ใช่รันใหม่อัตโนมัติ — คิดแบบเดียวกับ
  `dropped` คือไม่เดาแทน แต่บอกว่าทำไมถึงไม่นับ

### 6.7 `pipeline/retrieval.py` — โมดูลเดียวที่อนุญาตให้ "ประมาณ" ได้

เพราะมัน **ไม่ได้กล่าวอ้างอะไรเกี่ยวกับใครเลย** — แค่เรียงว่าเรซูเม่ไหนคุ้มที่จะจ่ายเงินให้โมเดล
ตัดสิน ลบทิ้งทั้งโมดูลก็ไม่มี verdict ไหนเปลี่ยน

- **คืนทุกเอกสารเสมอ เรียงลำดับ ไม่เคยกรองทิ้ง** — retriever ที่กรองจะคัดคนออกก่อนที่จะมีใคร
  ได้ดู และไม่มีใครเห็นว่ามันเกิดขึ้น (mutation-test: กรอง 0 คะแนนออก → ตก 9 เคส)
- **ภาษาไทย tokenize ด้วย character n-gram (n=3), ละตินด้วยคำ** — นี่คือ *การวัด* ไม่ใช่รสนิยม:
  `resume_th.pdf` มี run ยาว 31 ตัวอักษรติดกัน `ดูแลระบบกระทบยอดการชำระเงินด้วย` และคำจริงอย่าง
  `ชำระเงิน` กับ `วิศวกรรม` อยู่ **ข้างใน** ซึ่ง whitespace tokenizer หาไม่เจอทั้งคู่
  (n=2 ชนกันข้ามคำ, n=4 เริ่มพลาดคำสั้น)
- **ไม่ match กับ `job.description`** เด็ดขาด — จะเป็นการเอา free text กลับมาให้คะแนนทางประตูหลัง
  พิสูจน์สดแล้ว: เรซูเม่ที่มี *ทุกคำ* ใน description ยังได้ 0.0
- ยังไม่มีการวัดคุณภาพของลำดับ และนั่นจงใจ — เดิมเป็น M6 แต่ **review แล้วปิดโดยไม่สร้าง**
  (2026-08-16) ดูข้อ 12

---

## 7. เลเยอร์ธุรกิจ

### 7.1 Jobs & Requirements

requirement เป็น **row** มี `kind` (skill / experience / education / language / other),
`label`, `detail`, `must_have`, `weight` — สูงสุด 30 ข้อต่อประกาศ

- พิมพ์เข้ามาผ่าน CRUD **ไม่ใช่ให้โมเดลแตกออกมาจาก job description** — เพราะ requirement คือ
  *input* ไม่ใช่ *claim* ไม่มีอะไรให้ guardrail ตรวจ และการเอาโมเดลมาวางตรงนี้คือการเพิ่มจุดพัง
  โดยไม่เพิ่มการรับประกันอะไรเลย
- `description` เก็บไว้เป็นบริบทและ audit แต่ **ไม่ใช่สิ่งที่ใครถูกตัดสินด้วย** — ถ้าตัดสินจาก
  free text จะบอกไม่ได้ว่า verdict ตอบส่วนไหนของประกาศ
- route ของ requirement **nest อยู่ใต้ `/jobs/{id}`** เพื่อให้เรื่อง ownership จบในที่เดียว

### 7.2 Screening

`POST /jobs/{id}/screenings` → **202 เมื่อ queue งานใหม่ / 200 เมื่อผลเดิมตอบได้อยู่แล้ว**

ตัวตัดสินคือ `requirements_fingerprint` = hash ของ **(kind, label, detail) และลำดับ** เท่านั้น

- ไม่รวม `weight` / `must_have` — ไม่เคยไปถึง prompt รวมแล้วจะเผาเงินได้คำตอบเดิม
- ไม่รวม id — ลบ requirement แล้วพิมพ์อันเดิมกลับมา = คำถามเดิม
- `prompt_version` เก็บ **ข้าง ๆ** hash ไม่ยุบรวม เพื่อให้แยกออกว่า "stale เพราะ requirement
  เปลี่ยน" กับ "stale เพราะ prompt เปลี่ยน"
- **screening ที่ complete แล้วรันซ้ำได้ แต่ resume ที่ extract แล้วรันซ้ำไม่ได้** —
  requirement เปลี่ยนได้ แต่เอกสารเปลี่ยนไม่ได้ การ extract ซ้ำคือจ่ายเงินรอบสองเพื่อ profile
  ที่มีอยู่แล้ว
- ค่าใช้จ่ายของ judging ลงบัญชีที่ **screening ไม่ใช่ resume** — `LLMCallLog` มีทั้ง `resume_id`
  และ `screening_id` และเซ็ตอันเดียว ถ้าแขวน judging ไว้กับ resume ตัวเลข "เอกสารนี้ extract
  ไปเท่าไหร่" จะเพี้ยน

### 7.3 Careers — ฝั่งอ่านสาธารณะ (2026-08-22)

`api/app/api/routes/careers.py` — สองเส้น ไม่มี auth เลย

**`PostingOut` แคบกว่า `JobOut` และความต่างนั้นคือสาระ** `JobOut` คือสิ่งที่ระบบคืนให้คนที่
เขียนประกาศ ส่วนนี่คือ "ประกาศนี้คืออะไรในสายตาคนอื่นทั้งโลก"

| ตัดอะไรออก | เพราะ |
|---|---|
| `owner_id` | เป็น account id บอกว่าพนักงานคนไหนพิมพ์ประกาศ — เผยแพร่สู่อินเทอร์เน็ตโดยไม่เป็นประโยชน์กับผู้อ่านเลย |
| `weight` | เป็นตัวปรับของ ranking ไม่เคยไปถึง judge และการเผยแพร่มันคือการเผยแพร่วิธีโกงการคัดกรอง |
| — แต่ `must_have` **อยู่ต่อ** | สิ่งที่คุณจะถูกวัดไม่ใช่ความลับ การซ่อนไว้แล้วคัดด้วยมันคือพฤติกรรม ATS ที่โปรเจคนี้ปฏิเสธ |
| `status` | ทุกอย่างที่อ่านได้ตรงนี้เป็น published อยู่แล้วโดยโครงสร้าง — field ที่ค่าไม่เคยเปลี่ยนจะล่อให้ client เอาไปเขียนเงื่อนไข และ client ที่เอาเรื่องความปลอดภัยไปตัดสินเองคือ client ที่พลาดได้ |
| requirement `id` / `position` | รายการส่งมาเรียงตามลำดับอยู่แล้ว การใส่ id ไปด้วยจะเปิดช่องให้เอารายการสาธารณะไปจับคู่กับรายการส่วนตัว |

สองรายละเอียดที่วัดมาแล้ว

- เรียงด้วย `published_at` **ไม่ใช่ `updated_at`** — แก้ประกาศที่ยังใช้อยู่ต้องไม่ดันมันกลับ
  ขึ้นหัวกระดาน ซึ่งเป็นเหตุผลทั้งหมดที่ migration `0013` เก็บคอลัมน์แยก
- ไม่มีปัญหาการเรียง NULL และนั่นเป็นเพราะโครงสร้าง ไม่ใช่โชค: `0013` backfill `published_at`
  จาก `created_at` และ route ที่ publish ก็เซ็ตให้ — แถว `PUBLISHED` ที่ไม่มีค่านี้จึงไม่มีอยู่
  (สำคัญเพราะ SQLite กับ Postgres เรียง NULL คนละทางใต้ `DESC` และ suite นี้รันบนตัวที่ deploy
  ไม่ได้ใช้)
- predicate คือ `publication.is_public` ตัวเดียวกับที่ `_readable_job` ใช้ — **predicate
  ความปลอดภัยสามชุด = สามโอกาสที่จะพลาดสักครั้ง**

### 7.4 Publication lifecycle — state machine คนละชนิด (migration `0013`)

`JobStatus` = `draft` / `published` / `closed` และ `api/app/publication.py` เป็นที่เดียวที่
ตัดสินว่าใครย้ายไปไหนได้

> **นี่คือ state machine คนละชนิดกับ `applications.py` โดยเจตนา และความต่างนั้นแหละคือประเด็น**
> สถานะของใบสมัครเป็น *คำกล่าวอ้างเกี่ยวกับคน* จึงอนุมานจาก append-only log และย้อนไม่ได้
> ส่วนสถานะของประกาศเป็น **ข้อเท็จจริงเชิงบรรณาธิการ** เกี่ยวกับเอกสารที่นายจ้างเขียนเอง
> มันไม่ได้พูดถึงใคร และการถอนประกาศลงแล้วเอากลับขึ้นก็เป็นเรื่องปกติ → **ย้อนกลับได้
> และไม่เก็บประวัติ** ถ้าเก็บ log ว่า "published, unpublished, published" ก็จะกลายเป็นพิธีกรรม
> เปล่า ๆ และทำให้กฎ append-only ดูเหมือนเป็นสไตล์การเขียนโค้ด ทั้งที่จริงมันเป็นคำตอบเฉพาะเรื่อง
> คำกล่าวอ้างเกี่ยวกับตัวคนเท่านั้น

ตารางสิทธิ์ (อ่านเป็นตาราง ไม่ใช่โซ่ — "ไม่มีลำดับ" คือความหมายของคำว่าย้อนกลับได้)

| จาก | ADMIN ไปได้ | OWNER ไปได้ |
|---|---|---|
| `draft` | `published`, `closed` | `closed` เท่านั้น — **การละเว้น `published` ตรงนี้คือทั้ง slice** |
| `published` | `draft`, `closed` | `draft`, `closed` (ถอนของตัวเองลงได้ ไม่ต้องขอใคร) |
| `closed` | `draft`, `published` | `draft` |

- **มีแต่ admin ที่ publish ได้** เดิมเขียนไว้ตอนที่ `SelfServiceRole` ยังให้ใครก็สมัครเป็น
  recruiter ได้ (recruiter ที่ publish ได้ = คนแปลกหน้าที่ publish ได้) รูนั้นถูกอุดที่ต้นทาง
  ไปแล้ว และ **กฎนี้ยังอยู่** ด้วยเหตุผลที่ไม่เคยขึ้นกับรูนั้น: การเอาประกาศขึ้นเว็บใต้ชื่อ
  บริษัทเป็นการตัดสินใจในนามบริษัท ไม่ใช่งานของคนเขียนประกาศ — recruiter คนหนึ่งเขียนประกาศ
  ไม่เท่ากับบริษัทเป็นคนพูด
- **`decide` คืน `Refused(why)` ไม่ใช่เงียบแล้วไม่ทำอะไร** — state machine ที่เมินคำสั่งที่มันไม่ชอบ
  จะทำให้แยกไม่ออกว่าที่ไม่เกิดอะไรขึ้นนั้น เป็นเพราะระบบตัดสินใจ หรือเป็นเพราะมันพัง
- `current is target` **ไม่ใช่ error และไม่ใช่ no-op ที่โกหก** — คืนค่าเดิมให้ caller ตอบ 200
  แทน 409 คิดแบบเดียวกับตอนอัปโหลดไฟล์ซ้ำแล้วได้ 200
- **draft ปิดสามประตู** — อ่านเดี่ยว 404, ไม่อยู่ในลิสต์ค้นหา, สมัครไม่ได้ — เพราะมันเป็น
  code path คนละเส้น ปิดเส้นเดียวไม่พอ
- migration backfill ประกาศเดิมเป็น **`PUBLISHED` ไม่ใช่ค่า default ของคอลัมน์** เพราะนั่นคือ
  สถานะที่มันมีอยู่จริง ๆ อยู่แล้ว และ `draft` จะถอนประกาศที่ยังเปิดรับอยู่ออกกลางคัน

### 7.5 Applications + state machine

```
applied → screening → screened → shortlisted / rejected / withdrawn
```

- **`application_events` คือของจริง, `Application.state` เป็นแค่ projection** — replay log
  ต้องได้ค่าเดิมเสมอ
- `services/application_service.py` เป็น **ผู้เขียนเพียงคนเดียว** ของทั้งสองอย่าง และไม่เคย
  เขียน state โดยไม่เขียน event ที่ทำให้เกิด — การบังคับให้เขียนคู่กันนี่แหละคือตัวดีไซน์
- กฎที่หล่นออกมาเอง (บังคับใน `app/applications.py` ซึ่งเป็น pure function)
  - **shortlist ได้จาก `screened` เท่านั้น และต้องบันทึกด้วยว่าอิง screening ไหน** →
    *"จะ shortlist คนที่ยังไม่ถูกคัดกรองไม่ได้ เพราะการตัดสินใจนั้นจะไม่มีหลักฐานอะไรรองรับเลย"*
  - **reject ต้องมีเหตุผล**
  - ท่าที่ผิดกฎตอบ **409 พร้อมเหตุผล** ไม่ใช่เงียบ ๆ ไม่ทำอะไร
- **เรียงด้วย `position` ที่เก็บไว้ ไม่ใช่ `created_at`** — SQLite timestamp ละเอียดแค่ 1 วินาที
  journey ที่ใช้เวลาไม่กี่ ms จะได้เวลาเท่ากันหมด แล้ว tiebreak ไปตกที่ **UUID สุ่ม**
- `Actor` ถือ **account id** ไม่ใช่อนุมานเอา — เวอร์ชันแรกอนุมานจากผู้ย้าย ทำให้ **การตัดสินใจ
  ของ recruiter ทุกครั้งถูกบันทึกว่า "ระบบทำ"** เทสต์ที่ควรจับได้ดันเช็คแค่ `actor_role`
  (ซึ่งถูก) ไม่ได้เช็ค `actor_id` → เจอตอนอ่าน audit log จริง `actor_id` เป็น null ได้เฉพาะ
  กับระบบเท่านั้น
- **recruiter อ่านเรซูเม่ของคนที่สมัครงานตัวเองได้ แต่สั่งการไม่ได้** — `_owned_resume` ขยาย
  เฉพาะการอ่าน ส่วน `POST /retry` ยังต้องเป็นเจ้าของ เพราะการ replay ใช้เงินและเป็นของคนที่
  อัปโหลด "การได้ดู CV ไม่เท่ากับการได้รับปุ่มควบคุมมันมา"

### 7.6 ★ Screening Receipt — route ที่โปรเจคนี้เกิดมาเพื่อมัน

`GET /applications/{id}/screening` (2026-08-22)

`README.md` ระบุ pain point ว่าผู้สมัครถูกระบบคัดกรองปฏิเสธโดยไม่มีคำอธิบาย — และทุกหน้าจอ
ก่อนหน้านี้รับใช้ฝั่งที่เป็นคนปฏิเสธทั้งหมด route นี้คือครึ่งที่ยังขาดไป

**การเข้าถึง** — ผ่าน `_visible_application` ดังนั้นทั้งสองฝ่ายของใบสมัครได้ และไม่มีใครอื่นได้

- **404 ไม่ใช่ 403** ทั้งกับคนแปลกหน้า และกับใบสมัครที่ยังไม่ถูกคัดกรอง — 403 กับอย่างใด
  อย่างหนึ่งจะยืนยันว่า id นั้นมีอยู่ ซึ่งเป็นสิ่งที่ `_owned_job` และ `_owned_resume`
  ตอบ 404 เพื่อหลีกเลี่ยง และ "ถูกคัดกรองแล้วแต่คุณดูไม่ได้" ไม่ใช่สถานะที่ระบบนี้มี
- หา screening ผ่าน `application_service.completed_screening_id` ซึ่งเป็น lookup เดียวกับที่
  shortlist ยืนอยู่ — **receipt มีอยู่พอดีตอนที่นายจ้างมีของที่สมบูรณ์พอจะตัดสินใจ**
- screening ที่ complete แล้วแต่ผลที่เก็บไว้ validate ไม่ผ่าน → 404 เช่นกัน เพราะการสร้าง
  receipt ว่างเปล่าจะอ่านได้ว่า "ไม่พบอะไรในเอกสารของคุณ" ซึ่งเป็นคำกล่าวอ้างเกี่ยวกับตัวคน
  แทนที่จะเป็นเรื่องแถวที่พัง

**`ReceiptOut` แคบกว่า `ScreeningDetail` โดยเจตนา**

| ไม่มีใน receipt | เพราะ |
|---|---|
| `attempts`, `cost_usd`, `failure_reason`, `requirements_hash` | เป็นข้อเท็จจริงเรื่อง *การรัน* screening — เป็นของคนที่จ่ายเงิน |
| **score / rank / weight** | คะแนนมีความหมายก็ต่อเมื่อเทียบกับคนอื่น ถ้าโชว์ให้คนคนเดียวดู ก็จะเจอคำถามว่า "ทำไมได้ 62%" ซึ่งระบบนี้ตอบตรง ๆ ไม่ได้ |

สิ่งที่**มี**: `label`, `must_have`, `verdict`, `evidence[]` (quote + char range + page +
match kind), `dropped[]`, `document_text`, `state`, `reason`, `screened_at`,
`posting_changed_since`

- **ทุก field อ่านจาก judgment ที่เก็บไว้ ไม่เคยอ่านจากประกาศฉบับปัจจุบัน** — requirement
  ของประกาศแก้ทีหลังได้ ถ้าไป join เอา label ล่าสุดมาแสดง ก็เท่ากับแอบเปลี่ยนป้ายชื่อของ verdict
  ที่เคยแสดงให้เจ้าตัวดูไปแล้ว receipt จะกลายเป็นคำตัดสินเกี่ยวกับคนคนหนึ่ง ที่เขียนด้วยถ้อยคำ
  ซึ่งไม่เคยถูกใช้ตัดสินเขาเลย
- `posting_changed_since` **บอกออกมาตรง ๆ** แทนที่จะซ่อนหรือแอบแก้ให้ — verdict ข้างบนยังเป็น
  สิ่งที่ระบบอ่านจริง ๆ ในตอนนั้น ส่วนที่เปลี่ยนคือประกาศตอนนี้ขออะไร ผู้สมัครที่กำลังเทียบ
  สองอย่างนี้ควรได้รู้ว่าอันไหนเป็นอันไหน
- `reason` อ่านจาก event ล่าสุด ซึ่งคือ move ที่ผลิต state ปัจจุบัน — การที่
  `Application.state` เป็น projection ของ log คือสิ่งที่ทำให้สองอย่างนี้เป็นอันเดียวกัน

**และมันแทบไม่มีต้นทุนเลย** — ไม่ต้องทำ migration ไม่ต้องเพิ่ม schema ไม่เสีย model call
`ScreeningDetail` เป็น receipt อยู่แล้ว และ `_owned_screening` คือเหตุผลเดียวที่มันเคยเป็น
ของเจ้าของประกาศเท่านั้น เอา payload เดิมมาวางหลัง `_visible_application` ก็จบทั้ง slice —
เป็นครั้งที่สามในโปรเจคนี้ที่ส่วนที่ผู้ใช้มองเห็นทำได้ถูกมาก เพราะ slice ก่อนหน้าเก็บข้อมูล
ที่ถูกต้องไว้ให้แล้ว

### 7.7 RBAC — **403 กับ 404 ห้ามปนกัน**

| กรณี | ตอบ | เหตุผล |
|---|---|---|
| role ผิดสำหรับ route | **403** | route อยู่ใน `/docs` อยู่แล้ว บอกไปไม่รั่วอะไร |
| ไม่ใช่ทรัพยากรของคุณ | **404** | 403 บน id หนึ่ง = ยืนยันว่า id นั้นมีอยู่จริง → เป็น oracle ให้เดา account |

- `require_role` ใน `api/app/api/deps.py` เป็นที่เดียวที่ 403 ควรอยู่ และรันเป็น dependency
  **ก่อน** จะอ่าน row ใด ๆ เพื่อให้ candidate ที่ยิง id จริงกับที่ยิง id มั่ว ได้คำตอบเหมือนกันเป๊ะ
  (mutation-test: ตอบ 403 ตรงจุด ownership → ตก 7 เคส)
- `require_role` ให้สิทธิ์ `ADMIN` โดยปริยาย — role system ที่ทุก route ต้องจำว่าต้องใส่
  superuser เอง จะมีรูตั้งแต่ครั้งแรกที่มีคนลืม
- **role อ่านจาก row ไม่เคยฝังใน token** — ถ้าฝังใน JWT การถอดสิทธิ์จะไม่มีผลจนกว่า access
  token จะหมดอายุ คือช่วงเวลาที่สิทธิ์ซึ่งถูกถอดไปแล้วยังใช้ได้อยู่

#### `recruiter` สมัครเองไม่ได้แล้ว (2026-08-22) — ข้อที่ต้องแก้จากเอกสารรุ่นก่อน

`SelfServiceRole` เหลือสมาชิกเดียวคือ `candidate`

เดิมนี่ถูกบันทึกใน `README.md` ว่าเป็น **ข้อจำกัดที่โปรเจคนี้ตอบไม่ได้** ด้วยเหตุผลว่า
การยืนยันว่าใครสักคนเป็นตัวแทนบริษัทที่เขาอ้างจริง ๆ เป็นปัญหาเรื่อง identity เหตุผลนั้น
ใช้ได้ตอนที่ HireLens มีรูปร่างเป็นซอฟต์แวร์ที่นายจ้างซื้อไปใช้ **แต่ใช้ไม่ได้แล้ว**:
เว็บนี้มีนายจ้าง **รายเดียว** คือ HireLens เอง จึงไม่มีบริษัทให้ยืนยันใครกับใคร คนแปลกหน้า
ที่อ้างว่าเป็น `recruiter` ไม่เคยเป็น "นายจ้างที่ยังไม่ได้ยืนยัน" — เขาเป็นคนแปลกหน้าที่อยู่
ข้างในฝั่งจ้างงานของบริษัทนี้ การตัดสินใจเรื่อง careers site จึง **ทำให้ปัญหานี้หายไปเอง**
ไม่ใช่แก้มัน

- `recruiter` และ `admin` ถูกให้นอกระบบ (ตอนนี้คือคำสั่ง SQL — `tests/conftest.py::set_role`
  คือคำสั่งนั้น และจงใจไม่ทำเป็น endpoint)
- **เหลือสมาชิกเดียวยังดีกว่าตัด field ทิ้ง** — ถ้า schema ไม่ประกาศ field `role` ไว้เลย
  ค่าที่ส่งมาจะถูก *เมิน* เฉย ๆ ดังนั้น `{"role": "recruiter"}` จะสร้าง candidate เงียบ ๆ
  แล้วตอบ 201 การขอ role ที่ตัวเองไม่มีสิทธิ์ควรถูกปฏิเสธออกมาดัง ๆ และ 422 คือการปฏิเสธนั้น
- ฝั่ง web ก็ตัดพารามิเตอร์ทิ้ง ไม่ได้ใส่ default — *"พารามิเตอร์ที่ไม่มีใครเปลี่ยนค่าได้
  คือการตัดสินใจที่หน้าตาเหมือนตัวเลือก"*

- ข้อยกเว้นเดิมยังอยู่: **job posting อ่านได้สาธารณะ** เพราะมันคือประกาศรับสมัคร แต่ทุก write
  และทุกอย่างที่ posting ผลิตออกมา (ranking, screening, รายชื่อผู้สมัคร) ยังคง 404 ตามเดิม

### 7.8 PDPA

- **consent ไม่มี default** — `POST /resumes` ขาดไป = 422 จาก schema ก่อนที่จะเก็บ byte เดียว
  หรือเรียกโมเดล และเก็บ `consent_version` คู่กับ `consented_at` เพราะ "เขายินยอม" กับ
  "เขายินยอมกับ*ถ้อยคำนี้*" คือคนละคำกล่าวอ้าง `GET /resumes/consent` เสิร์ฟข้อความให้ client
  แสดง จะได้ไม่แต่งเอง
- `GET /auth/me/export` — คืน **ของจริง** รวม `document_text` และ profile ที่ verify แล้ว
  ถ้าคืนแค่สรุป สิทธิ์ในการขอสำเนาก็เป็นแค่ของประดับ
- `DELETE /auth/me` — **ลบไฟล์ก่อน แล้วค่อยลบ row และถ้าไฟล์ลบไม่ได้ ยกเลิกทั้งหมด** สลับลำดับ
  = row หายแต่ object ค้างใน bucket โดยไม่มีอะไรชี้ถึงมัน → หาไม่เจอ = ลบไม่ได้ตลอดกาล ส่วน
  "row ที่ไฟล์หาย" เป็นสถานะที่ pipeline จัดการได้อยู่แล้ว
- **`services/privacy_service.py` คือที่ที่จุดยืนเรื่อง receipt ถูกเขียนไว้ก่อนแล้ว** —
  verdict ที่พูดถึงคุณเป็นของคุณ มัน export ได้มาตั้งแต่ M4 เพียงแต่ยังไม่มีหน้าจอให้ดู

---

## 8. งานเบื้องหลังและ retry policy

`api/app/jobs.py` เป็นส่วนที่ใหม่และซับซ้อนที่สุด

### Status ของ resume

| Status | ความหมาย |
|---|---|
| `pending` | อยู่ในคิว หรือกำลังรอ backoff |
| `processing` | worker เคลมไปแล้ว ค้างเกิน `JOB_VISIBILITY_TIMEOUT_SECONDS` (900) แปลว่า worker ตาย |
| `parsed` | เหลือไว้เพื่อ row เก่าก่อน M2 เท่านั้น ไม่ใช่สถานะพักอีกต่อไป |
| `extracted` | มี profile ที่ verify แล้ว — terminal และปฏิเสธ retry |
| `failed` | **เอกสารนี้ประมวลผลไม่ได้** — ไฟล์เสีย/ว่าง/ไม่มี key/สแกนที่ OCR ปิดอยู่ retry ไม่ช่วย *เว้นแต่เปลี่ยน config* |
| `dead_lettered` | **ความล้มเหลวชั่วคราวใช้โควตา retry หมด** คุ้มที่จะเล่นซ้ำ |

การแยก `failed` / `dead_lettered` คือหัวใจของ M2 #2 — status เดียวพูดพร้อมกันไม่ได้ว่า
"หยุดถามได้แล้ว" กับ "ลองใหม่ทีหลังนะ"

### นโยบาย

- `is_retryable` เป็น **whitelist ของ error ที่ถาวร** (`ParseError`, `ObjectNotFoundError`,
  `LLMConfigError`) ที่เหลือทั้งหมดรวมถึง exception ที่ไม่รู้จักนับเป็นชั่วคราว ทิศทางนี้จงใจ:
  ความล้มเหลวที่ไม่คุ้นเคยมักเป็นอาการชั่วคราวมากกว่าข้อเท็จจริงเกี่ยวกับเอกสาร และ
  **retry ผิดเสียแค่วินาที แต่ยอมแพ้ผิดคือเสียงานทั้งชิ้น**
- backoff = `5s → 10s → 20s` สูงสุด 3 ครั้งติด แล้ว dead-letter (`arq` ตั้ง
  `max_tries = job_max_attempts + 2` เพื่อไม่ให้มันยอมแพ้ก่อน — การยอมแพ้เป็นการตัดสินใจของ
  job และถูกเขียนลงบน row)
- `decide_retry` เป็น **pure function** คืน `PERMANENT` / `RETRY` / `EXHAUSTED` ไม่คืน status
  ทำให้ resume กับ screening ใช้ policy ร่วมกันได้โดยไม่ต้องใช้ enum ร่วมกัน (screening ไม่มี
  วันเป็น `parsed` หรือ `extracted`) และเทสต์ได้โดยไม่ต้องมี Redis
- job **คืน `JobOutcome` ไม่ raise `Retry` ของ arq** → `jobs.py` ไม่รู้จัก arq เลย มีแต่
  `worker.py` ที่รู้
- **สอง counter**: `failed_attempts` = งบ retry (รีเซ็ตเมื่อสำเร็จหรือ retry มือ),
  `attempts` = ยอดจริงไม่เคยรีเซ็ต และเป็นตัวทำให้ job id ไม่ซ้ำ — arq ปฏิเสธ job id ที่เพิ่งเห็น
  ดังนั้น replay ที่ใช้ id เดิมจะถูกทิ้งเงียบ ๆ

### Reclaim — งานที่ worker ตายกลางทาง

งานที่ *fail* จัดการได้ด้วย retry แต่งานที่ **process ดับไปเฉย ๆ** (ไฟดับ, OOM, `docker kill`)
ไม่เคยได้ *fail* — row ค้างที่ `processing` ที่ซึ่งทุกทางออกถูกปิด: delivery ซ้ำก็ข้าม,
`POST /retry` ตอบ 409, อัปโหลดไฟล์เดิมก็ dedupe มาลงที่ row เดิม

`jobs.reclaim_stalled` เป็น arq cron ทุกนาที (และตอน startup) กวาด row ที่ค้างเกิน timeout
สามอย่างที่จงใจ

- **ใช้ `decide_retry` ซ้ำ ไม่ใช่รีเซ็ต status** — การ reclaim นับเข้า `failed_attempts` ด้วย
  ทำให้เอกสารที่ฆ่า worker ทุกครั้ง dead-letter ในที่สุด แทนที่จะวนลูป reap → requeue → die
  ตลอดกาล (mutation-test: รีเซ็ต status เฉย ๆ → ตก 3 เคส)
- **การ list กับการ reclaim แยกเป็นคนละฟังก์ชัน** เพราะ `_record_failure` commit ซึ่งปล่อย lock
  ทิ้ง → รายการที่ list มาเชื่อไม่ได้ ต้องอ่าน row ใหม่ `with_for_update` แล้วทดสอบเงื่อนไขซ้ำ
- **row ที่ `processing` แต่ไม่มี `last_attempt_at` นับว่า stalled** เพราะการเคลมเขียนทั้ง
  สองอย่างใน commit เดียว การรวมกันแบบนั้นจึงเป็นไปไม่ได้ถ้ามีอะไรกำลังรันอยู่

ครึ่งที่ทำด้วยมือ: `POST /resumes/{id}/retry` และ `POST /screenings/{id}/retry` รับ row ที่ค้าง
เกิน timeout ด้วย และนี่คือ **ครึ่งเดียวที่มีอยู่ภายใต้ `QUEUE_BACKEND=inline`** เพราะไม่มี
process ให้ตั้ง cron

### `InlineQueue` ทำอะไรไม่ได้

เลื่อนงานไม่ได้ และการนอนรอ backoff จะค้าง request ทิ้งไว้ทั้งนั้น มันจึง **ไม่ retry เลย** —
ความล้มเหลวชั่วคราวทิ้ง resume ไว้ที่ `pending` พร้อมเหตุผล แล้วอัปโหลดไฟล์เดิมซ้ำจะหยิบมันขึ้น
มาใหม่ และมันไม่รัน reaper ด้วยเหตุผลเดียวกัน นี่เป็นคุณสมบัติของการรันโดยไม่มีคิว ไม่ใช่บั๊ก

---

## 9. Frontend — route และการส่งข้อมูล

หัวข้อนี้พูดถึง **โครง route และข้อมูลไหลยังไง** เรื่องสีและการตกแต่งอยู่ใน `docs/DESIGN.md`

### 9.1 route map ปัจจุบัน

```
web/app/
├── page.tsx                  /                   หน้าแรกของบริษัท (สาธารณะ, ไทย)
├── careers/page.tsx          /careers            กระดานประกาศงาน (สาธารณะ)
├── careers/[id]/page.tsx     /careers/{id}       ประกาศหนึ่งใบ + requirement (สาธารณะ)
├── me/page.tsx               /me                 ใบสมัครของฉัน + **receipt**
├── me/documents/page.tsx     /me/documents       อัปโหลดเอกสาร + ผลที่ verify แล้ว
├── hire/page.tsx             /hire               หลังบ้าน: รายการประกาศ + สร้างใหม่
├── hire/jobs/[id]/page.tsx   /hire/jobs/{id}     requirement + คัดกรอง + ranking + verdict
└── usage/page.tsx            /usage              dashboard การใช้งานและคุณภาพ
```

**ยังไม่มี: `/how-we-screen` และ `/demo`** — และหน้าแรกลิงก์ไปหาอันแรก นี่คือปลายเปิดข้อเดียว
ของโปรเจคตอนนี้ (ดูข้อ 12)

### 9.2 shell ถูกเลือกด้วย **route** ไม่ใช่ session

`web/lib/nav.ts` — และนี่คือการตัดสินใจที่ควรจำ

เคยเลือกด้วย session อยู่หนึ่ง commit และมันผิดในแบบที่ควรบันทึกไว้: **ผู้สมัครที่ล็อกอินอยู่
แล้วเปิดอ่านประกาศงาน จะถูกแสดงแถบเมนูที่มี Documents, Usage และ — ถ้าเขาบังเอิญเป็น recruiter
— Hire** เว็บสาธารณะของบริษัทก็เลยกลายเป็นหน้าแรกของหลังบ้านเงียบ ๆ สำหรับผู้ชมกลุ่มที่มันมีอยู่
เพื่อสร้างความมั่นใจให้พอดี

```ts
const PUBLIC_PREFIXES = ["/careers", "/how-we-screen", "/demo"];
isPublicRoute(path)  // "/" ก็นับด้วย
```

- การล็อกอินเปลี่ยนอย่างเดียวบนหน้าสาธารณะ: ลิงก์ "เข้าสู่ระบบ" กลายเป็นลิงก์ไปใบสมัครของคุณ
  มันไม่ import หลังบ้านเข้ามาบนหน้าการตลาด
- `isActiveNav` ใช้ `path === target || path.startsWith(target + "/")` — ไม่ใช่ `startsWith`
  เปล่า ๆ เพราะ **`/` เป็น prefix ของทุกอย่าง** และ **prefix ไม่ใช่ path segment**
  (`/hire` ต้องไม่ยึด `/hireling`)
- `activeNavHref` เลือก match ที่ยาวที่สุด เพื่อให้ `/me/documents` สว่างที่ตัวเอง ไม่ใช่ที่ `/me`

### 9.3 nav แสดง role แต่ไม่แต่งกฎเอง

กฎเดิมคือ **"nav ต้องไม่ซ่อนลิงก์ที่เซิร์ฟเวอร์ยินดีเสิร์ฟ"** — เพราะนั่นคือ client ตั้งกฎที่
เซิร์ฟเวอร์ไม่มี กฎยังเหมือนเดิม แต่คำตอบเปลี่ยน: careers site เอาหลังบ้านไปไว้หลัง
`require_role` แล้ว `/hire` จึงเป็น 403 จริง ๆ สำหรับ candidate → การซ่อนมันคือ client
เห็นด้วยกับเซิร์ฟเวอร์

**`/usage` คือเคสที่ทำให้กฎนี้ยังซื่อสัตย์** — มันอยู่ **นอก** `/hire` และแสดงให้ทุกคนเห็น
เพราะ `GET /metrics/usage` รับ `CandidateDep` และไม่มี role gate: มัน scope แถวใน WHERE clause
ดังนั้น candidate ที่เปิดดูจะเห็นว่าเอกสารของตัวเองใช้ไปเท่าไหร่ การเอาไปไว้ใต้ `/hire`
แล้วซ่อนคือความผิดพลาดที่ docstring ของไฟล์นี้มีไว้เพื่อป้องกัน และ path ถูกเลือกมาเพื่อไม่ให้
มันน่าทำ

### 9.4 หลักการฝั่ง client ที่เหลือ

- **`lib/` ถือ logic บริสุทธิ์ทั้งหมด** (`screening.ts`, `applications.ts`, `evidence.ts`,
  `metrics.ts`, `requirements.ts`, `api.ts`, `auth.ts`, `nav.ts`, `theme.ts`, `overlay.ts`,
  `countUp.ts`) เพื่อให้ `npm test` **ไม่ต้องมี DOM และไม่ต้องมี React testing library** —
  ด้วยเหตุผลเดียวกับที่ Python suite ไม่ต้องมี server
- `lib/applications.ts` ตัดสินว่าจะ **เสนอ** ท่าไหนให้กด แต่ **จงใจไม่ตัดสินว่าอะไรทำได้** —
  server เป็นคนตัดสิน สำเนาชุดที่สองของกฎคือชุดที่จะ drift โดยไม่มีใครสังเกต
- `DocumentPane` รับ `references: EvidenceRef[]` **ไม่ใช่ profile** — นี่คือสิ่งที่ทำให้
  citation ของ screening ไป highlight ผ่าน component ที่ M1 เขียนไว้สำหรับ extraction ได้
  เพราะ offset ชี้เข้า `document_text` เดียวกัน และเป็นเหตุผลเดียวกับที่ **receipt ของผู้สมัคร
  ใช้ component ชุดเดิมทั้งหมด**
- `createScreening` คืน `queued` เพราะ **202 vs 200 เป็นการตัดสินใจเชิงออกแบบที่ UI ต้องรายงานได้**
  ไม่ใช่รายละเอียดที่ซ่อนไว้
- **session เป็น external store ไม่ใช่ component state** (`useSyncExternalStore` เหนือ
  `localStorage`) — component สองตัวบนหน้าเดียวกันจึงเห็นตรงกันเสมอ และ **sign out แท็บนึงแล้ว
  แท็บอื่นออกตาม** ผ่าน `storage` event ธีมก็ใช้รูปแบบเดียวกัน (`lib/theme.ts`)
- **เบราเซอร์ไม่ถือ token แล้ว** — session เป็น httpOnly cookie ที่ API ออกให้ สคริปต์บนหน้าเว็บ
  อ่านไม่ได้เลย จึงปิดช่อง XSS ขโมย token สิ่งที่ยังอยู่ใน `localStorage` คือ **identity marker**
  (id, email, role) ไม่ใช่ credential — มีไว้เพราะ React ต้องมีอะไรอ่านแบบ synchronous เพื่อ
  render และเพราะ **cookie ไม่ยิง `storage` event**

### 9.5 `npm run build` ต้องไม่พึ่ง API — และสิ่งที่ต้องแลก

- `fetch` ที่นี่ไม่ถูก cache โดยค่าตั้งต้น และหน้า public ที่ดึงข้อมูลยังใส่
  `export const dynamic = "force-dynamic"` (ใช้ได้ตราบที่ `cacheComponents` ปิดอยู่ใน
  `next.config.ts`) — ไม่มี `sitemap.ts` ที่ไล่ประกาศทั้งหมด ไม่มี `generateStaticParams`
- **สิ่งที่ต้องแลก ซึ่ง `PLAN.md` บันทึกไว้ว่าเลื่อนอย่างมีเหตุผล ไม่ใช่ลืม**: หน้า public
  เป็น client component เหมือนทุกหน้าจอที่นี่ ดังนั้น **ชื่อประกาศไม่อยู่ใน HTML ที่ server
  เรนเดอร์ → search engine เห็นกระดานว่างเปล่า** การแก้ต้องมี API base ตัวที่สองพร้อม failure
  mode เรื่อง container networking ของตัวเอง — เป็น slice ไม่ใช่บรรทัดที่แอบใส่ไปกับ slice อื่น
  (`force-dynamic` บน server component จะ fetch จาก *ข้างใน* container `web` ซึ่ง
  `NEXT_PUBLIC_API_BASE` ชี้กลับมาที่ตัวมันเอง)
- อีกเรื่องที่ค้างไว้: **`/me` ยังมีลิสต์ "Apply to a job" ของตัวเอง** ซึ่งตอนนี้เป็นกระดาน
  ประกาศใบที่สองข้าง ๆ `/careers` การเอาออกเป็นการตัดสินใจว่า "การสมัคร" ควรอยู่ที่ไหน

### 9.6 เรื่องดีไซน์ — ย่อหน้าเดียว

ทุกหน้าจอย้ายมาอยู่บน token ใน `web/app/globals.css` แล้ว (direction **C · Console**)
กฎข้อเดียวที่ต้องรู้: **สีสื่อความหมายก่อนสื่อสไตล์** — `cited`, `ambiguous`, `dropped`
พูดถึงสิ่งที่ระบบพบใน *เอกสาร* และห้ามเอาไปใช้กับ control, ค่าใช้จ่าย หรือสถานะ workflow
(ตอนย้ายเจอ 5 ที่ที่ทำผิดข้อนี้) ธีมเป็น `data-theme` ที่ผู้อ่านเลือกเอง ไม่ใช่ media query
เพราะ **ธีมที่ไม่มีใครเลือกได้คือธีมที่ไม่มีใครตรวจได้** รายละเอียดที่เหลือทั้งหมดอยู่ใน
`docs/DESIGN.md`

---

## 10. Observability

`GET /metrics/usage` = aggregate จาก `llm_call_logs` + `extracted_profiles`
**ไม่มี table ใหม่ ไม่มี migration**

schema ถูกออกแบบรองรับมาตั้งแต่ M1 — `claims_verified`, `claims_dropped`, `hallucination_rate`
ถูกยกออกมาเป็นคอลัมน์จริง *เพื่อการนี้โดยเฉพาะ* query จึงเป็น `GROUP BY` ไม่ใช่การเดิน JSON

**หมายเหตุที่สำคัญ:** slice นี้ถูก **respecify ก่อนสร้าง** — เดิม scope ไว้เป็น *cost* dashboard
แต่ไม่มี cost เลย เพราะ `app/llm/gemini.py` map ทุกโมเดลเป็น `FREE_TIER` ทำให้ทุก call เก็บ
`cost_usd = 0.0` — ถ้าสร้างตามที่เขียนไว้จะได้หน้าจอที่มีแต่เลขศูนย์ ซึ่งคนอ่านจะนึกว่าเป็นบั๊ก กฎเรื่อง cost
ยังอยู่ครบ (ราคาที่ไม่รู้ต้องขึ้น "unknown" ไม่ใช่ `$0.00`) แต่สิ่งที่หน้าจอนำเสนอคือ token,
latency, prompt family และตัวเลขคุณภาพ ซึ่งเป็นของจริงวันนี้

4 การตัดสินใจที่ mutation-test พิสูจน์แล้วว่า load-bearing (ผิดอันไหนก็ตก 1 เคส)

1. **cost ของกลุ่มเป็น `unknown` เว้นแต่ทุก call ในกลุ่มมีราคา** — `SUM` ข้าม null ทำให้รายงาน
   ยอดบางส่วนเหมือนยอดเต็ม ยอดที่หายไปมองเห็นได้ ยอดที่ขาดบางส่วนมองไม่เห็น
2. **hallucination rate คำนวณใหม่จากยอดรวม ไม่ใช่เฉลี่ยจากค่าที่เก็บไว้รายเอกสาร** —
   บนข้อมูลทดสอบสองสูตรต่างกัน **25 เท่า**
3. **owner scoping มีสองแขน** เพราะ `llm_call_logs` ไม่มีคอลัมน์เจ้าของเลย:
   `resume_id → resumes.candidate_id` (extraction) และ
   `screening_id → screenings → jobs.owner_id` (judging) ตัดแขนไหนออกครึ่งหนึ่งของ call
   จะรายงานเป็นศูนย์เงียบ ๆ
   *(เห็นผลจริงบนหน้าจอ: recruiter เปิดดูจะเห็น judging อย่างเดียว ส่วน "profiles" เป็น 0
   เพราะ extraction ลงบัญชีกับคนที่อัปโหลดเอกสาร)*
4. **แบ่งเป็น 4 bucket** รวมถึง `unattributed` — row ที่ไม่มีทั้งสอง id ถูกกฎหมายอยู่
   (invariant นั้นเป็น docstring ไม่ใช่ constraint) จึงต้องรายงานว่ามี ไม่ใช่หายเงียบ

**ADMIN เห็นทุก row โดยอ่าน role ใน WHERE clause** ไม่ใช่ gate ที่ route — `require_role`
ไม่รัน query เลย ถ้าใช้มันจะ 403 ใส่บัญชีที่เป็นเจ้าของ row พอดี

---

## 11. Test / CI / คุณภาพ

ตัวเลขด้านล่าง **รันเองเมื่อ 2026-08-22** ไม่ได้คัดลอกมาจากเอกสารรุ่นก่อน

- `pytest -q` → **721 ผ่าน / 38 skip** ใน 57 วินาที (skip คือ opt-in: Postgres + Tesseract +
  MinIO + live-LLM)
- `npm test` → **232 เคส / 11 ไฟล์** ใน ~1 วินาที (vitest ไม่มี DOM)
- gate ที่บังคับใน CI: `ruff check`, `ruff format --check`, `mypy app` (strict), `pytest -q`,
  แล้ว `npm ci` / `typecheck` / `lint` / `build` + **migration up/down round-trip บน SQLite**

### บทเรียนเรื่องเครื่องมือที่โกหก

มีบันทึกไว้ใน `HANDOFF.md` §10 อันที่สำคัญที่สุด

- **การตรวจที่ผลลัพธ์คือ "ความว่างเปล่า" ต้องมี positive control ก่อน** —
  `read_console_messages` เริ่มจับตอนถูกเรียกครั้งแรก หน้าที่โหลดก่อนหน้าจะคืน "ไม่มี message"
  ไม่ว่าจะสะอาดหรือไม่ ต้องยิง probe ให้เห็นก่อน แล้วค่อยเชื่อว่าไม่มี error
- **คำสั่งที่ทำสองอย่าง รายงานแค่อย่างเดียว** — `docker compose up -d --build` build สำเร็จ,
  recreate ล้มเหลว, exit 0 → container เสิร์ฟโค้ดเก่าอายุ 9 ชั่วโมงขณะที่คำสั่งบอกว่าสำเร็จ
  สาเหตุรากคือ `C:` เต็ม **เช็คพื้นที่ว่างก่อนเซสชันที่จะ rebuild** และถามคอนเทนเนอร์ตรง ๆ ว่า
  มันถืออะไรอยู่ (`docker compose exec api sh -c 'echo $LLM_PROVIDER'`)
- **suite แบบ opt-in ที่เงียบ หน้าตาเหมือน suite ที่ผ่าน** — `test_postgres.py` มี 2 ใน 5 เคส
  พังมา 3 วันโดยไม่มีใครเห็น ต้องรันทุก opt-in module ด้วยมือเป็นระยะ
- **ก่อนเชื่อการทดสอบสด ต้องพิสูจน์ว่ากำลังทดสอบสิ่งที่เพิ่งสร้าง** — เคยเจอ zombie server,
  ARQ worker ตัวที่สองจากเซสชันก่อนแอบรับงาน, และ dev server บน port ที่ไม่อยู่ใน CORS list
  เช็คด้วย `/openapi.json`

### กฎที่แพงที่สุดที่โปรเจคนี้ซื้อมา

> **slice จะ "เสร็จ" เมื่อมีคนใช้มันแล้ว ไม่ใช่เมื่อ API call ทุกตัวถูก verify แล้ว**

2026-08-13 การเปิด browser ดู M4 slice 5 ครั้งแรกเจอ **7 ข้อบกพร่อง 4 อันบล็อกงาน** ในโค้ดที่
ทุก gate เขียวหมด

- candidate มองไม่เห็นประกาศงานเลย (`GET /jobs` กรองตามเจ้าของ → `200 []`)
- ปุ่ม Create job กดไม่ได้ เพราะ `min=0.1 step=0.5` ทำให้ค่า default ของตัวเอง (1) ไม่ valid
- recruiter คัดกรองผู้สมัครไม่ได้ เพราะ picker สร้างจาก `GET /resumes` ซึ่งคืนแค่ของตัวเอง
- transition ทุกอันตอบ 422 เพราะ `moveApplication` / `applyToJob` ข้าม helper `json()`
  แล้วไม่ได้ส่ง `Content-Type`

ไม่มีอันไหนที่เทสต์ logic บริสุทธิ์จะเห็นได้เลย ตอนนี้ทุก slice จึงต้อง **ขับ browser ข้างใน
slice ไม่ใช่หลัง slice** — และ run วันที่ 2026-08-22 (careers site 7 commit) ทำแบบนั้นเป็น
*เงื่อนไขก่อนเริ่ม commit ถัดไป* ไม่ใช่การตรวจปิดท้าย

---

## 12. ตอนนี้โปรเจคถึงไหนแล้ว

*(ข้อมูล ณ 2026-08-22 — `docs/PLAN.md` คือสถานะที่เป็นทางการ)*

### มิลสโตน

| Milestone | ขอบเขต | สถานะ |
|---|---|---|
| **M1** | parse (PDF, offsets, ไทย), extract, verify evidence, retry, auth, upload API, web UI | ✅ 2026-07-30 |
| **M2** | async worker + queue, OCR, DOCX, two-column, MinIO, evidence viewer | ✅ 2026-08-08 |
| **M3** | job requirements, judging ระดับ requirement, ranking, retrieval, screening UI | ✅ 2026-08-12 |
| **M4** | visibility timeout, RBAC, application state machine, PDPA | ✅ 2026-08-12 |
| **M5** | dropped-claims view, dashboard, geometry, pdf.js overlay, production compose | ✅ 2026-08-16 |
| **M6** | ประเมิน ranking เทียบ BM25/embedding baseline | ⛔ **review แล้ว ปิดโดยไม่สร้าง** (2026-08-16) |

**M6 ปิดโดยไม่สร้าง ด้วยเหตุผล 4 ข้อ และห้ามรื้อกลับมาเป็น "งานเล็ก ๆ ที่ทำก็ดี"**: หัวข้อคือ
"วัด **ranking** เทียบ BM25" แต่ BM25 เป็น **retrieval** scorer และ docstring ของ
`retrieval.py` เองห้ามเอาสองอย่างนี้มาเทียบกันไว้ตั้งแต่ M3; retriever ตัวนี้**เป็น BM25
อยู่แล้ว** (มี IDF จริง); ครึ่ง embedding ติดกฎ paid-provider; และ gold set บน fixture
สังเคราะห์ 9 ใบที่เราเขียนเอง ก็เท่ากับตรวจข้อสอบที่เราออกเอง

### หลัง M5 — ไม่ใช่มิลสโตน แต่เป็นงานที่ทำจริง

**Redesign direction C · Console (2026-08-20 → 08-21) — ปิดครบ** เจ้าของรีเซ็ตลำดับความสำคัญ
มาที่ UI, เลือกทิศทาง C จาก mockup 3 แบบที่วาดบน token เดิม, และตอนนี้ **ทุกหน้าจอย้ายมาอยู่
บน token แล้ว** สิ่งที่การย้ายกลายเป็นจริง ๆ ไม่ใช่การทาสี: มี **5 ที่** ที่ใช้สีสงวนกับสิ่งที่
ไม่ใช่คำกล่าวอ้างเกี่ยวกับเอกสาร (แถวที่เลือกในตาราง ranking, must-have gate ที่ไม่ผ่าน,
panel "Not in the ranking", โน้ตค่าใช้จ่าย, และสถานะใบสมัครทุกอัน)

**Careers site — 7 จาก 11 slice**

| # | Slice | สถานะ |
|---|---|---|
| 0 | ปิดการสมัครเป็น recruiter เอง | ✅ 2026-08-22 (ไม่ได้อยู่ในลิสต์เดิม) |
| 1 | ความถูกต้องของการจับคู่ citation | ✅ 2026-08-20 |
| 2 | shell เดียว, nav ตาม role | ✅ 2026-08-20 · **แก้ใหม่ 2026-08-22 ให้ดูทั้ง role และ route** |
| 3 | receipt route `GET /applications/{id}/screening` | ✅ 2026-08-22 |
| 4 | `/me` — ใบสมัคร, เหตุผล, receipt บนหน้าจอ | ✅ 2026-08-22 |
| 5 | design token + typeface + primitive | ✅ (การย้ายข้างบนคือการใช้มัน) |
| 6 | **`/how-we-screen` + demo สาธารณะ** | ⛔ **ยังไม่เริ่ม และ `/` ลิงก์ไปหามัน** |
| 7 | migration `0013` — publication lifecycle | ✅ 2026-08-21 |
| 8 | careers API + board + หน้า posting + landing | ✅ 2026-08-22 **ยกเว้น metadata** ซึ่ง defer พร้อมเหตุผล |
| 9 | `/me/documents` — คลัง CV | ⚠️ **route เท่านั้น** — หน้าจออัปโหลดย้ายมาแล้ว แต่ "คลัง" ยังไม่มี |
| 10 | `/hire` — หลังบ้าน | ⚠️ **ย้ายแล้ว ยังไม่จัดใหม่** — route อยู่หลัง `/hire` แล้ว แต่ข้างในหน้าจอเหมือนเดิม |
| 11 | `/me/account` — export, เปลี่ยนรหัส, ลบบัญชี | ⛔ ยังไม่เริ่ม |

### ปลายเปิดข้อเดียวที่ชี้ไปที่ 404

**`/how-we-screen` และ `/demo` ยังไม่มี และหน้าแรกลิงก์ไปหาอันแรก** — นี่คือ slice ถัดไป

### สิ่งที่ถูก "ปฏิเสธ" ไว้ ให้อ่านเป็นการตัดสินใจ

- **ห้ามประกาศตัวเลข hallucination rate ต่อสาธารณะ** — มันวัดบน corpus สังเคราะห์ของโปรเจคเอง
  การเผยแพร่ราวกับว่ามันอธิบายเรซูเม่จริงคือความผิดพลาดแบบเดียวกับที่ปิด M6
- **copy เป็น slice ของตัวเอง** — Thai-first ครอบเฉพาะหน้า *สาธารณะ* (`<html lang="th">`,
  พาดหัวไทย + บรรทัดอังกฤษสั้นใต้) **ไม่ใช่** `[locale]` segment ส่วนหน้าจอภายในยังเป็นอังกฤษ
  เพื่อไม่ให้การย้ายหน้าจอกลายเป็นสองการเปลี่ยนแปลงพร้อมกัน

### สถานะ repo

- gate ล่าสุด (รันเอง 2026-08-22): pytest **721 ผ่าน / 38 skip**, vitest **232**
- จำนวน commit ที่ยังไม่ push **ให้ดูด้วย `git rev-list --count origin/main..main`**
  อย่าเชื่อบรรทัดนี้ — เอกสารในโปรเจคนี้เคยบอกเลขผิดมาแล้วสองครั้ง

---

## 13. กฎที่ห้ามพัง

**เรื่องหลักฐาน**

1. **ห้ามให้ claim ที่ยัง verify ไม่ได้เข้าไปใน response** — ใส่ `dropped` แทน
2. **ห้ามให้โมเดลผลิต character offset หรือเลขหน้า** — นี่คือความผิดพลาดที่ทั้งดีไซน์นี้มีอยู่
   เพื่อหลีกเลี่ยง
3. **`document_text` เก็บ verbatim** ห้าม re-parse / re-normalize ของที่เก็บแล้ว
4. **OCR ต้องถูกแทนเข้า page list ก่อน `_assemble` วัด span**
5. **`test_columns_should_read_one_after_the_other` ใน `test_parse.py` ต้องอยู่ต่อ**

**เรื่องสิทธิ์และตัวตน**

6. **403 คือ route, 404 คือ row** ห้ามยุบรวม
7. **`decode_token` กับ `token_service.assert_live` ต้องเรียกคู่กันเสมอ** และ `assert_live`
   รับแถวบัญชีเป็นอาร์กิวเมนต์**บังคับ**
8. **`recruiter` และ `admin` สมัครเองไม่ได้** — `SelfServiceRole` มีสมาชิกเดียว
9. **มีแต่ admin ที่ publish ประกาศได้**
10. **หน้าเว็บกับ API ต้อง same-site** — `localhost` ทั้งคู่ ไม่ใช่ `127.0.0.1`
11. **CSRF ตรวจเฉพาะที่ cookie เป็น credential** ไม่ใช่ทุก write

**เรื่องข้อมูลส่วนบุคคล**

12. **ห้าม log หรือ print document text** — เรซูเม่คือ PII (รวมถึง storage key ที่ฝัง candidate
    id + content hash)
13. **erasure ลบไฟล์ก่อน row และไม่ลบอะไรเลยถ้าไฟล์ลบไม่ได้**
14. **test data สังเคราะห์เท่านั้น** — เรซูเม่คนจริงห้ามเข้า repo

**เรื่องสภาพแวดล้อม**

15. **ห้ามทำให้ test suite ต้องมี server** — ใช้ opt-in module แทน
16. **`PRAGMA foreign_keys=ON` ใน `db.py` เป็น load-bearing**
17. **path ของโปรเจคต้องเป็น ASCII** — codepage เครื่องนี้คือ cp874 (ไทย)
18. **`LLM_PROVIDER=anthropic` raise โดยเจตนา** — adapter ที่ไม่เคยรันกับ API จริงแย่กว่า error
    ที่ซื่อสัตย์ และ provider ที่คิดเงินต้องมาพร้อมตารางราคาที่อัปเดต + การทดสอบสดที่บันทึกไว้
19. **fixture ไบนารีต้องอยู่ใน `.gitattributes`** — `core.autocrlf=true` เคยเขียนทับ `0x0A`
    ข้างใน compressed stream ของ PDF (ถ้าสงสัย ให้ **เทียบขนาดไฟล์ ไม่ใช่ hash**)

**เรื่องหน้าจอ**

20. **shell เลือกด้วย route ไม่ใช่ session**
21. **สีสงวน (`cited` / `ambiguous` / `dropped`) ใช้กับคำกล่าวอ้างเกี่ยวกับเอกสารเท่านั้น**
    ห้ามใช้กับ control, ค่าใช้จ่าย หรือสถานะ workflow

---

## 14. เริ่มเล่นเองยังไง

```bash
# เร็วที่สุด ไม่ต้องมี server ไม่ต้องมี DB ไม่ต้องมี API key
cd api && python -m app.cli tests/fixtures/resume_th.pdf
cd api && python -m app.cli tests/fixtures/resume_th.pdf --requirement skill:Python

# ทั้งระบบในคอนเทนเนอร์
docker compose up -d --build   # api :8000 (/docs), web :3000, minio console :9001
docker compose logs -f worker
docker compose exec api sh -c 'echo $LLM_PROVIDER $FAKE_MODE'   # เชื่อคอนเทนเนอร์ ไม่ใช่ .env
```

- เปิดเว็บที่ **`http://localhost:3000`** เท่านั้น
- อยากเห็นเส้นทาง **dropped-claims**: ตั้ง `FAKE_MODE=hallucinating` ใน `.env` รีสตาร์ท
  api + worker แล้วอัปโหลดใหม่ (แล้วอย่าลืมตั้งกลับเป็น `faithful`)
- อยากเห็นเส้นทาง **dead-letter**: `FAKE_MODE=unavailable` แล้วดู log ของ worker
- **ไม่มี worker รัน = อัปโหลดค้างที่ `pending` ตลอดไป** (อัปโหลดไฟล์เดิมซ้ำจะ re-queue ให้)

### ลองเส้นทางสาธารณะด้วย curl (ไม่ต้องล็อกอิน)

```bash
curl -s http://localhost:8000/careers/postings | head -c 400
curl -s http://localhost:8000/careers/postings/<id>
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/careers/postings/<draft-id>  # 404
```

### ลองเส้นทาง receipt

```bash
# ล็อกอินเป็นผู้สมัคร เก็บ cookie ไว้ในไฟล์
curl -s -c jar.txt -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' -d '{"email":"...","password":"..."}'
curl -s -b jar.txt http://localhost:8000/me/applications
curl -s -b jar.txt http://localhost:8000/applications/<id>/screening
```

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
12. **`api/app/publication.py`** ← state machine อีกชนิดหนึ่ง อ่านคู่กับข้อ 11 ให้เห็นความต่าง
13. **`api/app/api/routes/applications.py`** (ส่วน receipt) ← route ที่โปรเจคนี้เกิดมาเพื่อมัน
14. `api/app/api/deps.py` ← auth, RBAC, CSRF อยู่ในไฟล์เดียว
15. `web/lib/nav.ts`, `web/lib/api.ts` ← ฝั่ง client ทั้งหมดสรุปอยู่ในสองไฟล์นี้
16. `docs/PLAN.md`

### คำสั่งที่ใช้บ่อย

รันจาก `api/` ใน venv (`.venv\Scripts\activate`) หรือใส่ prefix `.venv/Scripts/python.exe -m`

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
