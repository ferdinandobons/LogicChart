import {
  mountLogicChartViewer,
  type MountedLogicChartViewer,
} from "./mount";
import type { ExportImageFormat } from "./mount";
import {
  buildFlowIndex,
  scopeNamesForFlow,
  scopeSummaries,
  type LogicChartFlow,
  type LogicChartLocation,
  type LogicChartPayload,
} from "./logicchart-model";
import type {
  DetailEdgeSelection,
  DetailNodeSelection,
  ViewerAppProps,
} from "./ViewerApp";
import type { ManualNodePosition } from "./viewer-layout";
import type { SelectedConnection } from "./viewer-store";

const EXPANSION_BATCH_SIZE = 250;

export interface StandaloneViewerOptions {
  initialScope?: string;
  location?: Pick<Location, "hash">;
}

export interface MountedStandaloneLogicChartViewer {
  expandAll: () => void;
  exportImage: (format: ExportImageFormat) => void;
  fitView: () => void;
  resetView: () => void;
  selectFlow: (flowId: string) => void;
  selectScope: (scope: string) => void;
  update: () => void;
  zoom: (factor: number) => void;
  unmount: () => void;
}

export function mountStandaloneLogicChartViewer(
  container: Element,
  payload: LogicChartPayload,
  options: StandaloneViewerOptions = {},
): MountedStandaloneLogicChartViewer {
  const canSubscribe =
    typeof window !== "undefined" && options.location === undefined;
  const flowById = buildFlowIndex(payload);
  const directConnectionIndex = directConnectionIndexForFlows(flowById);
  const stateStorageKey = viewerStateStorageKey(payload);
  const progress = createExpansionProgress(container);
  const persistedState = canSubscribe
    ? readViewerState(stateStorageKey, flowById)
    : emptyViewerState();
  const openedFlowIds = new Set<string>(persistedState.openedFlowIds);
  const openedDetailFlowIds = new Set<string>(persistedState.openedDetailFlowIds);
  const openedScopeIds = new Set<string>(persistedState.openedScopeIds);
  let expandedOverviewMode = persistedState.expandedOverviewMode;
  let manualNodePositions = new Map(persistedState.manualNodePositions);
  const persistState = () => {
    if (!canSubscribe) return;
    writeViewerState(stateStorageKey, {
      expandedOverviewMode,
      manualNodePositions,
      openedDetailFlowIds,
      openedFlowIds,
      openedScopeIds,
    });
  };
  const openFlowAndDirectConnectionScopes = (flowId: string): boolean => {
    if (!flowById.has(flowId)) return false;
    let changed = false;
    if (!openedFlowIds.has(flowId)) {
      openedFlowIds.add(flowId);
      changed = true;
    }
    if (!openedDetailFlowIds.has(flowId)) {
      openedDetailFlowIds.add(flowId);
      changed = true;
    }
    directConnectionScopeNames(flowById, directConnectionIndex, flowId).forEach(scope => {
      if (openedScopeIds.has(scope)) return;
      openedScopeIds.add(scope);
      changed = true;
    });
    return changed;
  };
  const navigateToHash = (hash: string) => {
    if (!canSubscribe) return;
    if (window.location.hash === hash) return;
    window.location.hash = hash;
  };
  let expansionJob: ExpansionJob | null = null;
  const cancelExpansionJob = () => {
    expansionJob?.cancel();
    expansionJob = null;
    progress.finish();
  };
  const renderWithProgress = (label: string, render: () => void) => {
    cancelExpansionJob();
    const job = createExpansionJob(() => {
      progress.start(label, 1);
      job.schedule(() => {
        if (expansionJob !== job) return;
        progress.update(0, 1);
        render();
        progress.update(1, 1);
        job.schedule(() => {
          if (expansionJob !== job) return;
          progress.finish();
          expansionJob = null;
        });
      });
    });
    expansionJob = job;
    job.start();
  };
  const buildProps = (): ViewerAppProps => {
    const props = propsFromLocation(payload, options);
    const routeRequestsRoot =
      props.expandedScopes !== undefined && props.expandedScopes.length === 0;
    const routeSelectsRoot = props.selectedRoot === true;
    const routeSelectsRootScopeEdge = props.selectedConnection?.kind === "root-scope";
    let openedFromRoute = false;
    if (
      !routeRequestsRoot &&
      !routeSelectsRoot &&
      !routeSelectsRootScopeEdge &&
      props.scope &&
      !openedScopeIds.has(props.scope)
    ) {
      openedScopeIds.add(props.scope);
      openedFromRoute = true;
    }
    if (!routeRequestsRoot && !routeSelectsRoot) {
      props.routeFlowIds?.forEach(flowId => {
        openedFromRoute = openFlowAndDirectConnectionScopes(flowId) || openedFromRoute;
      });
    }
    if (openedFromRoute) persistState();
    return {
      ...props,
      expandedScopes: routeRequestsRoot ? [] : [...openedScopeIds],
      contextFlowIds: routeRequestsRoot
        ? []
        : contextFlowIdsForOpenedFlows(directConnectionIndex, openedFlowIds),
      detailFlowIds: routeRequestsRoot ? [] : [...openedDetailFlowIds],
      initialManualNodePositions: manualNodePositions,
      layoutMode: expandedOverviewMode ? "expanded-overview" : "normal",
      routeFlowIds: routeRequestsRoot ? [] : [...openedFlowIds],
      syncHash: canSubscribe,
      onConnectionSelect(connection) {
        if (connection.kind === "root-scope") {
          navigateToHash(
            hashForRootScopeConnection(connection.scope, {
              rootOnly: routeRequestsRoot || (routeSelectsRootScopeEdge && openedScopeIds.size === 0),
            }),
          );
          publishShellScopeSelection(connection.scope);
        } else if (connection.kind === "scope-entry") {
          navigateToHash(hashForScopeEntryConnection(connection.scope, connection.target));
          publishShellFlowSelection(flowById, connection.target);
        } else {
          navigateToHash(hashForFlowCallConnection(connection.source, connection.target));
          publishShellFlowSelection(flowById, connection.target);
        }
      },
      onDetailEdgeSelect(selection) {
        publishShellDetailSelection(flowById, selection);
      },
      onDetailNodeSelect(selection) {
        publishShellDetailSelection(flowById, selection);
      },
      onFlowSelect(flowId) {
        if (openFlowAndDirectConnectionScopes(flowId)) {
          persistState();
        }
        publishShellFlowSelection(flowById, flowId);
        navigateToHash(hashForFlow(flowId));
      },
      onRootSelect() {
        navigateToHash(hashForRootNodeSelection());
        publishShellRootSelection();
      },
      onManualNodePositionsChange(positions) {
        manualNodePositions = new Map(positions);
        persistState();
      },
      onSelectionClear() {
        navigateToHash(
          routeRequestsRoot || (routeSelectsRootScopeEdge && openedScopeIds.size === 0)
            ? "#root"
            : `#scope=${encodeHashValue(props.scope)}`,
        );
      },
      onScopeSelect(scope) {
        openedScopeIds.add(scope);
        persistState();
        navigateToHash(`#scope=${encodeHashValue(scope)}`);
        publishShellScopeSelection(scope);
      },
    };
  };
  const initialProps = buildProps();
  let mounted: MountedLogicChartViewer | null = mountLogicChartViewer(container, initialProps);
  publishShellRouteSelection(flowById, initialProps);
  const updateMounted = () => {
    const props = buildProps();
    mounted?.update(props);
    publishShellRouteSelection(flowById, props);
  };
  const update = () => {
    cancelExpansionJob();
    updateMounted();
  };
  const handleHashChange = () => {
    if (expansionJob) return;
    update();
  };

  if (canSubscribe) {
    window.addEventListener("hashchange", handleHashChange);
  }

  return {
    expandAll() {
      cancelExpansionJob();
      const scopeNames = scopeSummaries(payload).map(scope => scope.name);
      const flowIds = payload.flows
        .filter(flow => !flow.metadata?.test)
        .map(flow => flow.id);
      const expansionTargets = [
        ...scopeNames.map(scope => ({ kind: "scope" as const, id: scope })),
        ...flowIds.map(flowId => ({ kind: "flow" as const, id: flowId })),
      ];
      const total = Math.max(1, scopeNames.length + flowIds.length + 2);
      const job = createExpansionJob(() => {
        progress.start("Expanding canvas", total);
        progress.update(0, total);
        let targetIndex = 0;
        const openNextBatch = () => {
          if (expansionJob !== job) return;
          const end = Math.min(targetIndex + EXPANSION_BATCH_SIZE, expansionTargets.length);
          for (; targetIndex < end; targetIndex += 1) {
            const target = expansionTargets[targetIndex];
            if (target.kind === "scope") openedScopeIds.add(target.id);
            else openedFlowIds.add(target.id);
          }
          progress.update(targetIndex, total);
          if (targetIndex < expansionTargets.length) {
            job.schedule(openNextBatch);
            return;
          }
          persistState();
          const hash = currentHash();
          const isCollapsedRoot = !hash || hash === "#root";
          if (isCollapsedRoot) {
            const firstScope = scopeNames[0] ?? [...openedScopeIds][0];
            if (firstScope) {
              navigateToHash(`#scope=${encodeHashValue(firstScope)}`);
              publishShellScopeSelection(firstScope);
            }
          }
          job.schedule(() => {
            if (expansionJob !== job) return;
            const props = buildProps();
            mounted?.update(props);
            publishShellRouteSelection(flowById, props);
            progress.update(total - 1, total);
            job.schedule(() => {
              if (expansionJob !== job) return;
              mounted?.fitView();
              progress.update(total, total);
              job.schedule(() => {
                if (expansionJob !== job) return;
                progress.finish();
                expansionJob = null;
              });
            });
          });
        };
        job.schedule(() => {
          expandedOverviewMode = true;
          openNextBatch();
        });
      });
      expansionJob = job;
      job.start();
    },
    exportImage(format) {
      mounted?.exportImage(format);
    },
    fitView() {
      mounted?.fitView();
    },
    resetView() {
      cancelExpansionJob();
      openedFlowIds.clear();
      openedDetailFlowIds.clear();
      openedScopeIds.clear();
      expandedOverviewMode = false;
      manualNodePositions = new Map();
      clearViewerState(stateStorageKey);
      mounted?.resetView();
      navigateToHash("#root");
      publishShellRootSelection();
      update();
    },
    selectFlow(flowId) {
      const changed = openFlowAndDirectConnectionScopes(flowId);
      if (changed) {
        persistState();
      }
      publishShellFlowSelection(flowById, flowId);
      navigateToHash(hashForFlow(flowId));
      if (changed) {
        renderWithProgress("Opening flow", updateMounted);
      } else {
        update();
      }
    },
    selectScope(scope) {
      const changed = !openedScopeIds.has(scope);
      openedScopeIds.add(scope);
      if (changed) persistState();
      publishShellScopeSelection(scope);
      navigateToHash(`#scope=${encodeHashValue(scope)}`);
      if (changed) {
        renderWithProgress("Opening scope", updateMounted);
      } else {
        update();
      }
    },
    update,
    zoom(factor) {
      mounted?.zoom(factor);
    },
    unmount() {
      cancelExpansionJob();
      if (canSubscribe) {
        window.removeEventListener("hashchange", handleHashChange);
      }
      mounted?.unmount();
      mounted = null;
      progress.remove();
    },
  };
}

interface ExpansionJob {
  cancel: () => void;
  schedule: (callback: () => void) => void;
  start: () => void;
}

function createExpansionJob(work: () => void): ExpansionJob {
  let cancelled = false;
  const timers = new Set<number>();
  const clearTimers = () => {
    timers.forEach(timer => window.clearTimeout(timer));
    timers.clear();
  };
  const schedule = (callback: () => void) => {
    const timer = window.setTimeout(() => {
      timers.delete(timer);
      if (!cancelled) callback();
    }, 0);
    timers.add(timer);
  };
  return {
    cancel() {
      cancelled = true;
      clearTimers();
    },
    schedule,
    start() {
      schedule(work);
    },
  };
}

interface ExpansionProgress {
  finish: () => void;
  remove: () => void;
  start: (label: string, total: number) => void;
  update: (completed: number, total: number) => void;
}

function createExpansionProgress(container: Element): ExpansionProgress {
  const ownerDocument = container.ownerDocument;
  const overlay = ownerDocument.createElement("div");
  overlay.className = "logicchart-expand-progress";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
  overlay.hidden = true;

  const label = ownerDocument.createElement("span");
  label.className = "logicchart-expand-progress-label";
  const bar = ownerDocument.createElement("div");
  bar.className = "logicchart-expand-progress-track";
  const value = ownerDocument.createElement("div");
  value.className = "logicchart-expand-progress-value";
  bar.appendChild(value);
  const count = ownerDocument.createElement("span");
  count.className = "logicchart-expand-progress-count";
  overlay.append(label, bar, count);
  container.appendChild(overlay);

  return {
    finish() {
      overlay.hidden = true;
      value.style.width = "0%";
    },
    remove() {
      overlay.remove();
    },
    start(nextLabel, total) {
      label.textContent = nextLabel;
      count.textContent = `0 / ${Math.max(1, total)}`;
      value.style.width = "0%";
      overlay.hidden = false;
    },
    update(completed, total) {
      const boundedTotal = Math.max(1, total);
      const boundedCompleted = Math.max(0, Math.min(completed, boundedTotal));
      count.textContent = `${boundedCompleted} / ${boundedTotal}`;
      value.style.width = `${Math.round((boundedCompleted / boundedTotal) * 100)}%`;
    },
  };
}

const VIEWER_STATE_VERSION = 4;

interface ViewerPersistedState {
  expandedOverviewMode: boolean;
  manualNodePositions: Map<string, ManualNodePosition>;
  openedDetailFlowIds: string[];
  openedFlowIds: string[];
  openedScopeIds: string[];
}

function emptyViewerState(): ViewerPersistedState {
  return {
    expandedOverviewMode: false,
    manualNodePositions: new Map(),
    openedDetailFlowIds: [],
    openedFlowIds: [],
    openedScopeIds: [],
  };
}

function directConnectionScopeNames(
  flowById: ReadonlyMap<string, LogicChartFlow>,
  directConnectionIndex: ReadonlyMap<string, ReadonlySet<string>>,
  flowId: string,
): string[] {
  const relatedFlowIds = new Set<string>([
    flowId,
    ...directConnectionFlowIds(directConnectionIndex, flowId),
  ]);
  const scopes = new Set<string>();
  relatedFlowIds.forEach(id => {
    const relatedFlow = flowById.get(id);
    if (!relatedFlow) return;
    scopeNamesForFlow(relatedFlow).forEach(scope => scopes.add(scope));
  });
  return [...scopes].sort();
}

function directConnectionFlowIds(
  directConnectionIndex: ReadonlyMap<string, ReadonlySet<string>>,
  flowId: string,
): string[] {
  return [...(directConnectionIndex.get(flowId) || [])].sort();
}

function directConnectionIndexForFlows(
  flowById: ReadonlyMap<string, LogicChartFlow>,
): Map<string, Set<string>> {
  const index = new Map<string, Set<string>>();
  const add = (sourceId: string, targetId: string) => {
    if (sourceId === targetId || !flowById.has(sourceId) || !flowById.has(targetId)) return;
    const sourceConnections = index.get(sourceId) || new Set<string>();
    sourceConnections.add(targetId);
    index.set(sourceId, sourceConnections);
    const targetConnections = index.get(targetId) || new Set<string>();
    targetConnections.add(sourceId);
    index.set(targetId, targetConnections);
  };
  flowById.forEach(flow => {
    (flow.calls || []).forEach(targetId => add(flow.id, targetId));
    (flow.called_by || []).forEach(sourceId => add(sourceId, flow.id));
  });
  return index;
}

function contextFlowIdsForOpenedFlows(
  directConnectionIndex: ReadonlyMap<string, ReadonlySet<string>>,
  openedFlowIds: ReadonlySet<string>,
): string[] {
  const context = new Set<string>();
  openedFlowIds.forEach(openedFlowId => {
    directConnectionFlowIds(directConnectionIndex, openedFlowId).forEach(flowId => {
      if (!openedFlowIds.has(flowId)) context.add(flowId);
    });
  });
  return [...context].sort();
}

function readViewerState(
  key: string,
  flowById: ReadonlyMap<string, LogicChartFlow>,
): ViewerPersistedState {
  const storage = browserStorage();
  if (!storage) return emptyViewerState();
  try {
    const raw = storage.getItem(key);
    if (!raw) return emptyViewerState();
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return emptyViewerState();
    const record = parsed as Record<string, unknown>;
    if (record.version !== VIEWER_STATE_VERSION) return emptyViewerState();
    const openedFlowIds = Array.isArray(record.openedFlowIds)
      ? record.openedFlowIds.filter(
          (flowId): flowId is string =>
            typeof flowId === "string" && flowById.has(flowId),
        )
      : [];
    const openedDetailFlowIds = Array.isArray(record.openedDetailFlowIds)
      ? record.openedDetailFlowIds.filter(
          (flowId): flowId is string =>
            typeof flowId === "string" && flowById.has(flowId),
        )
      : [];
    const openedScopeIds = Array.isArray(record.openedScopeIds)
      ? record.openedScopeIds.filter((scope): scope is string => typeof scope === "string")
      : [];
    const manualNodePositions = new Map<string, ManualNodePosition>();
    if (Array.isArray(record.manualNodePositions)) {
      record.manualNodePositions.forEach(item => {
        if (!Array.isArray(item) || item.length !== 2) return;
        const [key, value] = item as [unknown, unknown];
        if (typeof key !== "string" || !value || typeof value !== "object") return;
        const position = value as Record<string, unknown>;
        if (typeof position.x !== "number" || typeof position.y !== "number") return;
        if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) return;
        manualNodePositions.set(key, {
          x: position.x,
          y: position.y,
        });
      });
    }
    return {
      expandedOverviewMode: record.expandedOverviewMode === true,
      manualNodePositions,
      openedDetailFlowIds,
      openedFlowIds,
      openedScopeIds,
    };
  } catch {
    return emptyViewerState();
  }
}

function writeViewerState(
  key: string,
  state: {
    expandedOverviewMode: boolean;
    manualNodePositions: ReadonlyMap<string, ManualNodePosition>;
    openedDetailFlowIds: ReadonlySet<string>;
    openedFlowIds: ReadonlySet<string>;
    openedScopeIds: ReadonlySet<string>;
  },
) {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.setItem(
      key,
      JSON.stringify({
        manualNodePositions: [...state.manualNodePositions.entries()],
        expandedOverviewMode: state.expandedOverviewMode,
        openedDetailFlowIds: [...state.openedDetailFlowIds],
        openedFlowIds: [...state.openedFlowIds],
        openedScopeIds: [...state.openedScopeIds],
        version: VIEWER_STATE_VERSION,
      }),
    );
  } catch {
    // Read-only or quota-limited browser contexts still get an in-memory viewer.
  }
}

function clearViewerState(key: string) {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // Ignore storage failures in embedded contexts.
  }
}

function viewerStateStorageKey(payload: LogicChartPayload): string {
  const flowSignature = payload.flows
    .map(flow =>
      [
        flow.id,
        flow.location?.path || "",
        flow.location?.start_line || "",
        scopeNamesForFlow(flow).join(","),
      ].join(":"),
    )
    .sort()
    .join("|");
  return `logicchart-viewer-state:v${VIEWER_STATE_VERSION}:${hashString(flowSignature)}`;
}

function browserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage || null;
  } catch {
    return null;
  }
}

function hashForRootScopeConnection(
  scope: string,
  options: { rootOnly?: boolean } = {},
): string {
  return `#edge=${encodeHashValue(
    JSON.stringify({ kind: "root-scope", rootOnly: options.rootOnly || undefined, scope }),
  )}`;
}

function hashForScopeEntryConnection(scope: string, target: string): string {
  return `#edge=${encodeHashValue(JSON.stringify({ scope, target }))}`;
}

function hashForFlowCallConnection(source: string, target: string): string {
  return `#edge=${encodeHashValue(JSON.stringify({ kind: "flow-call", source, target }))}`;
}

function hashForRootNodeSelection(): string {
  return "#node=codebase";
}

function hashForFlow(flowId: string): string {
  return `#flow=${encodeHashValue(flowId)}`;
}

type DetailSelection = DetailEdgeSelection | DetailNodeSelection;

interface LogicChartShellSelection {
  edgeId?: string | null;
  endLine?: number | null;
  findingId?: string | null;
  flowId?: string | null;
  line?: number | null;
  nodeId?: string | null;
  path?: string | null;
  scope?: string | null;
}

interface LogicChartShell {
  openDetails?: () => void;
  select?: (selection: LogicChartShellSelection) => void;
}

function publishShellDetailSelection(
  flowById: ReadonlyMap<string, LogicChartFlow>,
  selection: DetailSelection,
) {
  const shell = logicChartShell();
  if (!shell?.select) return;
  const flow = flowById.get(selection.flowId);
  const nodeId = "target" in selection ? selection.target : selection.nodeId;
  const node = flow?.nodes?.find(item => item.id === nodeId);
  const location = node?.location || flow?.location;
  shell.select({
    edgeId: "edgeId" in selection ? selection.edgeId : null,
    endLine: endLineForLocation(location),
    findingId: null,
    flowId: selection.flowId,
    line: location?.start_line ?? null,
    nodeId,
    path: selection.path || node?.location?.path || flow?.location?.path || null,
  });
  shell.openDetails?.();
}

function publishShellFlowSelection(
  flowById: ReadonlyMap<string, LogicChartFlow>,
  flowId: string,
) {
  const shell = logicChartShell();
  if (!shell?.select) return;
  const flow = flowById.get(flowId);
  shell.select({
    edgeId: null,
    endLine: endLineForLocation(flow?.location),
    findingId: null,
    flowId,
    line: flow?.location?.start_line ?? null,
    nodeId: null,
    path: flow?.location?.path || null,
  });
  shell.openDetails?.();
}

function publishShellScopeSelection(scope: string) {
  const shell = logicChartShell();
  if (!shell?.select) return;
  shell.select({
    edgeId: null,
    endLine: null,
    findingId: null,
    flowId: null,
    line: null,
    nodeId: null,
    path: null,
    scope,
  });
  shell.openDetails?.();
}

function publishShellRootSelection() {
  const shell = logicChartShell();
  if (!shell?.select) return;
  shell.select({
    edgeId: null,
    endLine: null,
    findingId: null,
    flowId: null,
    line: null,
    nodeId: null,
    path: null,
    scope: null,
  });
  shell.openDetails?.();
}

function publishShellRouteSelection(
  flowById: ReadonlyMap<string, LogicChartFlow>,
  props: ViewerAppProps,
) {
  if (props.selectedFlowId) {
    publishShellFlowSelection(flowById, props.selectedFlowId);
    return;
  }
  const connection = props.selectedConnection;
  if (connection) {
    if (connection.kind === "root-scope") {
      publishShellScopeSelection(connection.scope);
      return;
    }
    publishShellFlowSelection(flowById, connection.target);
    return;
  }
  if (props.selectedRoot) {
    publishShellRootSelection();
  }
}

function endLineForLocation(location: LogicChartLocation | undefined): number | null {
  if (location?.end_line != null) return location.end_line;
  return location?.start_line ?? null;
}

function logicChartShell(): LogicChartShell | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as typeof window & { LC?: LogicChartShell }).LC;
}

export function propsFromLocation(
  payload: LogicChartPayload,
  options: StandaloneViewerOptions = {},
): ViewerAppProps {
  const fallbackScope = firstScope(payload, options.initialScope);
  const route = routeFromHash(payload, options.location?.hash ?? currentHash(), fallbackScope);
  return {
    expandedScopes: route.rootOnly ? [] : undefined,
    payload,
    routeFlowIds: route.routeFlowIds,
    selectedConnection: route.selectedConnection,
    selectedFlowId: route.selectedFlowId,
    selectedRoot: route.selectedRoot,
    scope: route.scope || fallbackScope,
  };
}

interface ViewerRoute {
  rootOnly?: boolean;
  selectedRoot?: boolean;
  selectedFlowId?: string | null;
  scope: string;
  routeFlowIds: string[];
  selectedConnection?: SelectedConnection;
}

function routeFromHash(
  payload: LogicChartPayload,
  hash: string,
  fallback = firstScope(payload),
): ViewerRoute {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!raw) return { scope: fallback, routeFlowIds: [] };
  if (raw === "root") {
    return { rootOnly: true, scope: fallback, routeFlowIds: [] };
  }
  const [key, encodedValue] = raw.includes("=")
    ? raw.split("=", 2)
    : ["flow", raw];
  const value = safeDecode(encodedValue);
  if (!value) return { scope: fallback, routeFlowIds: [] };

  if (key === "scope") {
    return { scope: value, routeFlowIds: [] };
  }

  if (key === "node" && value === "codebase") {
    return { scope: fallback, routeFlowIds: [], selectedRoot: true };
  }

  if (key === "edge") {
    const connection = edgeSelectionFromHashValue(value);
    if (connection) {
      if (connection.kind === "root-scope") {
        return {
          rootOnly: connection.rootOnly,
          routeFlowIds: [],
          scope: connection.scope,
          selectedConnection: connection,
        };
      }
      if (connection.kind === "flow-call") {
        const source = buildFlowIndex(payload).get(connection.source);
        return {
          routeFlowIds: source ? [source.id] : [],
          scope: source ? scopeNamesForFlow(source)[0] || fallback : fallback,
          selectedConnection: connection,
        };
      }
      return {
        routeFlowIds: [],
        scope: connection.scope,
        selectedConnection: connection,
      };
    }
    return { scope: fallback, routeFlowIds: [] };
  }

  if (key === "path") {
    return { scope: value.split("/").filter(Boolean)[0] || fallback, routeFlowIds: [] };
  }

  const byId = buildFlowIndex(payload);
  const flow = byId.get(value);
  if (key === "flow" && flow) {
    return {
      scope: scopeNamesForFlow(flow)[0] || fallback,
      selectedFlowId: flow.id,
      routeFlowIds: [flow.id],
    };
  }

  return { scope: fallback, routeFlowIds: [] };
}

function edgeSelectionFromHashValue(value: string): Extract<
  SelectedConnection,
  { kind: "root-scope" } | { kind: "scope-entry" } | { kind: "flow-call" }
> & { rootOnly?: boolean } | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    const record = parsed as Record<string, unknown>;
    if (record.kind === "root-scope") {
      if (typeof record.scope !== "string") return null;
      return {
        kind: "root-scope",
        rootOnly: record.rootOnly === true || undefined,
        scope: record.scope,
      };
    }
    if (record.kind === "flow-call") {
      if (typeof record.source !== "string" || typeof record.target !== "string") {
        return null;
      }
      return {
        kind: "flow-call",
        source: record.source,
        target: record.target,
      };
    }
    if (typeof record.scope !== "string" || typeof record.target !== "string") {
      return null;
    }
    return {
      kind: "scope-entry",
      scope: record.scope,
      target: record.target,
    };
  } catch {
    return null;
  }
}

function firstScope(payload: LogicChartPayload, preferred?: string): string {
  const scopes = scopeSummaries(payload).map(scope => scope.name);
  if (preferred && scopes.includes(preferred)) return preferred;
  return scopes[0] || "codebase";
}

function currentHash(): string {
  return typeof window === "undefined" ? "" : window.location.hash;
}

function safeDecode(value: string): string | null {
  try {
    if (typeof decodeURIComponent === "function") {
      return decodeURIComponent(value);
    }
  } catch {
    // Fall through to the local decoder below. Some embedded browser test
    // contexts expose a restricted global object without decodeURIComponent.
  }
  return decodePercentEncodedAscii(value);
}

function encodeHashValue(value: string): string {
  if (typeof encodeURIComponent === "function") return encodeURIComponent(value);
  return value.replace(/[^A-Za-z0-9_.~-]/g, char =>
    `%${char.charCodeAt(0).toString(16).padStart(2, "0").toUpperCase()}`,
  );
}

function decodePercentEncodedAscii(value: string): string | null {
  try {
    return value.replace(/%([0-9A-Fa-f]{2})/g, (_, hex: string) =>
      String.fromCharCode(Number.parseInt(hex, 16)),
    );
  } catch {
    return null;
  }
}

function hashString(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(36);
}
