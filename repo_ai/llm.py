from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.request


class LlmUnavailable(RuntimeError):
    pass


PLACEHOLDER_API_KEYS = {"", "your_api_key_here", "your_api_key", "sk-xxx"}


def _read_json_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LlmUnavailable(f"Invalid config file at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LlmUnavailable(f"Invalid config file at {path}: expected a JSON object.")
    return data


def load_config(root: Path | None = None) -> dict:
    config: dict = {}
    candidates = [
        Path.home() / ".repo-ai" / "config.json",
        Path.cwd() / ".repo-ai" / "config.json",
        Path(__file__).resolve().parents[1] / ".repo-ai" / "config.json",
    ]
    if root is not None:
        candidates.append(root.resolve() / ".repo-ai" / "config.json")

    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        config.update(_read_json_config(resolved))

    if os.environ.get("OPENAI_API_KEY"):
        config["api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("REPO_AI_API_KEY"):
        config["api_key"] = os.environ["REPO_AI_API_KEY"]
    if os.environ.get("REPO_AI_MODEL"):
        config["model"] = os.environ["REPO_AI_MODEL"]
    if os.environ.get("REPO_AI_BASE_URL"):
        config["base_url"] = os.environ["REPO_AI_BASE_URL"]

    return config


def is_configured(root: Path | None = None) -> bool:
    api_key = str(load_config(root).get("api_key", "")).strip()
    return api_key not in PLACEHOLDER_API_KEYS


def complete(system: str, user: str, temperature: float = 0.2, root: Path | None = None) -> str:
    config = load_config(root)
    api_key = str(config.get("api_key", "")).strip()
    if api_key in PLACEHOLDER_API_KEYS:
        raise LlmUnavailable(
            "Set REPO_AI_API_KEY/OPENAI_API_KEY or create .repo-ai/config.json to enable model responses."
        )

    base_url = config.get("base_url", "https://api.openai.com/v1/chat/completions")
    model = config.get("model", "gpt-4o-mini")
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise LlmUnavailable(f"LLM request failed: HTTP {exc.code} {details}") from exc
    except OSError as exc:
        raise LlmUnavailable(f"LLM request failed: {exc}") from exc

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmUnavailable(f"Unexpected LLM response: {data}") from exc
