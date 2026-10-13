from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import httpx

OPENALEX = "https://api.openalex.org"
UNIVERSITY_DATABASES = {
    "tohoku": "https://www.r-info.tohoku.ac.jp/en/",
    "tokyo": "https://www.u-tokyo.ac.jp/en/research/researchers.html",
    "kyoto": "https://kdb.iimc.kyoto-u.ac.jp/en/",
    "osaka": "https://rd.iai.osaka-u.ac.jp/en/",
    "nagoya": "https://profs.provost.nagoya-u.ac.jp/html/100000_en.html",
    "hokkaido": "https://researchers.general.hokudai.ac.jp/",
    "kyushu": "https://hyoka.ofc.kyushu-u.ac.jp/search/index_e.html",
    "tsukuba": "https://trios.tsukuba.ac.jp/en/",
    "keio": "https://k-ris.keio.ac.jp/en/",
    "waseda": "https://researchers.waseda.jp/",
}


@dataclass
class Lab:
    author_id: str
    name: str
    institution: str
    works_matched: int
    recent_titles: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    works_count: int = 0
    cited_by_count: int = 0
    orcid: str = ""
    topics: list[str] = field(default_factory=list)

    @property
    def openalex_url(self) -> str:
        return f"https://openalex.org/{self.author_id}"

    @property
    def researchmap_url(self) -> str:
        return f"https://researchmap.jp/researchers?q={quote_plus(self.name)}&lang=en"

    @property
    def scholar_url(self) -> str:
        return f"https://scholar.google.com/scholar?q={quote_plus(self.name + ' ' + self.institution)}"


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    country: str


def _client(mailto: str) -> httpx.Client:
    return httpx.Client(
        base_url=OPENALEX,
        headers={"User-Agent": f"scholaradar/0.2 (mailto:{mailto})"},
        timeout=60,
    )


def find_institution(client: httpx.Client, name: str) -> Institution:
    response = client.get("/institutions", params={"search": name, "per_page": 5})
    response.raise_for_status()
    results = [
        r
        for r in response.json()["results"]
        if r.get("type") in (None, "education", "facility")
    ] or response.json()["results"]
    if not results:
        raise LookupError(f"no institution found for '{name}'")
    best = results[0]
    return Institution(
        best["id"].rsplit("/", 1)[-1],
        best["display_name"],
        best.get("country_code") or "",
    )


def find_labs(
    field_query: str,
    university: str,
    years_back: int = 3,
    limit: int = 20,
    min_works: int = 10,
    mailto: str = "scholaradar@example.org",
) -> tuple[Institution, list[Lab]]:
    since = date.today().year - years_back
    with _client(mailto) as client:
        institution = find_institution(client, university)
        counts: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        titles: dict[str, list[tuple[int, str]]] = defaultdict(list)
        cursor = "*"
        pages = 0
        while cursor and pages < 5:
            response = client.get(
                "/works",
                params={
                    "search": field_query,
                    "filter": f"authorships.institutions.id:{institution.id},publication_year:>{since - 1}",
                    "per_page": 200,
                    "cursor": cursor,
                    "select": "id,title,publication_year,authorships",
                },
            )
            response.raise_for_status()
            payload = response.json()
            for work in payload["results"]:
                for authorship in work["authorships"]:
                    if not any(
                        i["id"].endswith(institution.id)
                        for i in authorship.get("institutions", [])
                    ):
                        continue
                    raw_id = (authorship.get("author") or {}).get("id")
                    if not raw_id:
                        continue
                    author_id = raw_id.rsplit("/", 1)[-1]
                    counts[author_id] += 1
                    names[author_id] = authorship["author"]["display_name"]
                    titles[author_id].append(
                        (work.get("publication_year") or 0, work.get("title") or "")
                    )
            cursor = payload["meta"].get("next_cursor")
            pages += 1
        ranked = sorted(counts, key=lambda a: counts[a], reverse=True)[: limit * 3]
        details: dict[str, dict] = {}
        for start in range(0, len(ranked), 50):
            batch = ranked[start : start + 50]
            response = client.get(
                "/authors",
                params={
                    "filter": "openalex:" + "|".join(batch),
                    "per_page": 50,
                    "select": "id,display_name,orcid,works_count,cited_by_count,topics,last_known_institutions",
                },
            )
            response.raise_for_status()
            for author in response.json()["results"]:
                details[author["id"].rsplit("/", 1)[-1]] = author
    labs = []
    for author_id in ranked:
        detail = details.get(author_id, {})
        if detail.get("works_count", 0) < min_works:
            continue
        recent = sorted(titles[author_id], reverse=True)
        affiliations = [
            i["display_name"] for i in detail.get("last_known_institutions", [])
        ]
        labs.append(
            Lab(
                author_id=author_id,
                name=names[author_id],
                institution=affiliations[0] if affiliations else institution.name,
                works_matched=counts[author_id],
                recent_titles=[title for _, title in recent[:3]],
                years=sorted({year for year, _ in recent if year}, reverse=True),
                works_count=detail.get("works_count", 0),
                cited_by_count=detail.get("cited_by_count", 0),
                orcid=(detail.get("orcid") or "").replace("https://orcid.org/", ""),
                topics=[t["display_name"] for t in detail.get("topics", [])[:4]],
            )
        )
        if len(labs) >= limit:
            break
    return institution, labs


def university_database(university: str) -> str:
    key = university.casefold()
    for name, url in UNIVERSITY_DATABASES.items():
        if name in key:
            return url
    return ""


def render_labs(
    institution: Institution, labs: list[Lab], field_query: str, years_back: int
) -> str:
    lines = [
        f'# Labs at {institution.name} working on "{field_query}"',
        "",
        f"Source: OpenAlex, papers from the last {years_back} years with an author affiliated to {institution.name}. Ranked by number of matching papers; authors with fewer than the minimum total works (students) are skipped. Confirm each person's current position on the university site before writing.",
        "",
    ]
    db_url = university_database(institution.name)
    if db_url:
        lines += [f"University researcher database: {db_url}", ""]
    lines += [
        "| # | Researcher | Matching papers | Total works / citations | Topics | Recent matching papers | Links |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, lab in enumerate(labs, start=1):
        recent = "<br>".join(t[:90].replace("|", "/") for t in lab.recent_titles)
        links = f"[OpenAlex]({lab.openalex_url}) · [researchmap]({lab.researchmap_url}) · [Scholar]({lab.scholar_url})"
        if lab.orcid:
            links += f" · [ORCID](https://orcid.org/{lab.orcid})"
        lines.append(
            f"| {index} | **{lab.name}** | {lab.works_matched} | {lab.works_count} / {lab.cited_by_count} | {', '.join(lab.topics)} | {recent} | {links} |"
        )
    lines.append("")
    return "\n".join(lines)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:60]


def write_labs(
    out_dir: Path,
    institution: Institution,
    labs: list[Lab],
    field_query: str,
    years_back: int,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slugify(institution.name)}-{slugify(field_query)}.md"
    path.write_text(
        render_labs(institution, labs, field_query, years_back), encoding="utf-8"
    )
    return path
