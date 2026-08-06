# LLM providers

`LLM_PROVIDER` picks the extraction backend. All three implement one interface,
[`StructuredExtractor`](../api/app/llm/base.py), so switching is an environment
variable rather than a code change.

| Value | Needs | Cost | Use for |
|---|---|---|---|
| `fake` (default) | nothing | none | Tests, CI, offline development, demoing the failure paths |
| `gemini` | a free API key | none on the free tier | Real extraction |
| `anthropic` | a paid API key | see below | Not implemented — see the note at the end |

## `fake`

A rule-based extractor over the real document: sections by heading (English and
Thai), roles by regex. Every quote it emits is copied from the document it was
given, so evidence verification downstream behaves exactly as it does with a real
model. That is the point — it is infrastructure, not a stub.

`FAKE_MODE` controls how it behaves:

| Mode | Behaviour |
|---|---|
| `faithful` (default) | Every quote is real |
| `hallucinating` | Adds one claim citing text that is not in the document |
| `unavailable` | Raises, to exercise the backend-down path |

`hallucinating` is the only practical way to see the dropped-claims UI without
waiting for a real model to misbehave.

## `gemini`

Uses `gemini-3.6-flash` through the [google-genai](https://github.com/googleapis/python-genai)
SDK. Get a key at <https://aistudio.google.com/apikey> — no card required.

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
```

Chosen as the default real provider because the free tier is enough to develop and
demo against, and its long context swallows a resume without chunking.

Two things the first live run taught us (2026-08-06), now baked into the adapter:

- **Model turnover is real.** `gemini-2.5-flash` — the original choice — returns
  `404 "no longer available to new users"` for API keys created after mid-2026.
  The adapter defaults to `gemini-3.6-flash`; if a model 404s, list what your key
  can use with `client.models.list()`.
- **`response_schema` rejects our Pydantic models.** The SDK renders
  `extra="forbid"` as `additionalProperties`, which the Developer API refuses with
  a 400. The adapter therefore sends `response_json_schema` (the plain JSON Schema
  from `model_json_schema()`) and validates the reply with Pydantic itself.

Note that thinking tokens are billed as output on Gemini, so
`thoughts_token_count` is folded into `output_tokens` when recording usage —
otherwise cost-per-document reads low for exactly the calls that cost most.

Prices in [`api/app/llm/gemini.py`](../api/app/llm/gemini.py) are zero, reflecting
the free tier. **If you move to a paid tier, update them** — a stale price silently
corrupts the cost figures.

### First live run — `gemini-3.6-flash` over every fixture (2026-08-06)

Via `python -m app.cli`, one run per fixture:

| Fixture | Verified | Hallucination rate | Attempts | Latency | Match kinds |
|---|---|---|---|---|---|
| `resume_th.pdf` | 10/10 | 0.0% | 1 | ~9.0 s | exact ×10 |
| `resume_en.pdf` | 12/12 | 0.0% | 1 | ~7.5 s | exact ×12 |
| `resume_two_column.pdf` | 7/7 | 0.0% | 2 | ~21.4 s | exact ×7 |
| `resume_mixed_scan.pdf` | 4/4 | 0.0% | 1 | ~5.5 s | exact ×4 |
| `resume_multipage.pdf` | 0/0 | — | 1 | ~3.5 s | (correctly empty — the fixture is a page-marker document, not a resume) |

Observations worth keeping:

- **Final hallucination rate 0% across the board**, and every verified quote was a
  tier-1 exact match — including all the Thai. The feared failure modes (Thai
  reformatting breaking verification, `RawClaim | None` rejected by the schema
  path, mid-JSON truncation) did not appear on these documents.
- **The two-column fixture needed the retry loop**: the first attempt cited quotes
  that did not verify against the interleaved text, and the second attempt
  recovered to 7/7. The guardrail and the retry both earned their keep on the
  exact document class M2's column detection targets.
- The multipage fixture extracting to nothing is the honest result — the model
  declined to invent a candidate from a project list.
- Cost recorded: $0.000000 per document (free tier).

These are single runs over synthetic fixtures — a smoke signal, not the M6
evaluation.

## Cost, if you were to use Claude instead

Rough figures for one application (extract a profile, then judge ~9 requirements in
M3), with prompt caching on the stable prefix:

| Model | Input / output per MTok | Per application |
|---|---|---|
| `claude-opus-5` | $5 / $25 | ~$0.16 |
| `claude-haiku-4-5` | $1 / $5 | ~$0.035 |

Across a project — assuming the fake backend covers day-to-day development and real
calls are reserved for validation — 200–500 real runs comes to roughly $30–80 on
Opus 5 or $7–18 on Haiku 4.5. Re-running everything after each prompt tweak
multiplies that several times over.

The free Gemini tier removes this line item entirely, which is why it is the
default.

## Why `anthropic` is not implemented

The seam exists and the registry names it, but there is no adapter. An adapter that
has never run against the real API is worse than an honest error: it looks finished
and fails at the worst moment. Adding one is small — a `messages.parse()` call with
`output_format`, plus `cache_control` on the stable prefix — and worth doing at the
same time as the first real key.

Three parameters to keep in mind when it is added, all of which return a 400 on
current Claude models: `temperature` / `top_p` / `top_k`, `budget_tokens` (use
`output_config.effort` instead), and assistant-turn prefill. Also note thinking is
on by default on Opus 5 and `max_tokens` caps thinking *plus* response text, so a
budget sized for the answer alone will truncate.
