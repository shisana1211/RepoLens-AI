# RepoLens AI

RepoLens AI 是一款面向代码仓库的 AI CLI 智能分析工具，支持对本地项目进行源码索引、RAG 问答、文件解释、Git Diff 智能审查和 Commit Message 生成。项目通过关键词检索、中文查询扩展与项目概览 fallback 构建轻量级代码检索增强流程，并支持 OpenAI-compatible API 配置，使开发者能够在命令行中快速理解项目结构、定位核心模块、分析代码改动风险。

RepoLens AI is intentionally compact enough for a resume project, while still showing the core ideas behind modern AI developer tools:

- local repository indexing
- retrieval-augmented generation over source code
- cited answers with file and line ranges
- Chinese query expansion and project overview fallback
- AI-assisted code review over `git diff`
- Conventional Commit message generation
- OpenAI-compatible API integration

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
python -m repo_ai --path C:\path\to\your\repo ask "How does authentication work?"
```

Explain a file:

```bash
python -m repo_ai --path C:\path\to\your\repo explain src/auth/login.py
```

Review unstaged changes:

```bash
python -m repo_ai --path C:\path\to\your\repo review
```

Generate a commit message:

```bash
python -m repo_ai --path C:\path\to\your\repo commit
```

## Optional LLM Configuration

RepoLens AI works without network access by using local retrieval and heuristics. To enable generated answers and deeper reviews, configure an OpenAI-compatible API.

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

`OPENAI_API_KEY` is also supported.

For other OpenAI-compatible providers, set `base_url` or `REPO_AI_BASE_URL` to the provider's chat completions endpoint.

## Commands

```text
repo-ai init
repo-ai ask "question"
repo-ai explain path/to/file
repo-ai review [--staged]
repo-ai commit [--staged]
```

`ask` also supports increasing the number of retrieved chunks:

```bash
python -m repo_ai --path C:\path\to\your\repo ask --top-k 15 "What are the project highlights?"
```

## How It Works

`repo-ai init` scans text-like files under the target repository, skips heavy generated folders such as `.git`, `node_modules`, `dist`, and `target`, then writes an index to:

```text
.repo-ai/index.json
```

`repo-ai ask` expands common Chinese project questions into code-oriented keywords, retrieves relevant code chunks with a small BM25-style scorer, and falls back to project overview files when direct retrieval is empty. It then either:

- sends the cited context to the configured model, or
- prints the best local retrieval results when no API key is configured.

The overview fallback prioritizes files such as README, build files, application configuration, controllers, services, API clients, and module-level code. This helps broad questions like "这个项目的主要功能是什么？" get useful context even when the exact words do not appear in source code.

`repo-ai review` and `repo-ai commit` read `git diff`. With an API key, they use the model. Without one, they fall back to simple local heuristics.

## Resume Description

> Built RepoLens AI, a Python CLI that indexes local code repositories and provides RAG-based code Q&A, file explanation, Git diff review, and Conventional Commit generation. Designed a lightweight hybrid retrieval pipeline with Chinese query expansion, project overview fallback, line-level citations, project-level LLM configuration, and optional OpenAI-compatible model integration.

## Future Extensions

- add MCP server mode with `repo-ai mcp serve`
- add `ask --show-context` for transparent RAG debugging
- add file/class-name exact recall
- add tree-sitter symbol extraction
- add vector embeddings with Chroma, LanceDB, or SQLite-vec
- add evaluation metrics for retrieval hit rate and answer faithfulness
