"""photo.PhotoFinder — MockTransport, fake narrator; no real network."""
import httpx

from drift_roadbook.photo import PhotoFinder

JPEG = b"\xff\xd8\xff\xe0fakejpeg"


def page(i, title, width=1600, mime="image/jpeg"):
    return {"index": i, "title": f"File:{title}", "imageinfo": [{
        "mime": mime, "width": width, "thumburl": f"https://upload.wikimedia.org/x/1280px-{i}.jpg",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{i}.jpg",
        "extmetadata": {"Artist": {"value": "<a>Someone</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "GPSLatitude": {"value": "31.31"}, "GPSLongitude": {"value": "120.63"}}}]}


def commons(pages_by_query, geo=None):
    def h(req):
        u = str(req.url)
        if "upload.wikimedia.org" in u:
            return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
        q = req.url.params.get("gsrsearch")
        if q is not None:
            return httpx.Response(200, json={"query": {"pages": {str(i): p for i, p in enumerate(pages_by_query.get(q, []))}}})
        return httpx.Response(200, json={"query": {"pages": {str(i): p for i, p in enumerate(geo or [])}}})
    return httpx.Client(transport=httpx.MockTransport(h))


class Eye:
    can_see_images = True

    def __init__(self, picks):
        self.picks = list(picks)
        self.seen = []

    def look(self, prompt, paths):
        self.seen.append((prompt, len(paths)))
        p = self.picks.pop(0)
        return '{"pick": %s, "why": "x"}' % ("null" if p is None else p)


def test_rejects_wrong_kinds_by_title_and_size():
    c = commons({"spot": [page(0, "Aerial view of Suzhou.jpg"), page(1, "Suzhou Wanda Plaza Block C.jpg"),
                          page(2, "Tiny.jpg", width=300), page(3, "Map of the canal.png", mime="image/png"),
                          page(4, "Riverside of Pingjiang Road.jpg")]})
    eye = Eye([0])
    ph = PhotoFinder(eye, client=c).find(["spot"], None, "我在石桥上看水")
    assert ph.page.endswith("4.jpg") and eye.seen[0][1] == 1
    assert ph.credit == "Someone · CC BY-SA 4.0" and ph.tier == "spot" and ph.lat == 31.31


def test_falls_back_to_street_tier_then_none():
    c = commons({"spot": [page(0, "Bridge.jpg")], "street": [page(1, "Street.jpg")]})
    ph = PhotoFinder(Eye([None, 0]), client=c).find(["spot", "street"], None, "游记")
    assert ph.tier == "street" and ph.page.endswith("1.jpg")
    assert PhotoFinder(Eye([None, None]), client=c).find(["spot", "street"], None, "游记") is None


def test_geotagged_candidates_join_the_spot_tier():
    c = commons({"spot": []}, geo=[page(7, "Near the spot.jpg")])
    ph = PhotoFinder(Eye([0]), client=c).find(["spot"], (31.3, 120.6), "游记")
    assert ph.page.endswith("7.jpg")


def test_without_eyes_no_photo():
    """Nobody can look → nobody can vouch for it → no photo (a wrong one is worse than none)."""
    c = commons({"spot": [page(0, "First.jpg"), page(1, "Second.jpg")]})
    assert PhotoFinder(None, client=c).find(["spot"], None, "游记") is None


def test_pick_index_follows_the_list_the_model_saw_and_rejects_bools():
    def h(req):
        u = str(req.url)
        if "upload.wikimedia.org" in u:
            if "-0.jpg" in u:                       # first candidate fails to download
                return httpx.Response(404)
            return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
        return httpx.Response(200, json={"query": {"pages": {str(i): p for i, p in enumerate(
            [page(0, "Broken.jpg"), page(1, "Wanted.jpg"), page(2, "Other.jpg")])}}})
    c = httpx.Client(transport=httpx.MockTransport(h))

    class Named(Eye):
        def look(self, prompt, paths):
            assert [p.rsplit("/", 1)[1] for p in paths] == ["0.jpg", "1.jpg"]
            return super().look(prompt, paths)
    assert PhotoFinder(Named([0]), client=c).find(["spot"], None, "游记").page.endswith("1.jpg")
    assert PhotoFinder(Eye(["true"]), client=c).find(["spot"], None, "游记") is None


def test_no_queries_no_coords_no_photo():
    assert PhotoFinder(Eye([]), client=commons({})).find([], None, "游记") is None
