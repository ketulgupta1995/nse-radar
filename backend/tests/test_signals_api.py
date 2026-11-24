import pandas as pd

from app import db
from app.analytics import frames


def _sig(c, source="screen", screen_id=1, name="S1", symbol="AAA", as_of="2026-01-05",
         rank=None, score=None):  # fmt: skip
    cur = c.execute(
        "INSERT INTO signals(source, screen_id, screen_name, symbol, as_of, rank, score, reasons, "
        "planned_entry, atr14, planned_stop, planned_target, exit_config, score_weights, "
        "app_version, bars_as_of, created_at) VALUES (?,?,?,?,?,?,?,'[\"r\"]',100,2,95,110,'{}','{}',"
        "'v','x','x')",
        (source, screen_id, name, symbol, as_of, rank, score),
    )  # fmt: skip
    return cur.lastrowid


def _out(c, sid, status="closed", ret=None, r=None, ex=None, days=None, exit_date=None):
    c.execute(
        "INSERT INTO signal_outcomes(signal_id, status, return_pct, r_multiple, excess_pct, "
        "days_held, exit_date, updated_at) VALUES (?,?,?,?,?,?,?,'x')",
        (sid, status, ret, r, ex, days, exit_date),
    )


def _group(body, key):
    return next(g for g in body["groups"] if g["key"] == key)


def test_list_filters_order_paging(client):
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha',1)")
        a = _sig(c, as_of="2026-01-05")
        b = _sig(c, as_of="2026-01-07")
        d = _sig(c, source="shortlist", screen_id=0, name=None, symbol="BBB", as_of="2026-01-06", rank=1)
        _out(c, a, "closed", 5)
        _out(c, d, "open", 1)
    body = client.get("/api/signals").json()
    assert body["total"] == 3
    assert [r["as_of"] for r in body["rows"]] == ["2026-01-07", "2026-01-06", "2026-01-05"]
    top = body["rows"][0]
    assert top["id"] == b and top["outcome"] is None and top["name"] == "Alpha"
    assert top["reasons"] == ["r"]
    assert body["rows"][2]["outcome"]["status"] == "closed"
    assert body["rows"][1]["name"] is None
    assert len(client.get("/api/signals?source=shortlist").json()["rows"]) == 1
    assert client.get("/api/signals?screen_id=1").json()["total"] == 2
    assert client.get("/api/signals?status=open").json()["total"] == 1
    assert client.get("/api/signals?symbol=aaa").json()["total"] == 2
    page = client.get("/api/signals?limit=1&offset=1").json()
    assert page["total"] == 3 and [r["as_of"] for r in page["rows"]] == ["2026-01-06"]


def test_summary_stats_and_enough(client):
    with db.tx() as c:
        old = _sig(c, name="Old name", symbol="A", as_of="2026-01-01")
        new = _sig(c, name="New name", symbol="B", as_of="2026-01-02")
        o = _sig(c, name="New name", symbol="C", as_of="2026-01-03")
        p = _sig(c, name="New name", symbol="D", as_of="2026-01-04")
        _out(c, old, "closed", 10, 2, 3, 4)
        _out(c, new, "closed", -5, -1, -2, 6)
        _out(c, o, "open", 99, 99, 99, 99)
        _ = p  # no outcome row -> pending
    body = client.get("/api/signals/summary").json()
    assert body["min_closed"] == 30
    g = _group(body, "screen:1")
    assert g["label"] == "New name" and g["kind"] == "screen"
    assert (g["n_closed"], g["n_open"], g["n_pending"]) == (2, 1, 1)
    assert g["hit_rate_pct"] == 50.0 and g["avg_return_pct"] == 2.5
    assert g["avg_r"] == 0.5 and g["avg_excess_pct"] == 0.5 and g["avg_days"] == 5.0
    assert g["enough"] is False
    empty = _group(body, "shortlist:rank1-3")
    assert empty["n_closed"] == 0 and empty["avg_return_pct"] is None and empty["hit_rate_pct"] is None
    assert [x["key"] for x in body["groups"]][-5:] == [
        "shortlist:rank1-3", "shortlist:rank4-10", "band:75+", "band:60-75", "band:<60"]

    with db.tx() as c:
        for i in range(27):
            _out(c, _sig(c, symbol=f"X{i}", as_of="2026-02-01"), "closed", 1, 1, 1, 1)
    assert _group(client.get("/api/signals/summary").json(), "screen:1")["enough"] is False
    with db.tx() as c:
        _out(c, p, "closed", 1, 1, 1, 1)
    g = _group(client.get("/api/signals/summary").json(), "screen:1")
    assert g["n_closed"] == 30 and g["enough"] is True


def test_summary_bands_and_ranks(client):
    with db.tx() as c:
        for i, sc in enumerate([75, 74.9, 60, 59.9, None]):
            _out(c, _sig(c, symbol=f"S{i}", score=sc), "closed", 1)
        _out(c, _sig(c, source="shortlist", screen_id=0, name=None, symbol="T1", rank=3, score=80),
             "closed", 2)  # fmt: skip
        _out(c, _sig(c, source="shortlist", screen_id=0, name=None, symbol="T2", rank=4, score=50),
             "open")  # fmt: skip
    body = client.get("/api/signals/summary").json()
    assert _group(body, "band:75+")["n_closed"] == 2
    assert _group(body, "band:60-75")["n_closed"] == 2
    low = _group(body, "band:<60")
    assert low["n_closed"] == 1 and low["n_open"] == 1
    assert _group(body, "shortlist:rank1-3")["n_closed"] == 1
    assert _group(body, "shortlist:rank4-10")["n_open"] == 1
    assert _group(body, "shortlist:rank1-3")["label"] == "Shortlist #1–3"
    assert low["label"] == "Score under 60"


def test_coverage_counts_benchmark_dates(client, monkeypatch):
    with db.tx() as c:
        for d in ("2026-01-05", "2026-01-09"):
            c.execute("INSERT INTO signal_days(as_of, logged, run_at) VALUES (?,1,'x')", (d,))
    idx = pd.DatetimeIndex(pd.to_datetime(
        ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-09", "2026-01-12"]))
    monkeypatch.setattr(frames, "load_benchmark", lambda start=None: pd.Series(1.0, index=idx))
    cov = client.get("/api/signals/summary").json()["coverage"]
    assert cov == {"first_day": "2026-01-05", "last_day": "2026-01-09",
                   "days_logged": 2, "trading_days": 4}  # fmt: skip


def test_coverage_empty(client):
    cov = client.get("/api/signals/summary").json()["coverage"]
    assert cov == {"first_day": None, "last_day": None, "days_logged": 0, "trading_days": 0}


def test_ideas_group_filter_sort_page(client):
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('AAA','Alpha Ltd',1)")
        a1 = _sig(c, screen_id=1, name="Momentum", as_of="2026-01-05", score=60)
        _sig(c, screen_id=2, name="Value", as_of="2026-01-06", score=70)
        _sig(c, source="shortlist", screen_id=0, name=None, as_of="2026-01-07", rank=2)
        _out(c, a1, "open", 3, 0.5)
        b = _sig(c, symbol="BBB", as_of="2026-01-08")
        _out(c, b, "closed", -4, -1, exit_date="2026-01-20")
        d = _sig(c, symbol="CCC", as_of="2026-01-02")
        _out(c, d, "closed", 6, 2, exit_date="2026-01-25")
        _sig(c, symbol="DDD", as_of="2026-01-09")  # no outcome -> pending
    body = client.get("/api/signals/ideas").json()
    assert body["total"] == 4
    assert body["counts"] == {"open": 1, "pending": 1, "closed": 2, "no_data": 0}
    assert [r["symbol"] for r in body["rows"]] == ["DDD", "BBB", "AAA", "CCC"]
    aaa = body["rows"][2]
    assert aaa["id"] == a1 and aaa["name"] == "Alpha Ltd" and aaa["score"] == 70
    assert (aaa["first_as_of"], aaa["last_as_of"]) == ("2026-01-05", "2026-01-07")
    assert [s["screen_name"] for s in aaa["seen"]] == ["Momentum", "Value", None]
    assert aaa["outcome"]["status"] == "open" and aaa["reasons"] == ["r"]
    assert "current_price" in aaa

    def syms(qs: str) -> list[str]:
        return [r["symbol"] for r in client.get(f"/api/signals/ideas?{qs}").json()["rows"]]

    assert syms("screen_id=2") == ["AAA"]  # matched through a non-anchor logging
    assert syms("source=shortlist") == ["AAA"]
    assert syms("q=alpha") == ["AAA"] and syms("q=bb") == ["BBB"]
    assert syms("since=2026-01-07") == ["DDD", "BBB", "AAA"]
    assert syms("status=closed") == ["CCC", "BBB"]  # newest exit first
    assert syms("status=pending") == ["DDD"]
    filtered = client.get("/api/signals/ideas?status=open&q=zzz").json()
    assert filtered["total"] == 0 and sum(filtered["counts"].values()) == 0
    page = client.get("/api/signals/ideas?limit=2&offset=1").json()
    assert page["total"] == 4 and [r["symbol"] for r in page["rows"]] == ["BBB", "AAA"]


def test_ideas_new_idea_after_exit(client):
    with db.tx() as c:
        a = _sig(c, as_of="2026-01-05")
        _out(c, a, "closed", 5, 1, exit_date="2026-01-10")
        _sig(c, screen_id=2, name="S2", as_of="2026-01-08")  # joins first idea
        _sig(c, as_of="2026-01-12")  # starts a second idea
    rows = client.get("/api/signals/ideas").json()["rows"]
    assert [len(r["seen"]) for r in rows] == [1, 2]


def test_summary_counts_ideas(client):
    with db.tx() as c:
        a = _sig(c, screen_id=1, name="Momentum", as_of="2026-01-05", score=80)
        _sig(c, screen_id=2, name="Value", as_of="2026-01-06", score=50)
        _sig(c, screen_id=1, name="Momentum", as_of="2026-01-07")
        _out(c, a, "closed", 5, 1, 1, 3, exit_date="2026-01-20")
    body = client.get("/api/signals/summary").json()
    assert (body["n_signals"], body["n_ideas"]) == (3, 1)
    assert _group(body, "screen:1")["n_closed"] == 1
    assert _group(body, "screen:2")["n_closed"] == 1
    assert _group(body, "band:75+")["n_closed"] == 1  # idea score = highest member score
    assert _group(body, "band:<60")["n_closed"] == 0
