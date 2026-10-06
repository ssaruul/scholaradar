from __future__ import annotations

import glob
import logging
import os
import platform
import signal
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases"
LINUX_ASSETS = {
    "vulkan": ["llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz"],
    "cuda-12.8": ["llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"],
    "cuda-13.4": ["llama-{tag}-bin-ubuntu-cuda-13.4-x64.tar.gz", "cudart-llama-{tag}-bin-ubuntu-cuda-13.4-x64.tar.gz"],
    "rocm": ["llama-{tag}-bin-ubuntu-rocm-10.0-x64.tar.gz"],
    "cpu": ["llama-{tag}-bin-ubuntu-x64.tar.gz"],
}
WINDOWS_ASSETS = {
    "vulkan": ["llama-{tag}-bin-win-vulkan-x64.zip"],
    "cuda-12.8": ["llama-{tag}-bin-win-cuda-12.8-x64.zip", "cudart-llama-{tag}-bin-win-cuda-12.8-x64.zip"],
    "cuda-13.4": ["llama-{tag}-bin-win-cuda-13.4-x64.zip", "cudart-llama-{tag}-bin-win-cuda-13.4-x64.zip"],
    "cpu": ["llama-{tag}-bin-win-cpu-x64.zip"],
}


class LlamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llama_mode: str = "docker"
    llama_bin: str = ""
    llama_model: str = "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
    llama_ctx: int = 65536
    llama_parallel: int = 4
    llama_kv_type: str = "q8_0"
    llama_port: int = 8089
    models_dir: str = str(Path.home() / "models" / "gguf")


@dataclass
class LlamaServer:
    root: Path
    settings: LlamaSettings

    @property
    def pid_file(self) -> Path:
        return self.root / "data" / "llama-server.pid"

    @property
    def log_file(self) -> Path:
        return self.root / "data" / "logs" / "llama-server.log"

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.settings.llama_port}/health"

    def resolve_models_dir(self) -> Path:
        pattern = os.path.expanduser(self.settings.models_dir)
        for match in sorted(glob.glob(pattern)):
            if Path(match).is_dir():
                return Path(match)
        raise FileNotFoundError(f"no directory matches MODELS_DIR={pattern} (is the drive mounted?)")

    def model_path(self) -> Path:
        path = self.resolve_models_dir() / self.settings.llama_model
        if not path.exists():
            raise FileNotFoundError(f"model file not found: {path}")
        return path

    def healthy(self) -> bool:
        try:
            return httpx.get(self.health_url, timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def wait_healthy(self, timeout_seconds: int = 600) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.healthy():
                return True
            time.sleep(3)
        return False

    def _binary(self) -> Path:
        if not self.settings.llama_bin:
            raise FileNotFoundError("LLAMA_BIN is not set; run `scholaradar llm install` or set LLAMA_MODE=docker")
        name = "llama-server.exe" if os.name == "nt" else "llama-server"
        path = Path(os.path.expanduser(self.settings.llama_bin)) / name
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        return path

    def _running_pid(self) -> int | None:
        if not self.pid_file.exists():
            return None
        pid = int(self.pid_file.read_text().strip() or 0)
        if pid <= 0:
            return None
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return pid

    def start(self) -> None:
        if self.healthy():
            log.info("llama-server already healthy on port %d", self.settings.llama_port)
            return
        if self.settings.llama_mode == "native":
            self._start_native()
        else:
            self._start_docker()
        if not self.wait_healthy():
            raise RuntimeError(f"llama-server did not become healthy at {self.health_url}; see {self.log_file}")
        log.info("llama-server ready at %s", self.health_url)

    def _start_native(self) -> None:
        if self._running_pid():
            return
        model = self.model_path()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        args = [
            str(self._binary()), "-m", str(model), "--alias", "local",
            "-c", str(self.settings.llama_ctx), "--parallel", str(self.settings.llama_parallel), "-ngl", "99",
            "--flash-attn", "on", "-ctk", self.settings.llama_kv_type, "-ctv", self.settings.llama_kv_type,
            "--jinja", "--host", "127.0.0.1", "--port", str(self.settings.llama_port),
        ]
        log.info("starting llama-server with %s", model)
        handle = self.log_file.open("ab")
        creation = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **creation)
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(process.pid))

    def _start_docker(self) -> None:
        env = {**os.environ, "MODELS_DIR": str(self.resolve_models_dir())}
        subprocess.run(["docker", "compose", "--profile", "llm", "up", "-d", "llama"], cwd=self.root, env=env, check=True)

    def stop(self) -> None:
        if self.settings.llama_mode == "native":
            pid = self._running_pid()
            if pid:
                os.kill(pid, signal.SIGTERM)
                for _ in range(60):
                    if self._running_pid() is None:
                        break
                    time.sleep(1)
                log.info("llama-server stopped (pid %d)", pid)
            self.pid_file.unlink(missing_ok=True)
        else:
            subprocess.run(["docker", "compose", "--profile", "llm", "stop", "llama"], cwd=self.root, check=False)


def latest_release_tag() -> str:
    response = httpx.get(RELEASES_API, params={"per_page": 5}, headers={"Accept": "application/vnd.github+json", "User-Agent": "scholaradar"}, timeout=30)
    response.raise_for_status()
    for release in response.json():
        if release["tag_name"].startswith("b") and release["tag_name"][1:].isdigit():
            return release["tag_name"]
    raise RuntimeError("no build release found")


def install_llama(backend: str, dest: Path) -> Path:
    system = platform.system()
    table = WINDOWS_ASSETS if system == "Windows" else LINUX_ASSETS
    if backend not in table:
        raise ValueError(f"backend {backend} not available for {system}; choose from {', '.join(table)}")
    tag = latest_release_tag()
    target = dest / f"llama-{tag}-{backend}"
    target.mkdir(parents=True, exist_ok=True)
    for pattern in table[backend]:
        asset = pattern.format(tag=tag)
        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset}"
        archive = target / asset
        print(f"downloading {asset}")
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            with archive.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(target, filter="data")
        archive.unlink()
    nested = [path for path in target.iterdir() if path.is_dir() and (path / ("llama-server.exe" if system == "Windows" else "llama-server")).exists()]
    binary_dir = nested[0] if nested else target
    print(f"installed to {binary_dir}")
    print("add to .env:")
    print("LLAMA_MODE=native")
    print(f"LLAMA_BIN={binary_dir}")
    return binary_dir


def default_install_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "scholaradar"
    return Path.home() / ".local" / "opt"


def python_executable() -> str:
    return sys.executable
