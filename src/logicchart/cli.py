from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Sequence
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logicchart import __version__
from logicchart.analysis import ProjectAnalyzer
from logicchart.artifacts import load_model, output_paths, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.install import install_agent_instructions
from logicchart.query import (
    git_changed_files,
    impact_model,
    query_model,
    render_impact,
    render_query,
)
from logicchart.render.html import render_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logicchart",
        description="Turn Python and TypeScript code into decision flowcharts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a source folder.")
    analyze.add_argument("path", nargs="?", default=".")
    analyze.add_argument("--full", action="store_true", help="Ignore the incremental cache.")
    analyze.add_argument("--no-html", action="store_true", help="Skip the local HTML artifact.")
    analyze.add_argument(
        "--include-gaps",
        action="store_true",
        help="Expand the review-only (POTENTIAL_GAP) findings section in the Markdown report.",
    )

    update = subparsers.add_parser("update", help="Incrementally refresh changed source files.")
    update.add_argument("path", nargs="?", default=".")
    update.add_argument("--no-html", action="store_true")
    update.add_argument("--include-gaps", action="store_true")

    impact = subparsers.add_parser("impact", help="Show flows affected by changed files.")
    impact.add_argument("files", nargs="*")
    impact.add_argument("--path", default=".")
    impact.add_argument("--json", action="store_true", dest="json_output")

    query = subparsers.add_parser("query", help="Search the logical model.")
    query.add_argument("question")
    query.add_argument("--path", default=".")
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--json", action="store_true", dest="json_output")

    view = subparsers.add_parser("view", help="Generate and serve the interactive flowchart.")
    view.add_argument("path", nargs="?", default=".")
    view.add_argument("--port", type=int, default=8765)
    view.add_argument("--no-open", action="store_true")
    view.add_argument("--render-only", action="store_true")

    install = subparsers.add_parser(
        "install", help="Install persistent LogicChart instructions for coding agents."
    )
    install.add_argument("path", nargs="?", default=".")
    install.add_argument(
        "--platform",
        choices=["all", "codex", "claude", "cursor", "gemini"],
        default="all",
    )

    init = subparsers.add_parser("init", help="Create a starter LogicChart configuration.")
    init.add_argument("path", nargs="?", default=".")

    mcp = subparsers.add_parser("mcp", help="Start the LogicChart MCP server over stdio.")
    mcp.add_argument("path", nargs="?", default=".")

    diff = subparsers.add_parser("diff", help="Compare two logic-flow.json models (CI gate).")
    diff.add_argument("base", help="Baseline logic-flow.json")
    diff.add_argument("head", help="Current logic-flow.json")
    diff.add_argument("--sarif", default=None, help="Write a SARIF report to this path.")
    diff.add_argument(
        "--fail-on-introduced",
        action="store_true",
        help="Exit non-zero when any finding is introduced.",
    )

    hook = subparsers.add_parser("hook", help="Manage the git auto-sync hooks.")
    hook.add_argument(
        "action", nargs="?", choices=["install", "uninstall", "status"], default="install"
    )
    hook.add_argument("path", nargs="?", default=".")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return _analyze(
                Path(args.path),
                full=args.full,
                include_html=not args.no_html,
                include_gaps=args.include_gaps,
            )
        if args.command == "update":
            return _analyze(
                Path(args.path),
                full=False,
                include_html=not args.no_html,
                include_gaps=args.include_gaps,
            )
        if args.command == "impact":
            return _impact(Path(args.path), args.files, args.json_output)
        if args.command == "query":
            return _query(Path(args.path), args.question, args.limit, args.json_output)
        if args.command == "view":
            return _view(Path(args.path), args.port, not args.no_open, args.render_only)
        if args.command == "install":
            return _install(Path(args.path), args.platform)
        if args.command == "init":
            return _init(Path(args.path))
        if args.command == "mcp":
            from logicchart.mcp_server import run_mcp

            run_mcp(Path(args.path))
            return 0
        if args.command == "diff":
            return _diff(Path(args.base), Path(args.head), args.sarif, args.fail_on_introduced)
        if args.command == "hook":
            return _hook(args.action, Path(args.path))
    except (FileNotFoundError, RuntimeError, ValueError, SyntaxError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _analyze(root: Path, *, full: bool, include_html: bool, include_gaps: bool = False) -> int:
    root = root.resolve()
    result = ProjectAnalyzer(root).analyze(full=full)
    json_path, markdown_path, html_path = write_artifacts(
        root, result.model, include_html=include_html, include_gaps=include_gaps
    )
    print(
        f"Analyzed {len(result.model.files)} files: {len(result.model.flows)} flows, "
        f"{len(result.model.findings)} review findings."
    )
    print(
        f"Incremental cache: {result.cache_hits} hits, {len(result.changed_files)} changed, "
        f"{len(result.deleted_files)} deleted."
    )
    if result.skipped_files:
        print(f"Skipped {len(result.skipped_files)} unparseable file(s):", file=sys.stderr)
        for relative, reason in result.skipped_files:
            print(f"  - {relative}: {reason}", file=sys.stderr)
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    if html_path:
        print(f"Wrote {html_path}")
    return 0


def _impact(root: Path, files: list[str], json_output: bool) -> int:
    root = root.resolve()
    changed = files or git_changed_files(root)
    result = impact_model(load_model(root), changed)
    if json_output:
        print(
            json.dumps(
                {
                    "changed_files": result.changed_files,
                    "directly_impacted": [item.id for item in result.directly_impacted],
                    "transitively_impacted": [item.id for item in result.transitively_impacted],
                    "findings": [item.id for item in result.findings],
                },
                indent=2,
            )
        )
    else:
        print(render_impact(result))
    return 0


def _query(root: Path, question: str, limit: int, json_output: bool) -> int:
    matches = query_model(load_model(root.resolve()), question, limit)
    if json_output:
        print(
            json.dumps(
                [
                    {
                        "flow_id": item.flow.id,
                        "name": item.flow.name,
                        "score": item.score,
                        "reasons": item.reasons,
                    }
                    for item in matches
                ],
                indent=2,
            )
        )
    else:
        print(render_query(matches))
    return 0


def _view(root: Path, port: int, should_open: bool, render_only: bool) -> int:
    root = root.resolve()
    config = LogicChartConfig.load(root)
    _, _, html_path = output_paths(root, config)
    model = load_model(root, config)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(model, source_root=root), encoding="utf-8")
    print(f"Wrote {html_path}")
    if render_only:
        return 0

    handler = partial(SimpleHTTPRequestHandler, directory=str(html_path.parent))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/{html_path.name}"
    print(f"Serving LogicChart at {url}. Press Ctrl+C to stop.")
    if should_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _install(root: Path, platform: str) -> int:
    changed = install_agent_instructions(root.resolve(), platform)
    if not changed:
        print("LogicChart agent instructions are already up to date.")
        return 0
    for path in changed:
        print(f"Updated {path}")
    return 0


def _init(root: Path) -> int:
    root = root.resolve()
    config_path = root / "logicchart.toml"
    if config_path.exists():
        print(f"{config_path} already exists.")
        return 0
    config_path.write_text(
        """[logicchart]
source_roots = ["."]
exclude = []
include_public_functions = true
max_call_depth = 4
output_dir = "logicchart-out"
self_exclude = true

[logicchart.entrypoints]
include = []
exclude = []
""",
        encoding="utf-8",
    )
    print(f"Created {config_path}")
    return 0


def _diff(
    base_path: Path, head_path: Path, sarif_path: str | None, fail_on_introduced: bool
) -> int:
    from logicchart.diff import diff_models, render_diff_markdown, render_sarif
    from logicchart.model import ProjectModel
    from logicchart.util import read_json, write_json

    base = ProjectModel.from_dict(read_json(base_path))
    head = ProjectModel.from_dict(read_json(head_path))
    diff = diff_models(base, head)
    print(render_diff_markdown(diff))
    if sarif_path:
        write_json(Path(sarif_path), render_sarif(diff))
        print(f"Wrote {sarif_path}")
    return 1 if fail_on_introduced and diff.has_regressions else 0


def _hook(action: str, root: Path) -> int:
    from logicchart.hooks import hooks_status, install_hooks, uninstall_hooks

    root = root.resolve()
    if action == "install":
        changed = install_hooks(root)
        for path in changed:
            print(f"Installed {path}")
        if not changed:
            print("LogicChart hooks are already installed.")
    elif action == "uninstall":
        removed = uninstall_hooks(root)
        for path in removed:
            print(f"Removed the managed block from {path}")
        if not removed:
            print("No managed LogicChart hooks found.")
    else:
        for name, present in hooks_status(root).items():
            print(f"{name}: {'installed' if present else 'absent'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
