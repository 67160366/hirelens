# HireLens บน Vercel + Render + Supabase Free

สถานะ: เตรียมโค้ดและการตั้งค่าแล้ว ยังไม่มี deployment URL ที่ตรวจยืนยันบน cloud

## รูปแบบที่เลือก

- Vercel Hobby: Next.js แบบ SSR พร้อม proxy `/api` ไป Render
- Render Free: FastAPI, Tesseract ไทย/อังกฤษ และ consumer คิวใน process เดียว
- Supabase Free: PostgreSQL และ private bucket สำหรับ PDF/DOCX

งานคิวอยู่ในแถว `pending` ของ PostgreSQL จึงไม่หายไปพร้อม filesystem ของ Render
consumer ค้นงานค้างเองหลัง restart ใช้ row lock, exponential backoff, dead letter
และ visibility timeout ของ pipeline เดิม ไม่เปลี่ยนเป็น fake หรือ inline queue
Render หลับได้ เมื่อมี request ปลุกจึงเริ่มทำงานต่อ; งานที่ค้าง processing จะรอ
visibility timeout ก่อน reclaim ไม่ได้รับประกัน worker ทำงานตลอด 24 ชั่วโมง

แผนนี้เป็นการติดตั้งใหม่ ไม่ได้ย้ายบัญชี/เรซูเม่จากเครื่องเดิมโดยอัตโนมัติ

## 1. Supabase

1. Login https://supabase.com/dashboard ด้วยบัญชีของคุณ สร้าง project บน Free
   ใน Singapore ถ้าเลือกได้ ตั้ง database password และเก็บไว้ในที่ปลอดภัย
2. Storage > สร้าง bucket ชื่อ `hirelens-resumes` แบบ **Private**
   ห้ามสร้าง public bucket สำหรับเรซูเม่
3. Storage > S3 configuration: สร้าง credentials ฝั่ง server และคัดลอก
   endpoint, region, Access Key ID, Secret Access Key ไปตั้งค่า Render เท่านั้น
   ห้ามใส่ไว้ใน Vercel หรือ `NEXT_PUBLIC_*`
4. Connect > Session pooler: คัดลอก URL ที่ port **5432** แล้วเปลี่ยน prefix เป็น
   `postgresql+asyncpg://` ใส่รหัสผ่านที่ URL-encode แล้ว ไม่ใช้ transaction pooler
   port 6543 หรือซื้อ IPv4 add-on

Render startup สร้าง schema `hirelens` และเพิกถอนสิทธิ์ PUBLIC/anon/authenticated
ที่ schema ก่อน migrations ทุก table ของแอปอยู่ใน schema นี้ รวม alembic_version
อย่าเพิ่ม `hirelens` ใน exposed schemas ของ Supabase Data API ระบบใช้ auth/RBAC
ของ HireLens เดิม ไม่ต้องย้าย login ไป Supabase Auth

หากตรวจสอบใบรับรอง TLS ไม่ผ่าน ให้ตรวจ hostname/pooler และ root CA ที่ Supabase
ให้มา ไม่ปิด certificate validation

Render ใช้ `DATABASE_SSL_CA_FILE=/app/certs/supabase-prod-ca-2021.crt`
เพื่อเพิ่ม Supabase Root CA ใน trust store โดยยังตรวจ hostname และ certificate
ไฟล์ CA เป็น public certificate จาก URL ที่ Supabase dashboard ใช้:
https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt

## 2. Render

1. Login https://dashboard.render.com แล้วสร้าง Blueprint จาก repository
   `67160366/hirelens` และ branch ที่มี `render.yaml`
2. Blueprint กำหนด service `hirelens-api`, plan **free**, region Singapore ไว้แล้ว
   ถ้าหน้าจอเสนอ plan เสียเงินอย่าเลือก ไม่มี Render Database/disk/worker เพิ่ม
3. ตั้งค่าที่ `sync: false` ตาม [ตัวอย่าง](../deploy/render.env.example)
   ใช้ S3 region/endpoint จาก Supabase จริง ไม่เดาจากชื่อ region
4. ใช้ Gemini key เดิมที่มี quota ฟรี และชื่อโมเดลที่บัญชีนั้นยังเรียกได้
   ไม่เปิด billing เพื่อแก้ quota หมด
5. `CORS_ORIGINS` ตั้งเป็น URL production ของ Vercel แบบตรงตัว
   ถ้ายังไม่ทราบ ให้ตั้ง placeholder แล้วแก้เป็น URL จริงก่อนทดสอบ login
   ค่าเหล่านี้เป็น allowlist ของ cookie-authenticated writes ห้ามใช้ wildcard
6. Deploy: startup สร้าง private schema, รัน Alembic แล้วเริ่ม Uvicorn **หนึ่ง worker**
   จาก `sh deploy-render.sh` ตรวจ `https://<ชื่อจริง>.onrender.com/health`

ไฟล์ bucket อยู่ Supabase ไม่ใช้ local storage บน Render
ถ้า migrations/storage/OCR ตั้งค่าไม่ถูก service จะ fail ที่ startup

## 3. Vercel

1. Login https://vercel.com/new แล้ว import repository และ branch เดียวกับ Render
2. ตั้ง **Root Directory = web** และ framework Next.js
3. ตั้งตัวแปรทั้ง 3 ตาม [ตัวอย่าง](../deploy/vercel.env.example) ก่อน build:
   `NEXT_PUBLIC_API_BASE=/api`, `API_PROXY_BASE=<Render HTTPS origin>`,
   `SERVER_API_BASE=<Render HTTPS origin>` ไม่ใส่ trailing path `/api` ที่สองค่าหลัง
4. Deploy แล้วนำ production URL ไปตั้ง `CORS_ORIGINS` ที่ Render ให้ตรง
5. เข้าผ่าน Vercel URL เสมอ: proxy ทำให้ cookies เป็น same-origin
   Render ตั้ง `COOKIE_PATH_PREFIX=/api` เพื่อให้ refresh cookie ไปถึง `/api/auth`
   ทั้งตอนตั้งและตอนล้าง session เลือก host-only, Secure, httpOnly และ SameSite=lax

เมื่อเปลี่ยน URL Render หรือ API_PROXY_BASE ต้อง rebuild Vercel เพราะ rewrites
อ่านตอน build และ public API base ถูก inline ใน bundle
Preview URL ต้องอยู่ใน CORS allowlist เองจึงทดสอบ writes ได้ ไม่เปิดทุก `*.vercel.app`

## ตรวจการใช้งานจริงก่อนถือว่าเสร็จ

- `/api/health`, หน้า landing, `/careers`, `/demo` ต้องโหลดผ่าน Vercel
- สมัคร/login/reload/refresh/logout ผ่าน cookie โดยไม่ใช้ Bearer แทน
- อัปโหลด synthetic PDF/DOCX และ scanned fixture พร้อม consent แล้วรอผล
- เปิด PDF viewer/หลักฐาน, ดู usage, สร้างงานและ requirements ด้วย recruiter
- publish ด้วย admin, สมัครงานด้วย candidate, screening/ranking และ receipt
- restart Render แล้วตรวจบัญชี ไฟล์ และงาน pending ว่ายังอยู่
- export/password change และ erasure เฉพาะบัญชีทดสอบที่ระบุว่าทิ้งได้

อย่า grant recruiter/admin ด้วยการเปิด public registration ให้เลือก role
ใช้วิธีจัดสิทธิ์นอกระบบเดิมใน RUNBOOK โดย table อยู่ schema `hirelens`

## ข้อจำกัดฟรีที่ยังมี

- Render sleep หลังไม่มี traffic 15 นาทีและมี quota RAM/ชั่วโมง จำกัด
  job serial ลดการใช้ RAM แต่ไฟล์ OCR ขนาดใหญ่อาจยังเกินโควตา ต้องตรวจจริง
- Supabase มี DB 500 MB / ไฟล์ 1 GB และอาจ pause เมื่อ activity ต่ำ 7 วัน
- Vercel Hobby ใช้เฉพาะส่วนตัวที่ไม่ใช่เชิงพาณิชย์
- Proxy/SSE อาจหมดเวลาเมื่อรอนาน client มี polling fallback เดิม
- ควรสำรองฐานข้อมูลและไฟล์; โฮสต์ฟรีไม่ได้แทนระบบ backup

แหล่งอ้างอิง:
https://render.com/docs/free
https://supabase.com/docs/guides/database/connecting-to-postgres
https://supabase.com/docs/guides/storage/s3/authentication
https://supabase.com/docs/guides/storage/s3/compatibility
https://supabase.com/docs/guides/platform/free-project-pausing
https://vercel.com/docs/plans/hobby
https://vercel.com/docs/routing/rewrites
