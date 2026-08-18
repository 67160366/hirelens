# Runbook

Operating the HireLens stack in production mode. Every command below was run on
2026-08-16 against a cold-started stack on this machine; where a command's output is
quoted, that is what it actually printed.

The development stack is a different thing and stays easy: `docker compose up -d --build`
with no flags. This file is about the other one.

**Read `docs/HANDOFF.md` §1 for where the project is, `CLAUDE.md` for the rules that must
not be weakened, and `docs/PLAN.md` for per-item status.** This file assumes you have.

---

## 1. What "production mode" is here

Two committed compose files, layered:

| File | Role |
|---|---|
| `docker-compose.yml` | The **dev** file. Unchanged, and it stays the one a fresh clone runs. |
| `docker-compose.prod.yml` | The overlay: no published data services, restart policies, secrets with no defaults, `APP_ENV=prod`, distinct image tags. |

```bash
docker compose --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

On a real prod host, set these once so a bare `docker compose up -d` means prod:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
export COMPOSE_ENV_FILES=.env.prod
```

This is a **production profile on one machine**, not a cloud deployment. There is no TLS
here, no reverse proxy, no log shipping, and no backup schedule — §6 tells you how to
take a backup, not when. The API and web are bound to `127.0.0.1` precisely because
something else is expected to terminate TLS in front of them.

### Why not `env_file:`, and why not `profiles:`

Both were tried and both are wrong, measured on Compose **v5.3.1** rather than assumed:

- **`profiles:`** cannot do this. With the profile inactive the project fails to load at
  all — `service "api" depends on undefined service "postgres"` — because every infra
  service is a `depends_on` target.
- **A service-level `env_file:`** silently loses to a base file's `environment:` key. The
  dev file sets every secret as `environment:`, so putting them in an `env_file` would
  leave every one of them at its dev default and nothing would say so. Only keys *absent*
  from the base come through.
- **`--env-file` / `COMPOSE_ENV_FILES` works**, because it feeds compose's own
  `${VAR:-default}` substitution, which is how the dev file already writes anything it
  does not hard-code. That is the mechanism this runbook uses.
- **`ports:` merged untagged appends** — you get the dev port *and* the prod port
  published. The overlay uses `!reset []` and `!override [...]`, which both work.

---

## 2. Bring it up from nothing

```bash
cp .env.prod.example .env.prod
```

Generate each secret separately and paste it in:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD
python -c "import secrets; print(secrets.token_urlsafe(24))"   # MINIO_ROOT_PASSWORD
```

`.env.prod` is gitignored. `.gitignore`'s `.env.*.local` does **not** match it, which is
why it has its own line — check that line is still there before you write secrets to it.

Then:

```bash
docker compose --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### What a healthy stack looks like

```
SERVICE    STATUS                    PORTS
api        Up (healthy)              127.0.0.1:8000->8000/tcp
minio      Up (healthy)              9000/tcp
postgres   Up (healthy)              5432/tcp
redis      Up (healthy)              6379/tcp
web        Up (healthy)              127.0.0.1:3000->3000/tcp
worker     Up
```

Two things to read in that table rather than skim:

- **`postgres`, `redis` and `minio` show a bare container port and no `->`.** They publish
  nothing to the host. If you see `0.0.0.0:5432->5432` you are running the dev file.
- **`worker` has no health status, on purpose.** The image's HEALTHCHECK probes the HTTP
  server and the worker does not run one; it is disabled so `docker compose ps` does not
  train you to ignore a permanently-unhealthy row.

### Two failures you should expect, and what they mean

**A missing secret stops the project before anything starts:**

```
error while interpolating services.postgres.environment.POSTGRES_PASSWORD:
required variable POSTGRES_PASSWORD is missing a value: set POSTGRES_PASSWORD in .env.prod
```

**A forgotten `JWT_SECRET` stops it at the `migrate` service**, which is the first one to
run, because `migrations/env.py` imports `get_settings()`:

```
migrate-1 | pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
migrate-1 |   Value error, JWT_SECRET is still the placeholder while APP_ENV=prod.
```

`api`, `worker` and `web` never start, because they gate on
`migrate: service_completed_successfully`. This is the intended behaviour and it has been
watched doing it — a deploy that forgets the secret must fail loudly rather than sign
every token with a value committed to this repository.

---

## 3. Migrations

They run as their own one-shot service, before anything connects. Not in the API's
entrypoint — two replicas would race to apply the same revision.

```bash
docker compose ... logs migrate          # what ran
docker compose ... exec api alembic current
```

`alembic current` on a healthy stack ends with `(head)`:

```
d0e1f2a3b4c5 (head)
```

On a cold start you should see the whole chain, initial schema through the newest
revision. To apply migrations after a code change, rebuild and bring the stack up again —
`migrate` re-runs and is a no-op when there is nothing to do.

If `migrate` exits non-zero, **nothing else starts**, and the log is the whole diagnosis.
Do not work around it by starting `api` by hand; a schema the code does not expect is how
you get errors that look like application bugs.

---

## 4. What to check after a deploy

In this order. Each one has caught something real on this project.

**1. The container serves the code you just built.** A green build is not this.

```bash
curl -s http://localhost:8000/openapi.json | grep -o '"/metrics/usage"'
```

Ask for a route the change added. **If the change added no route, ask the container what
it holds** — `docker compose ... exec api python -c "..."` — because `/openapi.json`
proves nothing then. A stale container that built fine and never got recreated has
happened here and reported success while doing it.

**2. The stack is healthy and the data services are not published.** §2's table.

**3. The worker is taking jobs.** Upload something and watch:

```bash
docker compose ... logs worker | grep process_resume
```

```
0.43s → resume:c770f866-...:0:process_resume('c770f866-...')
0.04s ← resume:c770f866-...:0:process_resume ●
```

If uploads sit at `pending` forever, the worker is not running or `QUEUE_BACKEND` is not
`arq`.

**4. A real document reaches `extracted` with its citations.** The end-to-end check
nothing else substitutes for. On `LLM_PROVIDER=fake` it costs nothing and still exercises
parsing, the queue, evidence resolution and the whole client.

**5. If you changed `NEXT_PUBLIC_API_BASE`, confirm the bundle carries it.** It is a
**build arg**, inlined by `next build`, so a restart does not pick it up — only
`up -d --build web` does. And `CORS_ORIGINS` on the API has to name the same origin or
every request fails preflight.

```bash
curl -s http://localhost:3000/ | grep -o '/_next/static/chunks/[a-zA-Z0-9._-]*\.js' \
  | sort -u | head -12 | while read c; do curl -s "http://localhost:3000$c"; done \
  | grep -o 'localhost:[0-9]*' | sort | uniq -c
```

---

## 5. Erase an account on request

The PDPA path. It is a real deletion and there is no undo.

```bash
curl -X DELETE http://localhost:8000/auth/me -H "Authorization: Bearer <their token>"
```

```json
{"account_id":"de8fb3f4-...","stored_files_removed":1,
 "message":"The account and everything belonging to it have been deleted."}
```

**Confirm it rather than trusting the 200**, all three:

```bash
# 1. the token is dead
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/auth/me \
  -H "Authorization: Bearer <their token>"            # 401

# 2. the rows are gone — the cascade, not just the account row
docker compose ... exec -T postgres psql -U hirelens -d hirelens -t -c \
  "select count(*) from candidates; select count(*) from resumes;
   select count(*) from extracted_profiles; select count(*) from llm_call_logs;"

# 3. the stored file is gone
docker compose ... exec -T api sh -c 'find /data/uploads -type f | wc -l'
# on STORAGE_BACKEND=minio, check the bucket instead — a filesystem cannot show
# "the object outlived the row" the way a bucket can
```

**Erasure deletes stored files before rows, and deletes nothing if a file refuses**
(503, nothing changed). Do not "fix" that order: rows-first leaves an object in the bucket
that nothing points at — undiscoverable, and so unerasable, which is the actual PDPA
failure. A row whose file is missing is already a handled state.

Export is the same question asked the other way, and answering one without the other means
one of them is lying:

```bash
curl http://localhost:8000/auth/me/export -H "Authorization: Bearer <their token>"
```

It returns the substance — `document_text`, the verified profile, the consent version and
timestamp — not a summary. A summary would make the right to a copy decorative.

---

## 6. Back up, restore, rotate

### Back up

```bash
docker compose ... exec -T postgres pg_dump -U hirelens -d hirelens > backup.sql
```

Check the dump carries `alembic_version`, or a restore will not know what schema it is:

```bash
grep -A3 'COPY public.alembic_version' backup.sql
```

**The dump is not the whole system.** Uploaded resumes live in the `uploads_data` volume
(or the MinIO bucket), and a database restored without them has rows pointing at files
that are not there. Back up both or neither.

### Restore

```bash
docker compose ... exec -T postgres psql -U hirelens -d hirelens < backup.sql
```

Into an **empty** database. Restoring over a populated one leaves you with whichever rows
happened to survive the conflicts.

### Rotate a secret

- **`JWT_SECRET`** — change it in `.env.prod`, then `up -d api worker`. Every existing
  token stops working immediately. **This is no longer the only revocation available**
  (it was, until 2026-08-16): `POST /auth/logout` ends one session, and a password change
  revokes the token that made it. Reach for the secret only when you need *everybody*
  signed out at once — a suspected key compromise — because that is what it does.
- **`POSTGRES_PASSWORD`** — changing it in `.env.prod` does **not** change the password
  in an existing database volume; `POSTGRES_PASSWORD` only initialises a fresh one. Do it
  with `ALTER ROLE` inside psql *and* in `.env.prod`, or the stack will not reconnect.
- **`MINIO_ROOT_PASSWORD`** — same shape. Change it in MinIO, then in `.env.prod`.

---

### End one session

```bash
curl -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer <their access token>" \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token": "<their refresh token>"}'      # 204
```

Both tokens are refused afterwards. **Send the refresh token**: omitting it revokes only
the access token, and the session stays renewable for the refresh token's full lifetime.

The revocations live in `revoked_tokens` and are swept once an hour, after each token's
own expiry — so the table is sized by outstanding sessions rather than by history, and a
row disappearing is housekeeping rather than a session coming back to life.

```bash
docker compose ... exec -T postgres psql -U hirelens -d hirelens \
  -c "select reason, token_type, count(*) from revoked_tokens group by 1,2;"
```

### End *every* session for one account

There is no route for it, but a password change does exactly this, and so does the one
statement behind it:

```bash
docker compose ... exec -T postgres psql -U hirelens -d hirelens \
  -c "update candidates set token_epoch = token_epoch + 1 where email = 'them@example.com';"
```

Every token that account holds — on every device, access and refresh alike — is refused
from the next request onward, because each carries the generation it was minted under and
the row no longer matches. Nothing had to know which sessions existed, which is the whole
reason it works: the denylist records only tokens that are *dead*, never the ones
outstanding.

Two things to know before running it. **They are signed out, not locked out** — their
password still works and signing in gives them a current pair. And **it leaves no record
of itself**: bumping an integer writes no history, so unlike a logout or a password change
there will be no row in `revoked_tokens` explaining what happened. Note in your own
incident log why you ran it.

Rotating `JWT_SECRET` still exists and is still the bigger hammer: it signs out
*everybody*, and it is the right tool only when the secret itself is what leaked.

## 7. When a document does not come out

Two failure statuses, and the difference is the whole point:

| Status | Meaning | What to do |
|---|---|---|
| `failed` | **This document cannot be processed** — broken file, empty, a scan with OCR off. | Retrying changes nothing *unless you change configuration*. |
| `dead_lettered` | **Transient failures used up the retry budget** — provider down, storage timeout. | Worth replaying. |

```bash
curl -X POST http://localhost:8000/resumes/<id>/retry -H "Authorization: Bearer <token>"
```

**A row stuck at `processing`** means the worker died rather than failed — a killed
container never gets to fail, so nothing else would ever move that row. The arq cron
`cron:reclaim` sweeps rows held past `JOB_VISIBILITY_TIMEOUT_SECONDS` (900 s), **through
the retry policy rather than a status reset** — that is what stops a document which kills
its worker every time from looping reap → requeue → die.

```bash
docker compose ... logs worker | grep -i reclaim
```

Under `QUEUE_BACKEND=inline` there is no worker and so no sweep; `POST /retry` on a
stalled row is the only way back. Prod runs `arq`, so both halves exist.

---

## 8. Rehearsing this beside a running dev stack

How the prod path was verified on this machine, and how to re-verify it after changing
either compose file. It uses its own project name, so it gets its own volumes and cannot
touch dev's data.

```bash
# .env.prod with API_PORT=8100, WEB_PORT=3100,
# NEXT_PUBLIC_API_BASE=http://localhost:8100, CORS_ORIGINS=http://localhost:3100
docker compose -p hirelens-prod --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The ports must differ or they collide with dev on 8000/3000. **`NEXT_PUBLIC_API_BASE` has
to change with them** — it is a build arg, so the web image genuinely rebuilds.

The overlay also gives the prod images their own tags (`hirelens-api:prod`,
`hirelens-web:prod`). Without that, a rehearsal build would overwrite `:local` and the
next dev `up` would silently adopt a web bundle built against the rehearsal's API URL.

Tear it down completely when finished:

```bash
docker compose -p hirelens-prod --env-file .env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml down -v
```

Then confirm dev is untouched — `docker compose ps`, and its row counts.

---

## 9. Things that have lied here before

`docs/HANDOFF.md` §10 keeps the full list. The four that matter when operating this stack:

- **`docker compose up -d --build` can build both images, fail to recreate the containers,
  print the failure on its last line and still exit 0.** The root cause was a full `C:`
  turning containerd's metadata store read-only. **Check free disk before a session that
  rebuilds anything**, and always ask the container what it holds afterwards.
- **An inline `VAR=x docker compose up` may not reach compose at all.** Export first, then
  run, then verify with `exec … env`. A shell export also *beats* `.env`, which is how a
  stack can quietly run a different provider than `.env` describes.
- **Checking for an absence needs a positive control.** `read_console_messages` only
  starts capturing when first called, so a page loaded earlier returns "no messages"
  whether it is clean or not. The same rule applies to "the port is closed": probe a port
  you know is open first, or you have only proven your probe does nothing.
- **An opt-in test suite going quiet looks exactly like one that passes.**
  `tests/test_postgres.py` had two of five cases failing for three days; `pytest -q` skips
  it and CI has no database. Run the opt-in modules by hand periodically and **read the
  number**, not the absence of red.
