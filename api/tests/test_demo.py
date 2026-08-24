"""The public demo: the guardrail, watched by somebody with no account.

The route exists so a visitor can see a fabricated quote refused rather than read
that one would be, which puts a specific burden on these tests: it is not enough
that the response *says* a claim was dropped. **The dropped quote has to be
genuinely absent from the document** — a demo that struck through a sentence the
document contains would teach the reader the opposite of the mechanism, and no
count or status code can tell them apart.

Three other properties are pinned here because a public route has nobody's
session to fall back on: it needs no account, it writes no rows, and it spends no
model call on whatever provider the deployment is configured with.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.demo import DEMO_DOCUMENT_TEXT, DEMO_REQUIREMENTS
from app.models import LLMCallLog


async def _row_count(sessionmaker: async_sessionmaker[AsyncSession], model: type) -> int:
    async with sessionmaker() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


class TestAStrangerMayWatchItRun:
    async def test_it_needs_no_account(self, client: AsyncClient):
        response = await client.get("/demo/screening")
        assert response.status_code == 200, response.text

    async def test_it_reports_the_document_every_offset_indexes_into(self, client: AsyncClient):
        body = (await client.get("/demo/screening")).json()
        assert body["document_text"] == DEMO_DOCUMENT_TEXT

    async def test_it_judges_every_requirement_the_posting_asks_for(self, client: AsyncClient):
        body = (await client.get("/demo/screening")).json()
        assert [item["label"] for item in body["requirements"]] == [
            spec.label for spec in DEMO_REQUIREMENTS
        ]

    # The verdict is derived from whether a quote resolved, so this is the same
    # assertion twice on purpose: `met` with no evidence, or `not_evidenced` with
    # some, would mean the two had come apart.
    async def test_every_verdict_is_backed_by_what_was_located(self, client: AsyncClient):
        body = (await client.get("/demo/screening")).json()
        for item in body["requirements"]:
            assert bool(item["evidence"]) is (item["verdict"] == "met"), item

    async def test_every_citation_slices_back_out_of_the_document(self, client: AsyncClient):
        body = (await client.get("/demo/screening")).json()
        text = body["document_text"]
        cited = [ref for item in body["requirements"] for ref in item["evidence"]]
        assert cited, "the demo shows nothing if it locates nothing"
        for ref in cited:
            assert text[ref["char_start"] : ref["char_end"]] == ref["quote"]

    # A demo where everything passes demonstrates nothing: the sentence worth
    # reading is the one beside a requirement the document does not evidence.
    async def test_something_is_left_unevidenced(self, client: AsyncClient):
        body = (await client.get("/demo/screening")).json()
        verdicts = {item["verdict"] for item in body["requirements"]}
        assert verdicts == {"met", "not_evidenced"}


class TestTheFabricationIsRefusedRatherThanDescribed:
    async def test_the_faithful_model_has_nothing_dropped(self, client: AsyncClient):
        body = (await client.get("/demo/screening", params={"mode": "faithful"})).json()
        assert body["dropped"] == []
        assert body["dropped_count"] == 0

    async def test_the_fabricating_model_has_exactly_one(self, client: AsyncClient):
        body = (await client.get("/demo/screening", params={"mode": "fabricating"})).json()
        assert body["dropped_count"] == 1
        assert len(body["dropped"]) == 1

    # **The assertion the demo rests on.** Everything else here would pass just as
    # well against a canned refusal; only this one says the quote on screen with a
    # line drawn through it is a quote the document really does not contain.
    async def test_the_dropped_quote_is_genuinely_not_in_the_document(self, client: AsyncClient):
        body = (await client.get("/demo/screening", params={"mode": "fabricating"})).json()
        quote = body["dropped"][0]["quote"]
        assert quote
        assert quote not in body["document_text"]
        assert body["dropped"][0]["reason"] == "not_found"

    # A fabricated quote must not be able to manufacture a verdict — the same
    # property `test_judge.py` pins on the pipeline, asserted here because this is
    # the surface a stranger judges the product by.
    async def test_a_fabrication_buys_no_verdict(self, client: AsyncClient):
        honest = (await client.get("/demo/screening", params={"mode": "faithful"})).json()
        lying = (await client.get("/demo/screening", params={"mode": "fabricating"})).json()
        assert [item["verdict"] for item in lying["requirements"]] == [
            item["verdict"] for item in honest["requirements"]
        ]

    async def test_an_unknown_mode_is_refused_rather_than_quietly_made_honest(
        self, client: AsyncClient
    ):
        response = await client.get("/demo/screening", params={"mode": "flattering"})
        assert response.status_code == 422


class TestItCostsNothingToRun:
    """A page a stranger can reload is a page a stranger can reload in a loop."""

    async def test_it_logs_no_model_call(self, client: AsyncClient):
        sessionmaker = client.app.state.sessionmaker  # type: ignore[attr-defined]
        before = await _row_count(sessionmaker, LLMCallLog)
        await client.get("/demo/screening")
        await client.get("/demo/screening", params={"mode": "fabricating"})
        assert await _row_count(sessionmaker, LLMCallLog) == before

    async def test_it_does_not_depend_on_the_configured_provider(self, client: AsyncClient):
        """The demo builds its own fake backend rather than taking `app.state`'s.

        Otherwise a deployment on a paid provider would bill a marketing page, and
        an outage on that provider would take the demo down with it.
        """
        app = client.app
        sentinel = object()
        app.state.extractor = sentinel  # type: ignore[attr-defined]
        response = await client.get("/demo/screening")
        assert response.status_code == 200
        assert app.state.extractor is sentinel  # type: ignore[attr-defined]
