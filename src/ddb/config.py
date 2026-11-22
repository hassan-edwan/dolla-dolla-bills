from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"


def load(name: str) -> dict:
    with open(CONFIG_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f)


def universe_symbols(cfg: dict | None = None, include_pool: bool = True) -> dict[str, list[str]]:
    """Map group name -> tickers (core industries, rotating pool, havens, benchmarks)."""
    cfg = cfg or load("universe")
    groups = {k: v["candidates"] for k, v in cfg["core_industries"].items()}
    if include_pool:
        groups.update({f"pool:{k}": v["candidates"] for k, v in cfg["rotating"]["pool"].items()})
    haven = cfg["safe_haven"]
    groups["haven"] = sorted({s for k in ("gold", "silver", "tbills") for s in haven[k]})
    bench = set(cfg["benchmarks"]) | {v["benchmark"] for v in cfg["core_industries"].values()}
    if include_pool:
        bench |= {v["benchmark"] for v in cfg["rotating"]["pool"].values()}
    groups["benchmarks"] = sorted(bench)
    return groups
