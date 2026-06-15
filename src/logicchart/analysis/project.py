from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from logicchart.analysis.common import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    DEFAULT_EXPORT_MARKER,
)
from logicchart.analysis.cross_flow import cross_flow_findings
from logicchart.analysis.discovery import discover_source_files
from logicchart.analysis.registry import LanguageAnalyzer, language_for, spec_for_language
from logicchart.config import LogicChartConfig
from logicchart.model import (
    FileAnalysis,
    FileRecord,
    Finding,
    FindingKind,
    Flow,
    FlowNode,
    NodeKind,
    ProjectModel,
)
from logicchart.util import (
    compact_text,
    file_sha256,
    read_json,
    relpath,
    stable_id,
    write_json,
)

CACHE_VERSION = "2"

# One bad file (mid-edit syntax error, non-UTF-8 bytes, a merge-conflict marker)
# must never abort the whole run - the tool's promise is to stay in sync on every
# commit. These are the errors the analyzers raise while ingesting one file.
_INGEST_ERRORS = (SyntaxError, UnicodeDecodeError, ValueError, OSError)


@dataclass(slots=True)
class AnalysisResult:
    model: ProjectModel
    changed_files: list[str]
    deleted_files: list[str]
    cache_hits: int
    skipped_files: list[tuple[str, str]] = field(default_factory=list)


class ProjectAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig | None = None) -> None:
        self.root = root.resolve()
        self.config = config or LogicChartConfig.load(self.root)
        self.cache_dir = self.root / ".logicchart" / "cache"
        self.index_path = self.cache_dir / "index.json"
        self.previous_generated_at: str | None = None
        # Language analyzers are built lazily from the registry, so a grammar is loaded
        # only when a file of that language is actually present.
        self._analyzers: dict[str, LanguageAnalyzer] = {}

    def analyze(self, *, full: bool = False) -> AnalysisResult:
        files = discover_source_files(self.root, self.config)
        previous_index = {} if full else self._load_index()
        current_paths = {relpath(path, self.root) for path in files}
        deleted_files = sorted(set(previous_index) - current_paths)
        analyses: list[FileAnalysis] = []
        changed_files: list[str] = []
        skipped_files: list[tuple[str, str]] = []
        cache_hits = 0
        new_index: dict[str, dict[str, str]] = {}

        for path in files:
            relative = relpath(path, self.root)
            digest = file_sha256(path)
            cache_file = self.cache_dir / f"{stable_id(relative, length=24)}.json"
            cached = previous_index.get(relative)
            reused = (
                not full
                and cached is not None
                and cached.get("sha256") == digest
                and self._load_cached_analysis(cache_file)
            )
            if reused:
                analysis = reused
                cache_hits += 1
            else:
                analysis, reason = self._safe_analyze_file(path, relative, digest)
                if reason is not None:
                    skipped_files.append((relative, reason))
                write_json(cache_file, analysis.to_dict())
                changed_files.append(relative)
            analyses.append(analysis)
            new_index[relative] = {"sha256": digest, "cache": cache_file.name}

        model = self._combine(analyses)
        if not full and not changed_files and not deleted_files and self.previous_generated_at:
            model.generated_at = self.previous_generated_at
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            self.index_path,
            {
                "cache_version": CACHE_VERSION,
                "generated_at": model.generated_at,
                "files": new_index,
            },
        )
        return AnalysisResult(
            model=model,
            changed_files=changed_files,
            deleted_files=deleted_files,
            cache_hits=cache_hits,
            skipped_files=skipped_files,
        )

    def _analyze_file(self, path: Path) -> FileAnalysis:
        return self._analyzer_for(language_for(path)).analyze(path)

    def _analyzer_for(self, language: str) -> LanguageAnalyzer:
        analyzer = self._analyzers.get(language)
        if analyzer is None:
            analyzer = spec_for_language(language).factory(self.root, self.config)
            self._analyzers[language] = analyzer
        return analyzer

    def _safe_analyze_file(
        self, path: Path, relative: str, digest: str
    ) -> tuple[FileAnalysis, str | None]:
        """Analyze one file, degrading to an empty record instead of aborting the run.

        A single un-parseable or non-UTF-8 file (common while editing, on a merge
        conflict, or in a mixed-language repo) is recorded as a skipped file and the
        rest of the model is still built - the "always in sync" guarantee can't hinge
        on every file parsing cleanly.
        """
        try:
            return self._analyze_file(path), None
        except _INGEST_ERRORS as error:
            return self._degraded_file(path, relative, digest), _skip_reason(error)

    def _degraded_file(self, path: Path, relative: str, digest: str) -> FileAnalysis:
        return FileAnalysis(path=relative, language=language_for(path), sha256=digest)

    def _load_cached_analysis(self, cache_file: Path) -> FileAnalysis | None:
        if not cache_file.exists():
            return None
        try:
            return FileAnalysis.from_dict(read_json(cache_file))
        except (ValueError, KeyError, TypeError, OSError):
            # A corrupt cache entry is never fatal - fall back to a fresh analysis.
            return None

    def _load_index(self) -> dict[str, dict[str, str]]:
        if not self.index_path.exists():
            return {}
        data = read_json(self.index_path)
        if data.get("cache_version") != CACHE_VERSION:
            return {}
        generated_at = data.get("generated_at")
        self.previous_generated_at = str(generated_at) if generated_at else None
        file_data = data.get("files", {})
        return {
            str(path): {"sha256": str(item["sha256"]), "cache": str(item["cache"])}
            for path, item in file_data.items()
        }

    def _combine(self, analyses: list[FileAnalysis]) -> ProjectModel:
        flows = [flow for analysis in analyses for flow in analysis.flows]
        findings = [finding for analysis in analyses for finding in analysis.findings]
        self._link_calls(flows)
        self._link_tests(flows)
        # Keyed by language so a Python enum and a same-named TS union stay distinct
        # value universes (they are different closed sets).
        enums: dict[str, dict[str, list[str]]] = {}
        for analysis in analyses:
            language_enums = enums.setdefault(analysis.language, {})
            for name, members in analysis.enums.items():
                known = language_enums.setdefault(name, [])
                known.extend(member for member in members if member not in known)
        constants_by_path = {analysis.path: analysis.constants for analysis in analyses}
        findings.extend(
            cross_flow_findings(flows, enums, constants_by_path, gated=self.config.gated_detectors)
        )
        findings = _suppress_redundant_missing_branch(findings)
        findings = _deduplicate_findings(findings)
        files = [
            FileRecord(
                path=analysis.path,
                language=analysis.language,
                sha256=analysis.sha256,
                flow_ids=[flow.id for flow in analysis.flows],
            )
            for analysis in analyses
        ]
        return ProjectModel(
            schema_version="1.1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            root=".",
            flows=sorted(flows, key=lambda item: (not item.is_entrypoint, item.symbol)),
            findings=sorted(findings, key=lambda item: (item.severity.value, item.message)),
            files=files,
            metadata={
                "languages": sorted({item.language for item in analyses}),
                "entrypoint_count": sum(flow.is_entrypoint for flow in flows),
                "flow_count": len(flows),
                "finding_count": len(findings),
                "enums": enums,
            },
        )

    def _link_calls(self, flows: list[Flow]) -> None:
        # Import-aware first (`qualified_calls` from the analyzers), short name as a
        # fallback. Ambiguous candidates are recorded, not dropped, and every link
        # carries a `link_confidence` so interprocedural detectors can weigh it.
        # Key on the flow symbol as-is (``module:qualified``) so a module-path
        # boundary can never collide with an attribute boundary. A default-export
        # flow also answers to the module's default marker.
        by_qualified: dict[str, list[Flow]] = {}
        by_name: dict[str, list[Flow]] = {}
        for flow in flows:
            by_qualified.setdefault(flow.symbol, []).append(flow)
            if flow.metadata.get("default_export"):
                module = flow.symbol.split(":", 1)[0]
                by_qualified.setdefault(f"{module}:{DEFAULT_EXPORT_MARKER}", []).append(flow)
            short = flow.symbol.split(":", 1)[-1].split(".")[-1]
            by_name.setdefault(short, []).append(flow)

        for flow in flows:
            for node in flow.nodes:
                if node.kind is not NodeKind.CALL:
                    continue
                candidates, confidence = self._resolve_call(flow, node, by_qualified, by_name)
                if not candidates:
                    continue
                node.metadata["link_confidence"] = confidence
                node.metadata["call_candidates"] = sorted(candidates)
                if len(candidates) == 1:
                    target = next(iter(candidates.values()))
                    node.metadata["target_flow"] = target.id
                    node.metadata["target_symbol"] = target.symbol
                    if target.id not in flow.calls:
                        flow.calls.append(target.id)
                    if flow.id not in target.called_by:
                        target.called_by.append(flow.id)

    @staticmethod
    def _resolve_call(
        flow: Flow,
        node: FlowNode,
        by_qualified: dict[str, list[Flow]],
        by_name: dict[str, list[Flow]],
    ) -> tuple[dict[str, Flow], str]:
        qualified: dict[str, Flow] = {}
        for name in node.metadata.get("qualified_calls", []):
            for candidate in by_qualified.get(str(name), []):
                if candidate.id != flow.id:
                    qualified[candidate.id] = candidate
        if qualified:
            return qualified, (CONFIDENCE_HIGH if len(qualified) == 1 else CONFIDENCE_LOW)

        short_name: dict[str, Flow] = {}
        for raw in node.metadata.get("calls", []):
            for candidate in by_name.get(str(raw).split(".")[-1], []):
                if candidate.id != flow.id:
                    short_name[candidate.id] = candidate
        if short_name:
            return short_name, (CONFIDENCE_MEDIUM if len(short_name) == 1 else CONFIDENCE_LOW)
        return {}, CONFIDENCE_NONE

    def _link_tests(self, flows: list[Flow]) -> None:
        by_id = {flow.id: flow for flow in flows}
        for flow in flows:
            if not flow.metadata.get("test"):
                continue
            for target_id in flow.calls:
                target = by_id.get(target_id)
                if target and flow.symbol not in target.tests:
                    target.tests.append(flow.symbol)


def _skip_reason(error: Exception) -> str:
    """A one-line, human-readable reason a file was skipped."""
    text = str(error).strip() or error.__class__.__name__
    return compact_text(text, 200)


def _suppress_redundant_missing_branch(findings: list[Finding]) -> list[Finding]:
    """Drop missing_branch where enum_exhaustiveness already names the missing members.

    Both fire on a state-like dispatch with no fallback; the declared-set finding is
    strictly more actionable, so keep it and suppress the generic one on that node.
    """
    enum_nodes = {
        (item.flow_id, item.node_id)
        for item in findings
        if item.kind == FindingKind.ENUM_EXHAUSTIVENESS
    }
    return [
        item
        for item in findings
        if not (
            item.kind == FindingKind.MISSING_BRANCH and (item.flow_id, item.node_id) in enum_nodes
        )
    ]


def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    return list({item.id: item for item in findings}.values())
