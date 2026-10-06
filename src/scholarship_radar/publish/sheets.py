from __future__ import annotations

import importlib
from pathlib import Path

from .csv_export import COLUMNS


def push_to_sheets(credentials_file: Path, spreadsheet_id: str, worksheet: str, rows: list[dict]) -> int:
    gspread = importlib.import_module("gspread")
    client = gspread.service_account(filename=str(credentials_file))
    spreadsheet = client.open_by_key(spreadsheet_id)
    titles = [sheet.title for sheet in spreadsheet.worksheets()]
    sheet = spreadsheet.worksheet(worksheet) if worksheet in titles else spreadsheet.add_worksheet(worksheet, rows=1000, cols=len(COLUMNS))
    values = [COLUMNS]
    for row in rows:
        flat = dict(row)
        flat["degree_levels"] = ";".join(row["degree_levels"])
        flat["fields_of_study"] = ";".join(row["fields_of_study"])
        flat["evidence_verified"] = int(row["evidence_verified"])
        values.append(["" if flat.get(column) is None else str(flat.get(column)) for column in COLUMNS])
    sheet.clear()
    sheet.update(values, "A1")
    return len(rows)
