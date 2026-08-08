"""Prompts for extraction, versioned.

Kept in one place and tagged with a version so `llm_call_log` rows can be traced
back to the exact wording that produced them. Comparing two prompt versions is
otherwise guesswork.
"""

from __future__ import annotations

from app.schemas.judgment import RequirementSpec

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


JUDGMENT_PROMPT_VERSION = "judge-v1"

JUDGMENT_SYSTEM = """\
You decide which of a job's requirements a candidate's resume shows evidence for.

You do this **only** by quoting the resume. For each requirement the resume \
supports, return the requirement's number and one or more quotes copied \
character-for-character out of the document. Every quote is checked against the \
source automatically, and any quote that cannot be found is discarded.

The single rule that matters most:

- **Only ever report requirements the resume DOES show.** If the resume does not \
show a requirement, leave that requirement out of your answer entirely. Do not \
report it with an empty quote list, do not explain its absence, and never state \
that the candidate lacks something. You are not being asked whether a candidate is \
qualified — you are being asked what the document says.

And the copying rules, which are the same as everywhere else in this system:

- Copy quotes exactly. Do not paraphrase, translate, re-order, fix typos, expand \
abbreviations, or tidy punctuation.
- A quote may span a line break. Reproduce the words; whitespace differences are \
tolerated.
- Quote the shortest span that actually establishes the requirement, and make it \
long enough to be unambiguous — a quote under 4 characters is rejected. Prefer the \
whole line a skill sits on over the bare word.
- Quote only from the resume, never from the requirement list. A requirement's own \
wording is not evidence that the candidate meets it.
- Use the requirement numbers exactly as given. Do not invent a number that is not \
in the list, and do not renumber.
- The document may be in Thai, English, or both. Quote in whatever language the \
document uses, and match a Thai requirement against Thai text.
- Text extracted from a PDF can arrive out of order, especially in multi-column \
layouts. If you cannot tell whether a line belongs to the candidate's own \
experience, leave the requirement out rather than guessing.\
"""

# The requirement list sits OUTSIDE <resume>, and that placement is load-bearing:
# `app/llm/fake.py` finds the document by this exact block, so a list inside it
# would be quoted as though it were the resume. It also matches what the model is
# told above — the resume is the only place a quote may come from.
_JUDGMENT_TEMPLATE = """\
Decide which of these requirements the resume below shows evidence for.

Requirements:
{requirements}

<resume>
{document}
</resume>\
"""

_JUDGMENT_RETRY_TEMPLATE = """\
Decide which of these requirements the resume below shows evidence for.

Your previous attempt included {count} quote(s) that do not appear in the resume. \
Verbatim copying is mandatory, so those were discarded. The rejected quotes were:

{rejected}

For each one: either quote the resume exactly, or leave the requirement out. Do not \
reword a rejected quote and resubmit it, and do not quote the requirement list to \
fill the gap — find the real text or report nothing for that requirement.

Requirements:
{requirements}

<resume>
{document}
</resume>\
"""


def format_requirements(requirements: list[RequirementSpec]) -> str:
    """Number the requirements the way the model is asked to refer back to them.

    1-based, because `RawRequirementMatch.requirement` is: an integer is far cheaper
    than a UUID in tokens and, unlike a garbled UUID, a number outside the range is
    something the verifier can catch and report.
    """
    lines = []
    for index, requirement in enumerate(requirements, start=1):
        line = f"{index}. [{requirement.kind}] {requirement.label}"
        if requirement.detail:
            line += f"\n   detail: {requirement.detail}"
        lines.append(line)
    return "\n".join(lines)


def build_judgment_user_prompt(document_text: str, requirements: list[RequirementSpec]) -> str:
    return _JUDGMENT_TEMPLATE.format(
        requirements=format_requirements(requirements), document=document_text
    )


def build_judgment_retry_prompt(
    document_text: str, requirements: list[RequirementSpec], rejected_quotes: list[str]
) -> str:
    """Re-ask, naming the quotes that failed verification. Capped like extraction's."""
    shown = rejected_quotes[:MAX_REJECTED_QUOTES_SHOWN]
    bullets = "\n".join(f"- {quote!r}" for quote in shown)
    if len(rejected_quotes) > len(shown):
        bullets += f"\n- ...and {len(rejected_quotes) - len(shown)} more"

    return _JUDGMENT_RETRY_TEMPLATE.format(
        count=len(rejected_quotes),
        rejected=bullets,
        requirements=format_requirements(requirements),
        document=document_text,
    )
