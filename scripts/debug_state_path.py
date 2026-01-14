#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from yahoo_crawler.infrastructure.yahoo.parser import extract_embedded_state, extract_quotes


def main() -> None:
    html_path = _find_latest_html()
    page_source = html_path.read_text(encoding="utf-8")
    state = extract_embedded_state(page_source)

    print(f"HTML: {html_path}")
    print(f"Top-level keys: {_safe_keys(state)}")

    stores = _get_stores(state)
    if isinstance(stores, dict):
        print(f"Stores keys: {_safe_keys(stores)}")
    else:
        print("Stores keys: []")

    paths = _find_quotes_paths(state)
    if not paths:
        print("No 'quotes' keys found.")
    else:
        print(f"Found {len(paths)} 'quotes' path(s):")
        for path, value in paths[:12]:
            path_str = _format_path(path)
            detail = _describe_value(value)
            print(f"- {path_str} | {detail}")

    try:
        quotes = extract_quotes(state)
        print(f"extract_quotes() -> {len(quotes)} item(s)")
        if quotes:
            sample = quotes[0]
            if isinstance(sample, dict):
                print(f"Sample keys: {list(sample.keys())[:20]}")
    except Exception as exc:
        print(f"extract_quotes() failed: {exc}")

    _print_sveltekit_scripts(page_source)


def _find_latest_html() -> Path:
    artifacts = Path("artifacts")
    if not artifacts.exists():
        raise SystemExit("artifacts/ not found")

    candidates = list(artifacts.glob("last_page_*.html"))
    legacy = artifacts / "last_page.html"
    if legacy.exists():
        candidates.append(legacy)

    if not candidates:
        raise SystemExit("No artifacts/last_page_*.html found")

    return max(candidates, key=lambda path: path.stat().st_mtime)


def _find_quotes_paths(data: Any) -> list[tuple[list[Any], Any]]:
    paths: list[tuple[list[Any], Any]] = []
    stack: list[tuple[Any, list[Any]]] = [(data, [])]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = path + [key]
                if key == "quotes":
                    paths.append((next_path, value))
                if isinstance(value, (dict, list)):
                    stack.append((value, next_path))
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    stack.append((item, path + [idx]))
    return paths


def _format_path(path: list[Any]) -> str:
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            if out:
                out += "."
            out += str(part)
    return out


def _describe_value(value: Any) -> str:
    if isinstance(value, list):
        detail = f"list len={len(value)}"
        if value and isinstance(value[0], dict):
            keys = list(value[0].keys())[:12]
            detail += f" keys={keys}"
        return detail
    if isinstance(value, dict):
        keys = list(value.keys())[:12]
        return f"dict keys={keys}"
    return f"type={type(value).__name__}"


def _get_stores(state: dict) -> Any:
    if not isinstance(state, dict):
        return None
    context = state.get("context")
    if not isinstance(context, dict):
        return None
    dispatcher = context.get("dispatcher")
    if not isinstance(dispatcher, dict):
        return None
    return dispatcher.get("stores")


def _safe_keys(data: Any, limit: int = 40) -> list[str]:
    if not isinstance(data, dict):
        return []
    return list(data.keys())[:limit]


def _print_sveltekit_scripts(page_source: str) -> None:
    scripts = _find_sveltekit_scripts(page_source)
    if not scripts:
        return
    print(f"SvelteKit scripts: {len(scripts)}")
    for script in scripts[:12]:
        print(
            f"- data-url={script['data_url']} | len={script['length']} | has_body={script['has_body']}"
        )


def _find_sveltekit_scripts(page_source: str) -> list[dict[str, Any]]:
    scripts = []
    for attrs, body in _iter_script_tags(page_source):
        if attrs.get("type") != "application/json":
            continue
        if "data-sveltekit-fetched" not in attrs:
            continue
        scripts.append(
            {
                "data_url": attrs.get("data-url"),
                "length": len(body),
                "has_body": "\"body\"" in body,
            }
        )
    return scripts


def _iter_script_tags(page_source: str) -> list[tuple[dict[str, str], str]]:
    scripts = []
    for match in re.finditer(
        r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
        page_source,
        re.DOTALL | re.IGNORECASE,
    ):
        attrs = _parse_attrs(match.group("attrs") or "")
        body = match.group("body") or ""
        scripts.append((attrs, body.strip()))
    return scripts


def _parse_attrs(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([a-zA-Z0-9_-]+)\s*=\s*\"([^\"]*)\"", attrs_text):
        attrs[match.group(1)] = match.group(2)
    for match in re.finditer(r"([a-zA-Z0-9_-]+)\s*=\s*'([^']*)'", attrs_text):
        attrs[match.group(1)] = match.group(2)
    return attrs


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise
