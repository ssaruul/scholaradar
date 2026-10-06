from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def sync_outputs(root: Path, paths: list[Path], message: str, remote: str, branch: str, push: bool) -> bool:
    relative = [str(path.relative_to(root)) for path in paths if path.exists()]
    if not relative:
        return False
    added = _git(root, "add", "--", *relative)
    if added.returncode != 0:
        log.warning("git add failed: %s", added.stderr.strip())
        return False
    if _git(root, "diff", "--cached", "--quiet", "--", *relative).returncode == 0:
        log.info("git: nothing new to commit")
        return False
    committed = _git(root, "commit", "-q", "-m", message, "--", *relative)
    if committed.returncode != 0:
        log.warning("git commit failed: %s", committed.stderr.strip())
        return False
    log.info("git: committed %s", message)
    if not push:
        return True
    pulled = _git(root, "pull", "--rebase", "--autostash", remote, branch)
    if pulled.returncode != 0:
        log.warning("git pull --rebase failed, not pushing: %s", pulled.stderr.strip()[-300:])
        return True
    pushed = _git(root, "push", remote, branch)
    if pushed.returncode != 0:
        log.warning("git push failed: %s", pushed.stderr.strip())
        return False
    log.info("git: pushed to %s/%s", remote, branch)
    return True
