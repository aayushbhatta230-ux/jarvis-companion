"""Email operations for JARVIS — draft, search, read emails.

Supports both local draft management and real SMTP sending via Gmail.
Credentials are read from environment variables or a config file, never
hardcoded.

For actual email sending, JARVIS composes drafts and hands them to the
user for confirmation before any external action.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any
from dataclasses import dataclass, asdict


def _load_dotenv() -> None:
    """Load environment variables from .env file if it exists."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.getenv(key):
                    os.environ[key] = value
    except Exception:
        pass


# Load .env file on module import
_load_dotenv()


# Local contacts registry (can be extended)
CONTACTS_FILE = Path(__file__).resolve().parent.parent / "memory" / "contacts.json"
DRAFTS_FILE = Path(__file__).resolve().parent.parent / "memory" / "drafts.json"


@dataclass
class EmailDraft:
    to: str
    subject: str
    body: str
    created_at: str
    status: str = "draft"  # draft, confirmed, sent, cancelled

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmailDraft":
        return cls(**data)


def _load_contacts() -> dict[str, str]:
    """Load contacts from the contacts file."""
    try:
        return json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_contacts(contacts: dict[str, str]) -> None:
    CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(contacts, indent=2) + "\n", encoding="utf-8")


def _load_drafts() -> list[dict[str, Any]]:
    try:
        return json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_drafts(drafts: list[dict[str, Any]]) -> None:
    DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DRAFTS_FILE.write_text(json.dumps(drafts, indent=2) + "\n", encoding="utf-8")


def resolve_contact(name: str) -> str | None:
    """Resolve a contact name to an email address or identifier."""
    contacts = _load_contacts()
    name_lower = name.strip().lower()

    # Exact match
    if name_lower in contacts:
        return contacts[name_lower]

    # Partial match
    for contact_name, email in contacts.items():
        if name_lower in contact_name or contact_name in name_lower:
            return email

    return None


def add_contact(name: str, email: str) -> str:
    """Add a contact to the local registry."""
    contacts = _load_contacts()
    contacts[name.strip().lower()] = email.strip()
    _save_contacts(contacts)
    return f"Added {name} ({email}) to contacts."


def draft_email(to: str, subject: str = "", body: str = "") -> str:
    """Create an email draft and save it locally."""
    # Try to resolve contact name
    resolved = resolve_contact(to)
    if resolved and "@" in resolved:
        to_address = resolved
    else:
        to_address = to

    draft = EmailDraft(
        to=to_address,
        subject=subject,
        body=body,
        created_at=datetime.now().isoformat(),
    )
    drafts = _load_drafts()
    drafts.append(draft.to_dict())
    _save_drafts(drafts)

    preview = f"To: {draft.to}\nSubject: {draft.subject or '(no subject)'}\n\n{draft.body}"
    return f"Draft saved:\n\n{preview}\n\nReady to send when you confirm."


def list_drafts() -> str:
    """List all saved email drafts."""
    drafts = _load_drafts()
    if not drafts:
        return "No email drafts saved."

    lines = [f"{len(drafts)} draft(s):"]
    for i, d in enumerate(drafts, 1):
        status = d.get("status", "draft")
        lines.append(f"  {i}. To: {d.get('to', '?')} — Subject: {d.get('subject', '(none)')} [{status}]")
    return "\n".join(lines)


def get_draft(index: int = -1) -> str:
    """Get a specific draft by index (default: last one)."""
    drafts = _load_drafts()
    if not drafts:
        return "No drafts available."
    try:
        d = drafts[index]
        return f"To: {d.get('to', '?')}\nSubject: {d.get('subject', '(no subject)')}\n\n{d.get('body', '')}"
    except IndexError:
        return f"Draft {index} doesn't exist. Use list_drafts to see available drafts."


def update_draft(index: int = -1, subject: str | None = None, body: str | None = None, to: str | None = None) -> str:
    """Update an existing draft."""
    drafts = _load_drafts()
    if not drafts:
        return "No drafts to update."
    try:
        d = drafts[index]
        if subject is not None:
            d["subject"] = subject
        if body is not None:
            d["body"] = body
        if to is not None:
            d["to"] = to
        d["created_at"] = datetime.now().isoformat()
        _save_drafts(drafts)
        return f"Draft updated:\n\nTo: {d.get('to')}\nSubject: {d.get('subject', '(no subject)')}\n\n{d.get('body', '')}"
    except IndexError:
        return f"Draft {index} doesn't exist."


def confirm_send(index: int = -1) -> str:
    """Mark a draft as confirmed for sending."""
    drafts = _load_drafts()
    if not drafts:
        return "No drafts available."
    try:
        d = drafts[index]
        d["status"] = "confirmed"
        _save_drafts(drafts)
        return f"Draft to {d.get('to')} confirmed and ready to send."
    except IndexError:
        return f"Draft {index} doesn't exist."


def list_contacts() -> str:
    """List all saved contacts."""
    contacts = _load_contacts()
    if not contacts:
        return "No contacts saved yet."
    lines = [f"{len(contacts)} contact(s):"]
    for name, email in sorted(contacts.items()):
        lines.append(f"  {name}: {email}")
    return "\n".join(lines)


def _get_email_config() -> dict[str, str] | None:
    """Get email configuration from environment variables or config file.

    Password is ONLY loaded from environment variables, never from the config file.
    This ensures credentials are never stored in plaintext on disk.
    """
    # Primary: environment variables (preferred method)
    env_user = os.getenv("JARVIS_GMAIL_ADDRESS") or os.getenv("JARVIS_EMAIL_USER")
    env_pass = os.getenv("JARVIS_GMAIL_APP_PASSWORD") or os.getenv("JARVIS_EMAIL_PASS")
    if env_user and env_pass:
        return {
            "user": env_user,
            "password": env_pass,
            "smtp_server": os.getenv("JARVIS_EMAIL_SMTP_SERVER", "smtp.gmail.com"),
            "smtp_port": os.getenv("JARVIS_EMAIL_SMTP_PORT", "587"),
        }

    # Fallback: config file for user/server, but password MUST come from env
    config_file = Path(__file__).resolve().parent.parent / "memory" / "email_config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            user = config.get("user")
            if user and env_pass:
                return {
                    "user": user,
                    "password": env_pass,
                    "smtp_server": config.get("smtp_server", "smtp.gmail.com"),
                    "smtp_port": config.get("smtp_port", "587"),
                }
        except (json.JSONDecodeError, KeyError):
            pass

    return None


@dataclass
class EmailActionResult:
    success: bool
    status: str  # DRAFTED, READY_TO_SEND, SENDING, SENT, FAILED, UNCONFIGURED, UNKNOWN
    recipient: str
    subject: str
    provider: str | None = "unknown"
    message_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "recipient": self.recipient,
            "subject": self.subject,
            "provider": self.provider,
            "message_id": self.message_id,
            "error": self.error,
        }

    def __str__(self) -> str:
        if self.success:
            sent = f" to {self.recipient}" if self.recipient else ""
            subj = f' with subject "{self.subject}"' if self.subject else ""
            return (
                f"Email sent{sent}{subj} via {self.provider or 'SMTP'}."
                + (f" Message-ID: {self.message_id}." if self.message_id else "")
            )
        if self.status == "UNCONFIGURED":
            return (
                "Email isn't configured yet. I have the draft, but I can't send it "
                "until a sender account is configured."
            )
        return f"Sending failed for {self.recipient or 'recipient'}: {self.error}"


# Friendly alias used across the codebase.
EmailResult = EmailActionResult


def _infer_provider(smtp_server: str) -> str:
    host = (smtp_server or "").lower()
    if "gmail" in host:
        return "Gmail"
    if "office365" in host or "outlook" in host or "hotmail" in host:
        return "Outlook"
    if "yandex" in host:
        return "Yandex"
    if "zoho" in host:
        return "Zoho"
    if "ses" in host or "amazon" in host:
        return "Amazon SES"
    return "Generic SMTP"


def _send_via_smtp(config: dict[str, str], to_address: str, subject: str, body: str) -> EmailActionResult:
    """Perform the real SMTP send. Returns an honest result — never success on failure.

    Generates a real Message-ID header for the outgoing message (this is the id
    that gets transmitted, not a fabricated claim about the server's queue).
    """
    try:
        import email.utils
        import smtplib
        import ssl
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        message_id = email.utils.make_msgid(domain=config["user"].split("@")[-1] or "local")
        msg = MIMEMultipart()
        msg["From"] = config["user"]
        msg["To"] = to_address
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        msg.attach(MIMEText(body, "plain"))

        context = ssl.create_default_context()
        server = smtplib.SMTP(config["smtp_server"], int(config["smtp_port"]))
        server.starttls(context=context)
        server.login(config["user"], config["password"])
        failures = server.sendmail(config["user"], to_address, msg.as_string())
        server.quit()

        if failures:
            return EmailActionResult(False, "FAILED", to_address, subject,
                                     provider=_infer_provider(config["smtp_server"]),
                                     message_id=None,
                                     error=f"Recipient refused: {failures}")
        return EmailActionResult(True, "SENT", to_address, subject,
                                 provider=_infer_provider(config["smtp_server"]),
                                 message_id=message_id)
    except Exception as exc:  # noqa: BLE001 - surface the safe error only
        # Never leak the password; str(exc) from smtplib is generally safe, but
        # if it contains the password we still report only a generic message.
        if config.get("password") and config["password"] in str(exc):
            error = "SMTP authentication failed (bad credentials)."
        else:
            error = str(exc)
        return EmailActionResult(False, "FAILED", to_address, subject,
                                 provider=_infer_provider(config.get("smtp_server", "")),
                                 message_id=None, error=error)
def save_email_config(user: str, password: str | None = None, smtp_server: str = "smtp.gmail.com", smtp_port: str = "587") -> str:
    """Save email configuration to a local config file.

    NOTE: Password is NOT stored in the config file for security.
    Set JARVIS_GMAIL_APP_PASSWORD environment variable instead.
    """
    config_file = Path(__file__).resolve().parent.parent / "memory" / "email_config.json"
    config = {
        "user": user.strip(),
        "smtp_server": smtp_server.strip(),
        "smtp_port": smtp_port.strip(),
    }
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    # Store password in environment for current session only
    if password:
        os.environ["JARVIS_GMAIL_APP_PASSWORD"] = password
    return (f"Email configuration saved for {user}. "
            "NOTE: Password was not saved to disk. "
            "Set JARVIS_GMAIL_APP_PASSWORD environment variable for persistent access.")

def send_email(draft_index: int = -1) -> EmailActionResult:
    """Send an email draft via SMTP. Requires configuration and a 'confirmed' draft."""
    config = _get_email_config()
    if not config:
        return EmailActionResult(
            False, "UNCONFIGURED", "", "",
            error="No SMTP configuration found.",
        )

    drafts = _load_drafts()
    if not drafts:
        return EmailActionResult(False, "FAILED", "", "",
                                 error="No email drafts available.")
    try:
        draft = drafts[draft_index]
    except IndexError:
        return EmailActionResult(False, "FAILED", "", "",
                                 error=f"Draft {draft_index} doesn't exist.")

    if draft.get("status") != "confirmed":
        return EmailActionResult(
            False, "FAILED", draft.get("to", ""), draft.get("subject", ""),
            error="Draft is not confirmed. Confirm before sending.",
        )

    result = _send_via_smtp(config, draft.get("to", ""), draft.get("subject", ""), draft.get("body", ""))
    if result.success:
        draft["status"] = "sent"
        draft["sent_at"] = datetime.now().isoformat()
        draft["message_id"] = result.message_id
        _save_drafts(drafts)
    return result


def send_email_direct(to: str, subject: str, body: str) -> EmailActionResult:
    """Send an email directly (used when the user explicitly says 'send it')."""
    config = _get_email_config()
    if not config:
        return EmailActionResult(
            False, "UNCONFIGURED", to, subject,
            error="No SMTP configuration found.",
        )

    resolved = resolve_contact(to)
    to_address = resolved if resolved and "@" in resolved else to
    return _send_via_smtp(config, to_address, subject, body)


# ---------------------------------------------------------------------- #
# Diagnostics
# ---------------------------------------------------------------------- #
def diagnostics_dict() -> dict[str, Any]:
    """Safe email-diagnostics view. NEVER includes the password."""
    config = _get_email_config()
    if not config:
        return {
            "configured": False,
            "provider": None,
            "sender": None,
            "smtp_host": None,
            "smtp_port": None,
            "authentication_available": False,
            "last_error": "No SMTP configuration found.",
        }
    return {
        "configured": True,
        "provider": _infer_provider(config.get("smtp_server", "")),
        "sender": config.get("user"),
        "smtp_host": config.get("smtp_server"),
        "smtp_port": config.get("smtp_port"),
        "authentication_available": bool(config.get("user") and config.get("password")),
        "last_error": None,
    }


def diagnostics() -> str:
    """Human-readable email configuration status (no secrets)."""
    d = diagnostics_dict()
    if not d["configured"]:
        return ("Email isn't configured yet. Set JARVIS_GMAIL_ADDRESS / "
                "JARVIS_GMAIL_APP_PASSWORD environment variables, or "
                "JARVIS_EMAIL_USER / JARVIS_EMAIL_PASS as fallback. "
                "Nothing has been invented.")
    lines = [
        "Email is configured.",
        f"Sender: {d['sender']}",
        f"Provider: {d['provider']}",
        f"SMTP host: {d['smtp_host']}",
        f"SMTP port: {d['smtp_port']}",
        f"Authentication configured: {d['authentication_available']}",
    ]
    if d.get("last_error"):
        lines.append(f"Last error: {d['last_error']}")
    return "\n".join(lines)
