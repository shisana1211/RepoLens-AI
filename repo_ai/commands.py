from __future__ import annotations

from collections import Counter, defaultdict
import re
from pathlib import Path

from . import git_tools, indexer, llm


CODE_REFERENCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".cs",
    ".c",
    ".cpp",
    ".h",
    ".vue",
}


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


def format_symbol(symbol: dict) -> str:
    name = str(symbol.get("name", ""))
    container = str(symbol.get("container", ""))
    qualified = f"{container}.{name}" if container else name
    start = int(symbol.get("line", 0))
    end = int(symbol.get("end_line", start))
    line_range = f"{start}" if start == end else f"{start}-{end}"
    detail = str(symbol.get("detail", "")).strip()
    suffix = f" - {detail}" if detail else ""
    return f"{symbol.get('kind', 'symbol')} `{qualified}` at {symbol.get('path')}:{line_range}{suffix}"


def symbol_answer(index: dict, question: str, reference_limit: int = 12) -> str:
    matches = indexer.find_symbol_matches(index, question)
    if not matches:
        return ""

    lines = ["Symbol analysis:"]
    for symbol in matches:
        name = str(symbol.get("name", ""))
        lines.append(f"- Definition: {format_symbol(symbol)}")
        references = indexer.find_symbol_references(index, name, limit=max(reference_limit * 4, 40))
        references.sort(
            key=lambda reference: (
                0 if is_code_reference_path(str(reference.get("path", ""))) else 1,
                0 if reference.get("kind") == "definition" else 1,
                str(reference.get("path", "")),
                int(reference.get("line", 0)),
            )
        )
        if references:
            lines.append(f"- References for `{name}`:")
            for reference in references[:reference_limit]:
                marker = "definition" if reference.get("kind") == "definition" else "reference"
                lines.append(
                    f"  - {reference['path']}:{reference['line']} [{marker}] "
                    f"{reference.get('text', '')}"
                )
        else:
            lines.append(f"- References for `{name}`: none found in indexed text.")
    return "\n".join(lines)


def init_repo(root: Path) -> str:
    index = indexer.build_index(root)
    output = indexer.save_index(root, index)
    return (
        f"Indexed {index['file_count']} files, {index['chunk_count']} chunks, "
        f"and {index.get('symbol_count', 0)} symbols.\n"
        f"Index saved to {output}"
    )


def ask(root: Path, question: str, top_k: int = 5, show_context: bool = False) -> str:
    index = indexer.load_index(root)
    expanded_question = indexer.expand_query(question)
    hits = indexer.search(index, expanded_question, top_k=top_k)
    symbol_context = symbol_answer(index, question)
    context_note = "retrieved by keyword search"
    if not hits:
        hits = indexer.project_overview_chunks(index, limit=max(top_k, 12))
        context_note = "retrieved by project overview fallback"
    if not hits and not symbol_context:
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
            f"{symbol_context}\n\n"
            f"Repository context:\n{context}"
        )
        try:
            return llm.complete(system, user, root=root)
        except llm.LlmUnavailable as exc:
            return f"LLM unavailable: {exc}\n\n" + local_answer_summary(hits, context_note, show_context)

    if symbol_context:
        return symbol_context + "\n\nLocal symbol analysis only. Add a real API key for a generated explanation."
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


def repo_map(root: Path) -> str:
    index = indexer.load_index(root)
    files = sorted(index.get("files", []), key=lambda item: item.get("path", ""))
    symbols = list(indexer.iter_symbols(index))
    symbol_counts = Counter(symbol.get("kind", "unknown") for symbol in symbols)
    languages = Counter(file.get("language", "Text") for file in files)

    output = [
        "Repository map:",
        "",
        "Summary:",
        f"- Indexed files: {index.get('file_count', len(files))}",
        f"- Chunks: {index.get('chunk_count', 0)}",
        f"- Symbols: {index.get('symbol_count', len(symbols))} "
        f"({format_counter(symbol_counts, default='none')})",
        f"- Languages: {format_counter(languages, default='unknown')}",
        "",
        "Module tree:",
        format_module_tree(files),
        "",
        "Main entry points:",
        format_entry_points(files),
        "",
        "Core files:",
        format_core_files(files),
        "",
        "Common imports:",
        format_common_imports(symbols),
    ]
    return "\n".join(output)


def format_counter(counter: Counter, default: str = "none", limit: int = 8) -> str:
    if not counter:
        return default
    return ", ".join(f"{name} {count}" for name, count in counter.most_common(limit))


def format_module_tree(files: list[dict], per_group_limit: int = 10) -> str:
    groups: dict[str, list[str]] = defaultdict(list)
    root_files: list[str] = []
    for file in files:
        path = str(file.get("path", ""))
        if "/" in path:
            top, rest = path.split("/", 1)
            groups[top].append(rest)
        else:
            root_files.append(path)

    lines: list[str] = []
    if root_files:
        lines.append("- ./")
        for path in sorted(root_files)[:per_group_limit]:
            lines.append(f"  - {path}")
        if len(root_files) > per_group_limit:
            lines.append(f"  - ... {len(root_files) - per_group_limit} more")

    for group, children in sorted(groups.items()):
        lines.append(f"- {group}/ ({len(children)} files)")
        for child in sorted(children)[:per_group_limit]:
            lines.append(f"  - {child}")
        if len(children) > per_group_limit:
            lines.append(f"  - ... {len(children) - per_group_limit} more")
    return "\n".join(lines) if lines else "- No indexed files."


def format_entry_points(files: list[dict]) -> str:
    entry_keywords = (
        "__main__.py",
        "cli.py",
        "main.py",
        "app.py",
        "manage.py",
        "pyproject.toml",
        "package.json",
        "pom.xml",
        "README.md",
    )
    lines: list[str] = []
    for file in files:
        path = str(file.get("path", ""))
        if not any(path.endswith(keyword) for keyword in entry_keywords):
            continue
        definitions = [
            symbol.get("name", "")
            for symbol in file.get("symbols", [])
            if symbol.get("kind") in {"class", "function", "method"}
        ]
        suffix = f" - symbols: {', '.join(definitions[:6])}" if definitions else ""
        lines.append(f"- {path}{suffix}")
    return "\n".join(lines[:12]) if lines else "- No obvious entry points found."


def format_core_files(files: list[dict], limit: int = 10) -> str:
    ranked: list[tuple[int, dict]] = []
    for file in files:
        path = str(file.get("path", ""))
        definitions = [symbol for symbol in file.get("symbols", []) if symbol.get("kind") != "import"]
        imports = [symbol for symbol in file.get("symbols", []) if symbol.get("kind") == "import"]
        score = len(definitions) * 6 + len(imports) + len(file.get("chunks", [])) * 2
        lowered = path.lower()
        if any(keyword in lowered for keyword in ("index", "command", "cli", "service", "controller", "main")):
            score += 10
        if score > 0:
            ranked.append((score, file))

    ranked.sort(key=lambda item: item[0], reverse=True)
    lines: list[str] = []
    for score, file in ranked[:limit]:
        definitions = Counter(
            symbol.get("kind", "symbol")
            for symbol in file.get("symbols", [])
            if symbol.get("kind") != "import"
        )
        lines.append(
            f"- {file.get('path')} - score {score}; "
            f"{format_counter(definitions, default='no definitions')}; "
            f"{len(file.get('chunks', []))} chunks"
        )
    return "\n".join(lines) if lines else "- No core files detected."


def format_common_imports(symbols: list[dict], limit: int = 12) -> str:
    imports = Counter()
    for symbol in symbols:
        if symbol.get("kind") != "import":
            continue
        module = str(symbol.get("module") or symbol.get("name") or "").strip()
        if not module or module == "__future__":
            continue
        root_module = module.lstrip(".").split(".")[0] or str(symbol.get("name", ""))
        if root_module:
            imports[root_module] += 1
    if not imports:
        return "- No imports detected."
    return "\n".join(f"- {name}: {count} references" for name, count in imports.most_common(limit))


def impact(root: Path, staged: bool = False) -> str:
    diff = git_tools.git_diff(root, staged=staged)
    if not diff.strip():
        return "No diff found."

    changed = git_tools.changed_files(diff)
    added, removed = git_tools.diff_stats(diff)
    try:
        index = indexer.load_index(root)
    except FileNotFoundError:
        return (
            "Impact analysis:\n\n"
            f"- Changed files: {len(changed)}\n"
            f"- Diff size: +{added} / -{removed}\n"
            "- No repository index found. Run `repo-ai init` for symbol and reference impact."
        )

    changed_lines = git_tools.changed_line_numbers(diff)
    changed_set = set(changed)
    module_names = sorted({indexer.module_name_from_path(path) for path in changed})
    touched_symbols = collect_touched_symbols(root, changed, changed_lines)
    reference_lines = format_reference_impact(index, touched_symbols, changed_set)
    import_lines = format_import_dependents(index, changed_set, module_names)
    risk_lines = format_diff_risks(diff)

    output = [
        "Impact analysis:",
        "",
        "Changed files:",
        *(f"- {path} (+{len(changed_lines.get(path, set()))} changed lines)" for path in changed),
        "",
        f"Diff size: +{added} / -{removed}",
        "",
        "Affected modules:",
        *(f"- {module}" for module in module_names[:12]),
        "",
        "Touched symbols:",
        *format_touched_symbols(touched_symbols),
        "",
        "Reference impact:",
        *reference_lines,
        "",
        "Import dependents:",
        *import_lines,
        "",
        "Risk signals:",
        *risk_lines,
        "",
        "Suggested next checks:",
        "- Run focused tests for the changed modules.",
        "- Run `repo-ai review` for line-level review findings.",
        "- Run `repo-ai init` after large edits so symbol references stay fresh.",
    ]
    return "\n".join(output)


def collect_touched_symbols(root: Path, changed: list[str], changed_lines: dict[str, set[int]]) -> list[dict]:
    touched: list[dict] = []
    for path in changed:
        target = root / path
        text = indexer.read_text(target)
        if text is None:
            continue
        symbols = [symbol for symbol in indexer.extract_symbols(path, text) if symbol.kind != "import"]
        line_numbers = changed_lines.get(path, set())
        if line_numbers:
            selected = [
                symbol
                for symbol in symbols
                if any(symbol.line <= line <= symbol.end_line for line in line_numbers)
            ]
        else:
            selected = []
        for symbol in selected or symbols[:5]:
            touched.append(
                {
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "path": symbol.path,
                    "line": symbol.line,
                    "end_line": symbol.end_line,
                    "container": symbol.container,
                    "detail": symbol.detail,
                }
            )
    return touched


def format_touched_symbols(symbols: list[dict], limit: int = 16) -> list[str]:
    if not symbols:
        return ["- No changed symbols detected. Changes may be in config, docs, imports, or new unindexed text."]
    return [f"- {format_symbol(symbol)}" for symbol in symbols[:limit]]


def format_reference_impact(index: dict, touched_symbols: list[dict], changed_files: set[str], limit: int = 12) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[str, int, str]] = set()
    for symbol in touched_symbols:
        name = str(symbol.get("name", ""))
        if not name:
            continue
        for reference in indexer.find_symbol_references(index, name, limit=30):
            if reference.get("kind") == "definition" or reference.get("path") in changed_files:
                continue
            if not is_code_reference_path(str(reference.get("path", ""))):
                continue
            key = (str(reference.get("path", "")), int(reference.get("line", 0)), name)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"- `{name}` referenced at {reference['path']}:{reference['line']} "
                f"{reference.get('text', '')}"
            )
            if len(lines) >= limit:
                return lines
    return lines or ["- No downstream symbol references found in the current index."]


def is_code_reference_path(path: str) -> bool:
    return Path(path).suffix.lower() in CODE_REFERENCE_SUFFIXES


def format_import_dependents(index: dict, changed_files: set[str], module_names: list[str], limit: int = 12) -> list[str]:
    module_tokens = {module for module in module_names if module}
    module_tokens.update(module.split(".")[-1] for module in module_names if module)
    lines: list[str] = []
    seen: set[tuple[str, int]] = set()
    for symbol in indexer.iter_symbols(index):
        if symbol.get("kind") != "import" or symbol.get("path") in changed_files:
            continue
        searchable = " ".join(
            str(symbol.get(key, ""))
            for key in ("name", "module", "detail")
        )
        if not any(token and re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", searchable) for token in module_tokens):
            continue
        key = (str(symbol.get("path", "")), int(symbol.get("line", 0)))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {symbol.get('path')}:{symbol.get('line')} imports {symbol.get('detail')}")
        if len(lines) >= limit:
            return lines
    return lines or ["- No import dependents found in the current index."]


def format_diff_risks(diff: str, limit: int = 10) -> list[str]:
    review = git_tools.heuristic_review(diff)
    if review.startswith("No obvious heuristic issues"):
        return ["- No obvious heuristic risk signals found."]
    return [f"- {line}" for line in review.splitlines()[:limit]]
