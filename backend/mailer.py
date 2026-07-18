"""SMTP delivery for passwordless login links."""
from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage


class MailerNotConfigured(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SMTPMailer:
    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "").strip()
        self.port = int(os.getenv("SMTP_PORT", "465"))
        self.username = os.getenv("SMTP_USERNAME", "").strip()
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.sender = os.getenv("SMTP_FROM", self.username).strip()
        self.use_ssl = _env_bool("SMTP_USE_SSL", True)
        self.starttls = _env_bool("SMTP_STARTTLS", False)

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    def send_magic_link(self, email: str, magic_link: str) -> None:
        if not self.configured:
            raise MailerNotConfigured("SMTP is not configured")

        message = EmailMessage()
        message["Subject"] = "登录 ScholarProfile"
        message["From"] = self.sender
        message["To"] = email
        ttl_minutes = int(os.getenv("MAGIC_LINK_TTL_MINUTES", "15"))
        message.set_content(
            f"请使用以下一次性链接登录 ScholarProfile。链接将在 {ttl_minutes} 分钟后失效：\n\n"
            f"{magic_link}\n\n如果不是你本人操作，请忽略此邮件。"
        )
        safe_link = html.escape(magic_link, quote=True)
        message.add_alternative(
            "<p>请点击下面的一次性链接登录 ScholarProfile：</p>"
            f'<p><a href="{safe_link}">登录 ScholarProfile</a></p>'
            f"<p>链接将在 {ttl_minutes} 分钟后失效。如果不是你本人操作，请忽略此邮件。</p>",
            subtype="html",
        )

        smtp_class = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
        with smtp_class(self.host, self.port, timeout=15) as client:
            if not self.use_ssl and self.starttls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(message)
