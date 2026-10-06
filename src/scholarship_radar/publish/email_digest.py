from __future__ import annotations

import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Secrets


def render_digest(templates_dir: Path, rows: list[dict], target_name: str, today: date) -> tuple[str, str]:
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html"]))
    context = {"rows": rows, "target_name": target_name, "today": today.isoformat()}
    return env.get_template("digest.html.j2").render(**context), env.get_template("digest.txt.j2").render(**context)


def send_digest(secrets: Secrets, subject: str, html: str, text: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = secrets.digest_from or secrets.smtp_user
    message["To"] = secrets.digest_to
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    with smtplib.SMTP(secrets.smtp_host, secrets.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if secrets.smtp_user:
            smtp.login(secrets.smtp_user, secrets.smtp_password)
        smtp.send_message(message)


def smtp_configured(secrets: Secrets) -> bool:
    return bool(secrets.smtp_host and secrets.digest_to)
