Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null
uv run scholaradar nightly @args
