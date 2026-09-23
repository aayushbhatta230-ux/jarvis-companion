"""Semantic file operations for JARVIS — search, read, create, edit, move, copy, rename, delete.

All functions return human-readable result strings. Destructive operations are
NOT performed here; they are gated by the safety/confirmation layer in core/.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

# Common user directories for semantic searches
USER_ROOT = Path.home()

def _resolve_common_dir(name: str) -> Path | None:
    """Resolve a common directory name to its actual path, handling OneDrive redirects."""
    name_lower = name.lower().strip()
    # Prefer the OneDrive redirected location (the user's real folders),
    # falling back to the direct folder when the OneDrive one doesn't exist.
    onedrive = USER_ROOT / "OneDrive" / name.capitalize()
    if onedrive.is_dir():
        return onedrive
    direct = USER_ROOT / name.capitalize()
    if direct.is_dir():
        return direct
    # Special case for Downloads (might be redirected)
    if name_lower == "downloads":
        for candidate in [USER_ROOT / "Downloads", USER_ROOT / "OneDrive" / "Downloads"]:
            if candidate.is_dir():
                return candidate
    return None


COMMON_DIRS = {
    "desktop": _resolve_common_dir("Desktop"),
    "documents": _resolve_common_dir("Documents"),
    "downloads": _resolve_common_dir("Downloads"),
    "pictures": _resolve_common_dir("Pictures"),
    "music": _resolve_common_dir("Music"),
    "videos": _resolve_common_dir("Videos"),
    "projects": _resolve_common_dir("Projects"),
}
# Filter out None values (directories that don't exist)
COMMON_DIRS = {k: v for k, v in COMMON_DIRS.items() if v is not None}

# Text file extensions we can read/edit
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml", ".csv",
    ".ini", ".cfg", ".yaml", ".yml", ".toml", ".log", ".bat", ".ps1",
    ".sh", ".cpp", ".c", ".h", ".hpp", ".java", ".rb", ".go", ".rs",
    ".ts", ".jsx", ".tsx", ".sql", ".env", ".gitignore", ".rst", ".tex",
}


def _resolve_directory(directory: str | None) -> Path:
    if not directory:
        return USER_ROOT
    path = Path(directory).expanduser()
    if path.is_dir():
        return path
    alias = directory.strip().lower()
    if alias in COMMON_DIRS and COMMON_DIRS[alias].is_dir():
        return COMMON_DIRS[alias]
    return path


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _format_time(timestamp: float) -> str:
    dt = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    delta = now - dt
    if delta.days == 0:
        return f"today at {dt.strftime('%I:%M %p')}"
    if delta.days == 1:
        return f"yesterday at {dt.strftime('%I:%M %p')}"
    if delta.days < 7:
        return dt.strftime('%A at %I:%M %p')
    return dt.strftime('%B %d, %Y')


def search_files(query: str, directory: str | None = None, extension: str | None = None,
                 limit: int = 20, sort_by: str = "relevance") -> str:
    """Search for files by name, optionally filtered by directory and extension."""
    search_dir = _resolve_directory(directory)
    if not search_dir.is_dir():
        return f"I couldn't find the directory '{directory}'."

    query_lower = query.lower().strip()
    if not query_lower:
        return "Please tell me what file you're looking for."

    results: list[dict[str, Any]] = []
    # Do not descend into internal / dependency / cache directories. This keeps
    # searches fast and avoids exposing private caches, even when search starts
    # at a folder that contains them (e.g. the project root with .venv).
    excluded_dir_names = {
        ".venv", "venv", "env", "site-packages", "node_modules", "__pycache__",
        ".git", ".idea", ".vscode", ".cache", "mypy_cache", ".pytest_cache",
        "dist", "build", "logs", "AppData",
    }
    try:
        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if d not in excluded_dir_names]
            for name in files:
                if query_lower in name.lower():
                    full_path = Path(root) / name
                    if extension and not name.lower().endswith(extension.lower()):
                        continue
                    try:
                        stat = full_path.stat()
                        results.append({
                            "path": str(full_path),
                            "name": name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                            "created": stat.st_ctime,
                        })
                    except OSError:
                        continue
    except PermissionError:
        return f"I don't have permission to search '{search_dir}'."

    if not results:
        ext_msg = f" with extension {extension}" if extension else ""
        return f"I couldn't find any files matching '{query}'{ext_msg} in {search_dir.name}."

    if sort_by == "modified":
        results.sort(key=lambda x: x["modified"], reverse=True)
    elif sort_by == "created":
        results.sort(key=lambda x: x["created"], reverse=True)
    elif sort_by == "name":
        results.sort(key=lambda x: x["name"].lower())
    elif sort_by == "size":
        results.sort(key=lambda x: x["size"], reverse=True)
    else:
        def relevance_key(r):
            name_lower = r["name"].lower()
            if name_lower == query_lower:
                return (0, -r["modified"])
            if name_lower.startswith(query_lower):
                return (1, -r["modified"])
            return (2, -r["modified"])
        results.sort(key=relevance_key)

    results = results[:limit]
    if len(results) == 1:
        r = results[0]
        return f"Found '{r['name']}' ({_format_size(r['size'])}, modified {_format_time(r['modified'])}) at {r['path']}."

    lines = [f"Found {len(results)} files matching '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. {r['name']} ({_format_size(r['size'])}, {_format_time(r['modified'])})")
    return "\n".join(lines)


def find_recent_files(directory: str | None = None, days: int = 7,
                      extension: str | None = None, limit: int = 10) -> str:
    """Find recently modified files."""
    search_dir = _resolve_directory(directory)
    if not search_dir.is_dir():
        return f"I couldn't find the directory '{directory}'."

    cutoff = datetime.now().timestamp() - (days * 86400)
    results: list[dict[str, Any]] = []

    try:
        for root, _dirs, files in os.walk(search_dir):
            for name in files:
                full_path = Path(root) / name
                if extension and not name.lower().endswith(extension.lower()):
                    continue
                try:
                    stat = full_path.stat()
                    if stat.st_mtime >= cutoff:
                        results.append({
                            "path": str(full_path),
                            "name": name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        })
                except OSError:
                    continue
    except PermissionError:
        return f"I don't have permission to search '{search_dir}'."

    if not results:
        return f"No files modified in the last {days} days in {search_dir.name}."

    results.sort(key=lambda x: x["modified"], reverse=True)
    results = results[:limit]

    lines = [f"Recently modified files in {search_dir.name}:"]
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. {r['name']} ({_format_time(r['modified'])})")
    return "\n".join(lines)


def read_file(filepath: str, max_lines: int | None = None) -> dict[str, Any]:
    """Read and return the contents of a text or rich document file.

    Returns a dict with success status, path, filename, file_type, and actual content.
    """
    from core.context import get_desktop_context
    from tools.documents import read_document_content, HAS_DOCX, HAS_PYPDF

    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return {"success": False, "path": str(path), "filename": path.name, "error": f"The file '{path.name}' doesn't exist."}
    if not path.is_file():
        return {"success": False, "path": str(path), "filename": path.name, "error": f"'{path.name}' is not a file."}

    ext = path.suffix.lower()
    supported = TEXT_EXTENSIONS | {".docx", ".pdf"}
    if ext not in supported:
        return {"success": False, "path": str(path), "filename": path.name, "error": f"I can't read '{path.name}' — unsupported format."}

    try:
        content = read_document_content(str(path))
        get_desktop_context().current_file = str(path)
    except Exception as exc:
        return {"success": False, "path": str(path), "filename": path.name, "error": f"I couldn't read '{path.name}': {exc}"}

    lines = content.splitlines()
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        content = "\n".join(lines)
        content += f"\n... ({max_lines} lines shown, file has more)"

    return {
        "success": True,
        "path": str(path),
        "filename": path.name,
        "file_type": path.suffix.lower(),
        "content": content,
        "error": None,
    }



def create_file(filepath: str, content: str = "") -> str:
    """Create a new file with optional content. Won't overwrite existing files."""
    path = Path(filepath).expanduser().resolve()
    if path.exists():
        return f"'{path.name}' already exists."
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Created '{path.name}' in {path.parent.name}."
    except Exception as exc:
        return f"I couldn't create '{path.name}': {exc}"


def edit_file(filepath: str, old_text: str, new_text: str) -> str:
    """Replace specific text in a file."""
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return f"The file '{path.name}' doesn't exist."
    if not path.is_file():
        return f"'{path.name}' is not a file."
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"I couldn't read '{path.name}': {exc}"
    count = content.count(old_text)
    if count == 0:
        return f"Couldn't find the text to replace in '{path.name}'."
    new_content = content.replace(old_text, new_text)
    try:
        path.write_text(new_content, encoding="utf-8")
        return f"Made {count} replacement(s) in '{path.name}'."
    except Exception as exc:
        return f"I couldn't write to '{path.name}': {exc}"


def write_file(filepath: str, content: str) -> dict[str, Any]:
    """Overwrite a file entirely with new content.

    Returns a dict with success status, path, written content, and verification.
    """
    path = Path(filepath).expanduser().resolve()
    if path.exists() and not path.is_file():
        return {"success": False, "path": str(path), "error": f"'{path.name}' exists and is not a file."}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        # Verify by reading back
        actual_content = path.read_text(encoding="utf-8")
        verified = actual_content == content
        return {
            "success": True,
            "path": str(path),
            "filename": path.name,
            "written_content": content,
            "verified_content": actual_content,
            "verified": verified,
            "error": None,
        }
    except Exception as exc:
        return {"success": False, "path": str(path), "error": f"I couldn't save '{path.name}': {exc}"}


def create_folder(folder_path: str) -> str:
    """Create a new folder."""
    path = Path(folder_path).expanduser().resolve()
    if path.exists():
        return f"'{path.name}' already exists."
    try:
        path.mkdir(parents=True, exist_ok=True)
        return f"Created folder '{path.name}'."
    except Exception as exc:
        return f"I couldn't create the folder '{path.name}': {exc}"


def move_file(source: str, destination: str) -> str:
    """Move a file from source to destination."""
    src = Path(source).expanduser().resolve()
    dst = Path(destination).expanduser().resolve()
    if not src.exists():
        return f"The file '{src.name}' doesn't exist."
    try:
        if dst.is_dir():
            dst = dst / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved '{src.name}' to {dst.parent.name}."
    except Exception as exc:
        return f"I couldn't move '{src.name}': {exc}"


def copy_file(source: str, destination: str) -> str:
    """Copy a file from source to destination."""
    src = Path(source).expanduser().resolve()
    dst = Path(destination).expanduser().resolve()
    if not src.exists():
        return f"The file '{src.name}' doesn't exist."
    try:
        if dst.is_dir():
            dst = dst / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return f"Copied '{src.name}' to {dst.parent.name}."
    except Exception as exc:
        return f"I couldn't copy '{src.name}': {exc}"


def rename_file(filepath: str, new_name: str) -> str:
    """Rename a file."""
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return f"The file '{path.name}' doesn't exist."
    new_path = path.parent / new_name
    if new_path.exists():
        return f"'{new_name}' already exists in {path.parent.name}."
    try:
        path.rename(new_path)
        return f"Renamed '{path.name}' to '{new_name}'."
    except Exception as exc:
        return f"I couldn't rename '{path.name}': {exc}"


def delete_file(filepath: str) -> str:
    """Delete a file. This is destructive and should be confirmation-gated."""
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return f"The file '{path.name}' doesn't exist."
    try:
        if path.is_file():
            path.unlink()
            return f"Deleted '{path.name}'."
        if path.is_dir():
            shutil.rmtree(str(path))
            return f"Deleted folder '{path.name}' and its contents."
    except Exception as exc:
        return f"I couldn't delete '{path.name}': {exc}"


def get_file_info(filepath: str) -> str:
    """Get metadata about a file."""
    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        return f"The file '{filepath}' doesn't exist."
    try:
        stat = path.stat()
        info = [
            f"Name: {path.name}",
            f"Location: {path.parent}",
            f"Size: {_format_size(stat.st_size)}",
            f"Modified: {_format_time(stat.st_mtime)}",
            f"Created: {_format_time(stat.st_ctime)}",
        ]
        if path.is_file():
            info.append(f"Type: {path.suffix or 'unknown'}")
        return "\n".join(info)
    except Exception as exc:
        return f"I couldn't get info for '{path.name}': {exc}"


def list_directory(directory: str | None = None) -> str:
    """List the contents of a directory."""
    path = _resolve_directory(directory)
    if not path.is_dir():
        return f"I couldn't find the directory '{directory}'."
    try:
        entries = list(path.iterdir())
    except PermissionError:
        return f"I don't have permission to list '{path.name}'."
    if not entries:
        return f"'{path.name}' is empty."

    dirs = sorted([e for e in entries if e.is_dir()], key=lambda e: e.name.lower())
    files = sorted([e for e in entries if e.is_file()], key=lambda e: e.name.lower())

    lines = [f"Contents of {path.name}:"]
    if dirs:
        lines.append(f"  Folders ({len(dirs)}):")
        for d in dirs:
            lines.append(f"    {d.name}/")
    if files:
        lines.append(f"  Files ({len(files)}):")
        for f in files:
            try:
                size = _format_size(f.stat().st_size)
            except OSError:
                size = "?"
            lines.append(f"    {f.name} ({size})")
    return "\n".join(lines)


def open_item(path: str) -> str:
    """Open a file or folder with its default Windows handler (Explorer etc.).

    Resolves common directory aliases (Desktop, Documents, Downloads, ...).
    Never claims success unless the OS accepted the open request.
    """
    import sys
    if sys.platform != "win32":
        return "Opening files/folders natively is only supported on Windows."
    resolved = _resolve_directory(path)
    target = resolved if resolved.is_dir() else Path(path).expanduser()
    if not target.exists():
        return f"I couldn't open '{path}' — it doesn't exist."
    try:
        os.startfile(str(target))  # type: ignore[attr-defined]
        return f"Opened {target.name if target.name else target}."
    except OSError as exc:
        return f"I couldn't open '{path}': {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't open '{path}': {exc}"
