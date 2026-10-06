# scholarship-radar

Daily, self-hosted discovery of scholarships and funded study opportunities, with a local LLM deciding whether citizens of your country are eligible. Built for Mongolian students; change one config block for any other nationality.

No paid APIs. Search runs through a self-hosted SearXNG instance, extraction runs through llama.cpp on your own GPU, and results land in a static HTML dashboard, a CSV file, and an optional email digest.

## How it works

1. **Discover**: re-checks a list of anchor programme pages and RSS feeds (`config/sources.yaml`), and runs a rotating set of multilingual search queries (`config/queries.yaml`) through SearXNG. Every URL is canonicalised and deduplicated in SQLite.
2. **Fetch**: downloads new pages politely (robots.txt, 2 s per host, size cap), extracts the main text with trafilatura (PDFs through pypdf), and drops pages that do not mention a scholarship term in any supported language.
3. **Extract**: sends each candidate page to the LLM with a JSON-schema-constrained prompt and gets back title, provider, host country, degree levels, funding type, deadline, an eligibility summary, a verdict (`yes` / `no` / `unclear`), and a verbatim evidence quote.
4. **Verify**: the evidence quote must literally appear in the page text or the verdict is downgraded to `unclear`. If the page names your country in an explicit eligible or excluded list, that overrides the model.
5. **Publish**: writes `data/site/index.html` (filterable, works offline), `data/exports/opportunities.csv`, and emails new items sorted by deadline.

## Requirements

- Linux with Docker and Docker Compose v2
- NVIDIA GPU with 16 GB+ VRAM and the NVIDIA Container Toolkit (AMD notes below)
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)

## Setup

```bash
git clone https://github.com/ssaruul/scholarship-radar
cd scholarship-radar
uv sync
cp .env.example .env            # SMTP settings for the email digest, optional

mkdir -p ~/models/gguf          # or set MODELS_DIR in .env
# download a GGUF, for example:
uv run huggingface-cli download unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF \
    Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf --local-dir ~/models/gguf

docker compose up -d searxng
docker compose --profile llm up -d llama
uv run scholarship-radar init-db
uv run scholarship-radar run --limit 50
xdg-open data/site/index.html
```

`LLAMA_MODEL`, `LLAMA_CTX`, `LLAMA_PARALLEL` and `MODELS_DIR` in `.env` control the llama-server container. The pipeline only needs an OpenAI-compatible endpoint, so `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` can point at Ollama, vLLM, or a hosted API instead.

## Daily run

`scripts/run_nightly.sh` starts the LLM container, runs the pipeline, then stops the container so the GPU is free for other work. Example crontab entry:

```
30 3 * * * /home/you/scholarship-radar/scripts/run_nightly.sh >> /home/you/scholarship-radar/data/logs/nightly.log 2>&1
```

## Commands

| Command | What it does |
|---|---|
| `init-db` | Create the SQLite database and register sources |
| `discover [--skip-search]` | Queue anchor pages, RSS entries and search results |
| `fetch [--limit N]` | Download and text-extract queued pages |
| `extract [--limit N] [--model NAME]` | Run the LLM on fetched pages |
| `publish [--send-test]` | Write site, CSV, email digest, Sheets |
| `run` | All of the above in order |
| `status` | Page and opportunity counts |
| `benchmark --model NAME` | Score a model against `benchmark/labels.yaml` |

## Configuration

- `config/settings.yaml`: target nationality names per language, languages searched, fetch and LLM limits, prefilter keywords, output toggles.
- `config/sources.yaml`: anchor pages (`follow_links: true` also queues scholarship-looking links found on them) and RSS feeds.
- `config/queries.yaml`: search templates per language with `{year}`, `{target}`, `{demonym}` placeholders.
- `.env`: secrets and machine-specific values (SMTP, model file, endpoints).

To adapt the project to another nationality, edit `target` in `settings.yaml` and the country-specific queries in `queries.yaml`.

## Choosing a model

`benchmark/labels.yaml` holds hand-labelled pages. `scripts/bench_all.sh` restarts llama-server with each model listed in it and runs `scholarship-radar benchmark`, printing eligibility accuracy, false positives, deadline accuracy, JSON validity and throughput. On an RTX 3090 (24 GB) the Q4_K_M quantisations of Qwen3-30B-A3B, Gemma 3 27B and Qwen3-32B all fit; on a 16 GB card use a 12B to 14B model.

### AMD GPUs

Swap the image in `docker-compose.yml` for `ghcr.io/ggml-org/llama.cpp:server-vulkan`, replace the `deploy.resources` block with `devices: ["/dev/dri:/dev/dri", "/dev/kfd:/dev/kfd"]`, and keep `-ngl 99`. Untested by the author.

## Google Sheets

Install the extra (`uv sync --extra sheets`), create a Google Cloud service account with Sheets access, share the spreadsheet with its email, save the JSON key as `service_account.json`, and set `outputs.sheets.enabled: true` plus `spreadsheet_id` in `settings.yaml`.

## Limits

- Facebook pages are not crawled; many Mongolian embassy announcements only appear there.
- A 27B to 32B local model is weaker than frontier APIs on long country lists. Treat `unclear` as "read the page yourself".
- Deadlines are re-verified only when an anchor page changes; search-discovered pages are extracted once.

## License

MIT
