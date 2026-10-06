from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DegreeLevel = Literal["bachelor", "master", "phd", "postdoc", "research", "exchange", "short_course", "language", "other"]
FundingType = Literal["full", "partial", "tuition_only", "stipend_only", "unknown"]
NationalityMode = Literal["all", "list", "region", "unclear"]
Eligibility = Literal["yes", "no", "unclear"]


class Opportunity(BaseModel):
    is_opportunity: bool = Field(description="True only if the page describes one specific scholarship, fellowship, grant or funded programme that people can apply to")
    title: str = Field(description="Official name of the opportunity in the page language")
    provider: str = Field(description="Organisation funding or running it")
    host_country: str = Field(description="Country where the study or activity takes place, in English")
    degree_levels: list[DegreeLevel] = Field(max_length=6, description="Each level at most once")
    fields_of_study: list[str] = Field(max_length=8, description="Empty list if open to all fields")
    funding_type: FundingType
    deadline: str | None = Field(description="Application deadline as YYYY-MM-DD, or null if none is stated")
    deadline_text: str = Field(description="Deadline exactly as written on the page, empty if none")
    eligibility_summary: str = Field(description="One or two sentences on who can apply, in English")
    nationality_mode: NationalityMode = Field(description="all = any nationality; list = explicit country list; region = a region or group such as developing countries; unclear = not stated")
    target_eligible: Eligibility
    evidence_quote: str = Field(description="A verbatim sentence copied from the page that justifies target_eligible; empty string if the page says nothing explicit")
    apply_url: str = Field(description="Application or official page URL if present in the text, else empty string")


def opportunity_json_schema() -> dict[str, Any]:
    schema = Opportunity.model_json_schema()
    schema["additionalProperties"] = False
    return schema
