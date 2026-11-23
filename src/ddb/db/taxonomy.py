"""Point-in-time industry tagging from SIC codes + dated company names."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from ..config import CONFIG_DIR

import yaml


@dataclass(frozen=True)
class Tag:
    industry: str
    sub_industry: str
    method: str
    matched: str
    confidence: str


class Taxonomy:
    def __init__(self, cfg: dict | None = None):
        if cfg is None:
            with open(CONFIG_DIR / "industries.yaml") as f:
                cfg = yaml.safe_load(f)
        self.exclude_sic = set(cfg.get("exclude_sic", []))
        self.low_kw = {k.lower() for k in cfg.get("low_confidence_keywords", [])}
        self.annual_forms = set(cfg.get("annual_report_forms", []))
        self.sic_map: dict[int, tuple[str, str]] = {}
        self.keywords: list[tuple[str, str, str]] = []
        for ind, body in cfg["industries"].items():
            for sub, rule in body["sub_industries"].items():
                for code in rule.get("sic", []) or []:
                    self.sic_map[int(code)] = (ind, sub)
                for kw in rule.get("keywords", []) or []:
                    self.keywords.append((kw.lower(), ind, sub))
        # Keywords match at the START of a word ("solar" -> "solaredge"). A keyword
        # written with a trailing space (e.g. " gene ") must match a whole word.
        self._kw_re = [(re.compile(r"(?<![a-z0-9])" + re.escape(kw.strip())
                                   + (r"(?![a-z0-9])" if kw.endswith(" ") else "")), kw, ind, sub)
                       for kw, ind, sub in self.keywords]
        self.industries = list(cfg["industries"])

    @staticmethod
    def _norm(name: str) -> str:
        return " " + re.sub(r"[^a-z0-9]+", " ", name.lower()) + " "

    def name_tags(self, name: str) -> set[Tag]:
        n = self._norm(name)
        tags = set()
        for rx, kw, ind, sub in self._kw_re:
            if rx.search(n):
                conf = "low" if kw in self.low_kw else "medium"
                tags.add(Tag(ind, sub, "keyword_name", kw.strip(), conf))
        return tags

    def sic_tag(self, sic) -> Tag | None:
        try:
            sic = int(sic)
        except (TypeError, ValueError):
            return None
        if sic in self.sic_map:
            ind, sub = self.sic_map[sic]
            return Tag(ind, sub, "sic", str(sic), "high")
        return None

    def tag_company(self, name_periods: list[tuple[str, pd.Timestamp, pd.Timestamp | None]],
                    sic, first_filing: pd.Timestamp) -> list[dict]:
        """Dated industry tags.

        name_periods: [(name, valid_from, valid_to)] sorted by valid_from, the last
        one being the current name (valid_to None).

        Keyword tags start when a matching name starts and carry forward through
        later neutral names, ending only when a later name matches a different
        industry. The current SIC applies from the first filing, unless an earlier
        name pointed to a different industry (a pivot). Then it starts at the first
        name after the pivot.
        """
        rows = []
        # --- keyword segments: (tags, start, end, end_of_last_matching_name)
        active: frozenset = frozenset()
        seg_start = last_match_end = None
        segments = []
        for name, start, end in name_periods:
            tags = frozenset(self.name_tags(name))
            if tags and {t.industry for t in tags} != {t.industry for t in active}:
                if active:
                    segments.append([active, seg_start, start, last_match_end])
                active, seg_start = tags, start
            if tags:
                last_match_end = end      # None while the matching name is current
        if active:
            segments.append([active, seg_start, None, last_match_end])

        # --- SIC tag (current code) and pivots
        st = self.sic_tag(sic)
        sic_row = None
        if st is not None:
            sic_start, conf = first_filing, st.confidence
            conflicting = [sg for sg in segments if st.industry not in {t.industry for t in sg[0]}]
            ongoing = any(sg[3] is None for sg in conflicting)
            if conflicting and not ongoing:
                # The company left the old industry when it dropped the matching name.
                cutoff = max(sg[3] for sg in conflicting)
                for sg in conflicting:
                    if sg[2] is None or sg[2] > cutoff:
                        sg[2] = cutoff
                sic_start, conf = cutoff, "medium"
            elif conflicting:
                conf = "medium"   # current name and SIC disagree (e.g. solar maker coded as semis)
            sic_row = {**st.__dict__, "confidence": conf, "valid_from": sic_start, "valid_to": None}

        for tags, start, end, _ in segments:
            for t in tags:
                rows.append({**t.__dict__, "valid_from": start, "valid_to": end})
        if sic_row:
            rows.append(sic_row)
        return rows
