from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


INDEX_DIR = ".repo-ai"
INDEX_FILE = "index.json"
INDEX_VERSION = 2

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".agents",
    ".codex",
    ".idea",
    ".repo-ai",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    "coverage",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".class",
    ".jar",
    ".pyc",
    ".lock",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "React JSX",
    ".ts": "TypeScript",
    ".tsx": "React TSX",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ header",
    ".vue": "Vue",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
}

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]+|\d+")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

SYMBOL_QUERY_MARKERS = {
    "symbol",
    "function",
    "method",
    "class",
    "where",
    "used",
    "usage",
    "reference",
    "references",
    "call",
    "calls",
    "explain",
    "does",
    "\u51fd\u6570",
    "\u65b9\u6cd5",
    "\u7c7b",
    "\u8c03\u7528",
    "\u5f15\u7528",
    "\u4f7f\u7528",
    "\u7528\u5230",
    "\u8d1f\u8d23",
    "\u54ea\u91cc",
    "\u5728\u54ea\u91cc",
}

COMMON_IDENTIFIER_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "class",
    "code",
    "does",
    "file",
    "for",
    "function",
    "how",
    "in",
    "is",
    "it",
    "main",
    "method",
    "of",
    "project",
    "the",
    "this",
    "to",
    "used",
    "what",
    "where",
}

GENERIC_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(.+)|from\s+([A-Za-z0-9_.$/-]+)\s+import\s+(.+)|"
    r"(?:const|let|var)\s+\w+\s*=\s*require\(['\"]([^'\"]+)['\"]\))"
)
GENERIC_CLASS_RE = re.compile(r"\b(?:class|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
GENERIC_FUNCTION_RE = re.compile(
    r"\b(?:function\s+([A-Za-z_$][A-Za-z0-9_$]*)|"
    r"def\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(|"
    r"(?:public|private|protected|static|async|\s)+[A-Za-z_$][A-Za-z0-9_$<>,\[\]\s]*\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\()"
)

QUERY_EXPANSIONS = {
    "主要功能": "README readme overview feature module controller service api endpoint",
    "项目功能": "README readme overview feature module controller service api endpoint",
    "项目介绍": "README readme overview architecture module controller service api",
    "项目概览": "README readme overview architecture module controller service api",
    "做什么": "README readme overview feature module controller service api",
    "核心模块": "module package controller service mapper entity config api",
    "后端模块": "backend server controller service mapper entity config application",
    "前端模块": "frontend web view component router api request",
    "登录": "auth login token jwt security user password",
    "认证": "auth login token jwt security user password",
    "权限": "auth permission role security jwt",
    "文件": "file upload download attachment storage",
    "上传": "file upload attachment storage",
    "流程": "flow process node instance approval publish",
    "审批": "approval flow process node instance",
    "通知": "notification message reminder websocket",
    "AI": "ai llm prompt deepseek model suggestion optimization",
    "ai": "ai llm prompt deepseek model suggestion optimization",
    "配置": "config application yml yaml properties docker compose pom package",
    "数据库": "database datasource mapper entity sql mysql redis",
}

OVERVIEW_PATH_KEYWORDS = {
    "readme": 100,
    "pom.xml": 90,
    "package.json": 90,
    "docker-compose": 75,
    "application.yml": 75,
    "application-dev.yml": 75,
    "application.properties": 75,
    "vite.config": 60,
    "router": 45,
    "/api/": 50,
    "controller": 55,
    "service": 45,
    "config": 42,
    "dto": 25,
    "entity": 25,
    "mapper": 25,
}


@dataclass
class Chunk:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str


@dataclass
class Symbol:
    name: str
    kind: str
    path: str
    line: int
    end_line: int
    container: str = ""
    detail: str = ""
    module: str = ""


@dataclass
class IndexedFile:
    path: str
    language: str
    size: int
    mtime: float
    sha1: str
    chunks: list[Chunk]
    symbols: list[Symbol]


def index_path(root: Path) -> Path:
    return root / INDEX_DIR / INDEX_FILE


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def expand_query(query: str) -> str:
    additions: list[str] = []
    lowered = query.lower()
    for trigger, expansion in QUERY_EXPANSIONS.items():
        if trigger.lower() in lowered:
            additions.append(expansion)
    if not additions:
        return query
    return f"{query} {' '.join(additions)}"


def discover_files(root: Path) -> Iterable[Path]:
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS and not name.endswith(".egg-info")]
        current_path = Path(current)
        for filename in filenames:
            path = current_path / filename
            if should_index(path):
                yield path


def should_index(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size == 0 or stat.st_size > 500_000:
        return False
    return True


def read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def chunk_text(relative_path: str, text: str, max_lines: int = 80, overlap: int = 8) -> list[Chunk]:
    lines = text.splitlines()
    chunks: list[Chunk] = []
    if not lines:
        return chunks

    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        body = "\n".join(lines[start:end]).strip()
        if body:
            raw_id = f"{relative_path}:{start + 1}:{end}"
            chunks.append(
                Chunk(
                    id=hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12],
                    path=relative_path,
                    start_line=start + 1,
                    end_line=end,
                    text=body,
                )
            )
        if end == len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_symbols(relative_path: str, text: str) -> list[Symbol]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    if suffix == ".py":
        return extract_python_symbols(relative_path, text)
    return extract_generic_symbols(relative_path, text)


def extract_python_symbols(relative_path: str, text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return extract_generic_symbols(relative_path, text)

    lines = text.splitlines()
    symbols: list[Symbol] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = alias.name
                display = alias.asname or imported
                symbols.append(
                    Symbol(
                        name=display,
                        kind="import",
                        path=relative_path,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        detail=f"import {imported}",
                        module=imported,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                display = alias.asname or alias.name
                symbols.append(
                    Symbol(
                        name=display,
                        kind="import",
                        path=relative_path,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        detail=f"from {module or '.'} import {alias.name}",
                        module=module,
                    )
                )

    def visit_definitions(body: list[ast.stmt], container: str = "") -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind="class",
                        path=relative_path,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        container=container,
                        detail=source_line(lines, node.lineno),
                    )
                )
                next_container = f"{container}.{node.name}" if container else node.name
                visit_definitions(node.body, next_container)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind="method" if container else "function",
                        path=relative_path,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        container=container,
                        detail=source_line(lines, node.lineno),
                    )
                )

    visit_definitions(tree.body)
    symbols.sort(key=lambda symbol: (symbol.line, symbol.kind, symbol.name))
    return symbols


def extract_generic_symbols(relative_path: str, text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        import_match = GENERIC_IMPORT_RE.search(stripped)
        if import_match:
            imported = next((group for group in import_match.groups() if group), stripped)
            imported_name = imported.split(",")[0].strip().split()[0].strip("'\"")
            symbols.append(
                Symbol(
                    name=imported_name,
                    kind="import",
                    path=relative_path,
                    line=line_number,
                    end_line=line_number,
                    detail=stripped[:200],
                    module=imported_name,
                )
            )
            continue

        class_match = GENERIC_CLASS_RE.search(stripped)
        if class_match:
            symbols.append(
                Symbol(
                    name=class_match.group(1),
                    kind="class",
                    path=relative_path,
                    line=line_number,
                    end_line=line_number,
                    detail=stripped[:200],
                )
            )
            continue

        function_match = GENERIC_FUNCTION_RE.search(stripped)
        if function_match:
            name = next(group for group in function_match.groups() if group)
            symbols.append(
                Symbol(
                    name=name,
                    kind="function",
                    path=relative_path,
                    line=line_number,
                    end_line=line_number,
                    detail=stripped[:200],
                )
            )
    return symbols


def source_line(lines: list[str], line_number: int) -> str:
    if line_number < 1 or line_number > len(lines):
        return ""
    line = lines[line_number - 1].strip()
    return line[:200]


def build_index(root: Path) -> dict:
    root = root.resolve()
    indexed_files: list[IndexedFile] = []
    for path in discover_files(root):
        text = read_text(path)
        if text is None:
            continue
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
        symbols = extract_symbols(relative, text)
        indexed_files.append(
            IndexedFile(
                path=relative,
                language=LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "Text"),
                size=stat.st_size,
                mtime=stat.st_mtime,
                sha1=digest,
                chunks=chunk_text(relative, text),
                symbols=symbols,
            )
        )

    return {
        "version": INDEX_VERSION,
        "root": str(root),
        "file_count": len(indexed_files),
        "chunk_count": sum(len(file.chunks) for file in indexed_files),
        "symbol_count": sum(len(file.symbols) for file in indexed_files),
        "files": [asdict(file) for file in indexed_files],
    }


def save_index(root: Path, index: dict) -> Path:
    output = index_path(root.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def load_index(root: Path) -> dict:
    path = index_path(root.resolve())
    if not path.exists():
        raise FileNotFoundError(f"No index found at {path}. Run `repo-ai init` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_chunks(index: dict) -> Iterable[dict]:
    for file in index.get("files", []):
        for chunk in file.get("chunks", []):
            yield chunk


def iter_symbols(index: dict) -> Iterable[dict]:
    for file in index.get("files", []):
        for symbol in file.get("symbols", []):
            yield symbol


def has_symbol_intent(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in SYMBOL_QUERY_MARKERS)


def is_symbolish_identifier(identifier: str) -> bool:
    if not identifier or identifier.lower() in COMMON_IDENTIFIER_WORDS:
        return False
    return "_" in identifier or any(char.isupper() for char in identifier[1:]) or len(identifier) >= 12


def query_symbol_names(index: dict, query: str, limit: int = 5) -> list[str]:
    identifiers = IDENTIFIER_RE.findall(query)
    if not identifiers:
        return []

    symbol_names_by_lower: dict[str, str] = {}
    for symbol in iter_symbols(index):
        if symbol.get("kind") in {"class", "function", "method"}:
            name = str(symbol.get("name", ""))
            symbol_names_by_lower.setdefault(name.lower(), name)

    intent = has_symbol_intent(query)
    matches: list[str] = []
    seen: set[str] = set()
    for identifier in identifiers:
        lowered = identifier.lower()
        if lowered in seen or lowered not in symbol_names_by_lower:
            continue
        if intent or is_symbolish_identifier(identifier):
            matches.append(symbol_names_by_lower[lowered])
            seen.add(lowered)
        if len(matches) >= limit:
            break
    return matches


def exact_identifier_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")


def find_symbol_matches(index: dict, query: str, limit: int = 8) -> list[dict]:
    wanted = {name.lower() for name in query_symbol_names(index, query, limit=limit)}
    if not wanted:
        return []

    matches: list[dict] = []
    seen: set[tuple[str, int, str, str]] = set()
    for symbol in iter_symbols(index):
        if symbol.get("kind") not in {"class", "function", "method"}:
            continue
        if str(symbol.get("name", "")).lower() not in wanted:
            continue
        key = (
            str(symbol.get("path", "")),
            int(symbol.get("line", 0)),
            str(symbol.get("kind", "")),
            str(symbol.get("name", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        matches.append(symbol)
        if len(matches) >= limit:
            break
    return matches


def find_symbol_references(index: dict, symbol_name: str, limit: int = 20) -> list[dict]:
    if not symbol_name:
        return []

    pattern = exact_identifier_pattern(symbol_name)
    definition_lines = {
        (str(symbol.get("path", "")), int(symbol.get("line", 0)))
        for symbol in iter_symbols(index)
        if symbol.get("kind") in {"class", "function", "method"} and symbol.get("name") == symbol_name
    }
    references: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for chunk in iter_chunks(index):
        path = str(chunk.get("path", ""))
        start_line = int(chunk.get("start_line", 1))
        for offset, line in enumerate(str(chunk.get("text", "")).splitlines()):
            if not pattern.search(line):
                continue
            line_number = start_line + offset
            key = (path, line_number)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "path": path,
                    "line": line_number,
                    "kind": "definition" if key in definition_lines else "reference",
                    "text": line.strip()[:220],
                }
            )
            if len(references) >= limit:
                return references
    return references


def module_name_from_path(path: str) -> str:
    posix_path = PurePosixPath(path)
    if posix_path.suffix != ".py":
        return posix_path.with_suffix("").as_posix().replace("/", ".")
    module_parts = list(posix_path.with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def search(index: dict, query: str, top_k: int = 5) -> list[dict]:
    query_terms = tokenize(query)
    if not query_terms:
        return []

    chunks = list(iter_chunks(index))
    symbol_names = query_symbol_names(index, query)
    symbol_patterns = [exact_identifier_pattern(name) for name in symbol_names]
    document_frequency: dict[str, int] = {}
    tokenized_chunks: list[tuple[dict, list[str]]] = []
    for chunk in chunks:
        terms = tokenize(chunk.get("path", "") + "\n" + chunk.get("text", ""))
        tokenized_chunks.append((chunk, terms))
        for term in set(terms):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    total = max(len(chunks), 1)
    scored: list[tuple[float, dict]] = []
    for chunk, terms in tokenized_chunks:
        if not terms:
            continue
        term_counts: dict[str, int] = {}
        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1

        score = 0.0
        length_norm = 1.0 + len(terms) / 180.0
        for term in query_terms:
            if term not in term_counts:
                continue
            idf = math.log((total + 1) / (document_frequency.get(term, 0) + 1)) + 1.0
            score += (term_counts[term] / length_norm) * idf
        searchable = chunk.get("path", "") + "\n" + chunk.get("text", "")
        for pattern in symbol_patterns:
            if pattern.search(searchable):
                score += 8.0
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [{**chunk, "score": round(score, 4)} for score, chunk in scored[:top_k]]


def project_overview_chunks(index: dict, limit: int = 12) -> list[dict]:
    ranked: list[tuple[int, dict]] = []
    for chunk in iter_chunks(index):
        path = chunk.get("path", "").lower()
        score = 0
        for keyword, weight in OVERVIEW_PATH_KEYWORDS.items():
            if keyword in path:
                score += weight
        if path.count("/") <= 2:
            score += 10
        if score > 0:
            ranked.append((score, chunk))

    ranked.sort(key=lambda item: (item[0], -item[1].get("start_line", 0)), reverse=True)
    return [{**chunk, "score": score, "source": "project-overview"} for score, chunk in ranked[:limit]]
