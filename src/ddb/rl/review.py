"""Review allocator decisions: deterministic rules, and an LLM auditor.

Both read the ANONYMIZED decision report from ddb.rl.explain (no dates, no names,
standardized values only) and return the same shape:

    {"verdict": "approve" | "review" | "block",
     "scores": {"consistency": 1-5, "risk": 1-5, "data_quality": 1-5},   # 5 = best
     "flags": [{"type": ..., "severity": "low" | "medium" | "high", "text": ...}],
     "justification": "..."}

The reviewers MONITOR decisions; they are not a training reward. A policy trained
to please a reviewer learns to sound right, not to make money, and the LLM has no
knowledge of what is profitable. Use: dashboard flags, alerts, and in live trading
a human approval step for flagged trades.

`evaluate()` measures a reviewer on planted faults (over-concentration, buying in a
stress regime, an implausible return in the data, buying a collapsing sector) and
on unchanged decisions (false alarms), so its flags can be trusted or not on evidence.
"""
from __future__ import annotations

import copy
import json
import os
import re

import requests

from ..config import load

SEVERITY = {"low": 0, "medium": 1, "high": 2}
SCHEMA_KEYS = ("verdict", "scores", "flags", "justification")


def _verdict(flags) -> str:
    worst = max([SEVERITY.get(f.get("severity"), 0) for f in flags], default=-1)
    return "block" if worst == 2 else "review" if worst == 1 else "approve"


def _haven(name: str) -> bool:
    return name in ("Gold fund", "T-bill fund")


class RuleReviewer:
    """Deterministic checks. Always on; independent of any model."""

    def __init__(self, cfg: dict | None = None):
        self.c = cfg or load("review")["rules"]

    def review(self, rep: dict) -> dict:
        c, flags = self.c, []
        to = {w["asset"]: w["to"] for w in rep["weights"]}
        frm = {w["asset"]: w["from"] for w in rep["weights"]}
        sectors = {a: v for a, v in to.items() if not _haven(a)}
        for a, v in sectors.items():
            if v > c["max_single_sector_high"]:
                flags.append({"type": "concentration", "severity": "high", "text": f"{v:.0%} in {a} alone"})
            elif v > c["max_single_sector"]:
                flags.append({"type": "concentration", "severity": "medium", "text": f"{v:.0%} in {a} alone"})
        eq = sum(sectors.values())
        if rep.get("market_state") == "stress" and eq > c["max_equity_in_stress"]:
            flags.append({"type": "stress_buying", "severity": "high",
                          "text": f"{eq:.0%} in sectors during a stress regime (the model has lost money in stress)"})
        turnover = sum(abs(to[a] - frm.get(a, 0)) for a in to)
        if turnover > c["max_turnover"] and sum(frm.values()) > 0.05:   # first deployment from cash isn't churn
            flags.append({"type": "turnover", "severity": "medium", "text": f"turnover {turnover:.0%} in one decision"})
        lo, hi = c["implausible_4w_return"]
        for a, r in (rep.get("recent_4w_return") or {}).items():
            if r is not None and (r > hi or r < lo) and (to.get(a, 0) > 0 or frm.get(a, 0) > 0):
                flags.append({"type": "data_anomaly", "severity": "high",
                              "text": f"{a} 4-week return {r:+.0%} looks implausible: check the data before trading"})
        # (No "far from normal = bad data" rule: macro conditions do move far from the training
        # period, e.g. 2022 T-bill yields. Data errors show up as implausible returns above.)
        trend = {}
        for e in rep.get("evidence", []):
            if e.get("measure") in ("12-week return", "price vs its 200-day average") and e.get("standardized") is not None:
                trend[e["input_group"]] = min(trend.get(e["input_group"], 99), e["standardized"])
        for a, z in trend.items():
            if z <= c["weak_trend_z"] and to.get(a, 0) - frm.get(a, 0) > 0.1:
                flags.append({"type": "weak_sector_buying", "severity": "medium",
                              "text": f"adding {to[a] - frm.get(a, 0):.0%} to {a} while its trend is {z:+.1f} SD below normal"})
        risk = 5 - min(4, sum(1 + SEVERITY[f["severity"]] for f in flags if f["type"] in ("concentration", "stress_buying", "turnover")))
        dq = 5 - min(4, 2 * sum(f["type"] == "data_anomaly" for f in flags))
        cons = 5 - min(4, 2 * sum(f["type"] == "weak_sector_buying" for f in flags))
        return {"verdict": _verdict(flags), "scores": {"consistency": cons, "risk": max(risk, 1), "data_quality": dq},
                "flags": flags, "justification": "; ".join(f["text"] for f in flags) or "no rule triggered",
                "reviewer": "rules"}


SYSTEM = """You are a risk auditor for an automated investment allocator. Each week it splits a
portfolio across sector baskets, a gold fund, a T-bill fund and cash. You receive one decision
report: the weights before and after, what inputs drove the change (counterfactual attribution),
the evidence as standardized values (z-scores, 0 = normal), the market state, and each asset's
recent 4-week return.

Rules:
- Judge ONLY from the report. Do not guess dates, companies or events; the report is anonymized on
  purpose. Do not predict returns.
- Check: (1) consistency: does the action follow from the evidence and the attribution?
  (2) risk: concentration, turnover, buying sectors heavily in a stress regime, adding to a
  collapsing sector; (3) data quality: values that look implausible or missing evidence.
- Severity: high = should not trade without a human check; medium = worth a look; low = note.
- verdict: "block" if any high flag, "review" if any medium flag, otherwise "approve".

Return ONLY a JSON object:
{"verdict": "approve|review|block",
 "scores": {"consistency": 1-5, "risk": 1-5, "data_quality": 1-5},
 "flags": [{"type": "concentration|stress_buying|turnover|data_anomaly|weak_sector_buying|inconsistent|other",
            "severity": "low|medium|high", "text": "..."}],
 "justification": "3-6 sentences in plain language explaining the decision and your verdict"}"""


def parse(text: str) -> dict:
    """First JSON object in a model reply, checked and clamped to the schema."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    obj = json.loads(m.group(0))
    for k in SCHEMA_KEYS:
        if k not in obj:
            raise ValueError(f"missing {k}")
    flags = [f for f in obj["flags"] if isinstance(f, dict) and f.get("severity") in SEVERITY]
    scores = {k: int(min(5, max(1, int(obj["scores"].get(k, 3))))) for k in ("consistency", "risk", "data_quality")}
    verdict = obj["verdict"] if obj["verdict"] in ("approve", "review", "block") else _verdict(flags)
    return {"verdict": verdict, "scores": scores, "flags": flags, "justification": str(obj["justification"])}


class LLMReviewer:
    """OpenAI-compatible chat endpoint (vLLM, llama.cpp server). `post` can be
    replaced (tests, other clients): post(url, json, headers, timeout) -> dict."""

    def __init__(self, cfg: dict | None = None, post=None):
        self.c = cfg or load("review")["llm"]
        self._post = post or (lambda url, payload, headers, timeout:
                              requests.post(url, json=payload, headers=headers, timeout=timeout).json())

    def _ask(self, messages) -> str:
        c = self.c
        payload = {"model": c["model"], "messages": messages, "temperature": c.get("temperature", 0),
                   "max_tokens": c.get("max_tokens", 900)}
        if c.get("json_mode", True):
            payload["response_format"] = {"type": "json_object"}
        headers = {}
        key = os.environ.get(c.get("api_key_env") or "", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = self._post(c["base_url"].rstrip("/") + "/chat/completions", payload, headers, c.get("timeout_s", 120))
        return r["choices"][0]["message"]["content"]

    def review(self, rep: dict) -> dict:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Decision report:\n" + json.dumps(rep, indent=1)}]
        try:
            text = self._ask(msgs)
            try:
                out = parse(text)
            except (ValueError, json.JSONDecodeError):
                msgs += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "Reply again with ONLY the JSON object described, nothing else."}]
                out = parse(self._ask(msgs))
        except Exception as exc:  # noqa: BLE001 - an unreachable or broken reviewer must not pass silently
            return {"verdict": "review", "scores": {"consistency": 3, "risk": 3, "data_quality": 3},
                    "flags": [{"type": "other", "severity": "medium", "text": f"LLM reviewer unavailable: {exc}"[:200]}],
                    "justification": "The LLM review could not be completed.", "reviewer": "llm", "error": True}
        out["reviewer"] = "llm"
        return out


# ------------------------------------------------------------------ evaluation on planted faults
def plant(rep: dict, fault: str) -> dict:
    r = copy.deepcopy(rep)
    sectors = [w for w in r["weights"] if not _haven(w["asset"])]
    if fault == "concentration":
        for w in r["weights"]:
            w["to"] = 0.0
        sectors[0]["to"] = 0.9
    elif fault == "stress_buying":
        r["market_state"] = "stress"
        for w in r["weights"]:
            w["to"] = 0.0 if _haven(w["asset"]) else 0.95 / len(sectors)
    elif fault == "data_anomaly":
        held = max(sectors, key=lambda w: w["to"])
        held["to"] = max(held["to"], 0.15)
        r.setdefault("recent_4w_return", {})[held["asset"]] = 2.1
    elif fault == "weak_sector_buying":
        tgt = sectors[0]
        tgt["from"], tgt["to"] = 0.0, 0.3
        r.setdefault("evidence", []).append({"input_group": tgt["asset"], "measure": "12-week return",
                                             "standardized": -2.6, "reading": "far below normal"})
    else:
        raise ValueError(fault)
    return r


FAULTS = ("concentration", "stress_buying", "data_anomaly", "weak_sector_buying")


def evaluate(reviewer, reports: list[dict]) -> dict:
    """Detection rate per planted fault (verdict not 'approve' AND a flag of that type)
    and the false-alarm rate on the unchanged reports."""
    out = {}
    base = [reviewer.review(r) for r in reports]
    out["false_alarm_rate"] = sum(b["verdict"] != "approve" for b in base) / max(len(base), 1)
    for f in FAULTS:
        hits = 0
        for r in reports:
            v = reviewer.review(plant(r, f))
            hits += v["verdict"] != "approve" and any(x.get("type") == f for x in v["flags"])
        out[f"detect_{f}"] = hits / max(len(reports), 1)
    return out
