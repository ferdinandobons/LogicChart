import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  layoutFlowDetail,
  type FlowDetailLayout,
  type FlowDetailEdgeRoute,
  type FlowDetailNodePosition,
} from "./flow-detail-layout";
import {
  type Bounds,
  type ExpandedFlowMeasure,
  type InlineAnchor,
  type ProgressiveFlowNode,
  type LayoutNodePosition,
  type ScopeEntryEdge,
  type ScopeLayoutPosition,
  type ScopeNodePosition,
} from "./flowchart-layout";
import {
  flowLabel,
  flowPath,
  scopeNamesForFlow,
  type LogicChartAnnotationText,
  type LogicChartFlow,
  type LogicChartPayload,
} from "./logicchart-model";
import {
  createViewerLayout,
  isLogicChartFlow,
  viewerNodeKey,
  type FlowCallEdge,
  type ManualNodePosition,
  type RootNodePosition,
  type RootScopeEdge,
  type ViewerNodeKind,
} from "./viewer-layout";
import { useViewerStore } from "./viewer-store";
import type { SelectedConnection } from "./viewer-store";

type ActiveConnection = Exclude<SelectedConnection, null>;
type SvgStyleVars = CSSProperties & Record<`--${string}`, string>;

const BLANK_CANVAS_CLICK_THRESHOLD = 4;
const DETAIL_EDGE_OBSTACLE_GAP = 18;
const DETAIL_EDGE_LANE_STEP = 20;
const DETAIL_EDGE_MAX_LANE_STEPS = 12;
const DRAG_FRAME_FALLBACK_MS = 16;
const VIEWER_LAYOUT_CACHE_LIMIT = 8;

export interface DetailNodeSelection {
  flowId: string;
  nodeId: string;
  path?: string;
}

export interface DetailEdgeSelection {
  edgeId: string;
  flowId: string;
  source: string;
  target: string;
  path?: string;
}

type SelectedDetail =
  | ({ kind: "detail-node" } & DetailNodeSelection)
  | ({ kind: "detail-edge" } & DetailEdgeSelection);

type ScheduledFrame = {
  cancel: () => void;
};

export interface ViewerAppProps {
  scope: string;
  scopeNode?: ScopeNodePosition;
  payload?: LogicChartPayload;
  layers?: ProgressiveFlowNode[][];
  routeFlowIds?: string[];
  contextFlowIds?: string[];
  expandedScopes?: readonly string[];
  selectedConnection?: SelectedConnection;
  selectedRoot?: boolean;
  onConnectionSelect?: (connection: ActiveConnection) => void;
  onDetailEdgeSelect?: (selection: DetailEdgeSelection) => void;
  onDetailNodeSelect?: (selection: DetailNodeSelection) => void;
  onFlowSelect?: (flowId: string) => void;
  onRootSelect?: () => void;
  onSelectionClear?: () => void;
  onScopeSelect?: (scope: string) => void;
  resetToken?: number;
  selectedFlowId?: string | null;
  syncHash?: boolean;
  expandedMeasures?: ReadonlyMap<string, ExpandedFlowMeasure>;
  initialManualNodePositions?: ReadonlyMap<string, ManualNodePosition>;
  onManualNodePositionsChange?: (positions: ReadonlyMap<string, ManualNodePosition>) => void;
}

export function ViewerApp({
  scope,
  scopeNode,
  payload,
  layers,
  routeFlowIds = [],
  contextFlowIds = [],
  expandedScopes,
  selectedConnection: selectedConnectionProp,
  selectedRoot: selectedRootProp = false,
  onConnectionSelect,
  onDetailEdgeSelect,
  onDetailNodeSelect,
  onFlowSelect,
  onRootSelect,
  onSelectionClear,
  onScopeSelect,
  resetToken = 0,
  selectedFlowId: selectedFlowIdProp,
  syncHash = false,
  expandedMeasures: expandedMeasuresProp,
  initialManualNodePositions,
  onManualNodePositionsChange,
}: ViewerAppProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const blankCanvasGesture = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    moved: number;
  } | null>(null);
  const suppressClickForNode = useRef<string | null>(null);
  const nodeDragCleanup = useRef<(() => void) | null>(null);
  const manualPositionsChangeRef = useRef(onManualNodePositionsChange);
  const latestManualNodePositions = useRef(
    new Map(initialManualNodePositions ? [...initialManualNodePositions] : []),
  );
  const lastResetToken = useRef(resetToken);
  const [draggingNodeKey, setDraggingNodeKey] = useState<string | null>(null);
  const [manualNodePositions, setManualNodePositions] = useState<
    Map<string, ManualNodePosition>
  >(() => new Map(latestManualNodePositions.current));
  const selectedConnection = useViewerStore(state => state.selectedConnection);
  const setSelectedConnection = useViewerStore(state => state.setSelectedConnection);
  const clearSelection = useViewerStore(state => state.clearSelection);
  const [localSelection, setLocalSelection] = useState<SelectedConnection | undefined>(undefined);
  const [selectedDetail, setSelectedDetail] = useState<SelectedDetail | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null);
  const [selectedRoot, setSelectedRoot] = useState(false);
  const [selectedScopeId, setSelectedScopeId] = useState<string | null>(null);
  const selectedConnectionPropKey = selectionKey(selectedConnectionProp);
  const detailLayoutCache = useRef(new Map<string, Map<string, FlowDetailLayout>>());
  const layoutCache = useRef(new Map<string, ReturnType<typeof createViewerLayout>>());
  const findingCountsByFlowId = useMemo(() => {
    const counts = new Map<string, number>();
    (payload?.findings || []).forEach(finding => {
      if (!finding.flow_id) return;
      counts.set(finding.flow_id, (counts.get(finding.flow_id) || 0) + 1);
    });
    return counts;
  }, [payload]);
  useEffect(() => {
    manualPositionsChangeRef.current = onManualNodePositionsChange;
  }, [onManualNodePositionsChange]);
  useEffect(() => {
    setLocalSelection(undefined);
  }, [selectedConnectionPropKey]);
  useEffect(() => {
    if (selectedFlowIdProp === undefined) return;
    setSelectedFlowId(selectedFlowIdProp);
    if (!selectedFlowIdProp) return;
    clearSelection();
    setLocalSelection(null);
    setSelectedDetail(null);
    setSelectedRoot(false);
    setSelectedScopeId(null);
  }, [clearSelection, selectedFlowIdProp]);
  useEffect(() => {
    if (lastResetToken.current === resetToken) return;
    lastResetToken.current = resetToken;
    blankCanvasGesture.current = null;
    nodeDragCleanup.current?.();
    nodeDragCleanup.current = null;
    suppressClickForNode.current = null;
    setDraggingNodeKey(null);
    const resetPositions = new Map<string, ManualNodePosition>();
    latestManualNodePositions.current = resetPositions;
    setManualNodePositions(resetPositions);
    manualPositionsChangeRef.current?.(resetPositions);
    setSelectedDetail(null);
    setSelectedFlowId(null);
    setSelectedRoot(false);
    setSelectedScopeId(null);
  }, [resetToken]);
  useEffect(
    () => () => {
      nodeDragCleanup.current?.();
      nodeDragCleanup.current = null;
    },
    [],
  );
  // React's server renderer observes Zustand's initial server snapshot. Reading the
  // current store state here keeps static-render tests and future SSR exports honest
  // while preserving the live client subscription above.
  const currentSelection: SelectedConnection =
    localSelection !== undefined
      ? localSelection
      : selectedConnectionProp ??
        selectedConnection ??
        useViewerStore.getState().selectedConnection;
  const detailLayoutSignature = useMemo(
    () => [payloadSignature(payload), routeFlowIds.join("\u0000")].join("\u0001"),
    [payload, routeFlowIds],
  );
  const detailLayouts = useMemo(() => {
    const cached = detailLayoutCache.current.get(detailLayoutSignature);
    if (cached) {
      detailLayoutCache.current.delete(detailLayoutSignature);
      detailLayoutCache.current.set(detailLayoutSignature, cached);
      return cached;
    }
    const nextLayouts = flowDetailLayouts(payload, routeFlowIds);
    detailLayoutCache.current.set(detailLayoutSignature, nextLayouts);
    while (detailLayoutCache.current.size > VIEWER_LAYOUT_CACHE_LIMIT) {
      const oldestKey = detailLayoutCache.current.keys().next().value;
      if (oldestKey === undefined) break;
      detailLayoutCache.current.delete(oldestKey);
    }
    return nextLayouts;
  }, [detailLayoutSignature, payload, routeFlowIds]);
  const effectiveExpandedMeasures = useMemo(() => {
    if (!detailLayouts.size) return expandedMeasuresProp;
    const measures = new Map(expandedMeasuresProp ? [...expandedMeasuresProp] : []);
    detailLayouts.forEach((detail, flowId) => {
      measures.set(flowId, detail.measure);
    });
    return measures;
  }, [detailLayouts, expandedMeasuresProp]);
  const layoutSignature = useMemo(
    () =>
      [
        scope,
        scopeNode
          ? `${scopeNode.scope}:${scopeNode.x}:${scopeNode.y}:${scopeNode.width}:${scopeNode.height}`
          : "",
        expandedScopes === undefined ? "__auto__" : [...expandedScopes].join("\u0000"),
        routeFlowIds.join("\u0000"),
        contextFlowIds.join("\u0000"),
        layersSignature(layers),
        payloadSignature(payload),
        expandedMeasuresSignature(effectiveExpandedMeasures),
        manualNodePositionsSignature(manualNodePositions),
      ].join("\u0001"),
    [
      contextFlowIds,
      effectiveExpandedMeasures,
      expandedScopes,
      layers,
      manualNodePositions,
      payload,
      routeFlowIds,
      scope,
      scopeNode,
    ],
  );
  const viewportLayoutSignature = useMemo(
    () =>
      [
        scope,
        scopeNode
          ? `${scopeNode.scope}:${scopeNode.x}:${scopeNode.y}:${scopeNode.width}:${scopeNode.height}`
          : "",
        expandedScopes === undefined ? "__auto__" : [...expandedScopes].join("\u0000"),
        routeFlowIds.join("\u0000"),
        contextFlowIds.join("\u0000"),
        layersSignature(layers),
        payloadSignature(payload),
        expandedMeasuresSignature(effectiveExpandedMeasures),
      ].join("\u0001"),
    [
      contextFlowIds,
      effectiveExpandedMeasures,
      expandedScopes,
      layers,
      payload,
      routeFlowIds,
      scope,
      scopeNode,
    ],
  );
  const layout = useMemo(() => {
    const cached = layoutCache.current.get(layoutSignature);
    if (cached) {
      layoutCache.current.delete(layoutSignature);
      layoutCache.current.set(layoutSignature, cached);
      return cached;
    }
    const nextLayout = createViewerLayout({
        expandedMeasures: effectiveExpandedMeasures,
        expandedScopes,
        layers,
        manualNodePositions,
        payload,
        contextFlowIds,
        routeFlowIds,
        scope,
        scopeNode,
      });
    layoutCache.current.set(layoutSignature, nextLayout);
    while (layoutCache.current.size > VIEWER_LAYOUT_CACHE_LIMIT) {
      const oldestKey = layoutCache.current.keys().next().value;
      if (oldestKey === undefined) break;
      layoutCache.current.delete(oldestKey);
    }
    return nextLayout;
  }, [
    contextFlowIds,
    effectiveExpandedMeasures,
    expandedScopes,
    layers,
    layoutSignature,
    manualNodePositions,
    payload,
    routeFlowIds,
    scope,
    scopeNode,
  ]);
  const viewportSignature = useMemo(
    () =>
      [
        viewportLayoutSignature,
      ].join("\u0001"),
    [viewportLayoutSignature],
  );
  const {
    entryEdges,
    flowById,
    flowCallEdges,
    flowPositions,
    inlineAnchors,
    rootEdges,
    rootNode,
    scopeNodes,
  } = layout;
  const focusedFlowId = selectedFlowIdProp !== undefined ? selectedFlowIdProp : selectedFlowId;
  const focusedFlowViewBox = useMemo(
    () =>
      focusedFlowId
        ? viewBoxForFocusedFlow(focusedFlowId, flowPositions, inlineAnchors)
        : null,
    [flowPositions, focusedFlowId, inlineAnchors],
  );
  const stableViewBox = useRef<{
    focusedFlowId: string | null;
    signature: string;
    viewBox: typeof layout.viewBox;
  } | null>(null);
  if (!stableViewBox.current || stableViewBox.current.signature !== viewportSignature) {
    stableViewBox.current = {
      focusedFlowId,
      signature: viewportSignature,
      viewBox: focusedFlowViewBox ?? layout.viewBox,
    };
  } else if (
    focusedFlowId &&
    focusedFlowViewBox &&
    stableViewBox.current.focusedFlowId !== focusedFlowId
  ) {
    stableViewBox.current = {
      focusedFlowId,
      signature: viewportSignature,
      viewBox: focusedFlowViewBox,
    };
  }
  const viewBox = stableViewBox.current.viewBox;
  const viewMinX = viewBox.minX;
  const viewMinY = viewBox.minY;
  const viewMaxX = viewBox.maxX;
  const viewMaxY = viewBox.maxY;
  const width = Math.max(900, viewMaxX - viewMinX);
  const height = Math.max(640, viewMaxY - viewMinY);
  const scopeToneStyles = useMemo(
    () => scopeToneStyleMap(scopeNodes.map(item => item.scope)),
    [scopeNodes],
  );
  const hasConnectionSelection = currentSelection !== null;
  const hasScopeSelection = currentSelection === null && selectedScopeId !== null;
  const selectedFlowNeighborhood = useMemo(
    () =>
      selectedFlowId
        ? flowNeighborhood(selectedFlowId, flowCallEdges, entryEdges)
        : null,
    [entryEdges, flowCallEdges, selectedFlowId],
  );
  const hasFlowSelection = currentSelection === null && selectedFlowNeighborhood !== null;
  const hasRootSelection = currentSelection === null && (selectedRootProp || selectedRoot);
  const hasDetailSelection = currentSelection === null && selectedDetail !== null;
  const selectedDetailScopeIds = useMemo(() => {
    if (!selectedDetail) return new Set<string>();
    const flow = flowById.get(selectedDetail.flowId);
    return flow && isLogicChartFlow(flow)
      ? new Set(scopeNamesForFlow(asLogicChartFlow(flow)))
      : new Set<string>();
  }, [flowById, selectedDetail]);
  const selectedScopeEntryTargets = useMemo(
    () =>
      selectedScopeId
        ? new Set(
            entryEdges
              .filter(edge => edge.scope === selectedScopeId)
              .map(edge => edge.target),
          )
        : new Set<string>(),
    [entryEdges, selectedScopeId],
  );
  const selectedScopeConnectedFlowIds = useMemo(() => {
    if (!selectedScopeId) return new Set<string>();
    return connectedFlowIdsFromSeeds(selectedScopeEntryTargets, flowCallEdges);
  }, [flowCallEdges, selectedScopeEntryTargets, selectedScopeId]);
  const hasAnySelection =
    hasConnectionSelection ||
    hasFlowSelection ||
    hasRootSelection ||
    hasScopeSelection ||
    hasDetailSelection;
  const clearCurrentSelection = useCallback(() => {
    clearSelection();
    setLocalSelection(null);
    setSelectedDetail(null);
    setSelectedFlowId(null);
    setSelectedRoot(false);
    setSelectedScopeId(null);
    onSelectionClear?.();
    if (!onSelectionClear && syncHash) setLocationHash(hashForScope(scope));
  }, [clearSelection, onSelectionClear, scope, syncHash]);
  const selectRoot = useCallback(() => {
    clearSelection();
    setLocalSelection(null);
    setSelectedDetail(null);
    setSelectedFlowId(null);
    setSelectedRoot(true);
    setSelectedScopeId(null);
    onRootSelect?.();
    if (!onRootSelect && syncHash) setLocationHash(hashForRootNode());
  }, [clearSelection, onRootSelect, syncHash]);
  const selectFlow = useCallback(
    (flowId: string) => {
      clearSelection();
      setLocalSelection(null);
      setSelectedDetail(null);
      setSelectedFlowId(flowId);
      setSelectedRoot(false);
      setSelectedScopeId(null);
      onFlowSelect?.(flowId);
      if (syncHash) setLocationHash(hashForFlow(flowId));
    },
    [clearSelection, onFlowSelect, syncHash],
  );
  const selectScope = useCallback(
    (nextScope: string) => {
      clearSelection();
      setLocalSelection(null);
      setSelectedDetail(null);
      setSelectedFlowId(null);
      setSelectedRoot(false);
      setSelectedScopeId(nextScope);
      onScopeSelect?.(nextScope);
      if (syncHash) setLocationHash(hashForScope(nextScope));
    },
    [clearSelection, onScopeSelect, syncHash],
  );
  const beginNodeDrag = useCallback(
    (
      event: ReactPointerEvent<SVGGElement>,
      kind: ViewerNodeKind,
      id: string,
      position: ManualNodePosition,
    ) => {
      if (event.button !== 0) return;
      const svg = svgRef.current;
      const viewBox = svg ? readSvgViewBox(svg) : null;
      if (!svg || !viewBox) return;

      event.stopPropagation();
      event.preventDefault();
      const nodeKey = viewerNodeKey(kind, id);
      const pointerId = event.pointerId;
      const startClientX = event.clientX;
      const startClientY = event.clientY;
      const startSvg = clientPointToSvgPoint(svg, viewBox, startClientX, startClientY);
      let moved = 0;
      let active = true;
      const target = event.currentTarget;
      let lastMoveEvent: PointerEvent | null = null;
      let pendingPositions: Map<string, ManualNodePosition> | null = null;
      let dragFrame: ScheduledFrame | null = null;

      const commitPendingPositions = () => {
        if (!pendingPositions) return;
        const nextPositions = pendingPositions;
        pendingPositions = null;
        latestManualNodePositions.current = nextPositions;
        setManualNodePositions(nextPositions);
      };
      const schedulePositionCommit = (nextPositions: Map<string, ManualNodePosition>) => {
        pendingPositions = nextPositions;
        if (dragFrame) return;
        dragFrame = scheduleFrame(() => {
          dragFrame = null;
          commitPendingPositions();
        });
      };

      const cleanup = () => {
        active = false;
        if (dragFrame) {
          dragFrame.cancel();
          dragFrame = null;
        }
        pendingPositions = null;
        window.removeEventListener("pointermove", handlePointerMove, true);
        window.removeEventListener("pointerup", handlePointerEnd, true);
        window.removeEventListener("pointercancel", handlePointerEnd, true);
        window.removeEventListener("mouseup", handlePointerAbort, true);
        window.removeEventListener("blur", handlePointerAbort, true);
        document.removeEventListener("pointermove", handlePointerMove, true);
        document.removeEventListener("pointerup", handlePointerEnd, true);
        document.removeEventListener("pointercancel", handlePointerEnd, true);
        document.removeEventListener("mouseup", handlePointerAbort, true);
        document.removeEventListener("visibilitychange", handleVisibilityChange, true);
        target.removeEventListener("lostpointercapture", handlePointerEnd as EventListener);
        if (nodeDragCleanup.current === cleanup) nodeDragCleanup.current = null;
      };
      const queuePositionFromPointer = (pointerEvent: PointerEvent) => {
        if (!active || pointerEvent.pointerId !== pointerId) return;
        if (pointerEvent === lastMoveEvent) return;
        lastMoveEvent = pointerEvent;
        const dx = pointerEvent.clientX - startClientX;
        const dy = pointerEvent.clientY - startClientY;
        const currentSvg = clientPointToSvgPoint(
          svg,
          viewBox,
          pointerEvent.clientX,
          pointerEvent.clientY,
        );
        moved = Math.max(moved, Math.abs(dx) + Math.abs(dy));
        const nextPositions = new Map(latestManualNodePositions.current);
        nextPositions.set(nodeKey, {
          x: position.x + currentSvg.x - startSvg.x,
          y: position.y + currentSvg.y - startSvg.y,
        });
        schedulePositionCommit(nextPositions);
      };
      const handlePointerMove = (pointerEvent: PointerEvent) => {
        queuePositionFromPointer(pointerEvent);
        pointerEvent.preventDefault();
      };
      const handlePointerEnd = (pointerEvent: PointerEvent) => {
        if (pointerEvent.pointerId !== pointerId) return;
        queuePositionFromPointer(pointerEvent);
        finishDrag(pointerEvent);
      };
      const handlePointerAbort = (pointerEvent: Event) => {
        finishDrag(pointerEvent);
      };
      const handleVisibilityChange = () => {
        if (document.visibilityState === "hidden") finishDrag();
      };
      const finishDrag = (pointerEvent?: Event) => {
        if (!active) return;
        commitPendingPositions();
        cleanup();
        setDraggingNodeKey(null);
        if (moved > 4) suppressClickForNode.current = nodeKey;
        manualPositionsChangeRef.current?.(latestManualNodePositions.current);
        try {
          target.releasePointerCapture(pointerId);
        } catch {
          // Embedded renderers and tests may not expose pointer capture.
        }
        pointerEvent?.preventDefault();
      };

      nodeDragCleanup.current?.();
      nodeDragCleanup.current = cleanup;
      setDraggingNodeKey(nodeKey);
      window.addEventListener("pointermove", handlePointerMove, true);
      window.addEventListener("pointerup", handlePointerEnd, true);
      window.addEventListener("pointercancel", handlePointerEnd, true);
      window.addEventListener("mouseup", handlePointerAbort, true);
      window.addEventListener("blur", handlePointerAbort, true);
      document.addEventListener("pointermove", handlePointerMove, true);
      document.addEventListener("pointerup", handlePointerEnd, true);
      document.addEventListener("pointercancel", handlePointerEnd, true);
      document.addEventListener("mouseup", handlePointerAbort, true);
      document.addEventListener("visibilitychange", handleVisibilityChange, true);
      target.addEventListener("lostpointercapture", handlePointerEnd as EventListener);
      try {
        target.setPointerCapture(pointerId);
      } catch {
        // Embedded renderers and tests may not expose pointer capture.
      }
    },
    [],
  );
  const beginBlankCanvasGesture = useCallback((event: ReactPointerEvent<SVGElement>) => {
    if (event.button !== 0) return;
    if (event.currentTarget === svgRef.current && event.target !== event.currentTarget) return;
    blankCanvasGesture.current = {
      moved: 0,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
    };
  }, []);
  const updateBlankCanvasGesture = useCallback((event: ReactPointerEvent<SVGElement>) => {
    const gesture = blankCanvasGesture.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const dx = event.clientX - gesture.startX;
    const dy = event.clientY - gesture.startY;
    gesture.moved = Math.max(gesture.moved, Math.abs(dx) + Math.abs(dy));
  }, []);
  const finishBlankCanvasGesture = useCallback(
    (event: ReactPointerEvent<SVGElement>) => {
      const gesture = blankCanvasGesture.current;
      if (!gesture || gesture.pointerId !== event.pointerId) return;
      blankCanvasGesture.current = null;
      const dx = event.clientX - gesture.startX;
      const dy = event.clientY - gesture.startY;
      const moved = Math.max(gesture.moved, Math.abs(dx) + Math.abs(dy));
      if (moved <= BLANK_CANVAS_CLICK_THRESHOLD) clearCurrentSelection();
    },
    [clearCurrentSelection],
  );
  const cancelBlankCanvasGesture = useCallback((event: ReactPointerEvent<SVGElement>) => {
    const gesture = blankCanvasGesture.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    blankCanvasGesture.current = null;
  }, []);
  const consumeSuppressedNodeClick = useCallback((kind: ViewerNodeKind, id: string): boolean => {
    const nodeKey = viewerNodeKey(kind, id);
    if (suppressClickForNode.current !== nodeKey) return false;
    suppressClickForNode.current = null;
    return true;
  }, []);
  const selectDetailNode = useCallback(
    (flowId: string, node: FlowDetailNodePosition) => {
      const selection: SelectedDetail = {
        flowId,
        kind: "detail-node",
        nodeId: node.id,
        path: node.node.location?.path,
      };
      clearSelection();
      setLocalSelection(null);
      setSelectedDetail(selection);
      setSelectedFlowId(null);
      setSelectedRoot(false);
      setSelectedScopeId(null);
      onDetailNodeSelect?.({
        flowId,
        nodeId: node.id,
        path: node.node.location?.path,
      });
    },
    [clearSelection, onDetailNodeSelect],
  );
  const selectDetailEdge = useCallback(
    (
      flowId: string,
      route: FlowDetailEdgeRoute,
      targetNode: FlowDetailNodePosition | undefined,
    ) => {
      const edgeId = detailEdgeId(route);
      const selection: SelectedDetail = {
        edgeId,
        flowId,
        kind: "detail-edge",
        path: targetNode?.node.location?.path,
        source: route.edge.source,
        target: route.edge.target,
      };
      clearSelection();
      setLocalSelection(null);
      setSelectedDetail(selection);
      setSelectedFlowId(null);
      setSelectedRoot(false);
      setSelectedScopeId(null);
      onDetailEdgeSelect?.({
        edgeId,
        flowId,
        path: targetNode?.node.location?.path,
        source: route.edge.source,
        target: route.edge.target,
      });
    },
    [clearSelection, onDetailEdgeSelect],
  );
  const selectFlowCallEdge = useCallback(
    (edge: FlowCallEdge) => {
      const connection: ActiveConnection = {
        kind: "flow-call",
        source: edge.source,
        target: edge.target,
      };
      setSelectedConnection(connection);
      setLocalSelection(connection);
      setSelectedDetail(null);
      setSelectedFlowId(null);
      setSelectedRoot(false);
      setSelectedScopeId(null);
      onConnectionSelect?.(connection);
      if (!onConnectionSelect && syncHash) setLocationHash(hashForConnection(connection));
    },
    [onConnectionSelect, setSelectedConnection, syncHash],
  );
  const selectRootScopeEdge = useCallback(
    (edge: RootScopeEdge) => {
      const connection: ActiveConnection = {
        kind: "root-scope",
        scope: edge.scope,
      };
      setSelectedConnection(connection);
      setLocalSelection(connection);
      setSelectedDetail(null);
      setSelectedFlowId(null);
      setSelectedRoot(false);
      setSelectedScopeId(null);
      onConnectionSelect?.(connection);
      if (!onConnectionSelect && syncHash) setLocationHash(hashForConnection(connection));
    },
    [onConnectionSelect, setSelectedConnection, syncHash],
  );

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    svg.dataset.interactive = "true";

    const handleEdgePress = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const edge = target.closest<SVGElement>(
        ".root-scope-hit, .root-scope-link, .edge-hit-path, .scope-entry-link, .flow-call-link, .flow-call-hit",
      );
      if (edge && svg.contains(edge)) {
        const targetScope = edge.getAttribute("data-target-scope");
        if (targetScope) {
          event.stopPropagation();
          const connection: ActiveConnection = {
            kind: "root-scope",
            scope: targetScope,
          };
          setSelectedConnection(connection);
          setLocalSelection(connection);
          setSelectedDetail(null);
          setSelectedFlowId(null);
          setSelectedRoot(false);
          setSelectedScopeId(null);
          onConnectionSelect?.(connection);
          if (!onConnectionSelect && syncHash) {
            setLocationHash(edge.getAttribute("data-edge-href") || hashForConnection(connection));
          }
          return;
        }
        const sourceScope = edge.getAttribute("data-source-scope");
        const targetFlowId = edge.getAttribute("data-target-flow-id");
        if (sourceScope && targetFlowId) {
          event.stopPropagation();
          setSelectedConnection({
            kind: "scope-entry",
            scope: sourceScope,
            target: targetFlowId,
          });
          const connection: ActiveConnection = {
            kind: "scope-entry",
            scope: sourceScope,
            target: targetFlowId,
          };
          setLocalSelection(connection);
          setSelectedDetail(null);
          setSelectedFlowId(null);
          setSelectedRoot(false);
          setSelectedScopeId(null);
          onConnectionSelect?.(connection);
          if (!onConnectionSelect && syncHash) {
            setLocationHash(edge.getAttribute("data-edge-href") || hashForConnection(connection));
          }
        }
        const sourceFlowId = edge.getAttribute("data-source-flow-id");
        const calledFlowId = edge.getAttribute("data-called-flow-id");
        if (sourceFlowId && calledFlowId) {
          event.stopPropagation();
          const connection: ActiveConnection = {
            kind: "flow-call",
            source: sourceFlowId,
            target: calledFlowId,
          };
          setSelectedConnection(connection);
          setLocalSelection(connection);
          setSelectedDetail(null);
          setSelectedFlowId(null);
          setSelectedRoot(false);
          setSelectedScopeId(null);
          onConnectionSelect?.(connection);
          if (!onConnectionSelect && syncHash) {
            setLocationHash(edge.getAttribute("data-edge-href") || hashForConnection(connection));
          }
        }
        return;
      }
    };

    svg.addEventListener("pointerdown", handleEdgePress);
    svg.addEventListener("mousedown", handleEdgePress);
    return () => {
      delete svg.dataset.interactive;
      svg.removeEventListener("pointerdown", handleEdgePress);
      svg.removeEventListener("mousedown", handleEdgePress);
    };
  }, [onConnectionSelect, setSelectedConnection, syncHash]);

  return (
    <svg
      aria-label="LogicChart progressive flowchart"
      className="logicchart-viewer"
      data-selected-kind={
        currentSelection?.kind ??
        (hasRootSelection
          ? "root"
          : hasScopeSelection
            ? "scope"
            : hasFlowSelection
              ? "flow"
              : selectedDetail?.kind === "detail-edge"
                ? "detail-edge"
                : selectedDetail?.kind === "detail-node"
                  ? "detail-node"
              : "none")
      }
      ref={svgRef}
      role="img"
      viewBox={`${viewMinX} ${viewMinY} ${width} ${height}`}
      onPointerCancel={cancelBlankCanvasGesture}
      onPointerDown={beginBlankCanvasGesture}
      onPointerMove={updateBlankCanvasGesture}
      onPointerUp={finishBlankCanvasGesture}
    >
      <defs>
        <filter id="typedNodeShadow" x="-18%" y="-28%" width="136%" height="156%">
          <feDropShadow dx="0" dy="8" stdDeviation="10" floodOpacity=".18" />
        </filter>
        <filter id="typedNodeLift" x="-20%" y="-30%" width="140%" height="160%">
          <feDropShadow dx="0" dy="12" stdDeviation="14" floodOpacity=".24" />
        </filter>
        <marker
          id="typedArrow"
          markerHeight="6.5"
          markerWidth="6.5"
          orient="auto"
          refX="5.7"
          refY="3.25"
          viewBox="0 0 6.5 6.5"
        >
          <path className="typed-arrow" d="M 0 0 L 6.5 3.25 L 0 6.5 z" />
        </marker>
        <marker
          id="typedArrowFocus"
          markerHeight="6.5"
          markerWidth="6.5"
          orient="auto"
          refX="5.7"
          refY="3.25"
          viewBox="0 0 6.5 6.5"
        >
          <path className="typed-arrow-focus" d="M 0 0 L 6.5 3.25 L 0 6.5 z" />
        </marker>
      </defs>
      <rect
        aria-hidden="true"
        className="canvas-hit-zone"
        height={height}
        width={width}
        x={viewMinX}
        y={viewMinY}
        onPointerDown={beginBlankCanvasGesture}
      />
      <g className="root-scope-edges">
        {rootEdges.map(edge => {
          const selected =
            currentSelection?.kind === "root-scope" && currentSelection.scope === edge.scope;
          const incident =
            hasRootSelection ||
            (hasScopeSelection && selectedScopeId === edge.scope) ||
            (hasFlowSelection &&
              (selectedFlowNeighborhood?.scopeIds.has(edge.scope) ?? false)) ||
            (hasDetailSelection && selectedDetailScopeIds.has(edge.scope));
          const dimmed =
            (hasConnectionSelection && !selected) ||
            (hasFlowSelection && !incident) ||
            (hasScopeSelection && !incident) ||
            (hasDetailSelection && !incident);
          const edgeHref = hashForConnection({
            kind: "root-scope",
            scope: edge.scope,
          });
          const edgeClassName = [
            "edge",
            "root-scope-link",
            selected ? "selected-link" : "",
            incident && !selected ? "incident" : "",
            dimmed ? "dimmed" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const selectEdge = () => selectRootScopeEdge(edge);
          return (
            <g
              aria-label={`codebase link to ${edge.scope}`}
              className="root-scope-edge-group"
              data-target-scope={edge.scope}
              data-edge-href={edgeHref}
              key={`codebase:${edge.scope}`}
              role="button"
              tabIndex={0}
              onClick={event => {
                event.stopPropagation();
                selectEdge();
              }}
              onKeyDown={event => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  selectEdge();
                }
              }}
              onPointerDown={event => {
                event.stopPropagation();
                selectEdge();
              }}
              onMouseDown={event => {
                event.stopPropagation();
                selectEdge();
              }}
            >
              <path
                aria-hidden="true"
                className="root-scope-hit"
                d={edge.d}
                data-target-scope={edge.scope}
                data-edge-href={edgeHref}
                vectorEffect="non-scaling-stroke"
              />
              <path
                className={edgeClassName}
                d={edge.d}
                data-target-scope={edge.scope}
                data-edge-href={edgeHref}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </g>
      <g className="root-node">
        <RootNode
          currentSelection={currentSelection}
          draggingNodeKey={draggingNodeKey}
          hasSelection={hasAnySelection}
          item={rootNode}
          onDragStart={beginNodeDrag}
          onSelect={selectRoot}
          selected={hasRootSelection}
          selectedByScope={hasScopeSelection}
          selectedByFlow={
            (selectedFlowNeighborhood?.scopeIds.size ?? 0) > 0 || hasDetailSelection
          }
          suppressNodeClick={consumeSuppressedNodeClick}
        />
      </g>
      <g className="scope-nodes">
        {scopeNodes.map(item => (
          <ScopeNode
            annotation={payload?.annotations?.scopes?.[item.scope]}
            currentSelection={currentSelection}
            draggingNodeKey={draggingNodeKey}
            hasRootSelection={hasRootSelection}
            hasSelection={hasAnySelection}
            item={item}
            onDragStart={beginNodeDrag}
            key={item.scope}
            onSelect={selectScope}
            selected={hasScopeSelection && selectedScopeId === item.scope}
            selectedByFlow={
              (selectedFlowNeighborhood?.scopeIds.has(item.scope) ?? false) ||
              selectedDetailScopeIds.has(item.scope)
            }
            suppressNodeClick={consumeSuppressedNodeClick}
            toneStyle={scopeToneStyles.get(item.scope)}
          />
        ))}
      </g>
      <g className="scope-entry-edges">
        {entryEdges.map(edge => {
          const selected =
            currentSelection?.kind === "scope-entry" &&
            currentSelection.scope === edge.scope &&
            currentSelection.target === edge.target;
          const incidentToFlow =
            hasFlowSelection &&
            (selectedFlowNeighborhood?.scopeEntryTargets.has(edge.target) ?? false);
          const incidentToScope = hasScopeSelection && selectedScopeId === edge.scope;
          const incidentToDetail = hasDetailSelection && selectedDetail?.flowId === edge.target;
          const dimmed =
            (hasConnectionSelection && !selected) ||
            (hasFlowSelection && !incidentToFlow) ||
            (hasScopeSelection && !incidentToScope) ||
            (hasDetailSelection && !incidentToDetail);
          const connection: ActiveConnection = {
            kind: "scope-entry",
            scope: edge.scope,
            target: edge.target,
          };
          const edgeHref = hashForConnection(connection);
          const selectEdge = () => {
            setSelectedConnection(connection);
            setLocalSelection(connection);
            setSelectedDetail(null);
            setSelectedFlowId(null);
            setSelectedRoot(false);
            setSelectedScopeId(null);
            onConnectionSelect?.(connection);
            if (!onConnectionSelect && syncHash) setLocationHash(edgeHref);
          };
          return (
            <a
              aria-label={`entry link from ${edge.scope} to ${edge.target}`}
              className="edge-link-group"
              data-source-scope={edge.scope}
              data-target-flow-id={edge.target}
              data-edge-href={edgeHref}
              href={edgeHref}
              key={`${edge.scope}:${edge.target}`}
              tabIndex={0}
              onClick={event => {
                event.preventDefault();
                selectEdge();
              }}
              onKeyDown={event => {
                if (event.key === " ") {
                  event.preventDefault();
                  selectEdge();
                }
              }}
            >
              <path
                aria-hidden="true"
                className="edge-hit-path"
                d={edge.d}
                data-source-scope={edge.scope}
                data-target-flow-id={edge.target}
                data-edge-href={edgeHref}
                vectorEffect="non-scaling-stroke"
                onClick={event => {
                  event.stopPropagation();
                  selectEdge();
                }}
                onPointerDown={event => {
                  event.stopPropagation();
                  selectEdge();
                }}
                onMouseDown={event => {
                  event.stopPropagation();
                  selectEdge();
                }}
              />
              <path
                className={[
                  "edge",
                  "scope-entry-link",
                  selected ? "selected-link" : "",
                  (incidentToFlow || incidentToScope || incidentToDetail) && !selected
                    ? "incident"
                    : "",
                  dimmed ? "dimmed" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                d={edge.d}
                data-source-scope={edge.scope}
                data-target-flow-id={edge.target}
                data-edge-href={edgeHref}
                vectorEffect="non-scaling-stroke"
                onClick={event => {
                  event.stopPropagation();
                  selectEdge();
                }}
                onPointerDown={event => {
                  event.stopPropagation();
                  selectEdge();
                }}
                onMouseDown={event => {
                  event.stopPropagation();
                  selectEdge();
                }}
              />
            </a>
          );
        })}
      </g>
      <g className="flow-call-edges">
        {flowCallEdges.map(edge => {
          const selected =
            currentSelection?.kind === "flow-call" &&
            currentSelection.source === edge.source &&
            currentSelection.target === edge.target;
          const incident =
            (currentSelection?.kind === "flow-call" &&
              (currentSelection.source === edge.source ||
                currentSelection.source === edge.target ||
                currentSelection.target === edge.source ||
                currentSelection.target === edge.target)) ||
            (hasFlowSelection &&
              ((selectedFlowNeighborhood?.flowIds.has(edge.source) ?? false) ||
                (selectedFlowNeighborhood?.flowIds.has(edge.target) ?? false))) ||
            (hasScopeSelection &&
              (selectedScopeConnectedFlowIds.has(edge.source) ||
                selectedScopeConnectedFlowIds.has(edge.target))) ||
            (hasDetailSelection &&
              (selectedDetail?.flowId === edge.source || selectedDetail?.flowId === edge.target));
          const dimmed =
            (hasConnectionSelection && !selected && !incident) ||
            (hasFlowSelection && !incident) ||
            hasRootSelection ||
            (hasScopeSelection && !incident) ||
            (hasDetailSelection && !incident);
          const edgeHref = hashForConnection({
            kind: "flow-call",
            source: edge.source,
            target: edge.target,
          });
          const edgeClassName = [
            "edge",
            "flow-call-link",
            selected ? "selected-link" : "",
            incident && !selected ? "incident" : "",
            dimmed ? "dimmed" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const selectEdge = () => selectFlowCallEdge(edge);
          return (
            <g
              aria-label={`call link from ${edge.source} to ${edge.target}`}
              className="flow-call-edge-group"
              data-source-flow-id={edge.source}
              data-called-flow-id={edge.target}
              data-edge-href={edgeHref}
              key={`${edge.source}:${edge.target}`}
              role="button"
              tabIndex={0}
              onClick={event => {
                event.stopPropagation();
                selectEdge();
              }}
              onKeyDown={event => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  selectEdge();
                }
              }}
              onPointerDown={event => {
                event.stopPropagation();
                selectEdge();
              }}
              onMouseDown={event => {
                event.stopPropagation();
                selectEdge();
              }}
            >
              <path
                aria-hidden="true"
                className="flow-call-hit"
                d={edge.d}
                data-source-flow-id={edge.source}
                data-called-flow-id={edge.target}
                data-edge-href={edgeHref}
                vectorEffect="non-scaling-stroke"
              />
              <path
                className={edgeClassName}
                d={edge.d}
                data-source-flow-id={edge.source}
                data-called-flow-id={edge.target}
                data-edge-href={edgeHref}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </g>
      <g className="flow-details">
        {inlineAnchors.map(anchor => {
          const detail = detailLayouts.get(anchor.flowId);
          if (!detail) return null;
          return (
            <FlowDetail
              annotations={payload?.annotations?.nodes}
              detail={detail}
              draggingNodeKey={draggingNodeKey}
              manualNodePositions={manualNodePositions}
              onDragStart={beginNodeDrag}
              onEdgeSelect={selectDetailEdge}
              onNodeSelect={selectDetailNode}
              selectedDetail={selectedDetail}
              suppressNodeClick={consumeSuppressedNodeClick}
              topLevelDimmed={
                hasRootSelection ||
                (hasScopeSelection && !selectedScopeConnectedFlowIds.has(anchor.flowId)) ||
                (hasDetailSelection && selectedDetail?.flowId !== anchor.flowId)
              }
              anchorX={anchor.x}
              anchorY={anchor.y}
              key={anchor.flowId}
              flowId={anchor.flowId}
            />
          );
        })}
      </g>
      <g className="flow-nodes">
        {[...flowPositions.values()].map(position => {
          const flow = flowById.get(position.id);
          const flowAnnotation = payload?.annotations?.flows?.[position.id];
          const flowFindingCount =
            flow && isLogicChartFlow(flow) ? findingCountsByFlowId.get(flow.id) || 0 : 0;
          const flowSummary =
            flow && isLogicChartFlow(flow)
              ? flowAccessibilitySummary(
                  asLogicChartFlow(flow),
                  flowFindingCount,
                  flowAnnotation,
                )
              : position.id;
          const flowTitle = annotationTitle(flowSummary, flowAnnotation);
          const flowOpen = routeFlowIds.includes(position.id);
          const targetSelected =
            currentSelection?.kind === "scope-entry" &&
            currentSelection.target === position.id;
          const callSourceSelected =
            currentSelection?.kind === "flow-call" &&
            currentSelection.source === position.id;
          const callTargetSelected =
            currentSelection?.kind === "flow-call" &&
            currentSelection.target === position.id;
          const flowSelected = hasFlowSelection && selectedFlowId === position.id;
          const flowConnected =
            hasFlowSelection &&
            (selectedFlowNeighborhood?.flowIds.has(position.id) ?? false);
          const scopeConnected =
            hasScopeSelection && selectedScopeConnectedFlowIds.has(position.id);
          const detailHostSelected =
            hasDetailSelection && selectedDetail?.flowId === position.id;
          const flowClassName = [
            "node",
            "flow-node",
            "movable",
            flowKindClass(flow),
            flowOpen ? "flow-open" : "",
            flowSelected ? "selected" : "",
            detailHostSelected ? "edge-source" : "",
            targetSelected || callTargetSelected ? "edge-target" : "",
            callSourceSelected ? "edge-source" : "",
            flowConnected && !flowSelected ? "edge-target" : "",
            scopeConnected ? "edge-target" : "",
            hasConnectionSelection && !targetSelected && !callSourceSelected && !callTargetSelected
              ? "dimmed"
              : "",
            hasFlowSelection && !flowSelected && !flowConnected
              ? "dimmed"
              : "",
            hasRootSelection ? "dimmed" : "",
            hasScopeSelection && !scopeConnected ? "dimmed" : "",
            hasDetailSelection && !detailHostSelected ? "dimmed" : "",
            draggingNodeKey === viewerNodeKey("flow", position.id) ? "dragging" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <g
              aria-label={flowSummary}
              className={flowClassName}
              data-annotation-label={flowAnnotation?.label}
              data-flow-id={position.id}
              data-flow-summary={flowSummary}
              key={position.id}
              role="button"
              tabIndex={0}
              transform={`translate(${position.x} ${position.y})`}
              onClick={event => {
                event.stopPropagation();
                if (consumeSuppressedNodeClick("flow", position.id)) return;
                selectFlow(position.id);
              }}
              onKeyDown={event => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  selectFlow(position.id);
                }
              }}
              onPointerDown={event =>
                beginNodeDrag(event, "flow", position.id, {
                  x: position.x,
                  y: position.y,
                })
              }
            >
              <rect
                className="shape"
                height={position.height}
                rx="32"
                vectorEffect="non-scaling-stroke"
                width={position.width}
                x={-position.width / 2}
                y={-position.height / 2}
              />
              <text textAnchor="middle">
                {flow ? displayFlowLabel(asLogicChartFlow(flow), flowAnnotation) : position.id}
              </text>
              {flow ? (
                <text className="meta" textAnchor="middle" y="22">
                  {flowMeta(flow).join(" · ")}
                </text>
              ) : null}
              {flow && flowPath(flow) ? (
                <title>{flowTitle}</title>
              ) : null}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

function RootNode({
  currentSelection,
  draggingNodeKey,
  hasSelection,
  item,
  onDragStart,
  onSelect,
  selected,
  selectedByScope,
  selectedByFlow,
  suppressNodeClick,
}: {
  currentSelection: SelectedConnection;
  draggingNodeKey: string | null;
  hasSelection: boolean;
  item: RootNodePosition;
  onDragStart: (
    event: ReactPointerEvent<SVGGElement>,
    kind: ViewerNodeKind,
    id: string,
    position: ManualNodePosition,
  ) => void;
  onSelect: () => void;
  selected: boolean;
  selectedByScope: boolean;
  selectedByFlow: boolean;
  suppressNodeClick: (kind: ViewerNodeKind, id: string) => boolean;
}) {
  const isEdgeSource = currentSelection?.kind === "root-scope";
  const dimmed =
    hasSelection && !selected && !isEdgeSource && !selectedByFlow && !selectedByScope;
  const className = [
    "node",
    "entry",
    "root-node",
    "movable",
    selected ? "selected" : "",
    isEdgeSource || selectedByFlow || selectedByScope ? "edge-source" : "",
    dimmed ? "dimmed" : "",
    draggingNodeKey === viewerNodeKey("root", item.id) ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <g
      className={className}
      data-root-id={item.id}
      role="button"
      tabIndex={0}
      transform={`translate(${item.x} ${item.y})`}
      onClick={event => {
        event.stopPropagation();
        if (suppressNodeClick("root", item.id)) return;
        onSelect();
      }}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      onPointerDown={event =>
        onDragStart(event, "root", item.id, {
          x: item.x,
          y: item.y,
        })
      }
    >
      <rect
        className="shape"
        height={item.height}
        rx="32"
        vectorEffect="non-scaling-stroke"
        width={item.width}
        x={-item.width / 2}
        y={-item.height / 2}
      />
      <text textAnchor="middle">{item.label}</text>
      <text className="meta" textAnchor="middle" y="24">
        {item.scopeCount} scopes · {item.flowCount} flows
      </text>
    </g>
  );
}

function ScopeNode({
  annotation,
  currentSelection,
  draggingNodeKey,
  hasRootSelection,
  hasSelection,
  item,
  onDragStart,
  onSelect,
  selected,
  selectedByFlow,
  suppressNodeClick,
  toneStyle,
}: {
  annotation?: LogicChartAnnotationText;
  currentSelection: SelectedConnection;
  draggingNodeKey: string | null;
  hasRootSelection: boolean;
  hasSelection: boolean;
  item: ScopeLayoutPosition;
  onDragStart: (
    event: ReactPointerEvent<SVGGElement>,
    kind: ViewerNodeKind,
    id: string,
    position: ManualNodePosition,
  ) => void;
  onSelect: (scope: string) => void;
  selected: boolean;
  selectedByFlow: boolean;
  suppressNodeClick: (kind: ViewerNodeKind, id: string) => boolean;
  toneStyle?: SvgStyleVars;
}) {
  const isEdgeSource =
    currentSelection?.kind === "scope-entry" && currentSelection.scope === item.scope;
  const isRootTarget =
    currentSelection?.kind === "root-scope" && currentSelection.scope === item.scope;
  const dimmed =
    hasSelection && !selected && !isEdgeSource && !isRootTarget && !selectedByFlow && !hasRootSelection;
  const className = [
    "node",
    "entry",
    "scope-node",
    "movable",
    item.expanded ? "expanded" : "",
    selected ? "selected" : "",
    isEdgeSource || selectedByFlow ? "edge-source" : "",
    isRootTarget || hasRootSelection ? "edge-target" : "",
    dimmed ? "dimmed" : "",
    draggingNodeKey === viewerNodeKey("scope", item.scope) ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const label = displayScopeLabel(item.scope, annotation);
  const baseTitle = `${label} · ${plural(item.flowCount, "flow")}`;
  const title = annotationTitle(baseTitle, annotation);

  return (
    <g
      aria-label={title}
      className={className}
      data-annotation-label={annotation?.label}
      data-scope={item.scope}
      role="button"
      style={toneStyle}
      tabIndex={0}
      transform={`translate(${item.x} ${item.y})`}
      onClick={event => {
        event.stopPropagation();
        if (suppressNodeClick("scope", item.scope)) return;
        onSelect(item.scope);
      }}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(item.scope);
        }
      }}
      onPointerDown={event =>
        onDragStart(event, "scope", item.scope, {
          x: item.x,
          y: item.y,
        })
      }
    >
      <rect
        className="shape"
        height={item.height}
        rx="32"
        vectorEffect="non-scaling-stroke"
        width={item.width}
        x={-item.width / 2}
        y={-item.height / 2}
      />
      <title>{title}</title>
      <text textAnchor="middle">{label}</text>
      <text className="meta" textAnchor="middle" y="24">
        {plural(item.flowCount, "flow")}
      </text>
    </g>
  );
}

function FlowDetail({
  anchorX,
  anchorY,
  annotations,
  detail,
  draggingNodeKey,
  flowId,
  manualNodePositions,
  onDragStart,
  onEdgeSelect,
  onNodeSelect,
  selectedDetail,
  suppressNodeClick,
  topLevelDimmed,
}: {
  anchorX: number;
  anchorY: number;
  annotations?: Record<string, LogicChartAnnotationText>;
  detail: FlowDetailLayout;
  draggingNodeKey: string | null;
  flowId: string;
  manualNodePositions: ReadonlyMap<string, ManualNodePosition>;
  onDragStart: (
    event: ReactPointerEvent<SVGGElement>,
    kind: ViewerNodeKind,
    id: string,
    position: ManualNodePosition,
  ) => void;
  onEdgeSelect: (
    flowId: string,
    route: FlowDetailEdgeRoute,
    targetNode: FlowDetailNodePosition | undefined,
  ) => void;
  onNodeSelect: (flowId: string, node: FlowDetailNodePosition) => void;
  selectedDetail: SelectedDetail | null;
  suppressNodeClick: (kind: ViewerNodeKind, id: string) => boolean;
  topLevelDimmed: boolean;
}) {
  const nodePositions = applyManualDetailPositions(
    flowId,
    detail,
    manualNodePositions,
    anchorX,
    anchorY,
  );
  const edgeRoutes = detail.edgeRoutes
    .map(route => routeDetailEdge(route, nodePositions))
    .filter((route): route is FlowDetailEdgeRoute => route !== null);
  const startRoutes = routeDetailStartEdges(nodePositions);
  const connectedNodeIds = selectedDetailConnectedNodeIds(selectedDetail, flowId, edgeRoutes);
  const selectedEdgeId =
    selectedDetail?.kind === "detail-edge" && selectedDetail.flowId === flowId
      ? selectedDetail.edgeId
      : null;
  const hasForeignDetailSelection = selectedDetail !== null && selectedDetail.flowId !== flowId;
  const hasLocalDetailSelection = selectedDetail !== null && selectedDetail.flowId === flowId;

  return (
    <g
      className="flow-detail"
      data-detail-flow-id={flowId}
      transform={`translate(${anchorX} ${anchorY})`}
    >
      <g className="flow-detail-edges">
        <g className="flow-detail-edge-hits">
          {[...startRoutes, ...edgeRoutes].map(route => {
            const edgeId = detailEdgeId(route);
            const targetNode = nodePositions.get(route.edge.target);
            const state = detailEdgeState({
              edgeId,
              flowId,
              hasForeignDetailSelection,
              route,
              selectedDetail,
              selectedEdgeId,
              topLevelDimmed,
            });
            return (
              <path
                aria-hidden="true"
                className={state.hitClassName}
                d={route.d}
                data-edge-id={edgeId}
                key={edgeId}
                vectorEffect="non-scaling-stroke"
                onClick={event => {
                  event.stopPropagation();
                  onEdgeSelect(flowId, route, targetNode);
                }}
                onPointerDown={event => {
                  event.stopPropagation();
                  onEdgeSelect(flowId, route, targetNode);
                }}
              />
            );
          })}
        </g>
        {startRoutes.map(route => {
          const edgeId = detailEdgeId(route);
          const targetNode = nodePositions.get(route.edge.target);
          const state = detailEdgeState({
            edgeId,
            flowId,
            hasForeignDetailSelection,
            route,
            selectedDetail,
            selectedEdgeId,
            topLevelDimmed,
          });
          return (
            <g
              className="flow-detail-edge-group"
              data-edge-id={edgeId}
              key={edgeId}
              role="button"
              tabIndex={0}
              onClick={event => {
                event.stopPropagation();
                onEdgeSelect(flowId, route, targetNode);
              }}
              onKeyDown={event => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onEdgeSelect(flowId, route, targetNode);
                }
              }}
              onPointerDown={event => {
                event.stopPropagation();
                onEdgeSelect(flowId, route, targetNode);
              }}
            >
              <path
                className={[state.edgeClassName, "flow-detail-start-edge"]
                  .filter(Boolean)
                  .join(" ")}
                d={route.d}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
        {edgeRoutes.map(route => {
          const edgeId = detailEdgeId(route);
          const targetNode = nodePositions.get(route.edge.target);
          const state = detailEdgeState({
            edgeId,
            flowId,
            hasForeignDetailSelection,
            route,
            selectedDetail,
            selectedEdgeId,
            topLevelDimmed,
          });
          return (
            <g
              className="flow-detail-edge-group"
              data-edge-id={edgeId}
              key={edgeId}
              role="button"
              tabIndex={0}
              onClick={event => {
                event.stopPropagation();
                onEdgeSelect(flowId, route, targetNode);
              }}
              onKeyDown={event => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onEdgeSelect(flowId, route, targetNode);
                }
              }}
              onPointerDown={event => {
                event.stopPropagation();
                onEdgeSelect(flowId, route, targetNode);
              }}
            >
              <path
                className={state.edgeClassName}
                d={route.d}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
        <g className="flow-detail-labels">
          {edgeRoutes.map(route => {
            if (!route.edge.label) return null;
            const edgeId = detailEdgeId(route);
            const targetNode = nodePositions.get(route.edge.target);
            const state = detailEdgeState({
              edgeId,
              flowId,
              hasForeignDetailSelection,
              route,
              selectedDetail,
              selectedEdgeId,
              topLevelDimmed,
            });
            const width = Math.max(44, route.edge.label.length * 7 + 18);
            return (
              <g
                className={state.labelClassName}
                data-edge-id={edgeId}
                key={`${edgeId}:label`}
                role="button"
                tabIndex={0}
                transform={`translate(${route.labelX} ${route.labelY})`}
                onClick={event => {
                  event.stopPropagation();
                  onEdgeSelect(flowId, route, targetNode);
                }}
                onKeyDown={event => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onEdgeSelect(flowId, route, targetNode);
                  }
                }}
                onPointerDown={event => {
                  event.stopPropagation();
                  onEdgeSelect(flowId, route, targetNode);
                }}
              >
                <rect height="20" rx="10" width={width} x={-width / 2} y="-10" />
                <text textAnchor="middle" y="4">{route.edge.label}</text>
              </g>
            );
          })}
        </g>
      </g>
      <g className="flow-detail-nodes">
        {[...nodePositions.values()].map(position => (
          <FlowDetailNode
            connectedNodeIds={connectedNodeIds}
            draggingNodeKey={draggingNodeKey}
            flowId={flowId}
            hasForeignDetailSelection={hasForeignDetailSelection}
            hasLocalDetailSelection={hasLocalDetailSelection}
            key={position.id}
            onDragStart={onDragStart}
            onSelect={onNodeSelect}
            position={position}
            suppressNodeClick={suppressNodeClick}
            topLevelDimmed={topLevelDimmed}
            anchorX={anchorX}
            anchorY={anchorY}
            annotation={annotations?.[position.id]}
          />
        ))}
      </g>
    </g>
  );
}

function FlowDetailNode({
  anchorX,
  anchorY,
  annotation,
  connectedNodeIds,
  draggingNodeKey,
  flowId,
  hasForeignDetailSelection,
  hasLocalDetailSelection,
  onDragStart,
  onSelect,
  position,
  suppressNodeClick,
  topLevelDimmed,
}: {
  anchorX: number;
  anchorY: number;
  annotation?: LogicChartAnnotationText;
  connectedNodeIds: ReadonlySet<string>;
  draggingNodeKey: string | null;
  flowId: string;
  hasForeignDetailSelection: boolean;
  hasLocalDetailSelection: boolean;
  onDragStart: (
    event: ReactPointerEvent<SVGGElement>,
    kind: ViewerNodeKind,
    id: string,
    position: ManualNodePosition,
  ) => void;
  onSelect: (flowId: string, node: FlowDetailNodePosition) => void;
  position: FlowDetailNodePosition;
  suppressNodeClick: (kind: ViewerNodeKind, id: string) => boolean;
  topLevelDimmed: boolean;
}) {
  const kind = position.node.kind || "action";
  const nodeKey = detailNodeKey(flowId, position.id);
  const selected = hasLocalDetailSelection && connectedNodeIds.has(position.id);
  const dimmed =
    topLevelDimmed ||
    hasForeignDetailSelection ||
    (hasLocalDetailSelection && !connectedNodeIds.has(position.id));
  const className = [
    "detail-node",
    "movable",
    kind,
    selected ? "selected" : "",
    dimmed ? "dimmed" : "",
    draggingNodeKey === viewerNodeKey("detail", nodeKey) ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const label = displayNodeLabel(position.node.label || position.id, annotation);
  const title = annotationTitle(label, annotation);
  return (
    <g
      aria-label={title}
      className={className}
      data-annotation-label={annotation?.label}
      data-detail-node-id={position.id}
      data-detail-flow-id={flowId}
      role="button"
      tabIndex={0}
      transform={`translate(${position.x} ${position.y})`}
      onClick={event => {
        event.stopPropagation();
        if (suppressNodeClick("detail", nodeKey)) return;
        onSelect(flowId, position);
      }}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(flowId, position);
        }
      }}
      onPointerDown={event =>
        onDragStart(event, "detail", nodeKey, {
          x: anchorX + position.x,
          y: anchorY + position.y,
        })
      }
    >
      <title>{title}</title>
      {kind === "decision" ? (
        <polygon
          className="detail-shape"
          points={`0 ${-position.height / 2} ${position.width / 2} 0 0 ${position.height / 2} ${-position.width / 2} 0`}
          vectorEffect="non-scaling-stroke"
        />
      ) : (
        <rect
          className="detail-shape"
          height={position.height}
          rx={kind === "entry" || kind === "terminal" ? 32 : 10}
          vectorEffect="non-scaling-stroke"
          width={position.width}
          x={-position.width / 2}
          y={-position.height / 2}
        />
      )}
      <text className="detail-kind" textAnchor="middle" y={-position.height / 2 + 21}>
        {kind}
      </text>
      {wrapLabel(label, kind === "decision" ? 25 : 31).map((line, index, lines) => (
        <text
          className="detail-label"
          key={`${position.id}:${index}`}
          textAnchor="middle"
          y={(index - (lines.length - 1) / 2) * 15 + 8}
        >
          {line}
        </text>
      ))}
      {position.node.location?.start_line ? (
        <text className="detail-meta" textAnchor="middle" y={position.height / 2 + 18}>
          {position.node.location.path}:{position.node.location.start_line}
        </text>
      ) : null}
    </g>
  );
}

function applyManualDetailPositions(
  flowId: string,
  detail: FlowDetailLayout,
  manualNodePositions: ReadonlyMap<string, ManualNodePosition>,
  anchorX: number,
  anchorY: number,
): Map<string, FlowDetailNodePosition> {
  return new Map(
    [...detail.nodePositions.entries()].map(([id, position]) => {
      const manual = manualNodePositions.get(viewerNodeKey("detail", detailNodeKey(flowId, id)));
      return [
        id,
        manual
          ? {
              ...position,
              x: manual.x - anchorX,
              y: manual.y - anchorY,
            }
          : position,
      ];
    }),
  );
}

function routeDetailEdge(
  route: FlowDetailEdgeRoute,
  positions: ReadonlyMap<string, FlowDetailNodePosition>,
): FlowDetailEdgeRoute | null {
  const source = positions.get(route.edge.source);
  const target = positions.get(route.edge.target);
  if (!source || !target) return null;
  const startY = source.y + source.height / 2;
  const endY = target.y - target.height / 2;
  const laneOffset = (Math.abs(hashString(detailEdgeId(route))) % 3 - 1) * 8;
  const defaultLaneY = (startY + endY) / 2 + laneOffset;
  const obstacles = detailObstacleBoxes(positions, source.id, target.id);
  const midY = routeDetailLaneY(
    source.x,
    startY,
    target.x,
    endY,
    defaultLaneY,
    obstacles,
  );
  return {
    ...route,
    d: `M ${source.x} ${startY} L ${source.x} ${midY} L ${target.x} ${midY} L ${target.x} ${endY}`,
    labelX: (source.x + target.x) / 2,
    labelY: midY - 8,
  };
}

function detailObstacleBoxes(
  positions: ReadonlyMap<string, FlowDetailNodePosition>,
  sourceId: string,
  targetId: string,
): Bounds[] {
  return [...positions.values()]
    .filter(position => position.id !== sourceId && position.id !== targetId)
    .map(position => ({
      maxX: position.x + position.width / 2 + DETAIL_EDGE_OBSTACLE_GAP,
      maxY: position.y + position.height / 2 + DETAIL_EDGE_OBSTACLE_GAP,
      minX: position.x - position.width / 2 - DETAIL_EDGE_OBSTACLE_GAP,
      minY: position.y - position.height / 2 - DETAIL_EDGE_OBSTACLE_GAP,
    }));
}

function routeDetailLaneY(
  sourceX: number,
  startY: number,
  targetX: number,
  endY: number,
  defaultLaneY: number,
  obstacles: readonly Bounds[],
): number {
  const candidates = detailLaneCandidates(defaultLaneY, obstacles);
  return (
    candidates.find(candidate =>
      detailLaneIsClear(sourceX, startY, targetX, endY, candidate, obstacles),
    ) ?? defaultLaneY
  );
}

function detailLaneCandidates(
  defaultLaneY: number,
  obstacles: readonly Bounds[],
): number[] {
  const candidates: number[] = [];
  const add = (candidate: number) => {
    if (!Number.isFinite(candidate)) return;
    if (!candidates.some(existing => Math.abs(existing - candidate) < 0.5)) {
      candidates.push(candidate);
    }
  };

  add(defaultLaneY);
  for (let step = 1; step <= DETAIL_EDGE_MAX_LANE_STEPS; step += 1) {
    add(defaultLaneY - step * DETAIL_EDGE_LANE_STEP);
    add(defaultLaneY + step * DETAIL_EDGE_LANE_STEP);
  }
  obstacles.forEach(box => {
    add(box.minY - DETAIL_EDGE_OBSTACLE_GAP);
    add(box.maxY + DETAIL_EDGE_OBSTACLE_GAP);
  });

  return candidates.sort(
    (left, right) => Math.abs(left - defaultLaneY) - Math.abs(right - defaultLaneY),
  );
}

function detailLaneIsClear(
  sourceX: number,
  startY: number,
  targetX: number,
  endY: number,
  laneY: number,
  obstacles: readonly Bounds[],
): boolean {
  return obstacles.every(
    box =>
      !horizontalSegmentIntersectsBox(sourceX, targetX, laneY, box) &&
      !verticalSegmentIntersectsBox(sourceX, startY, laneY, box) &&
      !verticalSegmentIntersectsBox(targetX, laneY, endY, box),
  );
}

function horizontalSegmentIntersectsBox(
  x1: number,
  x2: number,
  y: number,
  box: Bounds,
): boolean {
  const minX = Math.min(x1, x2);
  const maxX = Math.max(x1, x2);
  return y >= box.minY && y <= box.maxY && maxX >= box.minX && minX <= box.maxX;
}

function verticalSegmentIntersectsBox(
  x: number,
  y1: number,
  y2: number,
  box: Bounds,
): boolean {
  const minY = Math.min(y1, y2);
  const maxY = Math.max(y1, y2);
  return x >= box.minX && x <= box.maxX && maxY >= box.minY && minY <= box.maxY;
}

function routeDetailStartEdges(
  positions: ReadonlyMap<string, FlowDetailNodePosition>,
): FlowDetailEdgeRoute[] {
  return [...positions.values()]
    .filter(position => position.layer === 0)
    .map(position => {
      const endY = position.y - position.height / 2;
      const defaultLaneY = -19;
      const midY = routeDetailLaneY(
        0,
        -38,
        position.x,
        endY,
        defaultLaneY,
        detailObstacleBoxes(positions, "__flow_host__", position.id),
      );
      return {
        id: `start->${position.id}`,
        edge: {
          source: "__flow_host__",
          target: position.id,
        },
        d: `M 0 -38 L 0 ${midY} L ${position.x} ${midY} L ${position.x} ${endY}`,
        labelX: position.x / 2,
        labelY: midY - 8,
      };
    });
}

function selectedDetailConnectedNodeIds(
  selectedDetail: SelectedDetail | null,
  flowId: string,
  edgeRoutes: readonly FlowDetailEdgeRoute[],
): Set<string> {
  if (!selectedDetail || selectedDetail.flowId !== flowId) return new Set();
  if (selectedDetail.kind === "detail-edge") {
    return new Set([selectedDetail.source, selectedDetail.target]);
  }
  const connected = new Set([selectedDetail.nodeId]);
  edgeRoutes.forEach(route => {
    if (route.edge.source === selectedDetail.nodeId) connected.add(route.edge.target);
    if (route.edge.target === selectedDetail.nodeId) connected.add(route.edge.source);
  });
  return connected;
}

function detailEdgeIncident(
  selectedDetail: SelectedDetail | null,
  flowId: string,
  route: FlowDetailEdgeRoute,
): boolean {
  if (!selectedDetail || selectedDetail.flowId !== flowId) return false;
  if (selectedDetail.kind === "detail-edge") return selectedDetail.edgeId === detailEdgeId(route);
  return route.edge.source === selectedDetail.nodeId || route.edge.target === selectedDetail.nodeId;
}

function detailEdgeState({
  edgeId,
  flowId,
  hasForeignDetailSelection,
  route,
  selectedDetail,
  selectedEdgeId,
  topLevelDimmed,
}: {
  edgeId: string;
  flowId: string;
  hasForeignDetailSelection: boolean;
  route: FlowDetailEdgeRoute;
  selectedDetail: SelectedDetail | null;
  selectedEdgeId: string | null;
  topLevelDimmed: boolean;
}): { edgeClassName: string; hitClassName: string; labelClassName: string } {
  const incident = detailEdgeIncident(selectedDetail, flowId, route);
  const selected = selectedEdgeId === edgeId;
  const dimmed =
    topLevelDimmed || (selectedDetail !== null && (hasForeignDetailSelection || !incident));
  return {
    edgeClassName: [
      "flow-detail-edge",
      selected ? "selected-link" : "",
      incident && !selected ? "incident" : "",
      dimmed ? "dimmed" : "",
    ]
      .filter(Boolean)
      .join(" "),
    hitClassName: [
      "flow-detail-edge-hit",
      selected ? "selected-link" : "",
      dimmed ? "dimmed" : "",
    ]
      .filter(Boolean)
      .join(" "),
    labelClassName: ["flow-detail-label", dimmed ? "dimmed" : ""]
      .filter(Boolean)
      .join(" "),
  };
}

function detailEdgeId(route: FlowDetailEdgeRoute): string {
  return route.id || `${route.edge.source}->${route.edge.target}`;
}

interface FlowNeighborhood {
  flowIds: Set<string>;
  scopeEntryTargets: Set<string>;
  scopeIds: Set<string>;
}

function flowNeighborhood(
  flowId: string,
  flowCallEdges: readonly FlowCallEdge[],
  entryEdges: readonly ScopeEntryEdge[],
): FlowNeighborhood {
  const flowIds = connectedFlowIdsFromSeeds(new Set([flowId]), flowCallEdges);
  const scopeEntryTargets = new Set<string>();
  const scopeIds = new Set<string>();
  entryEdges.forEach(edge => {
    if (flowIds.has(edge.target)) {
      scopeIds.add(edge.scope);
      scopeEntryTargets.add(edge.target);
    }
  });
  return { flowIds, scopeEntryTargets, scopeIds };
}

function connectedFlowIdsFromSeeds(
  seeds: ReadonlySet<string>,
  flowCallEdges: readonly FlowCallEdge[],
): Set<string> {
  const connected = new Set(seeds);
  const queue = [...seeds];
  while (queue.length) {
    const current = queue.shift();
    if (!current) continue;
    flowCallEdges.forEach(edge => {
      const next =
        edge.source === current ? edge.target : edge.target === current ? edge.source : null;
      if (!next || connected.has(next)) return;
      connected.add(next);
      queue.push(next);
    });
  }
  return connected;
}

function detailNodeKey(flowId: string, nodeId: string): string {
  return `${flowId}:${nodeId}`;
}

function layersSignature(layers: readonly (readonly ProgressiveFlowNode[])[] | undefined): string {
  if (!layers) return "";
  return layers.map(layer => layer.map(node => node.id).join(",")).join("|");
}

function payloadSignature(payload: LogicChartPayload | undefined): string {
  if (!payload) return "";
  return payload.flows
    .map(
      flow =>
        `${flow.id}:${flow.location?.path ?? ""}:${flow.location?.start_line ?? ""}:${
          flow.nodes?.length ?? 0
        }:${flow.edges?.length ?? 0}:${flow.calls?.length ?? 0}:${flow.called_by?.length ?? 0}`,
    )
    .join("|");
}

function expandedMeasuresSignature(
  measures: ReadonlyMap<string, ExpandedFlowMeasure> | undefined,
): string {
  if (!measures) return "";
  return [...measures.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(
      ([flowId, measure]) =>
        `${flowId}:${measure.minX}:${measure.minY}:${measure.maxX}:${measure.maxY}:${measure.width}:${measure.height}`,
    )
    .join("|");
}

function manualNodePositionsSignature(
  positions: ReadonlyMap<string, ManualNodePosition>,
): string {
  if (!positions.size) return "";
  return [...positions.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, position]) => `${key}:${position.x}:${position.y}`)
    .join("|");
}

function viewBoxForFocusedFlow(
  flowId: string,
  flowPositions: ReadonlyMap<string, LayoutNodePosition>,
  inlineAnchors: readonly InlineAnchor[],
): Bounds | null {
  const host = flowPositions.get(flowId);
  if (!host) return null;
  const anchor = inlineAnchors.find(item => item.flowId === flowId);
  return expandBoundsToMinimum(
    paddedBounds(mergeSvgBounds([nodePositionBounds(host), anchor?.bounds]), 160, 130),
    900,
    640,
  );
}

function nodePositionBounds(position: LayoutNodePosition): Bounds {
  return {
    maxX: position.x + position.width / 2,
    maxY: position.y + position.height / 2,
    minX: position.x - position.width / 2,
    minY: position.y - position.height / 2,
  };
}

function mergeSvgBounds(bounds: Array<Bounds | undefined>): Bounds {
  const available = bounds.filter((item): item is Bounds => item !== undefined);
  if (!available.length) return { maxX: 0, maxY: 0, minX: 0, minY: 0 };
  return {
    maxX: Math.max(...available.map(item => item.maxX)),
    maxY: Math.max(...available.map(item => item.maxY)),
    minX: Math.min(...available.map(item => item.minX)),
    minY: Math.min(...available.map(item => item.minY)),
  };
}

function paddedBounds(bounds: Bounds, padX: number, padY: number): Bounds {
  return {
    maxX: bounds.maxX + padX,
    maxY: bounds.maxY + padY,
    minX: bounds.minX - padX,
    minY: bounds.minY - padY,
  };
}

function expandBoundsToMinimum(bounds: Bounds, minWidth: number, minHeight: number): Bounds {
  const width = bounds.maxX - bounds.minX;
  const height = bounds.maxY - bounds.minY;
  const extraX = Math.max(0, minWidth - width) / 2;
  const extraY = Math.max(0, minHeight - height) / 2;
  return {
    maxX: bounds.maxX + extraX,
    maxY: bounds.maxY + extraY,
    minX: bounds.minX - extraX,
    minY: bounds.minY - extraY,
  };
}

function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return hash;
}

interface SvgViewBox {
  height: number;
  width: number;
  x: number;
  y: number;
}

function readSvgViewBox(svg: SVGSVGElement): SvgViewBox | null {
  const values = (svg.getAttribute("viewBox") || "")
    .trim()
    .split(/\s+/)
    .map(value => Number(value));
  if (values.length !== 4 || values.some(value => !Number.isFinite(value))) return null;
  const [x, y, width, height] = values;
  if (width <= 0 || height <= 0) return null;
  return { height, width, x, y };
}

function clientPointToSvgPoint(
  svg: SVGSVGElement,
  viewBox: SvgViewBox,
  clientX: number,
  clientY: number,
): ManualNodePosition {
  const matrix = svg.getScreenCTM?.();
  if (matrix && typeof svg.createSVGPoint === "function") {
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const transformed = point.matrixTransform(matrix.inverse());
    return { x: transformed.x, y: transformed.y };
  }

  const rect = svg.getBoundingClientRect();
  const viewportWidth =
    rect.width || svg.clientWidth || Number(svg.getAttribute("width")) || viewBox.width;
  const viewportHeight =
    rect.height || svg.clientHeight || Number(svg.getAttribute("height")) || viewBox.height;
  return {
    x: viewBox.x + ((clientX - rect.left) / Math.max(1, viewportWidth)) * viewBox.width,
    y: viewBox.y + ((clientY - rect.top) / Math.max(1, viewportHeight)) * viewBox.height,
  };
}

function scheduleFrame(callback: () => void): ScheduledFrame {
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    const id = window.requestAnimationFrame(callback);
    return {
      cancel: () => window.cancelAnimationFrame(id),
    };
  }

  const id = globalThis.setTimeout(callback, DRAG_FRAME_FALLBACK_MS);
  return {
    cancel: () => globalThis.clearTimeout(id),
  };
}

function asLogicChartFlow(flow: ProgressiveFlowNode): LogicChartFlow {
  return flow as LogicChartFlow;
}

function flowMeta(flow: ProgressiveFlowNode): string[] {
  if (!isLogicChartFlow(flow)) return [];
  const item = asLogicChartFlow(flow);
  return [item.entry_kind, item.language].filter((value): value is string => Boolean(value));
}

function flowAccessibilitySummary(
  flow: LogicChartFlow,
  findingCount: number,
  annotation?: LogicChartAnnotationText,
): string {
  const nodes = flow.nodes || [];
  const decisionCount = nodes.filter(node => node.kind === "decision").length;
  const pieces = [
    displayFlowLabel(flow, annotation),
    flowMeta(flow).join(" in ") || "flow",
    plural(nodes.length, "node"),
    plural(decisionCount, "decision"),
    plural((flow.calls || []).length, "call"),
    plural((flow.called_by || []).length, "caller"),
    plural(findingCount, "finding"),
  ];
  const source = flowPath(flow);
  if (source) pieces.push(source);
  return pieces.join(" · ");
}

function displayFlowLabel(
  flow: LogicChartFlow,
  annotation?: LogicChartAnnotationText,
): string {
  return displayAnnotationLabel(flowLabel(flow), annotation);
}

function displayNodeLabel(label: string, annotation?: LogicChartAnnotationText): string {
  return displayAnnotationLabel(label, annotation);
}

function displayScopeLabel(scope: string, annotation?: LogicChartAnnotationText): string {
  return displayAnnotationLabel(scope, annotation);
}

function displayAnnotationLabel(
  fallback: string,
  annotation?: LogicChartAnnotationText,
): string {
  const label = annotation?.label?.trim();
  return label ? compactSvgText(label, 64) : fallback;
}

function annotationTitle(base: string, annotation?: LogicChartAnnotationText): string {
  const detail = annotation?.description || annotation?.summary || annotation?.explanation;
  return detail ? `${base}\n${detail}` : base;
}

function compactSvgText(value: string, limit: number): string {
  const compacted = value.replace(/\s+/g, " ").trim();
  return compacted.length <= limit ? compacted : `${compacted.slice(0, limit - 3).trim()}...`;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function flowKindClass(flow: ProgressiveFlowNode | undefined): string {
  if (!flow || !isLogicChartFlow(flow)) return "flow-kind-other";
  const value = (asLogicChartFlow(flow).entry_kind || "").toLowerCase();
  if (/route|endpoint|controller|resolver|handler/.test(value)) return "flow-kind-route";
  if (/component|page|view|screen/.test(value)) return "flow-kind-component";
  if (/method|member/.test(value)) return "flow-kind-method";
  if (/class|type|interface|enum/.test(value)) return "flow-kind-type";
  if (/service|usecase|use-case|interactor/.test(value)) return "flow-kind-service";
  if (/query|repository|dao|model|schema|database|db/.test(value)) return "flow-kind-data";
  if (/job|worker|task|queue|consumer|subscriber|listener/.test(value)) return "flow-kind-worker";
  if (/test|spec|fixture/.test(value)) return "flow-kind-test";
  if (/function|callback|lambda|procedure|proc/.test(value)) return "flow-kind-function";
  return "flow-kind-other";
}

function scopeToneStyleMap(scopes: readonly string[]): Map<string, SvgStyleVars> {
  const uniqueScopes = [...new Set(scopes)].sort((a, b) => a.localeCompare(b));
  if (!uniqueScopes.length) return new Map();
  const offset = stableHue(uniqueScopes.join("|"));
  const step = uniqueScopes.length === 1 ? 0 : 360 / uniqueScopes.length;
  return new Map(
    uniqueScopes.map((scope, index) => [
      scope,
      {
        "--scope-hue": String(Math.round((offset + index * step) % 360)),
      },
    ]),
  );
}

function stableHue(value: string): number {
  const raw = Math.abs(hashString(value));
  return (raw * 47 + 19) % 360;
}

function flowDetailLayouts(
  payload: LogicChartPayload | undefined,
  routeFlowIds: readonly string[],
): Map<string, FlowDetailLayout> {
  const details = new Map<string, FlowDetailLayout>();
  if (!payload) return details;
  const byId = new Map(payload.flows.map(flow => [flow.id, flow]));
  routeFlowIds.forEach(flowId => {
    const flow = byId.get(flowId);
    if (!flow) return;
    const detail = layoutFlowDetail(flow, { omitEntryNode: true });
    if (detail) details.set(flowId, detail);
  });
  return details;
}

function wrapLabel(value: string, width: number): string[] {
  const words = value.split(/\s+/);
  const lines: string[] = [];
  let current = "";
  words.forEach(word => {
    if (!current || `${current} ${word}`.length <= width) {
      current = current ? `${current} ${word}` : word;
    } else {
      lines.push(current);
      current = word;
    }
  });
  if (current) lines.push(current);
  return lines.slice(0, 3);
}

function hashForConnection(connection: ActiveConnection): string {
  if (connection.kind === "root-scope") {
    return `#edge=${encodeHashValue(
      JSON.stringify({ kind: "root-scope", scope: connection.scope }),
    )}`;
  }
  if (connection.kind === "scope-entry") {
    return `#edge=${encodeHashValue(
      JSON.stringify({ scope: connection.scope, target: connection.target }),
    )}`;
  }
  return `#edge=${encodeHashValue(
    JSON.stringify({
      kind: "flow-call",
      source: connection.source,
      target: connection.target,
    }),
  )}`;
}

function hashForScope(scope: string): string {
  return `#scope=${encodeHashValue(scope)}`;
}

function hashForRootNode(): string {
  return "#node=codebase";
}

function hashForFlow(flowId: string): string {
  return `#flow=${encodeHashValue(flowId)}`;
}

function setLocationHash(hash: string) {
  if (typeof window === "undefined") return;
  if (window.location.hash === hash) return;
  window.location.hash = hash;
}

function selectionKey(selection: SelectedConnection | undefined): string {
  if (!selection) return "none";
  if (selection.kind === "root-scope") {
    return `root-scope:${selection.scope}`;
  }
  if (selection.kind === "scope-entry") {
    return `scope-entry:${selection.scope}:${selection.target}`;
  }
  return `flow-call:${selection.source}:${selection.target}`;
}

function encodeHashValue(value: string): string {
  if (typeof encodeURIComponent === "function") return encodeURIComponent(value);
  return value.replace(/[^A-Za-z0-9_.~-]/g, char =>
    `%${char.charCodeAt(0).toString(16).padStart(2, "0").toUpperCase()}`,
  );
}
