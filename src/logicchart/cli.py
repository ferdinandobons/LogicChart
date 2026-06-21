from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Sequence
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from textwrap import dedent
from typing import Any

from logicchart import __version__
from logicchart.analysis import ProjectAnalyzer
from logicchart.artifacts import load_model, output_paths, write_artifacts
from logicchart.config import BUILTIN_PROFILES, LogicChartConfig
from logicchart.doctor import doctor_report, render_doctor, render_doctor_json
from logicchart.install import (
    MCP_CONFIG_TARGETS,
    install_agent_instructions,
    install_agent_skill,
    install_mcp_config,
)
from logicchart.quality import render_quality
from logicchart.render.html import render_html
from logicchart.validation import validate_logicchart


class LogicChartHelpFormatter(argparse.RawDescriptionHelpFormatter):
    pass


class LogicChartArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", LogicChartHelpFormatter)
        super().__init__(*args, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = LogicChartArgumentParser(
        prog="logicchart",
        description="Turn a local codebase into source-grounded workflow flowcharts.",
        epilog=dedent(
            """\
            Quick start:
              logicchart setup-agent codex
              logicchart update
              logicchart view
              logicchart validate
              logicchart doctor

            Add --help after any command for focused examples and advanced options.
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=LogicChartArgumentParser,
    )

    setup = subparsers.add_parser(
        "setup-agent",
        help="Configure LogicChart once for a coding agent.",
        description=(
            "Install agent instructions, register MCP, create config when needed, "
            "generate artifacts, run doctor, and validate the setup."
        ),
        epilog=dedent(
            """\
            Examples:
              logicchart setup-agent codex
              logicchart setup-agent claude ../my-app
              logicchart setup-agent gemini
              logicchart setup-agent cursor --full

            After setup, ask your coding agent ordinary questions about code logic. Use
            logicchart view when a human wants the manual workflow flowchart UI.
            """
        ),
    )
    setup.add_argument("agent", choices=["codex", "claude", "gemini", "cursor"])
    setup.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project folder to configure. Defaults to the current directory.",
    )
    setup.add_argument("--full", action="store_true", help="Ignore the incremental cache.")
    setup.add_argument("--no-html", action="store_true", help="Skip the local HTML artifact.")
    _add_profile_argument(setup)

    update = subparsers.add_parser(
        "update",
        help="Incrementally refresh changed source files.",
        description="Refresh existing LogicChart artifacts after source changes.",
        epilog=dedent(
            """\
            Examples:
              logicchart update
              logicchart update ../my-app
              logicchart update --full

            Use update during normal development. Use --full after analyzer upgrades or
            when cached file models should be ignored.
            """
        ),
    )
    update.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project folder to refresh. Defaults to the current directory.",
    )
    update.add_argument("--full", action="store_true", help="Ignore the incremental cache.")
    update.add_argument("--no-html", action="store_true", help="Skip the local HTML artifact.")
    _add_profile_argument(update)

    view = subparsers.add_parser(
        "view",
        help="Generate and serve the interactive flowchart.",
        description="Open the local interactive workflow flowchart viewer.",
        epilog=dedent(
            """\
            Examples:
              logicchart view
              logicchart view ../my-app
              logicchart view --port 8771

            The viewer is local-only. Use --render-only for CI or artifact generation.
            """
        ),
    )
    view.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project folder to view. Defaults to the current directory.",
    )
    view.add_argument("--port", type=int, default=8765, help="Local server port.")
    view.add_argument("--no-open", action="store_true", help="Serve without opening a browser.")
    view.add_argument(
        "--render-only",
        action="store_true",
        help="Write logic-flow.html without starting a server.",
    )
    _add_profile_argument(view)

    validate = subparsers.add_parser(
        "validate",
        help="Validate the generated LogicChart model.",
        description="Validate generated artifacts and optional analyzer-quality checks.",
        epilog=dedent(
            """\
            Examples:
              logicchart validate
              logicchart validate --check-sync
              logicchart validate --quality
            """
        ),
    )
    validate.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project folder containing generated LogicChart artifacts.",
    )
    validate.add_argument(
        "--check-sync",
        action="store_true",
        help="Re-analyze sources and fail if logic-flow.json is stale.",
    )
    validate.add_argument(
        "--json", action="store_true", dest="json_output", help="Emit JSON output."
    )
    validate.add_argument(
        "--quality",
        action="store_true",
        help="Include deterministic analysis-quality metrics in the report.",
    )
    validate.add_argument(
        "--max-skipped-files",
        type=int,
        help="Fail validation when skipped-file count exceeds this value.",
    )
    validate.add_argument(
        "--max-parse-warnings",
        type=int,
        help="Fail validation when parse-warning count exceeds this value.",
    )
    validate.add_argument(
        "--min-call-resolution",
        type=float,
        help="Fail validation when call-resolution rate is below this 0..1 value.",
    )
    validate.add_argument(
        "--max-generic-label-ratio",
        type=float,
        help="Fail validation when generic-label ratio exceeds this 0..1 value.",
    )
    _add_profile_argument(validate)

    doctor = subparsers.add_parser("doctor", help="Check the active LogicChart installation.")
    doctor.add_argument("path", nargs="?", default=".", help="Project folder to inspect.")
    doctor.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON output.")

    mcp = subparsers.add_parser("mcp", help="Start the LogicChart MCP server over stdio.")
    mcp.add_argument("path", nargs="?", default=".", help="Project folder served over MCP.")
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
        if args.command == "setup-agent":
            return _setup_agent(
                Path(args.path),
                args.agent,
                full=args.full,
                include_html=not args.no_html,
                profile=args.profile,
            )
        if args.command == "update":
            return _analyze(
                Path(args.path),
                full=args.full,
                include_html=not args.no_html,
                profile=args.profile,
            )
        if args.command == "view":
            return _view(
                Path(args.path),
                args.port,
                not args.no_open,
                args.render_only,
                args.profile,
            )
        if args.command == "validate":
            return _validate(
                Path(args.path),
                args.check_sync,
                args.json_output,
                args.quality,
                _quality_thresholds(args),
                args.profile,
            )
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
        print("LogicChart command FAILED", file=sys.stderr)
        print(f"Error: {error}", file=sys.stderr)
        print("Next steps:", file=sys.stderr)
        print("- Check the path and filesystem permissions.", file=sys.stderr)
        print("- Run `logicchart doctor` if this looks like an install issue.", file=sys.stderr)
        return 1
    return 0


def _setup_agent(
    root: Path,
    agent: str,
    *,
    full: bool,
    include_html: bool,
    profile: str | None = None,
) -> int:
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    root = root.resolve()
    display = {
        "codex": "Codex",
        "claude": "Claude",
        "gemini": "Gemini",
        "cursor": "Cursor",
    }[agent]
    print(f"LogicChart setup-agent for {display}")
    print(f"Project: {root}")

    config_path, created_config = _ensure_config(root)
    print("")
    print("Setup:")
    print(f"- Config: {'Created' if created_config else 'Already present'} ({config_path})")

    changed = install_agent_instructions(root, agent)
    changed.extend(install_agent_skill(root, agent))
    if agent in MCP_CONFIG_TARGETS:
        changed.extend(install_mcp_config(root, agent))
    if changed:
        print(f"- Agent files: updated {len(changed)} file{'s' if len(changed) != 1 else ''}")
        for path in changed:
            print(f"  - {path}")
    else:
        print("- Agent files: already up to date")

    print("")
    analyze_status = _analyze(
        root,
        full=full,
        include_html=include_html,
        profile=profile,
        show_next_steps=False,
    )
    if analyze_status != 0:
        return analyze_status

    print("")
    doctor_status = _doctor(root, json_output=False, show_next_steps=False)
    if doctor_status != 0:
        return doctor_status

    print("")
    validate_status = _validate(
        root,
        check_sync=False,
        json_output=False,
        include_quality=False,
        quality_thresholds=None,
        profile=profile,
        show_next_steps=False,
    )
    if validate_status != 0:
        return validate_status

    print("")
    print("Status: OK - LogicChart is ready for your coding agent.")
    print(f"LogicChart agent setup complete for {display}.")
    _print_next_steps(
        [
            "Ask your coding agent ordinary questions about the code logic.",
            "Try: How does this feature work?",
            "Try: Which workflows are affected by this change?",
            "Try: Show me the workflow for this feature.",
            "Manual UI: `logicchart view`",
        ]
    )
    return 0


def _ensure_config(root: Path) -> tuple[Path, bool]:
    config_path = root / "logicchart.toml"
    if config_path.exists():
        return config_path, False
    config_path.write_text(_starter_config_text(), encoding="utf-8")
    return config_path, True


def _analyze(
    root: Path,
    *,
    full: bool,
    include_html: bool,
    profile: str | None = None,
    show_next_steps: bool = True,
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
        config=config,
    )
    print("LogicChart update")
    print("Status: OK - artifacts refreshed.")
    print(f"Project: {root}")
    print(f"Summary: {len(result.model.files)} files, {len(result.model.flows)} flows.")
    print(
        "Cache: "
        f"{result.cache_hits} hits, {len(result.changed_files)} changed, "
        f"{len(result.deleted_files)} deleted."
    )
    if result.skipped_files:
        print(
            f"Warning: skipped {len(result.skipped_files)} unparseable file(s):",
            file=sys.stderr,
        )
        for relative, reason in result.skipped_files:
            print(f"  - {relative}: {reason}", file=sys.stderr)
    print("Artifacts:")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {markdown_path}")
    if html_path:
        print(f"- HTML: {html_path}")
    if show_next_steps:
        steps = [
            "Ask your coding agent questions about behavior, workflows, or changed-code context.",
            "Run `logicchart validate --check-sync` before committing generated artifacts.",
        ]
        if html_path:
            steps.append("Open the manual UI with `logicchart view`.")
        else:
            steps.append("Generate/open the manual UI with `logicchart view` when needed.")
        _print_next_steps(steps)
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
    print("LogicChart view")
    print("Status: OK - viewer artifact ready.")
    print(f"Project: {root}")
    print(f"HTML: {html_path}")
    if render_only:
        _print_next_steps(["Open the generated HTML file or run `logicchart view` to serve it."])
        return 0

    handler = partial(SimpleHTTPRequestHandler, directory=str(html_path.parent))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/{html_path.name}"
    print(f"URL: {url}")
    _print_next_steps(
        [
            "Use the browser to inspect the workflow flowchart.",
            "Press Ctrl+C in this terminal to stop the local server.",
        ]
    )
    if should_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _validate(
    root: Path,
    check_sync: bool,
    json_output: bool,
    include_quality: bool,
    quality_thresholds: dict[str, float | int] | None,
    profile: str | None = None,
    show_next_steps: bool = True,
) -> int:
    root = root.resolve()
    config = LogicChartConfig.load(root, profile=profile)
    report = validate_logicchart(
        root,
        config=config,
        check_sync=check_sync,
        include_quality=include_quality,
        quality_thresholds=quality_thresholds,
    )
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "OK" if report.ok else "FAILED"
        print(f"LogicChart validation {status}: {report.artifact}")
        print(
            f"Status: {status} - "
            f"{'artifacts are valid.' if report.ok else 'review the errors below.'}"
        )
        for warning in report.warnings:
            print(f"Warning: {warning}")
        for error in report.errors:
            print(f"Error: {error}", file=sys.stderr)
        if report.quality is not None:
            print(render_quality(report.quality))
        if show_next_steps:
            if report.ok:
                _print_next_steps(
                    [
                        "No repair needed.",
                        (
                            "If you changed source logic, commit the updated "
                            "`logicchart-out` artifacts."
                        ),
                    ]
                )
            else:
                _print_next_steps(
                    [
                        "Run `logicchart update` to refresh stale artifacts.",
                        "Fix any listed validation errors, then rerun `logicchart validate`.",
                    ]
                )
    return 0 if report.ok else 1


def _quality_thresholds(args: argparse.Namespace) -> dict[str, float | int]:
    thresholds: dict[str, float | int] = {}
    if args.max_skipped_files is not None:
        thresholds["max_skipped_files"] = args.max_skipped_files
    if args.max_parse_warnings is not None:
        thresholds["max_parse_warnings"] = args.max_parse_warnings
    if args.min_call_resolution is not None:
        thresholds["min_call_resolution"] = args.min_call_resolution
    if args.max_generic_label_ratio is not None:
        thresholds["max_generic_label_ratio"] = args.max_generic_label_ratio
    return thresholds


def _doctor(root: Path, json_output: bool, show_next_steps: bool = True) -> int:
    report = doctor_report(root)
    print(render_doctor_json(report) if json_output else render_doctor(report))
    if not json_output and show_next_steps:
        if report.ok:
            _print_next_steps(
                [
                    "Run `logicchart setup-agent codex` once in a new project.",
                    "Run `logicchart update` in an already configured project.",
                ]
            )
        else:
            _print_next_steps(
                [
                    f"Repair this interpreter with `{report.repair_command}`.",
                    "Rerun `logicchart doctor` after repair.",
                ]
            )
    return 0 if report.ok else 1


def _print_next_steps(steps: Sequence[str]) -> None:
    print("Next steps:")
    for step in steps:
        print(f"- {step}")


def _starter_config_text() -> str:
    return """[logicchart]
source_roots = ["."]
exclude = []
exclude_dirs = []
# Defaults always prune dependency, VCS, cache, temp, and generated directories such as
# .git, node_modules, venv/.venv, dist/build/out/target, coverage, .next, .turbo,
# .svelte-kit, vendor, and logicchart-out. Add project-specific directories above.
include_public_functions = true
max_call_depth = 4
output_dir = "logicchart-out"
self_exclude = true

[logicchart.entrypoints]
include = []
exclude = []

# Named macro-parts of the codebase (otherwise the top-level directory is the scope):
# [logicchart.scopes]
# backend = ["backend/**", "services/**"]
# frontend = ["frontend/**", "web/**"]
# edge = ["edge/**", "workers/**"]
"""


if __name__ == "__main__":
    raise SystemExit(main())
