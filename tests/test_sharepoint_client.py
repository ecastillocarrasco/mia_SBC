from __future__ import annotations

import pytest

from mia.sources.sharepoint import (
    ChangeTokenExpiredError,
    SharePointClient,
    SharePointError,
    StaticTokenProvider,
)
from tests.fakes.sharepoint import FakeSharePoint

SITE = "https://contoso.sharepoint.com/sites/rrhh"


def _client(
    fake: FakeSharePoint, tokens: StaticTokenProvider | None = None, retries: int = 3
) -> SharePointClient:
    return SharePointClient(
        site_url=SITE,
        tokens=tokens or StaticTokenProvider(),
        transport=fake.transport(),
        max_retries=retries,
        backoff_base=0,
    )


async def test_follows_pagination_until_the_end() -> None:
    fake = FakeSharePoint(page_size=2)
    for i in range(1, 6):
        fake.put("Empleados", {"ID": i, "Nombre": f"P{i}"})
    client = _client(fake)
    pages = [page async for page in client.iter_items("Empleados", select="ID,Nombre")]
    await client.aclose()
    assert [len(p) for p in pages] == [2, 2, 1]
    assert fake.requests[0].headers["Authorization"] == "Bearer test-token"
    assert fake.requests[0].url.params["$select"] == "ID,Nombre"


async def test_items_by_id() -> None:
    fake = FakeSharePoint(page_size=10)
    for i in range(1, 6):
        fake.put("L", {"ID": i})
    client = _client(fake)
    items = await client.items_by_id("L", [2, 4], select="ID")
    await client.aclose()
    assert [i["ID"] for i in items] == [2, 4]


async def test_retries_throttling_then_succeeds() -> None:
    fake = FakeSharePoint()
    fake.put("L", {"ID": 1})
    fake.fail_next = [429, 503]
    client = _client(fake)
    token = await client.current_change_token("L")
    await client.aclose()
    assert token == "t1"


async def test_refreshes_token_on_401() -> None:
    fake = FakeSharePoint()
    fake.fail_next = [401]
    tokens = StaticTokenProvider()
    client = _client(fake, tokens)
    await client.current_change_token("L")
    await client.aclose()
    assert tokens.refreshes == 1


async def test_gives_up_after_retries() -> None:
    fake = FakeSharePoint()
    fake.fail_next = [503, 503, 503]
    client = _client(fake, retries=2)
    with pytest.raises(SharePointError):
        await client.current_change_token("L")
    await client.aclose()


async def test_change_log_keeps_last_change_and_paginates() -> None:
    fake = FakeSharePoint()
    fake.put("L", {"ID": 1})
    start = await (c := _client(fake)).current_change_token("L")
    fake.put("L", {"ID": 2})
    fake.put("L", {"ID": 1, "v": 2})
    fake.remove("L", 2)
    changes, token = await c.changes_since("L", start, fetch_limit=2)
    await c.aclose()
    assert {(ch.item_id, ch.deleted) for ch in changes} == {(1, False), (2, True)}
    assert token == f"t{fake.seq}"


async def test_expired_token_is_detected() -> None:
    fake = FakeSharePoint()
    fake.expired_tokens.add("t0")
    client = _client(fake)
    with pytest.raises(ChangeTokenExpiredError):
        await client.changes_since("L", "t0")
    await client.aclose()
