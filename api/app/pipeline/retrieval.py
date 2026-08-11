"""Decide which resumes are worth paying to judge.

The pre-filter in front of screening, and the last slice of M3. A screening costs
one model call per resume; a shortlist of fifty makes that a real bill. Retrieval
orders the pile so the expensive step can be spent where it is most likely to pay
off.

**It is a hint, never a gate.** `retrieve` scores every document it is given and
returns all of them, ordered — it does not drop the tail. A retriever that silently
removed candidates would be the same failure as a UI that hides `excluded`
screenings: a person disappears from the process and nobody can see why. Choosing a
cut-off is the caller's decision, made in the open.

**It never touches what a screening sees.** Retrieval reads `document_text` and
reports overlapping terms; it produces no claim about a candidate, so there is
nothing here for `EvidenceResolver` to verify and nothing that can reach a verdict.
A `met` still requires a quote the application located in the document. This module
could be deleted and every verdict in the system would be unchanged — which is the
property that makes it safe to be approximate.

**A retrieval score is not a ranking score.** `pipeline/ranking.py` answers "what do
this candidate's citations prove"; this answers "does this document look worth
reading". They are different questions on different scales and must not be shown as
though they were comparable.

The backend is a seam with a no-server default, like `Storage` and `OCREngine`:
`LexicalRetriever` is pure Python over text the database already holds, so
`git clone && pytest -q` keeps working with no Postgres, no extension and no
embedding provider.
"""

from __future__ import annotations

import math
import re
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

from app.config import RetrievalBackend, Settings


class RetrievalError(Exception):
    """The retriever is selected but not usable."""


@dataclass(frozen=True)
class RetrievableDocument:
    """One resume, as retrieval sees it.

    A plain value object rather than the ORM row, so this module stays free of the
    database exactly as `judge.py` and `ranking.py` do, and so its tests need no
    session.
    """

    resume_id: str
    text: str


@dataclass(frozen=True)
class RetrievalHit:
    """One document's place in the order, and why it is there."""

    resume_id: str
    score: float
    """Relative, not absolute. Comparable between documents scored in the same
    call, and meaningless on its own — see the module docstring."""

    matched: list[str] = field(default_factory=list)
    """Which of the job's terms were found. The reason this is carried rather than
    just the number: a bare relevance score is exactly the sort of figure this
    project refuses to produce elsewhere, and a recruiter deciding where to spend a
    model call deserves to see what the decision rests on."""


class Retriever(ABC):
    """Orders documents by how well they match a job's terms."""

    @abstractmethod
    def retrieve(
        self, terms: list[str], documents: list[RetrievableDocument]
    ) -> list[RetrievalHit]:
        """Score every document and return them all, best first.

        Implementations must not drop low scorers: the order is the product, and
        the cut-off belongs to the caller.
        """


# ---------------------------------------------------------------------------
# Tokenizing text that may have no word boundaries
# ---------------------------------------------------------------------------

_THAI = r"฀-๿"
_LATIN_RUN = re.compile(rf"[^\W{_THAI}]+", re.UNICODE)
_THAI_RUN = re.compile(rf"[{_THAI}]+")

THAI_NGRAM = 3
"""Character n-gram length for Thai runs.

**Thai has no spaces between words**, which is not a detail — it decides this
module's design. Measured on `resume_th.pdf`: the document contains one unbroken
31-character run, `ดูแลระบบกระทบยอดการชำระเงินด้วย`, inside which sit the real terms
`ชำระเงิน` and `วิศวกรรม`. A whitespace tokenizer finds **neither**, while a plain
substring search finds both.

The measurement also shows why a test could hide this: `ทักษะ` happens to be
followed by a colon, so it *is* a standalone whitespace token and a naive
implementation looks correct on it. That is the two-column fixture with no header,
in a new costume — so the Thai cases in `tests/test_retrieval.py` deliberately use
terms buried mid-run.

3 is the usual choice for Thai character n-grams: 2 collides heavily across
unrelated words, and 4 starts to miss short ones. Most Thai syllables are 2–4
characters, so a 3-gram overlap survives the inflectional prefixes that a
dictionary-free tokenizer cannot strip.
"""

MIN_LATIN_TOKEN = 2
"""Below this a Latin token carries no signal — "a", "of", "3". Not a stopword
list: those are language-specific and this project handles two languages plus
whatever a resume mixes in."""


def _fold(text: str) -> str:
    """Case-fold and NFC-normalize, so matching does not depend on either.

    NFC because `parse.py` already normalizes `document_text` that way, and a term
    typed into a job form has not been through it.
    """
    return unicodedata.normalize("NFC", text).casefold()


def tokenize(text: str) -> list[str]:
    """Split mixed text into comparable units.

    Latin runs become whole words; Thai runs become overlapping character n-grams.
    Two scripts, two rules, because the alternative — one rule — is wrong for one of
    them and this project's documents routinely contain both in a single line.
    """
    folded = _fold(text)
    tokens: list[str] = []

    for match in _LATIN_RUN.finditer(folded):
        token = match.group()
        if len(token) >= MIN_LATIN_TOKEN:
            tokens.append(token)

    for match in _THAI_RUN.finditer(folded):
        run = match.group()
        if len(run) <= THAI_NGRAM:
            # Shorter than one n-gram: keep it whole rather than discarding a term
            # someone deliberately typed.
            tokens.append(run)
            continue
        tokens.extend(run[i : i + THAI_NGRAM] for i in range(len(run) - THAI_NGRAM + 1))

    return tokens


class LexicalRetriever(Retriever):
    """Score by term overlap, weighting rare terms above common ones.

    BM25's idea without its tuning knobs: a term that appears in every resume says
    nothing about which one to read, so it is worth less than one that appears in a
    few. Scoring runs over `document_text` the database already holds, in memory —
    no index to build, nothing to keep in sync, and it works on SQLite, which is
    what the test suite runs on.

    At this project's scale — one recruiter's resumes per job — that is the right
    trade. It is linear in total document length per request, so a deployment with
    thousands of resumes per job wants a real index; that is what the seam is for.
    """

    def retrieve(
        self, terms: list[str], documents: list[RetrievableDocument]
    ) -> list[RetrievalHit]:
        if not documents:
            return []

        # Each term keeps its own tokens so a hit can name the term a person typed
        # rather than the n-gram fragment that actually matched.
        term_tokens = [(term, set(tokenize(term))) for term in terms]
        term_tokens = [(term, tokens) for term, tokens in term_tokens if tokens]

        doc_tokens = [(doc, Counter(tokenize(doc.text))) for doc in documents]
        frequency = self._document_frequency([counts for _, counts in doc_tokens])
        total = len(documents)

        hits = [
            self._score(doc, counts, term_tokens, frequency, total) for doc, counts in doc_tokens
        ]

        # Descending score, then resume id — a total order, so a list never
        # reshuffles between identical runs. Ranking learned this the hard way
        # (docs/NOTES.md 2026-08-08); the same reasoning applies to any list a
        # person reads twice.
        hits.sort(key=lambda hit: (-hit.score, hit.resume_id))
        return hits

    @staticmethod
    def _document_frequency(counters: list[Counter[str]]) -> Counter[str]:
        frequency: Counter[str] = Counter()
        for counts in counters:
            frequency.update(counts.keys())
        return frequency

    @staticmethod
    def _score(
        document: RetrievableDocument,
        counts: Counter[str],
        term_tokens: list[tuple[str, set[str]]],
        frequency: Counter[str],
        total: int,
    ) -> RetrievalHit:
        score = 0.0
        matched: list[str] = []

        for term, tokens in term_tokens:
            present = [token for token in tokens if counts[token]]
            if not present:
                continue

            # The share of a term's tokens that appear at all. A Thai term is
            # several n-grams, so this is what stops a single incidental fragment
            # counting as much as the whole phrase.
            coverage = len(present) / len(tokens)

            # Smoothed IDF, averaged over the tokens that hit: a term every
            # document contains cannot help choose between them.
            idf = sum(math.log(1 + total / (1 + frequency[token])) for token in present) / len(
                present
            )

            score += coverage * idf
            matched.append(term)

        return RetrievalHit(resume_id=document.resume_id, score=score, matched=matched)


def build_retriever(settings: Settings) -> Retriever:
    """Construct the retriever named by `settings.retrieval_backend`."""
    match settings.retrieval_backend:
        case RetrievalBackend.LEXICAL:
            return LexicalRetriever()

        case RetrievalBackend.PGVECTOR:
            # Not implemented rather than half-implemented, exactly as
            # `LLM_PROVIDER=anthropic` is. Embeddings are a paid call, so this
            # adapter lands only together with a price table in the adapter and a
            # live verification run recorded in docs/llm-providers.md — a stale
            # price silently corrupts every cost figure, and an embedding backend
            # nobody has run is worse than an honest error.
            raise RetrievalError(
                "The pgvector retriever is not implemented yet. Use "
                "RETRIEVAL_BACKEND=lexical, which needs no server and no embedding "
                "provider."
            )
