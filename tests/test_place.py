"""place.resolve — httpx.MockTransport only, no real network."""
import time

import httpx
import pytest

from drift_roadbook import place as pl


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


HANOI = {"title": "Hoàn Kiếm Lake", "coordinates": {"lat": 21.0289, "lon": 105.8525}}


def test_direct_hit_is_spot_level():
    def h(req):
        assert "/page/summary/Hoan_Kiem_Lake" in str(req.url)
        return httpx.Response(200, json=HANOI)
    p = pl.resolve("Hoan Kiem Lake", "河内", client=_client(h))
    assert (p.name, p.lat, p.lon, p.level, p.wiki) == ("河内", 21.0289, 105.8525, "spot", "Hoàn Kiếm Lake")


def test_search_fallback_and_settlement_is_city_level():
    def h(req):
        u = str(req.url)
        if "/page/summary/Some_Cafe" in u:
            return httpx.Response(404, json={})
        if "/search/page" in u:
            return httpx.Response(200, json={"pages": [{"key": "No_Coords"}, {"key": "Hanoi"}]})
        if "/page/summary/No_Coords" in u:
            return httpx.Response(200, json={"title": "No coords"})
        if "/page/summary/Hanoi" in u:
            return httpx.Response(200, json={**HANOI, "title": "Hanoi", "description": "Capital city of Vietnam"})
        return httpx.Response(500)
    p = pl.resolve("Some Cafe", "河内", client=_client(h))
    assert p.wiki == "Hanoi" and p.level == "city"


def test_steps_down_to_broader_name_is_street_level():
    def h(req):
        u = str(req.url)
        if "/search/page" in u:
            return httpx.Response(200, json={"pages": []})
        if "/page/summary/Balat" in u and "Caddesi" not in u:
            return httpx.Response(200, json={"title": "Balat", "coordinates": {"lat": 41.03, "lon": 28.95},
                                             "description": "Neighbourhood in Fatih"})
        return httpx.Response(404, json={})
    p = pl.resolve("Kiremit Caddesi Balat", "伊斯坦布尔", client=_client(h))
    assert p.wiki == "Balat" and p.level == "street" and p.name == "伊斯坦布尔"


def test_zh_city_fallback():
    def h(req):
        u = str(req.url)
        if "zh.wikipedia.org" in u and "/page/summary/" in u:
            return httpx.Response(200, json={"title": "伊斯坦堡", "coordinates": {"lat": 41.01, "lon": 28.96}})
        if "/search/page" in u:
            return httpx.Response(200, json={"pages": []})
        return httpx.Response(404, json={})
    assert pl.resolve("Kiremit Caddesi Balat", "伊斯坦布尔", client=_client(h)).level == "city"
    assert pl.resolve("", "伊斯坦布尔", client=_client(h)).lat == 41.01


def test_nothing_found_or_network_error_keeps_city_only():
    def none(req):
        if "/search/page" in str(req.url):
            return httpx.Response(200, json={"pages": []})
        return httpx.Response(404, json={})

    def boom(req):
        raise httpx.ConnectError("boom")
    for h in (none, boom):
        p = pl.resolve("Nowhere", "某地", client=_client(h))
        assert p.name == "某地" and p.lat is None and p.lon is None


def test_empty_input_skips_network():
    def h(req):
        raise AssertionError("no request expected")
    assert pl.resolve(None, None, client=_client(h)).lat is None
    assert pl.resolve("  ", "", client=_client(h)).name is None


def test_request_budget_is_capped():
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        if "/search/page" in str(req.url):
            return httpx.Response(200, json={"pages": [{"key": "A"}, {"key": "B"}, {"key": "C"}]})
        return httpx.Response(200, json={"title": "no coords"})
    assert pl.resolve("w1 w2 w3 w4 w5 w6", "某地", client=_client(h)).lat is None
    assert n["c"] <= 13


@pytest.mark.parametrize("bad", [
    {"title": "X", "coordinates": [1]},
    {"title": 123, "coordinates": {"lat": 1, "lon": 2}},
    {"title": "X", "coordinates": {"lat": True, "lon": False}},
    {"title": "X", "coordinates": {"lat": float("nan"), "lon": 2}},
    {"title": "X", "coordinates": {"lat": 123, "lon": 5}},
    ["not", "a", "dict"],
])
def test_malformed_wiki_never_raises(bad):
    def h(req):
        if "/search/page" in str(req.url):
            return httpx.Response(200, json={"pages": "weird"})
        return httpx.Response(200, json=bad)
    p = pl.resolve("X", "某地", client=_client(h))
    assert p.name == "某地" and (p.lat is None) == (p.lon is None)
    assert p.wiki is None or isinstance(p.wiki, str)


def test_total_deadline():
    def slow(req):
        time.sleep(0.3)
        return httpx.Response(200, json={"title": "no coords"})
    t0 = time.monotonic()
    p = pl.resolve("a b c d", "某地", client=_client(slow), deadline=0.5)
    assert time.monotonic() - t0 < 1.5 and p.lat is None
