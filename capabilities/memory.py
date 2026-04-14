# Agent capability: Persistent Memory
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Literal

MemoryType = Literal["user", "feedback", "project", "reference"]


class MemoryManager:
    """
    Persistent cross-session memory store.
    Each memory is a .md file with frontmatter, plus a compact MEMORY.md index.
    """

    MEMORY_TYPES = ("user", "feedback", "project", "reference")
    MAX_INDEX_LINES = 200

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memories: dict[str, dict] = {}  # name -> {description, type, content, file}

    def load_all(self) -> None:
        self.memories.clear()
        if not self.memory_dir.exists():
            return
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            parsed = self._parse_frontmatter(md_file.read_text())
            if parsed:
                name = parsed.get("name", md_file.stem)
                self.memories[name] = {
                    "description": parsed.get("description", ""),
                    "type": parsed.get("type", "project"),
                    "content": parsed.get("content", ""),
                    "file": md_file.name,
                }
        count = len(self.memories)
        if count > 0:
            print(f"[Memory loaded: {count} memories from {self.memory_dir}]")

    def load_memory_prompt(self) -> str:
        """Build a memory section for injection into the system prompt."""
        if not self.memories:
            return ""
        sections = ["# Memories (persistent across sessions)", ""]
        for mem_type in self.MEMORY_TYPES:
            typed = {k: v for k, v in self.memories.items() if v["type"] == mem_type}
            if not typed:
                continue
            sections.append(f"## [{mem_type}]")
            for name, mem in typed.items():
                sections.append(f"### {name}: {mem['description']}")
                if mem["content"].strip():
                    sections.append(mem["content"].strip())
                sections.append("")
        return "\n".join(sections)

    def save_memory(self, name: str, description: str, mem_type: str, content: str) -> str:
        if mem_type not in self.MEMORY_TYPES:
            return f"Error: type must be one of {self.MEMORY_TYPES}"
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        if not safe_name:
            return "Error: invalid memory name"

        self.memory_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = (
            f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n{content}\n"
        )
        file_path = self.memory_dir / f"{safe_name}.md"
        file_path.write_text(frontmatter)

        self.memories[name] = {
            "description": description,
            "type": mem_type,
            "content": content,
            "file": file_path.name,
        }
        self._rebuild_index()
        return f"Saved memory '{name}' [{mem_type}] to {file_path.name}"

    def _rebuild_index(self) -> None:
        lines = ["# Memory Index", ""]
        for name, mem in self.memories.items():
            lines.append(f"- {name}: {mem['description']} [{mem['type']}]")
            if len(lines) >= self.MAX_INDEX_LINES:
                lines.append(f"... (truncated at {self.MAX_INDEX_LINES} lines)")
                break
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (self.memory_dir / "MEMORY.md").write_text("\n".join(lines) + "\n")

    def _parse_frontmatter(self, text: str) -> dict | None:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        header, body = match.group(1), match.group(2)
        result = {"content": body.strip()}
        for line in header.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
        return result
