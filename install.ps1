param(
  [string]$Dir = "$HOME\scholaradar",
  [string]$Backend = "vulkan",
  [switch]$Small,
  [switch]$NoModel,
  [switch]$NoLlm,
  [switch]$NoTask
)
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/ssaruul/scholaradar"
$ModelRepo = "unsloth/gemma-4-26B-A4B-it-GGUF"
$ModelFile = "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
if ($Small) { $ModelRepo = "unsloth/gemma-4-12b-it-GGUF"; $ModelFile = "gemma-4-12b-it-Q4_K_M.gguf" }

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say "installing uv"
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$HOME\.local\bin;$env:Path"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required (https://git-scm.com/download/win)" }

if (Test-Path "$Dir\.git") { Say "updating $Dir"; git -C $Dir pull --ff-only }
else { Say "cloning into $Dir"; git clone $Repo $Dir }
Set-Location $Dir

Say "installing Python dependencies"
uv sync

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$ModelsDir = "$HOME\models\gguf"
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
$envText = Get-Content ".env" -Raw
$envText = $envText -replace "(?m)^MODELS_DIR=.*$", "MODELS_DIR=$ModelsDir" -replace "(?m)^LLAMA_MODEL=.*$", "LLAMA_MODEL=$ModelFile"

if (-not $NoLlm) {
  Say "installing llama.cpp ($Backend)"
  $output = uv run scholaradar llm install --backend $Backend | Out-String
  Write-Host $output
  $binLine = ($output -split "`n" | Where-Object { $_ -match "^LLAMA_BIN=" } | Select-Object -Last 1)
  if ($binLine) {
    $bin = $binLine.Trim() -replace "^LLAMA_BIN=", ""
    $envText = $envText -replace "(?m)^LLAMA_MODE=.*$", "LLAMA_MODE=native" -replace "(?m)^LLAMA_BIN=.*$", "LLAMA_BIN=$bin"
  }
}
Set-Content ".env" $envText

if (-not $NoModel -and -not (Test-Path "$ModelsDir\$ModelFile")) {
  Say "downloading $ModelFile (this is the slow part)"
  uvx --from huggingface_hub hf download $ModelRepo $ModelFile --local-dir $ModelsDir
}

Say "starting the search engine"
if (Get-Command docker -ErrorAction SilentlyContinue) {
  try { docker compose up -d searxng } catch { Write-Host "could not start SearXNG; is Docker Desktop running?" }
} else { Write-Host "Docker Desktop not found; install it to enable web search discovery" }

Say "creating the database"
uv run scholaradar init-db

if (-not $NoTask) {
  Say "scheduling the nightly run at 03:00 (Task Scheduler)"
  $action = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$Dir\scripts\run_nightly.ps1`""
  schtasks /Create /F /SC DAILY /ST 03:00 /TN Scholaradar /TR $action | Out-Null
}

Say "done"
Write-Host "First run (takes a while, then opens the dashboard):"
Write-Host "  cd $Dir; uv run scholaradar nightly --open"
