from __future__ import annotations

from pathlib import Path

import yaml

from ..urls import canonicalize


def load_overrides(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    table: dict[str, dict] = {}
    for item in raw.get("overrides", []) or []:
        if not item.get("url"):
            continue
        verdict = item.get("target_eligible")
        if isinstance(verdict, bool):
            item["target_eligible"] = "yes" if verdict else "no"
        table[canonicalize(item["url"])] = item
    return table


def apply_overrides(rows: list[dict], overrides: dict[str, dict]) -> list[dict]:
    if not overrides:
        return rows
    result = []
    for row in rows:
        keys = {canonicalize(row["page_url"])}
        if row["apply_url"]:
            keys.add(canonicalize(row["apply_url"]))
        match = next((overrides[key] for key in keys if key in overrides), None)
        if match is None:
            result.append(row)
            continue
        if match.get("dismiss"):
            continue
        fixed = dict(row)
        for field in ("target_eligible", "deadline", "title", "host_country", "provider", "funding_type"):
            if field in match and match[field] is not None:
                fixed[field] = str(match[field])
        if "degree_levels" in match:
            fixed["degree_levels"] = list(match["degree_levels"])
        if "target_eligible" in match or "deadline" in match:
            fixed["evidence_quote"] = f"Manual correction: {match.get('note', 'see config/overrides.yaml')}"
            fixed["evidence_verified"] = True
        result.append(fixed)
    return result
