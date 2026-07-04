from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


INDEX_DIR = ".repo-ai"
INDEX_FILE = "index.json"
INDEX_VERSION = 1

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".repo-ai",
    ".venv",
    "venv",
    "__pycache__",
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
class IndexedFile:
    path: str
    language: str
    size: int
    mtime: float
    sha1: str
    chunks: list[Chunk]


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
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
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
        indexed_files.append(
            IndexedFile(
                path=relative,
                language=LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "Text"),
                size=stat.st_size,
                mtime=stat.st_mtime,
                sha1=digest,
                chunks=chunk_text(relative, text),
            )
        )

    return {
        "version": INDEX_VERSION,
        "root": str(root),
        "file_count": len(indexed_files),
        "chunk_count": sum(len(file.chunks) for file in indexed_files),
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


def search(index: dict, query: str, top_k: int = 5) -> list[dict]:
    query_terms = tokenize(query)
    if not query_terms:
        return []

    chunks = list(iter_chunks(index))
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
