"""Decision records: the format every model must use to explain itself.

A *run* is one model/strategy version. Each *decision* is one action on one
company on one date (buy / sell / hold, target weight, confidence). Each
decision carries *factors*: the inputs that drove it, with
  - value         what the model saw
  - contribution  signed push toward buying (+) or selling (-), in the model's units
                  (e.g. SHAP values for ML models, score terms for rules)
  - group         thesis / screen / context / risk ...
  - evidence      source table + reference (accession, URL, article) + knowable_at

THE NO-HINDSIGHT CHECK: record() refuses any factor whose knowable_at is
after the decision's as_of. The dashboard shows this check for every decision.

    from ddb.decisions import DecisionLog
    log = DecisionLog(con)
    run = log.new_run("momentum-12-1", params={...}, description="...")
    log.record(run, as_of, cik, ticker, "buy", target_weight=0.1, confidence=0.6, factors=[...])
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import pandas as pd

DDL = """
CREATE TABLE IF NOT EXISTS decision_runs (
    run_id VARCHAR PRIMARY KEY, model VARCHAR, description VARCHAR,
    params VARCHAR, created_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id VARCHAR PRIMARY KEY, run_id VARCHAR, as_of TIMESTAMPTZ, cik BIGINT, ticker VARCHAR,
    action VARCHAR, target_weight DOUBLE, prev_weight DOUBLE, confidence DOUBLE, score DOUBLE,
    rationale VARCHAR
);
CREATE TABLE IF NOT EXISTS decision_factors (
    decision_id VARCHAR, factor VARCHAR, factor_group VARCHAR, value DOUBLE, value_text VARCHAR,
    contribution DOUBLE, description VARCHAR, source_table VARCHAR, source_ref VARCHAR,
    knowable_at TIMESTAMPTZ
);
"""


class HindsightError(ValueError):
    pass


@dataclass
class Factor:
    factor: str
    contribution: float
    value: float | None = None
    value_text: str | None = None
    group: str = "thesis"
    description: str = ""
    source_table: str | None = None
    source_ref: str | None = None
    knowable_at: pd.Timestamp | None = None


@dataclass
class DecisionLog:
    con: object
    _pending: list = field(default_factory=list)

    def __post_init__(self):
        self.con.execute(DDL)

    def new_run(self, model: str, params: dict | None = None, description: str = "") -> str:
        run_id = f"{model}-{uuid.uuid4().hex[:8]}"
        self.con.execute("INSERT INTO decision_runs VALUES (?, ?, ?, ?, now())",
                         [run_id, model, description, json.dumps(params or {})])
        return run_id

    def record(self, run_id: str, as_of, cik: int, ticker: str, action: str, *, target_weight: float,
               prev_weight: float = 0.0, confidence: float | None = None, score: float | None = None,
               rationale: str = "", factors: list[Factor]) -> str:
        as_of = pd.Timestamp(as_of)
        as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
        for f in factors:
            if f.knowable_at is not None:
                k = pd.Timestamp(f.knowable_at)
                k = k.tz_localize("UTC") if k.tzinfo is None else k.tz_convert("UTC")
                if k > as_of:
                    raise HindsightError(f"factor {f.factor!r} knowable at {k} is after decision time {as_of}")
        did = uuid.uuid4().hex[:16]
        self._pending.append(("d", (did, run_id, as_of, int(cik), ticker, action, target_weight, prev_weight,
                                    confidence, score, rationale)))
        for f in factors:
            self._pending.append(("f", (did, f.factor, f.group, f.value, f.value_text, f.contribution,
                                        f.description, f.source_table, f.source_ref, f.knowable_at)))
        if len(self._pending) > 5000:
            self.flush()
        return did

    def flush(self):
        d = [x for k, x in self._pending if k == "d"]
        f = [x for k, x in self._pending if k == "f"]
        if d:
            self.con.executemany("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)", d)
        if f:
            self.con.executemany("INSERT INTO decision_factors VALUES (?,?,?,?,?,?,?,?,?,?)", f)
        self._pending = []
