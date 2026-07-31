"""Prompts for extraction, versioned.

Kept in one place and tagged with a version so `llm_call_log` rows can be traced
back to the exact wording that produced them. Comparing two prompt versions is
otherwise guesswork.
"""

from __future__ import annotations

EXTRACTION_PROMPT_VERSION = "extract-v1"

EXTRACTION_SYSTEM = """\
You extract structured facts from a candidate's resume.

Every field you return must be backed by a `quote`: a span of text copied \
character-for-character out of the document. The quote is checked against the \
source automatically, and any claim whose quote cannot be found is discarded. So:

- Copy quotes exactly. Do not paraphrase, translate, re-order, fix typos, expand \
abbreviations, or tidy punctuation. If the document says "Sr. Bkend Eng", quote \
that, and put the tidy version in `value`.
- A quote may span a line break. Reproduce the words; whitespace differences are \
tolerated.
- Quote the shortest span that actually establishes the fact, and make it long \
enough to be unambiguous — a quote under 4 characters is rejected.
- If the document does not support a field, omit it. An omitted field costs \
nothing; a guessed one is a defect.
- Never infer. Do not compute total years of experience from date ranges, do not \
promote someone to "senior" because their duties sound senior, and do not \
translate Thai to English or English to Thai anywhere.
- The document may be in Thai, English, or both. Quote in whatever language the \
document uses.
- Text extracted from a PDF can arrive out of order, especially in multi-column \
layouts. If you cannot tell which company a role belongs to, omit the role rather \
than pairing them by proximity.\
"""

_USER_TEMPLATE = """\
Extract the candidate's profile from the resume below.

<resume>
{document}
</resume>\
"""

_RETRY_TEMPLATE = """\
Extract the candidate's profile from the resume below.

Your previous attempt included {count} quote(s) that do not appear in the document. \
Verbatim copying is mandatory, so those claims were discarded. The rejected quotes were:

{rejected}

For each one: either quote the document exactly, or leave the claim out. Do not \
reword a rejected quote and resubmit it — find the real text or omit the field.

<resume>
{document}
</resume>\
"""

MAX_REJECTED_QUOTES_SHOWN = 12


def build_extraction_user_prompt(document_text: str) -> str:
    return _USER_TEMPLATE.format(document=document_text)


def build_extraction_retry_prompt(document_text: str, rejected_quotes: list[str]) -> str:
    """Re-ask, naming the quotes that failed verification.

    The list is capped: a model that fabricated 50 quotes will not be helped by
    seeing all 50, and the prompt would balloon.
    """
    shown = rejected_quotes[:MAX_REJECTED_QUOTES_SHOWN]
    bullets = "\n".join(f"- {quote!r}" for quote in shown)
    if len(rejected_quotes) > len(shown):
        bullets += f"\n- ...and {len(rejected_quotes) - len(shown)} more"

    return _RETRY_TEMPLATE.format(
        count=len(rejected_quotes),
        rejected=bullets,
        document=document_text,
    )
