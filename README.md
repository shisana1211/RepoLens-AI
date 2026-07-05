# RepoLens AI

RepoLens AI is an AI-powered CLI for understanding local code repositories. It supports repository indexing, RAG-style Q&A, file explanation, Git Diff review, and Conventional Commit message generation.

The project is intentionally compact enough for a resume project, while still showing the core ideas behind modern AI developer tools:

- local repository indexing
- retrieval-augmented generation over source code
- cited answers with file and line ranges
- symbol-level indexing for classes, functions, methods, and imports
- Chinese query expansion and project overview fallback
- concise local retrieval output when no API key is configured
- repository structure mapping
- Git Diff impact analysis
- AI-assisted code review over `git diff`
- Conventional Commit message generation
- OpenAI-compatible API integration

## Requirements

Required:

- Python 3.10 or later
- Git 2.x
- A local code repository to analyze

Optional:

- An OpenAI-compatible API key for generated answers and deeper review
- PowerShell on Windows, or any shell that can run Python commands

No third-party Python package is required for the minimal version. The CLI uses only the Python standard library.

## Environment Setup

Clone the project and enter the RepoLens AI directory:

```powershell
git clone https://github.com/shisana1211/RepoLens-AI.git
cd RepoLens-AI
```

Check Python and Git:

```powershell
python --version
git --version
```

For the best CLI experience, install RepoLens AI in editable mode:

```powershell
python -m pip install -e .
```

After installation, the `repo-ai` command is available from any directory:

```powershell
repo-ai --help
```

## Quick Start

Run from this project directory:

```bash
python -m repo_ai --help
```

Index a repository:

```bash
python -m repo_ai --path C:\path\to\your\repo init
```

Ask a question:

```bash
python -m repo_ai --path C:\path\to\your\repo ask "What are the main features?"
```

Explain a file:

```bash
python -m repo_ai --path C:\path\to\your\repo explain src/auth/login.py
```

Review unstaged changes:

```bash
python -m repo_ai --path C:\path\to\your\repo review
```

Map the repository:

```bash
python -m repo_ai --path C:\path\to\your\repo map
```

Analyze the impact of unstaged changes:

```bash
python -m repo_ai --path C:\path\to\your\repo impact
```

Generate a commit message:

```bash
python -m repo_ai --path C:\path\to\your\repo commit
```

## Install As A Command

From the RepoLens AI project directory:

```powershell
python -m pip install -e .
```

Then you can run `repo-ai` from any directory:

```powershell
repo-ai --help
repo-ai --path "C:\Users\your-name\Projects\your-repo" ask "What are the main features?"
```

If you update RepoLens AI source code, the editable install will use the latest local files automatically.

## LLM Configuration

RepoLens AI works without network access by using local retrieval and heuristics. Without a valid API key, `ask` prints a concise source list instead of dumping long code snippets.

To enable generated answers and deeper reviews, configure an OpenAI-compatible API.

Recommended project-level setup:

```bash
copy .repo-ai\config.example.json .repo-ai\config.json
```

Then edit `.repo-ai/config.json`:

```json
{
  "api_key": "your_api_key_here",
  "model": "deepseek-v4-flash",
  "base_url": "https://api.deepseek.com/chat/completions"
}
```

`.repo-ai/config.json` is ignored by Git, while `.repo-ai/config.example.json` is safe to commit.

Environment variables are also supported and take priority over config files:

```bash
set REPO_AI_API_KEY=your_api_key
set REPO_AI_MODEL=deepseek-v4-flash
set REPO_AI_BASE_URL=https://api.deepseek.com/chat/completions
```

`OPENAI_API_KEY` is also supported. For other OpenAI-compatible providers, set `base_url` or `REPO_AI_BASE_URL` to the provider's chat completions endpoint.

## Commands

```text
repo-ai init
repo-ai ask "question"
repo-ai explain path/to/file
repo-ai review [--staged]
repo-ai map
repo-ai impact [--staged]
repo-ai commit [--staged]
```

`ask` supports increasing the number of retrieved chunks:

```bash
python -m repo_ai --path C:\path\to\your\repo ask --top-k 15 "What are the project highlights?"
```

When no API key is configured, use `--show-context` to inspect the retrieved snippets:

```bash
python -m repo_ai --path C:\path\to\your\repo ask --show-context "How does authentication work?"
```

## How It Works

`repo-ai init` scans text-like files under the target repository, skips heavy generated folders such as `.git`, `node_modules`, `dist`, and `target`, then writes an index to:

```text
.repo-ai/index.json
```

The index includes chunked text plus lightweight symbols. Python symbols are extracted with the standard-library `ast` module, while other text code uses simple regex fallback extraction for imports, classes, and functions.

`repo-ai ask` expands common Chinese project questions into code-oriented keywords, retrieves relevant code chunks with a small BM25-style scorer, and falls back to project overview files when direct retrieval is empty. It then either:

- sends the cited context to the configured model, or
- prints a concise source list when no API key is configured.

Symbol-oriented questions such as `where is format_snippet used?` are answered from the symbol index and exact identifier references.

`repo-ai map` summarizes indexed files, languages, symbol counts, likely entry points, core files, module groups, and common imports.

`repo-ai impact` reads `git diff`, identifies changed files and touched symbols, looks for downstream references/import dependents in the index, and reports heuristic risk signals.

The overview fallback prioritizes files such as README, build files, application configuration, controllers, services, API clients, and module-level code. This helps broad questions like `这个项目的主要功能是什么？` get useful context even when the exact words do not appear in source code.

`repo-ai review` and `repo-ai commit` read `git diff`. With an API key, they use the model. Without one, they fall back to simple local heuristics.

## Resume Description

> Built RepoLens AI, a Python CLI that indexes local code repositories and provides RAG-based code Q&A, file explanation, Git diff review, and Conventional Commit generation. Designed a lightweight hybrid retrieval pipeline with Chinese query expansion, project overview fallback, line-level citations, project-level LLM configuration, concise local retrieval output, and optional OpenAI-compatible model integration.

## Future Extensions

- add MCP server mode with `repo-ai mcp serve`
- add tree-sitter symbol extraction
- add vector embeddings with Chroma, LanceDB, or SQLite-vec
- add evaluation metrics for retrieval hit rate and answer faithfulness
