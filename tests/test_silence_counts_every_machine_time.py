"""A silence holds no time this machine wrote, of any record.

Found working "was this machine unused for a while": every one of the 30
silences reported on the exhibit held machine-side times -- the longest,
23 Nov to 7 Dec, held cache uses at nine distinct minutes on 25 Nov,
because each record took part only through its one key instant. A record
also shows the machine at work when its cache entry was used, written or
re-checked with the server; the server's own dates are not activity."""
from webcache.engine.forensic_engine import ForensicEngine

DAY = 864_000_000_000                     # one day in FILETIME units
BASE = 134_100_000_000_000_000


def _ft(day):
    return BASE + day * DAY


def _history(day, **times):
    e = {"ContainerType": "History", "ModifiedTime_raw": _ft(day)}
    e.update({k: _ft(v) for k, v in times.items()})
    return e


def _engine(extra):
    records = ([_history(d) for d in range(0, 10)]
               + [_history(d) for d in range(30, 40)] + extra)
    eng = ForensicEngine()
    eng.load_entries(records)
    return eng


def _spans(eng):
    return sorted((v["From"][:10], v["To"][:10])
                  for v in eng.analyze_time_voids(min_gap_hours=48))


def test_with_nothing_inside_the_gap_is_one_silence():
    assert len(_spans(_engine([]))) == 1


def test_a_cache_use_inside_the_gap_breaks_it():
    use = _history(5, AccessedTime_raw=20)
    spans = _spans(_engine([use]))
    assert len(spans) == 2, spans


def test_a_re_check_with_the_server_inside_the_gap_breaks_it():
    spans = _spans(_engine([_history(5, SyncTime_raw=20)]))
    assert len(spans) == 2, spans


def test_a_cached_files_server_date_inside_the_gap_does_not():
    cached = {"ContainerType": "Content", "ModifiedTime_raw": _ft(20),
              "AccessedTime_raw": _ft(5), "CreationTime_raw": _ft(5)}
    assert len(_spans(_engine([cached]))) == 1
