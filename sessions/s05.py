"""
s05.py — Session 05: Skills System
===================================
Skills are directories with SKILL.md files containing frontmatter.
The agent can load any skill's full body into context with load_skill.
Skills live in a skills/ directory.
"""

import os, re
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\10621\Desktop\code_source\agent_code\.env", override=True)

WORKDIR = Path.cwd()
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

SKILLS_DIR = WORKDIR / "skills"

# ---- SkillRegistry ----
class SkillRegistry:
    def __init__(self, skills_dir):
        self.skills_dir = Path(skills_dir)
        self.documents = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.rglob("SKILL.md")):
            meta, body = self._parse_frontmatter(path.read_text())
            name = meta.get("name", path.parent.name)
            desc = meta.get("description", "No description")
            self.documents[name] = {"description": desc, "body": body.strip(), "path": path}

    def _parse_frontmatter(self, text):
        m = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not m:
            return {}, text
        meta = {}
        for line in m.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, m.group(2)

    def describe_available(self):
        if not self.documents:
            return "(no skills available)"
        return "\n".join(f"- {n}: {d['description']}" for n, d in sorted(self.documents.items()))

    def load_full_text(self, name):
        doc = self.documents.get(name)
        if not doc:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(sorted(self.documents)) or '(none)'}"
        return f'<skill name="{name}">\n{doc["body"]}\n</skill>'

SKILLS = SkillRegistry(SKILLS_DIR)

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "skills_list", "description": "List available skills.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "load_skill", "description": "Load the full body of a named skill.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
]

def safe_path(p):
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command):
    import subprocess
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120)
        return (r.stdout + r.stderr).strip()[:50000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path):
    try:
        return safe_path(path).read_text()[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path, content):
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path, old_text, new_text):
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

TOOL_HANDLERS = {
    "bash": lambda kw: run_bash(kw["command"]),
    "read_file": lambda kw: run_read(kw["path"]),
    "write_file": lambda kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "skills_list": lambda kw: SKILLS.describe_available(),
    "load_skill": lambda kw: SKILLS.load_full_text(kw["name"]),
}

SYSTEM_BASE = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks."

def build_system():
    return SYSTEM_BASE + f"\n\nAvailable skills:\n{SKILLS.describe_available()}\n\nUse load_skill to load a skill's full instructions."

def agent_loop(messages):
    while True:
        response = client.messages.create(model=MODEL, system=build_system(), messages=messages, tools=TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            h = TOOL_HANDLERS.get(block.name, lambda _: f"Unknown: {block.name}")
            out = h(block.input)
            print(f"> {block.name}: {str(out)[:200]}")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(out)})
        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    print(f"s05 — Skills system. {len(SKILLS.documents)} skills loaded from {SKILLS_DIR}")
    history = []
    while True:
        try:
            query = input("\033[36ms05 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        content = history[-1]["content"]
        if isinstance(content, list):
            for b in content:
                if hasattr(b, "text"):
                    print(b.text)
        print()
