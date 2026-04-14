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


def normalize_messages(messages: list) -> list:
    """
    Clean up messages before sending to the API.
    - Strip internal metadata fields
    - Ensure every tool_use has a matching tool_result
    - Merge consecutive same-role messages
    """
    cleaned = []
    for msg in messages:
        clean = {"role": msg["role"]}
        if isinstance(msg.get("content"), str):
            clean["content"] = msg["content"]
        elif isinstance(msg.get("content"), list):
            clean["content"] = [
                {k: v for k, v in block.items() if not k.startswith("_")}
                for block in msg["content"]
                if isinstance(block, dict)
            ]
        else:
            clean["content"] = msg.get("content", "")
        cleaned.append(clean)

    # Insert placeholder tool_result for orphaned tool_use blocks
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
                cleaned.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block["id"], "content": "(cancelled)"}
                ]})

    # Merge consecutive same-role messages
    if not cleaned:
        return cleaned
    merged = [cleaned[0]]
    for msg in cleaned[1:]:
        if msg["role"] == merged[-1]["role"]:
            prev = merged[-1]
            prev_c = prev["content"] if isinstance(prev["content"], list) \
                else [{"type": "text", "text": str(prev["content"])}]
            curr_c = msg["content"] if isinstance(msg["content"], list) \
                else [{"type": "text", "text": str(msg["content"])}]
            prev["content"] = prev_c + curr_c
        else:
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
