from __future__ import annotations

import re
import subprocess
from pathlib import Path


def run_git(root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or "git command failed")
    return result.stdout


def git_diff(root: Path, staged: bool = False) -> str:
    args = ["diff", "--staged"] if staged else ["diff"]
    return run_git(root, args)


def changed_files(diff: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+)$", diff, flags=re.MULTILINE):
        path = match.group(2)
        if path not in seen:
            files.append(path)
            seen.add(path)
    if files:
        return files

    for path in re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE):
        if path not in seen:
            files.append(path)
            seen.add(path)
    return files


def changed_line_numbers(diff: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current_file = ""
    new_line = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            changed.setdefault(current_file, set())
            new_line = 0
            continue
        if line.startswith("+++ /dev/null"):
            current_file = ""
            new_line = 0
            continue
        match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if match:
            new_line = int(match.group(1)) - 1
            continue
        if not current_file:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_line += 1
            changed[current_file].add(new_line)
        elif line.startswith(" ") and new_line:
            new_line += 1
    return changed


def diff_stats(diff: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def heuristic_review(diff: str) -> str:
    findings: list[str] = []
    current_file = "unknown"
    new_line = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            new_line = 0
            continue
        match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if match:
            new_line = int(match.group(1)) - 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_line += 1
            lowered = line.lower()
            body = line[1:].strip()
            if "todo" in lowered or "fixme" in lowered:
                findings.append(f"[P3] {current_file}:{new_line} contains unfinished marker: `{body}`")
            if "console.log" in lowered or re.search(r"\bprint\(", body):
                findings.append(f"[P2] {current_file}:{new_line} adds debug output: `{body}`")
            if "except:" in lowered and "pass" in lowered:
                findings.append(f"[P1] {current_file}:{new_line} may swallow errors with broad exception handling.")
            if re.search(r"(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]+['\"]", lowered):
                findings.append(f"[P1] {current_file}:{new_line} looks like a hard-coded credential.")
            if re.search(r"\beval\(", lowered):
                findings.append(f"[P1] {current_file}:{new_line} uses eval; validate whether this can execute untrusted input.")
        elif line.startswith(" ") and new_line:
            new_line += 1

    if not findings:
        return "No obvious heuristic issues found. Use an API key for deeper model-based review."
    return "\n".join(findings)


def heuristic_commit_message(diff: str) -> str:
    files = changed_files(diff)
    added, removed = diff_stats(diff)
    lowered = "\n".join(files).lower()
    if any(path.endswith((".md", ".rst")) for path in files):
        kind = "docs"
    elif any("test" in path.lower() or path.endswith(("_test.py", ".spec.ts", ".test.ts")) for path in files):
        kind = "test"
    elif any(path.endswith((".toml", ".yml", ".yaml", ".json")) for path in files):
        kind = "chore"
    elif "fix" in diff.lower() or "bug" in diff.lower():
        kind = "fix"
    elif added > removed:
        kind = "feat"
    else:
        kind = "refactor"

    if "auth" in lowered or "login" in lowered:
        scope = "auth"
    elif "cli" in lowered:
        scope = "cli"
    elif "test" in lowered:
        scope = "tests"
    elif files:
        scope = Path(files[0]).stem.replace("_", "-")[:18] or "repo"
    else:
        scope = "repo"

    summary = "update repository changes"
    if files:
        summary = f"update {len(files)} file{'s' if len(files) != 1 else ''}"
    return f"{kind}({scope}): {summary}"
