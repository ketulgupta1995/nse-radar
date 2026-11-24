import json

import pandas as pd
import pytest

from app import db
from app.analytics import custom_indicators as ci
from app.analytics import indicators
from app.jobs import runner

GOOD = "def compute(frame, bench, n=20):\n    return frame.close.rolling(n).mean()\n"
SCHEMA = [{"name": "n", "kind": "int", "default": 20, "min": 2, "max": 100, "label": "Days"}]


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    for name in [d["name"] for d in indicators.catalogue() if d["custom"]]:
        indicators.unregister(name)


def body(code=GOOD, name="my_avg", schema=SCHEMA):
    return {"name": name, "params_schema": schema, "explain": "Average of the last {n} closes", "code": code}


def wrap(line: str) -> str:
    return f"def compute(frame, bench):\n    {line}\n"


@pytest.mark.parametrize(
    "code",
    [
        "import os\n",
        wrap("import os"),
        wrap("return open('x')"),
        wrap("return frame.__class__"),
        wrap("return eval('1')"),
        wrap("return pd.read_pickle('x')"),
        wrap("return frame.to_csv('x')"),
        wrap("return np.fromfile('x')"),
        wrap("return frame.query('close > 1')"),
        wrap("return frame.close.apply(abs)"),
        wrap("return getattr(frame, 'close')"),
        wrap("return pd.io.common"),
        "def compute(frame, bench):\n    return frame.close\nx = 1\n",
        "x = 1\n",
        "def compute(frame, bench):\n    return frame.close\n" + "#" * 4000,
    ],
)
def test_static_check_rejects(code):
    assert ci.static_check(code)


def test_static_check_accepts_simple():
    assert ci.static_check(GOOD) == []


@pytest.mark.parametrize(
    "line",
    [
        "return np.ctypeslib.load_library('x', '.')",
        "return pd.HDFStore('x')",
        "return pd.ExcelWriter('x')",
        "return np.DataSource().open('http://x')",
        "return np.f2py",
        "return '{0.__class__}'.format(1)",
        "return frame.style",
        "return pd.util",
        "return np.distutils",
    ],
)
def test_allowlist_rejects_escapes(line):
    assert ci.static_check(wrap(line))


@pytest.mark.parametrize(
    "line",
    [
        "return frame.close.rolling(20).mean()",
        "return (frame.high - frame.low).rolling(14).mean()",
        "return (frame.close / bench).pct_change(20)",
        "return pd.Series(np.where(frame.close > frame.close.shift(1), 1.0, 0.0), index=frame.index)",
    ],
)
def test_allowlist_accepts(line):
    assert ci.static_check(wrap(line)) == []


def test_allowed_vocabulary_sorted():
    v = ci.allowed_vocabulary()
    assert v == sorted(set(v)) and "rolling" in v and "format" not in v


def test_post_never_executes(client):
    code = "def compute(frame, bench):\n    while True:\n        pass\n"
    r = client.post("/api/custom-indicators", json=body(code, schema=[]))
    assert r.status_code == 200
    assert r.json()["status"] == "pending" and r.json()["problems"] == []
    raiser = "def compute(frame, bench):\n    raise ValueError('boom')\n"
    r = client.post("/api/custom-indicators", json=body(raiser, name="raiser", schema=[]))
    assert r.status_code == 200 and r.json()["status"] == "pending"


def test_post_stores_problems_and_rejects_bad_names(client):
    r = client.post("/api/custom-indicators", json=body(wrap("import os"), schema=[]))
    assert r.status_code == 200 and r.json()["problems"]
    assert client.post("/api/custom-indicators", json=body(name="Bad Name")).status_code == 400
    assert client.post("/api/custom-indicators", json=body(name="sma")).status_code == 400
    assert (
        client.post("/api/custom-indicators", json=body(name="dup_one", schema=[{"name": "n"}])).status_code
        == 400
    )


def test_trial_run_ok_and_wrong_length():
    ok = ci.trial_run(GOOD, {"n": 20})
    assert ok["ok"] and len(ok["sample"]) == 5
    bad = ci.trial_run("def compute(frame, bench):\n    return frame.close.iloc[:10]\n", {})
    assert not bad["ok"] and "10" in bad["error"]


def test_trial_run_timeout(monkeypatch):
    monkeypatch.setattr(ci, "TRIAL_TIMEOUT", 1.0)  # the code loops forever
    r = ci.trial_run("def compute(frame, bench):\n    while True:\n        pass\n", {})
    assert not r["ok"] and "longer than" in r["error"]


def approve(client, cid: int) -> dict:
    """POST approve (the request never runs the code), then run the queued job like the worker would."""
    r = client.post(f"/api/custom-indicators/{cid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"  # nothing executed on the request (SPEC §17.2)
    run_id = r.json()["run_id"]
    assert runner.run_one("interactive") == run_id
    return client.get(f"/api/jobs/runs/{run_id}").json()


def test_approve_timeout_stays_pending(client, monkeypatch):
    monkeypatch.setattr(ci, "TRIAL_TIMEOUT", 1.0)  # the code loops forever
    code = "def compute(frame, bench):\n    while True:\n        pass\n"
    cid = client.post("/api/custom-indicators", json=body(code, name="looper", schema=[])).json()["id"]
    run = approve(client, cid)
    assert run["status"] == "done" and run["failed"] == 1
    assert run["message"].startswith("Could not approve") and "longer than" in run["message"]
    assert client.get("/api/custom-indicators").json()[0]["status"] == "pending"
    with pytest.raises(ValueError):
        indicators.get("looper")


def test_approve_refuses_at_once_without_running(client):
    cid = client.post("/api/custom-indicators", json=body("import os\n", name="bad_one")).json()["id"]
    assert client.post(f"/api/custom-indicators/{cid}/approve").status_code == 400
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 0


def test_approve_registers_and_pending_not_loaded(client):
    cid = client.post("/api/custom-indicators", json=body()).json()["id"]
    client.post("/api/custom-indicators", json=body(name="other_one"))
    ci.load_approved()
    with pytest.raises(ValueError):
        indicators.get("my_avg")
    run = approve(client, cid)
    assert run["status"] == "done" and run["ok"] == 1
    assert run["message"].startswith("Approved. Trial run")
    assert len(run["message"].rsplit(": ", 1)[1].split(", ")) == 5  # the last 5 trial values
    statuses = {r["id"]: r["status"] for r in client.get("/api/custom-indicators").json()}
    assert statuses[cid] == "approved"
    frame = pd.DataFrame({"close": [float(i) for i in range(1, 31)]})
    out = indicators.compute("my_avg", frame, None, n=5)
    assert out.iloc[-1] == pytest.approx(28.0)
    assert indicators.get("my_avg").custom
    # reload from the database
    indicators.unregister("my_avg")
    assert ci.load_approved() == 1
    assert indicators.get("my_avg").custom
    with pytest.raises(ValueError):
        indicators.get("other_one")


def test_reject_and_delete(client):
    cid = client.post("/api/custom-indicators", json=body()).json()["id"]
    assert approve(client, cid)["ok"] == 1
    rule = {"all": [{"left": {"ind": "my_avg"}, "op": ">", "right": {"value": 1}}]}
    with db.tx() as c:
        c.execute(
            "INSERT INTO screens (name, rule, created_at, updated_at) VALUES ('s', ?, 'x', 'x')",
            (json.dumps(rule),),
        )
    assert client.delete(f"/api/custom-indicators/{cid}").status_code == 400
    with db.tx() as c:
        c.execute("DELETE FROM screens")
    assert client.post(f"/api/custom-indicators/{cid}/reject").json()["status"] == "rejected"
    with pytest.raises(ValueError):
        indicators.get("my_avg")
    assert client.delete(f"/api/custom-indicators/{cid}").status_code == 200
    assert client.get("/api/custom-indicators").json() == []
