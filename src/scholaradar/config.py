from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TargetConfig(BaseModel):
    name: str
    demonym: str
    names: dict[str, list[str]]

    def all_names(self) -> list[str]:
        seen: dict[str, None] = {}
        for names in self.names.values():
            for name in names:
                seen.setdefault(name, None)
        return list(seen)

    def name_for(self, lang: str) -> str:
        return self.names.get(lang, self.names["en"])[0]


class SearchConfig(BaseModel):
    base_url: str = "http://localhost:8888"
    queries_per_run: int = 100
    results_per_query: int = 10
    years_ahead: int = 1
    query_delay_seconds: float = 1.5
    language_map: dict[str, str] = Field(default_factory=dict)


class FetchConfig(BaseModel):
    per_host_delay_seconds: float = 2.0
    timeout_seconds: float = 20.0
    max_bytes: int = 3_000_000
    user_agent: str = "scholaradar/0.1"
    max_pages_per_run: int = 400
    source_recheck_hours: int = 20
    max_links_per_source: int = 40
    blocked_hosts: list[str] = Field(default_factory=list)


class LlmConfig(BaseModel):
    base_url: str = "http://localhost:8089/v1"
    model: str = "local"
    api_key: str = ""
    max_input_chars: int = 12000
    max_tokens: int = 2000
    temperature: float = 0.0
    timeout_seconds: float = 300.0
    concurrency: int = 4
    extra_body: dict[str, Any] = Field(default_factory=dict)


class PrefilterConfig(BaseModel):
    keywords: list[str]


class SiteOutput(BaseModel):
    enabled: bool = True
    dir: Path = Path("docs")
    pages_url: str = ""
    repo_url: str = "https://github.com/ssaruul/scholaradar"


class CsvOutput(BaseModel):
    enabled: bool = True
    path: Path = Path("docs/opportunities.csv")


class ReportOutput(BaseModel):
    enabled: bool = True
    dir: Path = Path("reports")
    window_days: int = 30


class SocialOutput(BaseModel):
    enabled: bool = False
    max_items: int = 8
    language: str = "en"
    only_eligible: bool = True
    page_id: str = ""
    chat_id: str = ""
    graph_version: str = "v23.0"


class GitOutput(BaseModel):
    enabled: bool = False
    push: bool = True
    remote: str = "origin"
    branch: str = "main"


class EmailOutput(BaseModel):
    enabled: bool = False
    only_new: bool = True
    subject_prefix: str = "[scholaradar]"


class SheetsOutput(BaseModel):
    enabled: bool = False
    spreadsheet_id: str = ""
    worksheet: str = "opportunities"
    credentials_file: Path = Path("service_account.json")


class OutputsConfig(BaseModel):
    funding: list[str] = Field(default_factory=list)
    site: SiteOutput = Field(default_factory=SiteOutput)
    csv: CsvOutput = Field(default_factory=CsvOutput)
    report: ReportOutput = Field(default_factory=ReportOutput)
    facebook: SocialOutput = Field(default_factory=SocialOutput)
    telegram: SocialOutput = Field(default_factory=SocialOutput)
    git: GitOutput = Field(default_factory=GitOutput)
    email: EmailOutput = Field(default_factory=EmailOutput)
    sheets: SheetsOutput = Field(default_factory=SheetsOutput)


class SourceConfig(BaseModel):
    name: str
    url: str
    kind: str = "page"
    lang: str = "en"
    enabled: bool = True
    follow_links: bool = False
    title_filter: bool = False
    implies_eligible: bool = False
    render: bool = False


class Settings(BaseModel):
    target: TargetConfig
    languages: list[str]
    search: SearchConfig = Field(default_factory=SearchConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    prefilter: PrefilterConfig
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    data_dir: Path = Path("data")
    root_dir: Path = Path(".")
    sources: list[SourceConfig] = Field(default_factory=list)
    query_templates: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "radar.sqlite"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def text_dir(self) -> Path:
        return self.data_dir / "text"

    @property
    def templates_dir(self) -> Path:
        return self.root_dir / "templates"


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    digest_from: str = ""
    digest_to: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    searx_base_url: str = ""
    git_push: str = ""
    facebook_page_id: str = ""
    facebook_page_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def load_settings(root_dir: Path) -> Settings:
    config_dir = root_dir / "config"
    raw = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    sources = yaml.safe_load((config_dir / "sources.yaml").read_text(encoding="utf-8"))
    queries = yaml.safe_load((config_dir / "queries.yaml").read_text(encoding="utf-8"))
    settings = Settings.model_validate(
        {
            **raw,
            "root_dir": root_dir.resolve(),
            "sources": sources.get("sources", []),
            "query_templates": queries.get("templates", {}),
        }
    )
    settings.data_dir = _resolve(settings.root_dir, settings.data_dir)
    settings.outputs.site.dir = _resolve(settings.root_dir, settings.outputs.site.dir)
    settings.outputs.csv.path = _resolve(settings.root_dir, settings.outputs.csv.path)
    settings.outputs.report.dir = _resolve(settings.root_dir, settings.outputs.report.dir)
    settings.outputs.sheets.credentials_file = _resolve(settings.root_dir, settings.outputs.sheets.credentials_file)
    secrets = Secrets(_env_file=str(root_dir / ".env"))
    if secrets.llm_base_url:
        settings.llm.base_url = secrets.llm_base_url
    if secrets.llm_model:
        settings.llm.model = secrets.llm_model
    if secrets.llm_api_key:
        settings.llm.api_key = secrets.llm_api_key
    if secrets.searx_base_url:
        settings.search.base_url = secrets.searx_base_url
    if secrets.git_push:
        settings.outputs.git.enabled = secrets.git_push.lower() in {"1", "true", "yes"}
    if secrets.facebook_page_id:
        settings.outputs.facebook.page_id = secrets.facebook_page_id
    if secrets.telegram_chat_id:
        settings.outputs.telegram.chat_id = secrets.telegram_chat_id
    return settings


def load_secrets(root_dir: Path) -> Secrets:
    return Secrets(_env_file=str(root_dir / ".env"))
