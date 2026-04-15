# Common utilities for all sessions
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Optional


def get_workdir() -> Path:
    """Current working directory for the agent."""
    return Path.cwd()


def get_repo_root(cwd: Path | None = None) -> Path:
    """Detect git repo root, falling back to workdir."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or get_workdir(), capture_output=True, text=True, timeout=10,
        )
        root = Path(r.stdout.strip())
        if r.returncode == 0 and root.exists():
            return root
    except Exception:
        pass
    return cwd or get_workdir()


def safe_path(path_str: str, workdir: Path | None = None) -> Path:
    """Resolve path relative to workdir, reject escapes."""
    wd = workdir or get_workdir()
    path = (wd / path_str).resolve()
    if not path.is_relative_to(wd):
        raise ValueError(f"Path escapes workspace: {path_str}")
    return path


# Dangerous command patterns — blocked regardless of permission mode
DANGEROUS_PATTERNS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]


def is_dangerous(command: str) -> bool:
    return any(p in command for p in DANGEROUS_PATTERNS)


def run_bash(command: str, workdir: Path | None = None, timeout: int = 120) -> str:
    """Run a shell command, capture output."""
    if is_dangerous(command):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=workdir or get_workdir(),
            capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


def read_file(path_str: str, workdir: Path | None = None, limit: int | None = None) -> str:
    """Read file contents, optionally limited to first N lines."""
    try:
        lines = safe_path(path_str, workdir).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def write_file(path_str: str, content: str, workdir: Path | None = None) -> str:
    """Write content to file, creating parent dirs as needed."""
    try:
        fp = safe_path(path_str, workdir)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path_str}"
    except Exception as e:
        return f"Error: {e}"


def edit_file(path_str: str, old_text: str, new_text: str, workdir: Path | None = None) -> str:
    """Replace exact text in file once."""
    try:
        fp = safe_path(path_str, workdir)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path_str}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path_str}"
    except Exception as e:
        return f"Error: {e}"


def _to_dict(obj):
    """Convert Pydantic models or dicts to plain dicts, strip private fields."""
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if not k.startswith("_")}
    if hasattr(obj, "model_dump"):          # Pydantic v2
        return {k: v for k, v in obj.model_dump().items() if not k.startswith("_")}
    if hasattr(obj, "as_dict"):             # Pydantic v1
        return {k: v for k, v in obj.as_dict().items() if not k.startswith("_")}
    return obj

def normalize_messages(messages: list) -> list:
    """
    Clean up messages before sending to the API.
    - Strip internal metadata fields
    - Ensure every tool_use has a matching tool_result (idempotent: placeholders only added once)
    - Merge consecutive same-role TEXT-ONLY messages (blocks are never merged)
    """
    cleaned = []
    for msg in messages:
        clean = {"role": msg["role"]}
        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            clean["content"] = raw_content
        elif isinstance(raw_content, list):
            blocks = [_to_dict(b) for b in raw_content if _to_dict(b) is not None]
            clean["content"] = blocks
        else:
            clean["content"] = raw_content if raw_content is not None else ""
        cleaned.append(clean)

    # Insert placeholder tool_result for orphaned tool_use blocks (idempotent)
    existing_results = set()
    for msg in cleaned:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    existing_results.add(block.get("tool_use_id"))

    for msg in cleaned:
        if msg["role"] != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") not in existing_results:
                # Mark this tool_use id so we don't add a second placeholder on re-normalize
                existing_results.add(block.get("id"))
                cleaned.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block["id"], "content": "(cancelled)"}
                ]})

    # Merge consecutive same-role TEXT-ONLY messages (blocks are never merged)
    if not cleaned:
        return cleaned
    merged = [cleaned[0]]
    for msg in cleaned[1:]:
        if msg["role"] == merged[-1]["role"]:
            prev_c = merged[-1]["content"]
            curr_c = msg["content"]
            prev_is_text = isinstance(prev_c, str) or (
                isinstance(prev_c, list) and len(prev_c) == 0
            )
            curr_is_text = isinstance(curr_c, str) or (
                isinstance(curr_c, list) and len(curr_c) == 0
            )
            if prev_is_text and curr_is_text:
                # Both text-only: merge string content
                merged[-1]["content"] = str(prev_c) + "\n" + str(curr_c)
                continue
        merged.append(msg)
    return merged


def extract_text(content) -> str:
    """Extract plain text from API response content."""
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()
