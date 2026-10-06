from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = [
    "id", "title", "provider", "host_country", "degree_levels", "fields_of_study", "funding_type", "deadline", "deadline_text",
    "target_eligible", "evidence_verified", "nationality_mode", "eligibility_summary", "evidence_quote", "apply_url", "page_url",
    "lang", "first_seen", "extracted_at", "model",
]


def write_csv(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["degree_levels"] = ";".join(row["degree_levels"])
            flat["fields_of_study"] = ";".join(row["fields_of_study"])
            flat["evidence_verified"] = int(row["evidence_verified"])
            writer.writerow(flat)
    return len(rows)
