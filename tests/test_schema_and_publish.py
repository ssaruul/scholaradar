import json
from datetime import date
from pathlib import Path

from scholaradar.llm.schema import Opportunity, opportunity_json_schema
from scholaradar.publish.csv_export import write_csv
from scholaradar.publish.site import write_site

ROOT = Path(__file__).resolve().parents[1]


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_schema_is_grammar_friendly() -> None:
    schema = opportunity_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(Opportunity.model_fields)
    assert all("format" not in node for node in _walk(schema))


def test_opportunity_roundtrip() -> None:
    payload = {
        "is_opportunity": True, "title": "GKS 2027", "provider": "NIIED", "host_country": "South Korea",
        "degree_levels": ["master", "phd"], "fields_of_study": [], "funding_type": "full", "deadline": "2027-03-01",
        "deadline_text": "March 1, 2027", "eligibility_summary": "Open to 150 countries including Mongolia.",
        "nationality_mode": "list", "target_eligible": "yes", "evidence_quote": "Mongolia", "apply_url": "",
    }
    opp = Opportunity.model_validate(payload)
    assert json.loads(opp.model_dump_json())["deadline"] == "2027-03-01"


SAMPLE_ROWS = [
    {
        "id": 1, "title": "Test <Scholarship>", "provider": "Org", "host_country": "Japan", "degree_levels": ["master"],
        "fields_of_study": ["engineering"], "funding_type": "full", "deadline": "2027-01-15", "deadline_text": "15 Jan 2027",
        "target_eligible": "yes", "evidence_verified": True, "nationality_mode": "list", "eligibility_summary": "Open to Mongolia.",
        "evidence_quote": "Mongolia is eligible.", "apply_url": "https://example.com/apply", "page_url": "https://example.com/page",
        "lang": "en", "first_seen": "2026-10-06T00:00:00+00:00", "extracted_at": "2026-10-06T00:00:00+00:00", "model": "test",
        "discovered_via": "source", "page_id": 1, "dismissed": 0,
    }
]


def test_site_and_csv_render(tmp_path: Path) -> None:
    index = write_site(tmp_path / "site", ROOT / "templates", SAMPLE_ROWS, "Mongolia", date(2026, 10, 6))
    html = index.read_text(encoding="utf-8")
    assert "Scholarship Radar" in html
    assert "Test <Scholarship>" in html
    assert "</script>" not in json.dumps(SAMPLE_ROWS[0]["title"])
    data = json.loads((tmp_path / "site" / "data.json").read_text(encoding="utf-8"))
    assert data[0]["title"] == "Test <Scholarship>"
    count = write_csv(tmp_path / "out.csv", SAMPLE_ROWS)
    assert count == 1
    assert "engineering" in (tmp_path / "out.csv").read_text(encoding="utf-8")
