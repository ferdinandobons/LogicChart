from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import webbrowser
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

from codedebrief import __version__
from codedebrief.analysis import ProjectAnalyzer
from codedebrief.artifacts import load_model, model_hash_path, output_paths, write_artifacts
from codedebrief.config import (
    BUILTIN_PROFILES,
    DEFAULT_OUTPUT_DIR,
    CodeDebriefConfig,
    default_config_path,
    find_config_path,
    legacy_config_path,
)
from codedebrief.doctor import doctor_report, render_doctor, render_doctor_json
from codedebrief.errors import (
    append_error_event,
    clear_error_events,
    error_report,
    render_error_report,
    render_error_report_json,
)
from codedebrief.install import (
    AGENT_INSTRUCTION_TARGETS,
    AGENT_SKILL_TARGETS,
    CODEX_MCP_END,
    CODEX_MCP_START,
    END,
    LEGACY_CODEX_MCP_END,
    LEGACY_CODEX_MCP_START,
    MCP_CONFIG_TARGETS,
    START,
    install_agent_instructions,
    install_agent_skill,
    install_mcp_config,
)
from codedebrief.quality import render_quality
from codedebrief.render.html import render_html
from codedebrief.util import atomic_write_text, project_update_lock
from codedebrief.validation import validate_codedebrief


class CodeDebriefHelpFormatter(argparse.RawDescriptionHelpFormatter):
    pass


class CodeDebriefArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", CodeDebriefHelpFormatter)
        super().__init__(*args, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = CodeDebriefArgumentParser(
        prog="codedebrief",
        description="Turn a local codebase into source-grounded workflow flowcharts.",
        epilog=dedent(
            """\
            Quick start:
              codedebrief setup codex
              codedebrief update
              codedebrief view
              codedebrief validate
              codedebrief doctor
              codedebrief clear

            Add --help after any command for focused examples and advanced options.
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{setup,update,view,validate,doctor,clear,mcp}",
        parser_class=CodeDebriefArgumentParser,
    )

    _add_setup_parser(
        subparsers,
        "setup",
        help_text="Configure CodeDebrief once for a coding agent.",
    )
    update = subparsers.add_parser(
        "update",
        help="Incrementally refresh changed source files.",
        description="Refresh existing CodeDebrief artifacts after source changes.",
        epilog=dedent(
            """\
            Examples:
              codedebrief update
              codedebrief update ../my-app
              codedebrief update --full

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
    update.add_argument("--verbose", action="store_true", help="Show detailed progress output.")
    _add_profile_argument(update)

    view = subparsers.add_parser(
        "view",
        help="Generate and serve the interactive flowchart.",
        description="Open the local interactive workflow flowchart viewer.",
        epilog=dedent(
            """\
            Examples:
              codedebrief view
              codedebrief view ../my-app
              codedebrief view --port 8771

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
        help="Write codedebrief.html without starting a server.",
    )
    _add_profile_argument(view)

    validate = subparsers.add_parser(
        "validate",
        help="Validate the generated CodeDebrief model.",
        description="Validate generated artifacts and optional analyzer-quality checks.",
        epilog=dedent(
            """\
            Examples:
              codedebrief validate
              codedebrief validate --check-sync
              codedebrief validate --quality
            """
        ),
    )
    validate.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project folder containing generated CodeDebrief artifacts.",
    )
    validate.add_argument(
        "--check-sync",
        action="store_true",
        help="Re-analyze sources and fail if codedebrief.json is stale.",
    )
    validate.add_argument(
        "--json", action="store_true", dest="json_output", help="Emit JSON output."
    )
    validate.add_argument("--verbose", action="store_true", help="Show detailed progress output.")
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
        help="Fail validation when project-call resolution rate is below this 0..1 value.",
    )
    validate.add_argument(
        "--max-generic-label-ratio",
        type=float,
        help="Fail validation when generic-label ratio exceeds this 0..1 value.",
    )
    _add_profile_argument(validate)

    doctor = subparsers.add_parser("doctor", help="Check the active CodeDebrief installation.")
    doctor.add_argument("path", nargs="?", default=".", help="Project folder to inspect.")
    doctor.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON output.")
    doctor.add_argument("--verbose", action="store_true", help="Show detailed runtime output.")
    doctor.add_argument(
        "--errors",
        action="store_true",
        help="Show saved CodeDebrief error events from codedebrief-out.",
    )
    doctor.add_argument(
        "--clear",
        action="store_true",
        dest="clear_errors",
        help="With --errors, clear saved CodeDebrief error events.",
    )

    clear = subparsers.add_parser(
        "clear",
        help="Remove CodeDebrief files from a project folder.",
        description=(
            "Remove CodeDebrief config, generated artifacts, installed skills, MCP config "
            "entries, and managed instruction blocks from a project folder."
        ),
        epilog=dedent(
            """\
            Examples:
              codedebrief clear
              codedebrief clear --yes
              codedebrief clear ../my-app --yes

            Without --yes, CodeDebrief asks for confirmation before deleting anything.
            User-authored content outside CodeDebrief managed blocks is preserved.
            """
        ),
    )
    clear.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project folder to clean. Defaults to the current directory.",
    )
    clear.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    mcp = subparsers.add_parser("mcp", help="Start the CodeDebrief MCP server over stdio.")
    mcp.add_argument("path", nargs="?", default=".", help="Project folder served over MCP.")
    _add_profile_argument(mcp)
    return parser


def _add_setup_parser(
    subparsers: Any,
    name: str,
    *,
    help_text: str,
) -> argparse.ArgumentParser:
    setup = subparsers.add_parser(
        name,
        help=help_text,
        description=(
            "Install agent instructions, register MCP, create config when needed, "
            "generate artifacts, run doctor, and validate the setup."
        ),
        epilog=dedent(
            """\
            Examples:
              codedebrief setup codex
              codedebrief setup claude
              codedebrief setup claude --source backend/ frontend/
              codedebrief setup claude ../my-app --source backend-api frontend/src
              codedebrief setup claude ../pipeline-map --source ../repo-a ../repo-b
              codedebrief setup cursor --full

            After setup, ask your coding agent ordinary questions about code logic. Use
            codedebrief view when a human wants the manual workflow flowchart UI.
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
    setup.add_argument("--verbose", action="store_true", help="Show installed file paths.")
    setup.add_argument(
        "--source",
        nargs="+",
        dest="source_roots",
        metavar="PATH",
        help=(
            "Analyze only these folders or files during setup, including sibling repos; "
            "artifacts still write under the configured project root."
        ),
    )
    _add_profile_argument(setup)
    return cast(argparse.ArgumentParser, setup)


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=BUILTIN_PROFILES,
        default=None,
        help=(
            "Use a built-in analysis profile: self maps CodeDebrief internals, "
            "project maps the whole checkout."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "setup":
            return _setup_agent(
                Path(args.path),
                args.agent,
                full=args.full,
                include_html=not args.no_html,
                profile=args.profile,
                source_roots=args.source_roots,
                verbose=args.verbose,
            )
        if args.command == "update":
            return _analyze(
                Path(args.path),
                full=args.full,
                include_html=not args.no_html,
                profile=args.profile,
                verbose=args.verbose,
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
                verbose=args.verbose,
            )
        if args.command == "doctor":
            return _doctor(
                Path(args.path),
                args.json_output,
                errors=args.errors,
                clear_errors=args.clear_errors,
                verbose=args.verbose,
            )
        if args.command == "clear":
            return _clear(Path(args.path), assume_yes=args.yes)
        if args.command == "mcp":
            from codedebrief.mcp_server import run_mcp

            config = CodeDebriefConfig.load(Path(args.path).resolve(), profile=args.profile)
            run_mcp(Path(args.path), config)
            return 0
    except (OSError, RuntimeError, TimeoutError, ValueError, SyntaxError) as error:
        command = str(getattr(args, "command", "unknown"))
        saved_error_path = append_error_event(
            _args_root(args),
            command=command,
            phase="command",
            code="command_failed",
            message=str(error),
            next_steps=[
                "Check the path and filesystem permissions.",
                "Run `codedebrief doctor` if this looks like an install issue.",
            ],
        )
        # OSError subsumes FileNotFoundError/PermissionError, so a missing path or a
        # permission-denied write surfaces as a clean message instead of a raw traceback.
        print("CodeDebrief command FAILED", file=sys.stderr)
        print(f"Error: {error}", file=sys.stderr)
        if saved_error_path is not None:
            print(f"Saved: {saved_error_path}", file=sys.stderr)
        print("Next steps:", file=sys.stderr)
        print("- Check the path and filesystem permissions.", file=sys.stderr)
        print("- Run `codedebrief doctor --errors` to inspect saved errors.", file=sys.stderr)
        return 1
    return 0


def _args_root(args: argparse.Namespace) -> Path:
    value = getattr(args, "path", ".")
    try:
        return Path(value).resolve()
    except TypeError:
        return Path(".").resolve()


def _setup_agent(
    root: Path,
    agent: str,
    *,
    full: bool,
    include_html: bool,
    profile: str | None = None,
    source_roots: Sequence[str] | None = None,
    verbose: bool = False,
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
    print("CodeDebrief setup")
    print(f"Project: {root}")
    print(f"Agent: {display}")

    normalized_source_roots = _normalize_source_roots(root, source_roots)
    config_path, created_config, updated_config = _ensure_config(root, normalized_source_roots)
    config_state = (
        "Created" if created_config else "Updated" if updated_config else "Already present"
    )
    print(f"Sources: {_format_source_roots(normalized_source_roots or ['.'])}")
    print(f"Output: {config_path.parent}")
    print("")
    print("Status:")
    print(f"- Config {config_state.lower()}: {config_path}")
    if normalized_source_roots:
        print(f"- Source roots set: {', '.join(normalized_source_roots)}")

    changed = install_agent_instructions(root, agent)
    changed.extend(install_agent_skill(root, agent))
    if agent in MCP_CONFIG_TARGETS:
        changed.extend(install_mcp_config(root, agent))
    if changed:
        print(f"- Agent integration updated: {len(changed)} file{'s' if len(changed) != 1 else ''}")
        if verbose:
            for path in changed:
                print(f"  - {path}")
    else:
        print("- Agent integration already up to date")

    analyze_status = _analyze(
        root,
        full=full,
        include_html=include_html,
        profile=profile,
        show_next_steps=False,
        quiet=True,
        verbose=verbose,
    )
    if analyze_status != 0:
        return analyze_status
    config = CodeDebriefConfig.load(root, profile=profile)
    model = load_model(root, config)
    print(f"- Artifacts refreshed: {len(model.files)} files, {len(model.flows)} flows")
    skipped_files = model.metadata.get("skipped_files", [])
    if isinstance(skipped_files, list) and skipped_files:
        print(
            f"- Analysis warnings: {len(skipped_files)} skipped file(s); "
            "run `codedebrief doctor --errors`"
        )

    runtime = doctor_report(root)
    if not runtime.ok:
        print("- Runtime check failed")
        print(_render_doctor_compact(runtime))
        append_error_event(
            root,
            command="setup",
            phase="doctor",
            code="doctor_failed",
            message="Runtime check failed during setup.",
            next_steps=[runtime.repair_command, "Rerun `codedebrief setup <agent>`."],
            config=config,
        )
        return 1
    print(f"- Runtime checked: codedebrief {runtime.package_version}")

    validation = validate_codedebrief(
        root,
        config=config,
        check_sync=False,
        include_quality=False,
        quality_thresholds=None,
    )
    if not validation.ok:
        print("- Artifact validation failed")
        _log_validation_report(root, validation, config=config)
        for error in validation.errors:
            print(f"  Error: {error}", file=sys.stderr)
        return 1
    print("- Artifacts valid")

    print("")
    print("Ready: CodeDebrief is configured for your coding agent.")
    _print_next_steps(
        [
            "Ask your coding agent ordinary questions about the code logic.",
            "Try: How does this feature work?",
            "Try: Which workflows are affected by this change?",
            "Try: Show me the workflow for this feature.",
            "Manual UI: `codedebrief view`",
        ]
    )
    return 0


def _ensure_config(
    root: Path, source_roots: Sequence[str] | None = None
) -> tuple[Path, bool, bool]:
    config_path = find_config_path(root)
    if config_path is not None:
        if source_roots is None:
            return config_path, False, False
        original = config_path.read_text(encoding="utf-8")
        updated = _set_source_roots(original, source_roots)
        if updated != original:
            atomic_write_text(config_path, updated, encoding="utf-8")
            return config_path, False, True
        return config_path, False, False
    config_path = default_config_path(root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config_path, _starter_config_text(source_roots), encoding="utf-8")
    return config_path, True, bool(source_roots)


def _analyze(
    root: Path,
    *,
    full: bool,
    include_html: bool,
    profile: str | None = None,
    show_next_steps: bool = True,
    quiet: bool = False,
    verbose: bool = False,
) -> int:
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    root = root.resolve()
    config = CodeDebriefConfig.load(root, profile=profile)
    json_path, markdown_path, configured_html_path = output_paths(root, config)
    hash_path = model_hash_path(root, config)
    if not quiet:
        print("CodeDebrief update")
        print(f"Project: {root}")
        if verbose:
            print(f"Mode: {'full refresh' if full else 'incremental update with cache'}")
            print(f"Source roots: {_format_source_roots(config.source_roots)}")
            print(f"Output dir: {json_path.parent}")
            print(f"HTML artifact: {'enabled' if include_html else 'disabled'}")
            print("Progress:")
            _print_progress("Waiting for the project update lock")
    with project_update_lock(root):
        if not quiet and verbose:
            _print_progress("Analyzing source files and linking workflows")
        result = ProjectAnalyzer(root, config).analyze(full=full)
        if result.artifacts_unchanged and _artifacts_available(
            json_path,
            markdown_path,
            configured_html_path if include_html else None,
            hash_path,
        ):
            if not quiet and verbose:
                _print_progress("Reusing unchanged artifacts")
            html_path = configured_html_path if include_html else None
        else:
            artifact_names = "JSON, Markdown, hash"
            if include_html:
                artifact_names += ", and HTML"
            if not quiet and verbose:
                _print_progress(f"Writing {artifact_names} artifacts")
            json_path, markdown_path, html_path = write_artifacts(
                root,
                result.model,
                include_html=include_html,
                config=config,
            )
    if not quiet:
        print("")
        if verbose:
            print("Status: OK - artifacts refreshed.")
            print(f"Summary: {len(result.model.files)} files, {len(result.model.flows)} flows.")
        else:
            print(
                "Status: OK - refreshed "
                f"{len(result.model.files)} files and {len(result.model.flows)} flows."
            )
        print(
            "Cache: "
            f"{result.cache_hits} hits, {len(result.changed_files)} changed, "
            f"{len(result.deleted_files)} deleted."
        )
    if result.skipped_files:
        append_error_event(
            root,
            command="update",
            phase="analyze",
            severity="warning",
            code="skipped_files",
            message=f"Skipped {len(result.skipped_files)} unparseable file(s).",
            next_steps=[
                "Run `codedebrief validate --quality` for analyzer-health details.",
                "Inspect syntax or parser support for the skipped files.",
            ],
            context={
                "skipped_files": [
                    {"path": relative, "reason": reason}
                    for relative, reason in result.skipped_files
                ]
            },
            config=config,
        )
        if not quiet:
            if verbose:
                print(
                    f"Warning: skipped {len(result.skipped_files)} unparseable file(s):",
                    file=sys.stderr,
                )
                for relative, reason in result.skipped_files:
                    print(f"  - {relative}: {reason}", file=sys.stderr)
            else:
                print(
                    "Warning: skipped "
                    f"{len(result.skipped_files)} unparseable file(s). "
                    "Run `codedebrief doctor --errors` for details.",
                    file=sys.stderr,
                )
    if not quiet:
        if verbose:
            print("Artifacts:")
            print(f"- JSON: {json_path}")
            print(f"- Markdown: {markdown_path}")
            print(f"- Hash: {hash_path}")
            if html_path:
                print(f"- HTML: {html_path}")
        else:
            print(f"Output: {json_path.parent}")
        if show_next_steps:
            if verbose:
                steps = [
                    (
                        "Ask your coding agent questions about behavior, workflows, "
                        "or changed-code context."
                    ),
                    (
                        "Run `codedebrief validate --check-sync` before committing "
                        "generated artifacts."
                    ),
                ]
                if html_path:
                    steps.append("Open the manual UI with `codedebrief view`.")
                else:
                    steps.append("Generate/open the manual UI with `codedebrief view` when needed.")
                _print_next_steps(steps)
            else:
                print("Next: codedebrief view | codedebrief validate --check-sync")
    return 0


def _view(
    root: Path,
    port: int,
    should_open: bool,
    render_only: bool,
    profile: str | None = None,
) -> int:
    root = root.resolve()
    print("CodeDebrief view")
    print(f"Project: {root}")
    print("Progress:")
    _print_progress("Loading generated model")
    config = CodeDebriefConfig.load(root, profile=profile)
    _, _, html_path = output_paths(root, config)
    model = load_model(root, config)
    _print_progress("Rendering viewer HTML")
    atomic_write_text(html_path, render_html(model, source_root=root), encoding="utf-8")
    print("")
    print("Status: OK - viewer artifact ready.")
    print(f"HTML: {html_path}")
    if render_only:
        _print_next_steps(["Open the generated HTML file or run `codedebrief view` to serve it."])
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
    verbose: bool = False,
) -> int:
    root = root.resolve()
    config = CodeDebriefConfig.load(root, profile=profile)
    if not json_output:
        print("CodeDebrief validation")
        print(f"Project: {root}")
        if verbose:
            print("Progress:")
            _print_progress("Loading artifact, schema, and sync metadata")
    report = validate_codedebrief(
        root,
        config=config,
        check_sync=check_sync,
        include_quality=include_quality,
        quality_thresholds=quality_thresholds,
    )
    if report.errors or report.warnings:
        _log_validation_report(root, report, config=config)
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "OK" if report.ok else "FAILED"
        print("")
        if verbose:
            print(f"CodeDebrief validation {status}: {report.artifact}")
        print(f"Status: {status} - {'artifacts are valid.' if report.ok else 'review errors.'}")
        for warning in report.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        for error in report.errors:
            print(f"Error: {error}", file=sys.stderr)
        if report.quality is not None:
            print(render_quality(report.quality))
        if show_next_steps:
            if not verbose and report.ok:
                print("Next: codedebrief update after source changes")
            elif report.ok:
                _print_next_steps(
                    [
                        "No repair needed.",
                        (
                            "If you changed source logic, commit the updated "
                            "`codedebrief-out` artifacts."
                        ),
                    ]
                )
            else:
                _print_next_steps(
                    [
                        "Run `codedebrief update` to refresh stale artifacts.",
                        "Run `codedebrief doctor --errors` for saved diagnostics.",
                        "Fix any listed validation errors, then rerun `codedebrief validate`.",
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


def _doctor(
    root: Path,
    json_output: bool,
    show_next_steps: bool = True,
    *,
    errors: bool = False,
    clear_errors: bool = False,
    verbose: bool = False,
) -> int:
    root = root.resolve()
    if errors:
        if clear_errors:
            path = clear_error_events(root)
            payload = {
                "schema_version": "codedebrief_errors_clear.v1",
                "project": str(root),
                "path": str(path),
                "cleared": True,
            }
            print(
                json.dumps(payload, indent=2)
                if json_output
                else f"CodeDebrief errors cleared: {path}"
            )
            return 0
        report_payload = error_report(root)
        print(
            render_error_report_json(report_payload)
            if json_output
            else render_error_report(report_payload)
        )
        return 0

    report = doctor_report(root)
    print(
        render_doctor_json(report)
        if json_output
        else render_doctor(report)
        if verbose
        else _render_doctor_compact(report)
    )
    if not json_output and show_next_steps:
        if report.ok:
            if verbose:
                _print_next_steps(
                    [
                        "Run `codedebrief setup codex` once in a new project.",
                        "Run `codedebrief update` in an already configured project.",
                    ]
                )
            else:
                print("Next: codedebrief update | codedebrief doctor --errors")
        else:
            _print_next_steps(
                [
                    f"Repair this interpreter with `{report.repair_command}`.",
                    "Run `codedebrief doctor --errors` for saved diagnostics.",
                    "Rerun `codedebrief doctor` after repair.",
                ]
            )
    return 0 if report.ok else 1


def _render_doctor_compact(report: Any) -> str:
    status = "OK" if report.ok else "FAILED"
    lines = [
        f"CodeDebrief doctor {status}",
        f"Package: codedebrief {report.package_version}",
        f"Python: {report.executable}",
    ]
    if report.missing_dependencies:
        lines.append(
            "Missing dependencies: "
            + ", ".join(item.package for item in report.missing_dependencies)
        )
    if report.legacy_mcp_configs:
        lines.append(f"Legacy MCP configs: {len(report.legacy_mcp_configs)}")
    if report.ok:
        capabilities = report.language_capabilities
        lines.append(f"Languages: {len(capabilities.supported_languages)} supported")
    return "\n".join(lines)


def _log_validation_report(root: Path, report: Any, *, config: CodeDebriefConfig) -> None:
    for error in report.errors:
        append_error_event(
            root,
            command="validate",
            phase="artifact",
            code="validation_failed",
            message=error,
            artifact=str(report.artifact),
            next_steps=[
                "Run `codedebrief update` to refresh stale artifacts.",
                "Rerun `codedebrief validate` after fixing the issue.",
            ],
            config=config,
        )
    for warning in report.warnings:
        append_error_event(
            root,
            command="validate",
            phase="artifact",
            severity="warning",
            code="validation_warning",
            message=warning,
            artifact=str(report.artifact),
            next_steps=["Review the warning, then rerun `codedebrief validate`."],
            config=config,
        )


@dataclass(frozen=True, slots=True)
class _ClearAction:
    path: Path
    description: str
    kind: str
    replacement: str | None = None


def _clear(root: Path, *, assume_yes: bool) -> int:
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    root = root.resolve()
    actions = _collect_clear_actions(root)
    print("CodeDebrief clear")
    print(f"Project: {root}")
    if not actions:
        print("Status: OK - no CodeDebrief files or managed sections found.")
        return 0

    print("Will remove:")
    for action in actions:
        print(f"- {action.description}: {action.path}")
    if not assume_yes:
        try:
            answer = input("Remove these CodeDebrief files and managed sections? [y/N] ")
        except EOFError:
            print("Status: cancelled - confirmation required; rerun with `--yes`.")
            return 1
        if answer.strip().lower() not in {"y", "yes"}:
            print("Status: cancelled - no files changed.")
            return 1

    _print_progress("Removing CodeDebrief files and managed sections")
    for action in actions:
        if action.kind == "delete_dir":
            shutil.rmtree(action.path, ignore_errors=True)
        elif action.kind == "delete_file":
            action.path.unlink(missing_ok=True)
        elif action.kind == "write_file" and action.replacement is not None:
            atomic_write_text(action.path, action.replacement, encoding="utf-8")
        else:  # pragma: no cover - defensive guard for future action kinds.
            raise RuntimeError(f"unknown clear action: {action.kind}")
    _prune_empty_dirs(root)
    print("")
    print("Status: OK - CodeDebrief files removed from this folder.")
    _print_next_steps(
        [
            "Run `codedebrief setup <agent>` if you want to configure this project again.",
            "Run `codedebrief update` after setup to regenerate artifacts.",
        ]
    )
    return 0


def _collect_clear_actions(root: Path) -> list[_ClearAction]:
    actions: list[_ClearAction] = []
    output_dirs = _configured_output_dirs(root)
    for directory in sorted(output_dirs):
        if not directory.exists() or not _is_inside_root(root, directory):
            continue
        if directory.resolve() == root:
            for artifact_name in (
                "codedebrief.json",
                "codedebrief.md",
                "codedebrief.hash.json",
                "codedebrief.html",
            ):
                artifact_path = root / artifact_name
                if artifact_path.exists():
                    actions.append(_ClearAction(artifact_path, "artifact file", "delete_file"))
            continue
        actions.append(_ClearAction(directory, "artifact directory", "delete_dir"))

    for config_path in (
        legacy_config_path(root),
        default_config_path(root),
        root / ".codedebriefignore",
    ):
        if config_path.exists():
            if _is_deleted_by_directory_action(config_path, actions):
                continue
            actions.append(_ClearAction(config_path, "config file", "delete_file"))

    for skill_relative in AGENT_SKILL_TARGETS.values():
        skill_dir = root / skill_relative.parent
        if skill_dir.exists():
            actions.append(_ClearAction(skill_dir, "agent skill directory", "delete_dir"))

    for instruction_relative in AGENT_INSTRUCTION_TARGETS.values():
        instruction_path = root / instruction_relative
        if not instruction_path.exists():
            continue
        if instruction_path == root / ".cursor" / "rules" / "codedebrief.mdc":
            actions.append(_ClearAction(instruction_path, "Cursor rule file", "delete_file"))
            continue
        replacement = _remove_instruction_block(instruction_path.read_text(encoding="utf-8"))
        _append_text_file_action(actions, instruction_path, replacement, "agent instruction block")

    codex_config = root / ".codex" / "config.toml"
    if codex_config.exists():
        replacement = _remove_managed_block(
            codex_config.read_text(encoding="utf-8"),
            LEGACY_CODEX_MCP_START,
            LEGACY_CODEX_MCP_END,
        )
        replacement = _remove_managed_block(replacement, CODEX_MCP_START, CODEX_MCP_END)
        _append_text_file_action(actions, codex_config, replacement, "Codex MCP config block")

    for mcp_config_path in (
        root / ".mcp.json",
        root / ".cursor" / "mcp.json",
        root / ".gemini" / "settings.json",
    ):
        if not mcp_config_path.exists():
            continue
        json_replacement = _remove_json_mcp_server(mcp_config_path)
        if json_replacement is not None:
            _append_text_file_action(actions, mcp_config_path, json_replacement, "MCP server entry")
    return _dedupe_clear_actions(actions)


def _configured_output_dirs(root: Path) -> set[Path]:
    output_dirs = {root / DEFAULT_OUTPUT_DIR}
    try:
        config = CodeDebriefConfig.load(root)
    except (OSError, ValueError, SyntaxError):
        return output_dirs
    output_dirs.add((root / config.output_dir).resolve())
    return output_dirs


def _remove_instruction_block(existing: str) -> str:
    return _remove_managed_block(existing, START, END)


def _remove_managed_block(existing: str, start: str, end: str) -> str:
    if start not in existing or end not in existing:
        return existing
    before, remainder = existing.split(start, 1)
    _, after = remainder.split(end, 1)
    separator = "\n\n" if before.strip() and after.strip() else ""
    combined = before.rstrip() + separator + after.lstrip()
    return combined.rstrip() + ("\n" if combined.strip() else "")


def _remove_json_mcp_server(path: Path) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or "codedebrief" not in servers:
        return None
    servers.pop("codedebrief", None)
    if not servers:
        data.pop("mcpServers", None)
    return json.dumps(data, indent=2) + "\n" if data else ""


def _append_text_file_action(
    actions: list[_ClearAction],
    path: Path,
    replacement: str,
    description: str,
) -> None:
    if replacement == path.read_text(encoding="utf-8"):
        return
    stripped = replacement.strip()
    if stripped:
        actions.append(_ClearAction(path, description, "write_file", replacement))
    else:
        actions.append(_ClearAction(path, description, "delete_file"))


def _dedupe_clear_actions(actions: Sequence[_ClearAction]) -> list[_ClearAction]:
    unique: list[_ClearAction] = []
    seen: set[Path] = set()
    for action in actions:
        if action.path in seen:
            continue
        unique.append(action)
        seen.add(action.path)
    return unique


def _is_deleted_by_directory_action(path: Path, actions: Sequence[_ClearAction]) -> bool:
    for action in actions:
        if action.kind != "delete_dir":
            continue
        with suppress(ValueError):
            path.resolve().relative_to(action.path.resolve())
            return True
    return False


def _prune_empty_dirs(root: Path) -> None:
    candidates = [
        root / ".agents" / "skills",
        root / ".agents",
        root / ".claude" / "skills",
        root / ".claude",
        root / ".gemini" / "skills",
        root / ".gemini",
        root / ".cursor" / "rules",
        root / ".cursor",
        root / ".codex",
    ]
    for directory in candidates:
        with suppress(OSError):
            directory.rmdir()


def _is_inside_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _print_next_steps(steps: Sequence[str]) -> None:
    print("Next steps:")
    for step in steps:
        print(f"- {step}")


def _print_progress(message: str) -> None:
    print(f"- {message}...", flush=True)


def _format_source_roots(source_roots: Sequence[str]) -> str:
    return ", ".join(source_roots) if source_roots else "."


def _artifacts_available(
    json_path: Path,
    markdown_path: Path,
    html_path: Path | None,
    hash_path: Path,
) -> bool:
    return (
        json_path.exists()
        and markdown_path.exists()
        and hash_path.exists()
        and (html_path is None or html_path.exists())
    )


def _normalize_source_roots(root: Path, source_roots: Sequence[str] | None) -> list[str] | None:
    if not source_roots:
        return None
    root_resolved = root.resolve()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_source in source_roots:
        source = raw_source.strip()
        if not source:
            raise ValueError("--source values must not be empty")
        candidate = Path(source)
        resolved = (candidate if candidate.is_absolute() else root_resolved / candidate).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"source path does not exist: {source}")
        value = _source_root_config_value(root_resolved, resolved)
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _source_root_config_value(root_resolved: Path, resolved: Path) -> str:
    try:
        value = os.path.relpath(resolved, root_resolved).replace(os.sep, "/")
    except ValueError:
        # Windows cannot relativize across drives. Keep the source usable rather than
        # rejecting a valid multi-root workspace.
        value = resolved.as_posix()
    return "." if value == "." else value


def _set_source_roots(existing: str, source_roots: Sequence[str]) -> str:
    source_line = f"source_roots = {_toml_string_array(source_roots)}\n"
    lines = existing.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "[codedebrief]"),
        None,
    )
    if start is None:
        prefix = "[codedebrief]\n" + source_line
        return prefix + ("\n" if existing.strip() else "") + existing
    end = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start + 1)
            if line.lstrip().startswith("[") and line.strip().endswith("]")
        ),
        len(lines),
    )
    for index in range(start + 1, end):
        stripped = lines[index].lstrip()
        if stripped.startswith("source_roots"):
            lines[index] = source_line
            return "".join(lines)
    lines.insert(start + 1, source_line)
    return "".join(lines)


def _toml_string_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"


def _starter_config_text(source_roots: Sequence[str] | None = None) -> str:
    roots = source_roots or ["."]
    return """[codedebrief]
# Analyze only these folders or files. Paths are relative to the project root where you
# run CodeDebrief unless absolute; sibling repos such as "../api" are supported.
# Artifacts still write under output_dir relative to this project root.
source_roots = __SOURCE_ROOTS__
exclude = []
exclude_dirs = []
# Defaults always prune dependency, VCS, cache, temp, and generated directories such as
# .git, node_modules, venv/.venv, dist/build/out/target, coverage, .next, .turbo,
# .nx, .svelte-kit, .pytest_cache, .mypy_cache, .ruff_cache, vendor, and codedebrief-out.
# Add project-specific directories above.
include_public_functions = true
max_call_depth = 4
output_dir = "codedebrief-out"
self_exclude = true

[codedebrief.entrypoints]
include = []
exclude = []

# Named macro-parts of the codebase (otherwise the top-level directory is the scope):
# [codedebrief.scopes]
# backend = ["backend/**", "services/**"]
# frontend = ["frontend/**", "web/**"]
# edge = ["edge/**", "workers/**"]
""".replace("__SOURCE_ROOTS__", _toml_string_array(roots))


if __name__ == "__main__":
    raise SystemExit(main())
