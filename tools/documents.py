"""Document parsing and structural context extraction for JARVIS.

Supports reading, summarizing, and extracting structural sections from
DOCX, PDF, MD, TXT, CSV, XLSX, and source code files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

HAS_DOCX = True
try:
    import docx
except ImportError:
    HAS_DOCX = False

HAS_PYPDF = True
try:
    import pypdf
except ImportError:
    HAS_PYPDF = False


def read_document_content(file_path: str) -> str:
    """Read document content across DOCX, PDF, TXT, MD, CSV, XLSX, and code files."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()

    if ext == ".docx":
        if not HAS_DOCX:
            return "(DOCX reader requires 'python-docx'. Install with: pip install python-docx)"
        try:
            doc = docx.Document(path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except Exception:
            return path.read_text(encoding="utf-8", errors="replace")

    if ext == ".pdf":
        if not HAS_PYPDF:
            return "(PDF reader requires 'pypdf'. Install with: pip install pypdf)"
        try:
            reader = pypdf.PdfReader(path)
            pages_text = [page.extract_text() for page in reader.pages if page.extract_text()]
            return "\n\n".join(pages_text)
        except Exception:
            return path.read_text(encoding="utf-8", errors="replace")

    # Standard text files (TXT, MD, CSV, PY, JS, HTML, JSON, etc.)

    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Error reading file {path.name}: {exc}"


def summarize_text(text: str, max_words: int = 150) -> str:
    """Summarize text content into key sentences."""
    if not text.strip():
        return "The document is empty."
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) <= 3:
        return text.strip()
    return " ".join(sentences[:4])


def extract_sections(file_path: str) -> dict[str, str]:
    """Extract named sections from a document (e.g. Profile, Education, Experience in CV)."""
    content = read_document_content(file_path)
    lines = content.splitlines()

    sections: dict[str, str] = {}
    current_section = "General"
    buffer = []

    header_pattern = re.compile(
        r"^(#+|\d+\.|\b(profile|summary|experience|education|skills|projects|interests|background|overview|about)\b)",
        re.IGNORECASE,
    )

    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        if header_pattern.match(cleaned) and len(cleaned) < 50:
            if buffer:
                sections[current_section] = "\n".join(buffer).strip()
                buffer = []
            current_section = cleaned.lstrip("#").strip(" :")
        else:
            buffer.append(cleaned)

    if buffer:
        sections[current_section] = "\n".join(buffer).strip()

    return sections


def count_words(text: str) -> str:
    words = len(re.findall(r"\w+", text))
    lines = len(text.splitlines())
    return f"Document contains {words} words and {lines} lines."


def clean_formatting(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def create_document(file_path: str, content: str) -> str:
    path = Path(file_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Created document at {path}"
