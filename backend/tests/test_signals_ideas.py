from app.signals.ideas import best_rank, best_score, group_ideas, merged_reasons


def _s(id, symbol="AAA", as_of="2026-01-05", status="open", exit_date=None, score=None, reasons="[]",
       source="screen", rank=None):  # fmt: skip
    return {"id": id, "symbol": symbol, "as_of": as_of, "status": status, "exit_date": exit_date,
            "score": score, "reasons": reasons, "source": source, "rank": rank}  # fmt: skip


def test_repeats_while_open_join_one_idea():
    out = group_ideas([_s(3, as_of="2026-01-07"), _s(1, as_of="2026-01-05"), _s(2, as_of="2026-01-06")])
    assert len(out) == 1
    assert out[0]["anchor"]["id"] == 1
    assert [m["as_of"] for m in out[0]["members"]] == ["2026-01-05", "2026-01-06", "2026-01-07"]


def test_logging_after_exit_starts_new_idea():
    sigs = [
        _s(1, as_of="2026-01-05", status="closed", exit_date="2026-01-09"),
        _s(2, as_of="2026-01-08"),  # before exit: joins
        _s(3, as_of="2026-01-09"),  # on exit date: new idea
        _s(4, as_of="2026-01-12"),  # joins idea 3 (still open)
    ]
    out = group_ideas(sigs)
    assert [[m["id"] for m in i["members"]] for i in out] == [[1, 2], [3, 4]]


def test_pending_anchor_absorbs_repeats_and_symbols_never_mix():
    out = group_ideas([_s(1, status="pending"), _s(2, as_of="2026-02-01"), _s(3, symbol="BBB")])
    assert sorted(len(i["members"]) for i in out) == [1, 2]
    assert {i["anchor"]["symbol"] for i in out} == {"AAA", "BBB"}


def test_anchor_tiebreak_by_id_on_same_day():
    out = group_ideas([_s(9), _s(4)])
    assert out[0]["anchor"]["id"] == 4


def test_score_rank_reasons():
    members = [
        _s(1, score=60, reasons='["Trend", "Volume"]', source="shortlist", rank=7),
        _s(2, score=None, reasons='["Volume", "Cheap"]'),
        _s(3, score=72, reasons="not json", source="shortlist", rank=2),
    ]
    assert best_score(members) == 72
    assert best_score([_s(1)]) is None
    assert best_rank(members) == 2
    assert merged_reasons(members) == ["Trend", "Volume", "Cheap"]
