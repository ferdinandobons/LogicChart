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
from logicchart.config import BUILTIN_PROFILES, LogicChartConfig
from logicchart.doctor import doctor_report, render_doctor, render_doctor_json
from logicchart.install import install_all
from logicchart.query import (
    git_changed_files,
    impact_model,
    query_model,
    render_impact,
    render_query,
)
from logicchart.render.html import render_html
from logicchart.validation import validate_logicchart


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logicchart",
        description="Turn a polyglot codebase into navigable decision flowcharts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a source folder.")
    analyze.add_argument("path", nargs="?", default=".")
    analyze.add_argument("--full", action="store_true", help="Ignore the incremental cache.")
    analyze.add_argument("--no-html", action="store_true", help="Skip the local HTML artifact.")
    _add_profile_argument(analyze)
    analyze.add_argument(
        "--include-gaps",
        action="store_true",
        help="Expand the review-only (POTENTIAL_GAP) findings section in the Markdown report.",
    )

    update = subparsers.add_parser("update", help="Incrementally refresh changed source files.")
    update.add_argument("path", nargs="?", default=".")
    update.add_argument("--no-html", action="store_true")
    update.add_argument("--include-gaps", action="store_true")
    _add_profile_argument(update)

    impact = subparsers.add_parser("impact", help="Show flows affected by changed files.")
    impact.add_argument("files", nargs="*")
    impact.add_argument("--path", default=".")
    impact.add_argument("--scope", default=None, help="Restrict to a named macro-part.")
    _add_profile_argument(impact)
    impact.add_argument("--json", action="store_true", dest="json_output")

    query = subparsers.add_parser("query", help="Search the logical model.")
    query.add_argument("question")
    query.add_argument("--path", default=".")
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--scope", default=None, help="Restrict to a named macro-part.")
    query.add_argument("--language", default=None, help="Restrict to one language id.")
    query.add_argument(
        "--finding-kind",
        default=None,
        help="Restrict to flows with this finding kind.",
    )
    _add_profile_argument(query)
    query.add_argument("--json", action="store_true", dest="json_output")

    view = subparsers.add_parser("view", help="Generate and serve the interactive flowchart.")
    view.add_argument("path", nargs="?", default=".")
    view.add_argument("--port", type=int, default=8765)
    view.add_argument("--no-open", action="store_true")
    view.add_argument("--render-only", action="store_true")
    _add_profile_argument(view)

    install = subparsers.add_parser(
        "install", help="Install persistent LogicChart instructions for coding agents."
    )
    install.add_argument("path", nargs="?", default=".")
    install.add_argument(
        "--platform",
        choices=["all", "codex", "claude", "cursor", "gemini"],
        default="all",
    )
    install.add_argument(
        "--mcp-config",
        choices=["none", "all", "codex", "claude", "cursor"],
        default="none",
        nargs="?",
        const="all",
        help="Also install project-scoped MCP config for Codex, Claude Code, or Cursor.",
    )

    init = subparsers.add_parser("init", help="Create a starter LogicChart configuration.")
    init.add_argument("path", nargs="?", default=".")

    validate = subparsers.add_parser("validate", help="Validate the generated LogicChart model.")
    validate.add_argument("path", nargs="?", default=".")
    validate.add_argument(
        "--check-sync",
        action="store_true",
        help="Re-analyze sources and fail if logic-flow.json is stale.",
    )
    validate.add_argument("--json", action="store_true", dest="json_output")
    _add_profile_argument(validate)

    doctor = subparsers.add_parser("doctor", help="Check the active LogicChart installation.")
    doctor.add_argument("path", nargs="?", default=".")
    doctor.add_argument("--json", action="store_true", dest="json_output")

    mcp = subparsers.add_parser("mcp", help="Start the LogicChart MCP server over stdio.")
    mcp.add_argument("path", nargs="?", default=".")
    _add_profile_argument(mcp)
    return parser


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=BUILTIN_PROFILES,
        default=None,
        help=(
            "Use a built-in analysis profile: demo keeps the public example artifact, "
            "self maps LogicChart internals, project maps the whole checkout."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return _analyze(
                Path(args.path),
                full=args.full,
                include_html=not args.no_html,
                include_gaps=args.include_gaps,
                profile=args.profile,
            )
        if args.command == "update":
            return _analyze(
                Path(args.path),
                full=False,
                include_html=not args.no_html,
                include_gaps=args.include_gaps,
                profile=args.profile,
            )
        if args.command == "impact":
            return _impact(Path(args.path), args.files, args.json_output, args.scope, args.profile)
        if args.command == "query":
            return _query(
                Path(args.path),
                args.question,
                args.limit,
                args.json_output,
                args.scope,
                args.language,
                args.finding_kind,
                args.profile,
            )
        if args.command == "view":
            return _view(
                Path(args.path),
                args.port,
                not args.no_open,
                args.render_only,
                args.profile,
            )
        if args.command == "install":
            return _install(Path(args.path), args.platform, args.mcp_config)
        if args.command == "init":
            return _init(Path(args.path))
        if args.command == "validate":
            return _validate(Path(args.path), args.check_sync, args.json_output, args.profile)
        if args.command == "doctor":
            return _doctor(Path(args.path), args.json_output)
        if args.command == "mcp":
            from logicchart.mcp_server import run_mcp

            config = LogicChartConfig.load(Path(args.path).resolve(), profile=args.profile)
            run_mcp(Path(args.path), config)
            return 0
    except (OSError, RuntimeError, ValueError, SyntaxError) as error:
        # OSError subsumes FileNotFoundError/PermissionError, so a missing path or a
        # permission-denied write surfaces as a clean message instead of a raw traceback.
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _analyze(
    root: Path,
    *,
    full: bool,
    include_html: bool,
    include_gaps: bool = False,
    profile: str | None = None,
) -> int:
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    root = root.resolve()
    config = LogicChartConfig.load(root, profile=profile)
    result = ProjectAnalyzer(root, config).analyze(full=full)
    json_path, markdown_path, html_path = write_artifacts(
        root,
        result.model,
        include_html=include_html,
        include_gaps=include_gaps,
        config=config,
    )
    findings = len(result.model.findings)
    print(
        f"Analyzed {len(result.model.files)} files: {len(result.model.flows)} flows, "
        f"{findings} finding{'s' if findings != 1 else ''}."
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


def _impact(
    root: Path,
    files: list[str],
    json_output: bool,
    scope: str | None = None,
    profile: str | None = None,
) -> int:
    root = root.resolve()
    config = LogicChartConfig.load(root, profile=profile)
    changed = files or git_changed_files(root)
    result = impact_model(load_model(root, config), changed, scope)
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


def _query(
    root: Path,
    question: str,
    limit: int,
    json_output: bool,
    scope: str | None = None,
    language: str | None = None,
    finding_kind: str | None = None,
    profile: str | None = None,
) -> int:
    root = root.resolve()
    config = LogicChartConfig.load(root, profile=profile)
    model = load_model(root, config)
    if scope is not None:
        known_scopes = model.metadata.get("scopes", {})
        if scope not in known_scopes:
            print(
                f"warning: unknown scope {scope!r}; known scopes: "
                f"{', '.join(sorted(known_scopes)) or '(none)'}",
                file=sys.stderr,
            )
    if limit < 0:
        # A negative slice would silently drop results; treat it as "no limit".
        print(
            f"warning: ignoring negative --limit {limit}; returning all matches",
            file=sys.stderr,
        )
        limit = 0
    matches = query_model(
        model,
        question,
        limit,
        scope,
        language=language,
        finding_kind=finding_kind,
    )
    if json_output:
        print(json.dumps([item.to_dict() for item in matches], indent=2))
    else:
        print(render_query(matches))
    return 0


def _view(
    root: Path,
    port: int,
    should_open: bool,
    render_only: bool,
    profile: str | None = None,
) -> int:
    root = root.resolve()
    config = LogicChartConfig.load(root, profile=profile)
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


def _validate(root: Path, check_sync: bool, json_output: bool, profile: str | None = None) -> int:
    root = root.resolve()
    config = LogicChartConfig.load(root, profile=profile)
    report = validate_logicchart(root, config=config, check_sync=check_sync)
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "OK" if report.ok else "FAILED"
        print(f"LogicChart validation {status}: {report.artifact}")
        for warning in report.warnings:
            print(f"warning: {warning}")
        for error in report.errors:
            print(f"error: {error}", file=sys.stderr)
    return 0 if report.ok else 1


def _install(root: Path, platform: str, mcp_config: str = "none") -> int:
    changed = install_all(root.resolve(), platform, mcp_config)
    if not changed:
        print("LogicChart agent instructions and MCP config are already up to date.")
        return 0
    for path in changed:
        print(f"Updated {path}")
    return 0


def _doctor(root: Path, json_output: bool) -> int:
    report = doctor_report(root)
    print(render_doctor_json(report) if json_output else render_doctor(report))
    return 0 if report.ok else 1


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
# Defaults already skip dependency caches and generated output such as node_modules,
# dist/build/out/target, coverage, .next/.turbo/.svelte-kit, vendor, and *.generated.*.
include_public_functions = true
max_call_depth = 4
output_dir = "logicchart-out"
self_exclude = true
gated_detectors = false

[logicchart.entrypoints]
include = []
exclude = []

# Named macro-parts of the codebase (otherwise the top-level directory is the scope):
# [logicchart.scopes]
# backend = ["backend/**", "services/**"]
# frontend = ["frontend/**", "web/**"]
# edge = ["edge/**", "workers/**"]
""",
        encoding="utf-8",
    )
    print(f"Created {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
