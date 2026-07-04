from __future__ import annotations

import re
from pathlib import Path

from . import git_tools, indexer, llm


def format_snippet(chunk: dict, max_chars: int = 1200) -> str:
    text = chunk.get("text", "")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n..."
    return f"{chunk['path']}:{chunk['start_line']}-{chunk['end_line']}\n{text}"


def format_source_list(hits: list[dict], limit: int = 10) -> str:
    lines = []
    seen: set[str] = set()
    for hit in hits:
        source = f"{hit['path']}:{hit['start_line']}-{hit['end_line']}"
        if source in seen:
            continue
        seen.add(source)
        score = hit.get("score")
        suffix = f" score={score}" if isinstance(score, (int, float)) else ""
        lines.append(f"- {source}{suffix}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def local_answer_summary(hits: list[dict], context_note: str, show_context: bool) -> str:
    sources = format_source_list(hits)
    output = [
        "Local retrieval only: no valid LLM API key is configured.",
        f"Retrieval note: {context_note}.",
        "",
        "Most relevant sources:",
        sources or "- None",
        "",
        "What to do next:",
        "- Add a real API key in .repo-ai/config.json for a generated answer.",
        "- Use `explain <file>` when you want a precise explanation of one file.",
        "- Use `ask --show-context` to print the retrieved code snippets.",
    ]
    if show_context:
        context = "\n\n---\n\n".join(format_snippet(hit) for hit in hits)
        output.extend(["", "Retrieved context:", context])
    return "\n".join(output)


def init_repo(root: Path) -> str:
    index = indexer.build_index(root)
    output = indexer.save_index(root, index)
    return (
        f"Indexed {index['file_count']} files and {index['chunk_count']} chunks.\n"
        f"Index saved to {output}"
    )


def ask(root: Path, question: str, top_k: int = 5, show_context: bool = False) -> str:
    index = indexer.load_index(root)
    expanded_question = indexer.expand_query(question)
    hits = indexer.search(index, expanded_question, top_k=top_k)
    context_note = "retrieved by keyword search"
    if not hits:
        hits = indexer.project_overview_chunks(index, limit=max(top_k, 12))
        context_note = "retrieved by project overview fallback"
    if not hits:
        return "No relevant indexed context found."

    context = "\n\n---\n\n".join(format_snippet(hit) for hit in hits)
    if llm.is_configured(root):
        system = (
            "You are Repo AI, a precise codebase assistant. Answer only from the provided repository context. "
            "Cite files with path:line ranges. If the context is insufficient, say what is missing."
        )
        user = (
            f"Question:\n{question}\n\n"
            f"Retrieval note: {context_note}.\n"
            f"Repository context:\n{context}"
        )
        try:
            return llm.complete(system, user, root=root)
        except llm.LlmUnavailable as exc:
            return f"LLM unavailable: {exc}\n\n" + local_answer_summary(hits, context_note, show_context)

    return local_answer_summary(hits, context_note, show_context)


def explain(root: Path, file_path: str) -> str:
    target = (root / file_path).resolve()
    root = root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("File must be inside the repository root.") from exc
    if not target.exists() or not target.is_file():
        raise RuntimeError(f"File not found: {file_path}")

    text = indexer.read_text(target)
    if text is None:
        raise RuntimeError(f"Could not read text file: {file_path}")
    relative = target.relative_to(root).as_posix()
    trimmed = text[:12_000]

    if llm.is_configured(root):
        system = "You explain source files for developers. Be concise and concrete. Mention responsibilities, key functions, and risks."
        user = f"Explain this file: {relative}\n\n```text\n{trimmed}\n```"
        try:
            return llm.complete(system, user, root=root)
        except llm.LlmUnavailable as exc:
            return f"LLM unavailable: {exc}\n\n{local_file_summary(relative, text)}"

    return local_file_summary(relative, text)


def local_file_summary(relative: str, text: str) -> str:
    lines = text.splitlines()
    imports = [line.strip() for line in lines if re.match(r"\s*(import|from|package|using|require\()", line)]
    definitions = [
        line.strip()
        for line in lines
        if re.match(r"\s*(def|class|function|export function|const \w+\s*=|public class|private|public|protected)\b", line)
    ]
    output = [
        f"File: {relative}",
        f"Lines: {len(lines)}",
        "",
        "Notable imports/packages:",
        *(f"- {item}" for item in imports[:12]),
        "",
        "Notable definitions:",
        *(f"- {item}" for item in definitions[:20]),
    ]
    if not imports:
        output.insert(4, "- None detected")
    if not definitions:
        output.append("- None detected")
    return "\n".join(output)


def review(root: Path, staged: bool = False) -> str:
    diff = git_tools.git_diff(root, staged=staged)
    if not diff.strip():
        return "No diff found."

    if llm.is_configured(root):
        system = (
            "You are a senior engineer doing code review. Lead with findings only. "
            "Use severity tags [P1], [P2], [P3]. Cite file paths and lines when possible."
        )
        user = f"Review this git diff:\n\n```diff\n{diff[:30_000]}\n```"
        try:
            return llm.complete(system, user, root=root)
        except llm.LlmUnavailable as exc:
            return f"LLM unavailable: {exc}\n\n{git_tools.heuristic_review(diff)}"

    return git_tools.heuristic_review(diff)


def commit_message(root: Path, staged: bool = False) -> str:
    diff = git_tools.git_diff(root, staged=staged)
    if not diff.strip():
        return "No diff found."

    if llm.is_configured(root):
        system = "Generate one Conventional Commit message. Return only the commit message, no markdown."
        user = f"Generate a commit message for this diff:\n\n```diff\n{diff[:25_000]}\n```"
        try:
            return llm.complete(system, user, temperature=0.1, root=root)
        except llm.LlmUnavailable:
            pass

    return git_tools.heuristic_commit_message(diff)
