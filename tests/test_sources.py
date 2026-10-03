from drift_roadbook.sources import _related


def test_related_keeps_overlapping_titles_only():
    assert _related("哲学之道", "京都 哲学之道")
    assert _related("Pingjiang Road", "pingjiang road canal")
    assert not _related("埔里", "京都 哲学之道")
    assert not _related("Bergen", "Suzhou canal")


def test_latin_titles_need_a_shared_word():
    assert not _related("Bergen", "suzhou canal garden")
    assert _related("Hoan Kiem Lake", "hanoi hoan kiem lake at sunrise")
