"""Decision explanations, anonymized reports and the reviewers."""
import json

import numpy as np
import pytest

from ddb.rl.explain import DATING, Explainer
from ddb.rl.review import FAULTS, LLMReviewer, RuleReviewer, evaluate, parse, plant

FEATS = ["mkt__points", "mkt__vix_pct", "tbill_yield", "tech__ret_12w", "tech__cand_score", "energy__ret_12w", "gold__trend"]
ASSETS = ["energy", "tech", "gold", "tbills"]


def make_obs(z):
    F, A = len(FEATS), len(ASSETS)
    o = np.zeros(2 * F + A + 2, np.float32)
    o[:F] = z
    o[2 * F + A] = 1.0
    return o


def market_only_policy(obs):
    obs = np.atleast_2d(obs)
    risk_off = (obs[:, 0] > 1)[:, None]                 # mkt__points z
    return np.where(risk_off, np.array([0, 0, .3, .7]), np.array([.5, .5, 0, 0]))


def test_attribution_isolates_the_driving_group():
    ex = Explainer(FEATS, ASSETS, ["energy", "tech"])
    obs = make_obs([2.0, 1.5, 3.0, -2.0, 0.5, 1.0, 0.2])
    action, attr = ex.attribute(market_only_policy, obs)
    assert np.allclose(action, [0, 0, .3, .7])
    assert np.abs(attr["market"]).sum() > 1 and all(np.abs(v).sum() == 0 for g, v in attr.items() if g != "market")


def test_anonymized_report_has_no_names_dates_or_dating_levels():
    import pandas as pd
    ex = Explainer(FEATS, ASSETS, ["energy", "tech"], seed=3)
    obs = make_obs([2.0, 1.5, 3.0, -2.0, 0.5, 1.0, 0.2])
    action, attr = ex.attribute(market_only_policy, obs)
    raw = pd.Series({"mkt__points": 3.0, "tech__ret_4w": 0.05, "energy__ret_4w": -0.02})
    rep = ex.report("2022-06-17", obs, action, np.array([.5, .5, 0, 0]), attr, raw)
    text = json.dumps(rep["anonymized"])
    assert "2022" not in text and "tech" not in text and "energy" not in text
    assert "T-bill yield" not in text                    # absolute macro levels are left out
    assert rep["anonymized"]["market_state"] == "stress" and rep["clear"]["date"] == "2022-06-17"
    assert {"Sector A", "Sector B"} <= set(rep["anonymized"]["recent_4w_return"])
    assert "tbill_yield" in DATING


def anon_report(**over):
    r = {"weights": [{"asset": "Sector A", "from": .2, "to": .2}, {"asset": "Sector B", "from": .2, "to": .2},
                     {"asset": "Sector C", "from": .2, "to": .2}, {"asset": "Gold fund", "from": .2, "to": .2},
                     {"asset": "T-bill fund", "from": .2, "to": .2}],
         "market_state": "calm", "recent_4w_return": {"Sector A": .03, "Sector B": -.02, "Sector C": .01},
         "evidence": [], "what_drove_it": []}
    r.update(over)
    return r


def test_rule_reviewer_catches_planted_faults_and_passes_normal():
    rr = RuleReviewer()
    assert rr.review(anon_report())["verdict"] == "approve"
    res = evaluate(rr, [anon_report(), anon_report(market_state="caution")])
    assert res["false_alarm_rate"] == 0 and all(res[f"detect_{f}"] == 1.0 for f in FAULTS)
    first = anon_report(weights=[{"asset": "Sector A", "from": 0, "to": .3}, {"asset": "T-bill fund", "from": 0, "to": .7}])
    assert not any(f["type"] == "turnover" for f in rr.review(first)["flags"])      # deploying cash is not churn


def test_llm_reviewer_parses_retries_and_fails_safe():
    good = {"verdict": "review", "scores": {"consistency": 4, "risk": 2, "data_quality": 5},
            "flags": [{"type": "concentration", "severity": "medium", "text": "x"}], "justification": "ok"}
    replies = iter(["Sure! Here you go: not json", json.dumps(good)])
    calls = []

    def post(url, payload, headers, timeout):
        calls.append(payload)
        return {"choices": [{"message": {"content": next(replies)}}]}
    lr = LLMReviewer({"base_url": "http://x/v1", "model": "m", "temperature": 0, "max_tokens": 10, "timeout_s": 1}, post=post)
    out = lr.review(anon_report())
    assert out["verdict"] == "review" and out["scores"]["risk"] == 2 and len(calls) == 2
    assert "2022" not in calls[0]["messages"][1]["content"]
    assert calls[0]["response_format"] == {"type": "json_object"}

    def down(*a):
        raise ConnectionError("refused")
    bad = LLMReviewer({"base_url": "http://x/v1", "model": "m"}, post=down).review(anon_report())
    assert bad["verdict"] == "review" and bad.get("error")              # unavailable never means "approve"
    with pytest.raises(ValueError):
        parse('{"verdict": "approve"}')


def test_plant_changes_only_what_it_claims():
    base = anon_report()
    p = plant(base, "data_anomaly")
    assert max(p["recent_4w_return"].values()) == 2.1 and base["recent_4w_return"]["Sector A"] == .03
