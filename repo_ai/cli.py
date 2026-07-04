from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-ai",
        description="AI-powered CLI for repository indexing, Q&A, review, and commit messages.",
    )
    parser.add_argument("--version", action="version", version=f"repo-ai {__version__}")
    parser.add_argument("--path", default=".", help="Repository path. Defaults to current directory.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Build a local repository search index.")

    ask_parser = subparsers.add_parser("ask", help="Ask a question about the indexed repository.")
    ask_parser.add_argument("question", help="Question to answer from repository context.")
    ask_parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to retrieve.")
    ask_parser.add_argument("--show-context", action="store_true", help="Print retrieved code snippets when no LLM answer is available.")

    explain_parser = subparsers.add_parser("explain", help="Explain a file.")
    explain_parser.add_argument("file", help="File path relative to the repository root.")

    review_parser = subparsers.add_parser("review", help="Review the current git diff.")
    review_parser.add_argument("--staged", action="store_true", help="Review staged changes instead of unstaged changes.")

    commit_parser = subparsers.add_parser("commit", help="Generate a Conventional Commit message from git diff.")
    commit_parser.add_argument("--staged", action="store_true", help="Use staged changes instead of unstaged changes.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.path).resolve()

    try:
        if args.command == "init":
            output = commands.init_repo(root)
        elif args.command == "ask":
            output = commands.ask(root, args.question, top_k=args.top_k, show_context=args.show_context)
        elif args.command == "explain":
            output = commands.explain(root, args.file)
        elif args.command == "review":
            output = commands.review(root, staged=args.staged)
        elif args.command == "commit":
            output = commands.commit_message(root, staged=args.staged)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
