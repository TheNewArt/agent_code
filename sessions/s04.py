"""
s04.py — Session 04: Subagent / Task Delegation
================================================
Spawn a subagent in a background thread to handle a sub-task.
The subagent has its own messages and tools, and writes results to disk.
"""

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\10621\Desktop\code_source\agent_code\.env", override=True)

WORKDIR = Path.cwd()
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "spawn", "description": "Spawn a subagent in a background thread. Returns task_id.",
     "input_schema": {"type": "object", "properties": {
         "prompt": {"type": "string", "description": "Task description for the subagent"},
         "output_file": {"type": "string", "description": "File to write results to"}}, "required": ["prompt"]}},
    {"name": "check_spawn", "description": "Check subagent result.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
]

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120)
        return (r.stdout + r.stderr).strip()[:50000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str) -> str:
    try:
        return safe_path(path).read_text()[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

_subagent_results: dict = {}
_subagent_lock = threading.Lock()

def _subagent_loop(prompt: str, output_file: str, task_id: str):
    sys_prompt = (
        f"You are a subagent at {WORKDIR}. "
        "Use bash, read_file, write_file, edit_file to complete the task. "
        "Write your final result to the output file."
    )
    sub_tools = [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace exact text in file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    ]
    messages = [{"role": "user", "content": prompt}]
    try:
        response = client.messages.create(model=MODEL, system=sys_prompt, messages=messages, tools=sub_tools, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                args = block.input or {}
                if block.name == "bash":
                    out = run_bash(args.get("command", ""))
                elif block.name == "read_file":
                    out = run_read(args.get("path", ""))
                elif block.name == "write_file":
                    out = run_write(args.get("path", ""), args.get("content", ""))
                elif block.name == "edit_file":
                    out = "Cannot edit in subagent mode (use write_file instead)"
                else:
                    out = f"Unknown: {block.name}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
        messages.append({"role": "user", "content": results})
        # Write result
        if output_file:
            out_path = safe_path(output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            final = response.content[0].text if response.content else "(no output)"
            out_path.write_text(final)
        final_text = response.content[0].text if response.content else "(no output)"
    except Exception as e:
        final_text = f"Error: {e}"
        if output_file:
            safe_path(output_file).parent.mkdir(parents=True, exist_ok=True)
            safe_path(output_file).write_text(final_text)
    with _subagent_lock:
        _subagent_results[task_id] = final_text

def do_spawn(prompt: str, output_file: str = "") -> str:
    task_id = str(uuid.uuid4())[:8]
    thread = threading.Thread(target=_subagent_loop, args=(prompt, output_file, task_id), daemon=True)
    thread.start()
    return f"Spawned subagent task_id={task_id} (background thread)"

def do_check_spawn(task_id: str) -> str:
    with _subagent_lock:
        result = _subagent_results.get(task_id)
    if result is None:
        return f"Task {task_id}: still running or unknown"
    return f"Task {task_id} result:\n{result}"

TOOL_HANDLERS = {
    "bash": lambda kw: run_bash(kw["command"]),
    "read_file": lambda kw: run_read(kw["path"]),
    "write_file": lambda kw: run_write(kw["path"], kw["content"]),
    "spawn": lambda kw: do_spawn(kw["prompt"], kw.get("output_file", "")),
    "check_spawn": lambda kw: do_check_spawn(kw["task_id"]),
}

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools. Spawn subagents for parallel work."

def agent_loop(messages: list):
    while True:
        response = client.messages.create(model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(block.input) if handler else f"Unknown: {block.name}"
            print(f"> {block.name}: {str(output)[:200]}")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    print("s04 — Subagent delegation. spawn starts a background thread.")
    history = []
    while True:
        try:
            query = input("\033[36ms04 >> \033[0m")
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
