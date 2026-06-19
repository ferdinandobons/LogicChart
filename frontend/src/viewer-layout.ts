import {
  layoutProgressiveRows,
  layoutScopeNodes,
  scopeEntryEdges,
  type Bounds,
  type ExpandedFlowMeasure,
  type InlineAnchor,
  type LayoutNodePosition,
  type ProgressiveFlowNode,
  type ProgressiveLayout,
  type ProgressiveLayoutOptions,
  type ScopeEntryEdge,
  type ScopeLayoutOptions,
  type ScopeLayoutPosition,
  type ScopeNodePosition,
} from "./flowchart-layout";
import {
  buildProgressiveModel,
  scopeNamesForFlow,
  scopeSummaries,
  type LogicChartFlow,
  type LogicChartPayload,
} from "./logicchart-model";

export const DEFAULT_PROGRESSIVE_LAYOUT_OPTIONS: ProgressiveLayoutOptions = {
  flowWidth: 238,
  flowHeight: 68,
  gapX: 70,
  rowGap: 150,
  layerGap: 360,
  chipY: 27,
  decisionPad: 90,
  detailTopPad: 36,
  maxNodesPerRow: 8,
};

export const DEFAULT_SCOPE_LAYOUT_OPTIONS: ScopeLayoutOptions = {
  scopeWidth: 220,
  scopeHeight: 108,
  gapX: 150,
  gapY: 110,
  maxColumns: 4,
  topY: 80,
};

const CALL_CHILD_GAP_Y = 116;
const CALL_CHILD_ROW_GAP_Y = 96;
const FLOW_CALL_LANE_STEP = 16;
const FLOW_CALL_OBSTACLE_GAP = 18;
const MAX_CALL_CHILDREN_PER_ROW = 4;
const DETAIL_CONTENT_COLLISION_GAP = 24;
const DETAIL_CONTENT_COLLISION_MAX_PASSES = 24;
const STRUCTURAL_COLLISION_GAP = 28;
const STRUCTURAL_COLLISION_MAX_PASSES = 32;
const ROOT_NODE_ID = "codebase";

export interface ViewerLayoutInput {
  scope: string;
  payload?: LogicChartPayload;
  layers?: ProgressiveFlowNode[][];
  routeFlowIds?: readonly string[];
  contextFlowIds?: readonly string[];
  expandedScopes?: readonly string[];
  expandedMeasures?: ReadonlyMap<string, ExpandedFlowMeasure>;
  performanceMode?: "normal" | "expanded-overview";
  manualNodePositions?: ReadonlyMap<string, ManualNodePosition>;
  scopeNode?: ScopeNodePosition;
  progressiveOptions?: ProgressiveLayoutOptions;
  scopeOptions?: ScopeLayoutOptions;
}

export interface ViewerLayout {
  activeScopeNode: ScopeLayoutPosition;
  entryEdges: ScopeEntryEdge[];
  flowCallEdges: FlowCallEdge[];
  flowById: Map<string, ProgressiveFlowNode>;
  flowPositions: Map<string, LayoutNodePosition>;
  inlineAnchors: InlineAnchor[];
  rootEdges: RootScopeEdge[];
  rootNode: RootNodePosition;
  scopeNodes: ScopeLayoutPosition[];
  viewBox: Bounds;
}

export interface RootNodePosition {
  id: "codebase";
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  flowCount: number;
  scopeCount: number;
}

export interface RootScopeEdge {
  scope: string;
  d: string;
  focusD: string;
  points: Array<{ x: number; y: number }>;
}

export interface FlowCallEdge {
  source: string;
  target: string;
  d: string;
  focusD: string;
  points: Array<{ x: number; y: number }>;
}

export type ViewerLayoutEdgeKind = "flow-call" | "root-scope" | "scope-entry";

export interface ViewerLayoutEdgeObstacleHit {
  edge: string;
  kind: ViewerLayoutEdgeKind;
  obstacle: string;
}

export interface ViewerLayoutQualityReport {
  bounds: Bounds;
  boxCount: number;
  contentArea: number;
  density: number;
  detailRegionCount: number;
  edgeCount: number;
  edgeObstacleHits: ViewerLayoutEdgeObstacleHit[];
  flowCallEdgeCount: number;
  flowNodeCount: number;
  isClear: boolean;
  overlapCount: number;
  overlaps: Array<[string, string]>;
  rootEdgeCount: number;
  scopeEntryEdgeCount: number;
  scopeNodeCount: number;
  structureIssueCount: number;
  structureIssues: ViewerLayoutStructureIssue[];
  viewBoxArea: number;
}

export interface ViewerLayoutQualityOptions {
  edgeGap?: number;
  overlapGap?: number;
}

export interface ViewerLayoutStructureIssue {
  id: string;
  kind:
    | "detail-above-host"
    | "detail-detached-from-host"
    | "flow-call-detached-from-source"
    | "flow-call-detached-from-target"
    | "root-scope-reversed"
    | "scope-entry-reversed"
    | "visible-flow-unreachable";
}

export interface ViewerLayoutStructureOptions {
  tolerance?: number;
}

export interface LayoutBox {
  id: string;
  kind: "detail" | "flow" | "root" | "scope";
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export interface ManualNodePosition {
  x: number;
  y: number;
}

export type ViewerNodeKind = "detail" | "flow" | "root" | "scope";

interface OpenedCallChildGroup {
  children: string[];
  parentId: string;
  rows: string[][];
  subtreeHeight: number;
  subtreeWidth: number;
}

interface AbsoluteInlineAnchor {
  bounds: Bounds;
  flowId: string;
  x: number;
  y: number;
}

interface FlowCallPair {
  source: LayoutNodePosition;
  startY: number;
  target: LayoutNodePosition;
  targetTopY: number;
}

interface ProgressiveSectionSeed {
  entryFlowIds: string[];
  flowById: Map<string, ProgressiveFlowNode>;
  layout: ProgressiveLayout;
  openedCallGroups: OpenedCallChildGroup[];
  scope: string;
}

interface InlineAnchorRecord {
  anchor: InlineAnchor;
  offsetX: number;
  offsetY: number;
}

interface StructuralCollisionNode {
  height: number;
  id: string;
  kind: "root" | "scope";
  manual: boolean;
  scopeIndex?: number;
  width: number;
  x: number;
  y: number;
}

interface Segment {
  x1: number;
  x2: number;
  y1: number;
  y2: number;
}

type RouteDirection = "h" | "v";

export function viewerNodeKey(kind: ViewerNodeKind, id: string): string {
  return `${kind}:${id}`;
}

export function createViewerLayout(input: ViewerLayoutInput): ViewerLayout {
  const progressiveOptions = input.progressiveOptions ?? DEFAULT_PROGRESSIVE_LAYOUT_OPTIONS;
  const scopeOptions = input.scopeOptions ?? DEFAULT_SCOPE_LAYOUT_OPTIONS;
  const expandedOverviewMode = input.performanceMode === "expanded-overview";
  const scopeInputs = input.payload
    ? scopeSummaries(input.payload).map(summary => ({
        name: summary.name,
        flowCount: summary.flowIds.length,
      }))
    : [{ name: input.scope, flowCount: (input.layers ?? []).flat().length }];
  const expandedScopeSet = expandedScopesForInput(input, scopeInputs);
  const scopeNodesBase = layoutScopeNodes(scopeInputs, input.scope, scopeOptions).map(item => {
    const expanded = expandedScopeSet.has(item.scope);
    return input.scopeNode && item.scope === input.scope
      ? {
          ...item,
          x: input.scopeNode.x,
          y: input.scopeNode.y,
          width: input.scopeNode.width,
          height: input.scopeNode.height,
          expanded,
        }
      : {
          ...item,
          expanded,
        };
  });
  const activeScopeNodeBase =
    scopeNodesBase.find(item => item.scope === input.scope) ?? {
      scope: input.scope,
      x: 0,
      y: scopeOptions.topY,
      width: scopeOptions.scopeWidth,
      height: scopeOptions.scopeHeight,
      flowCount: input.layers?.flat().length ?? 0,
      expanded: true,
    };
  const appliedScopeNodes = scopeNodesBase.map(item =>
    applyManualNodePosition(item, input.manualNodePositions, "scope", item.scope),
  );
  const rootNodeBase = layoutRootNode(scopeNodesBase, scopeInputs);
  const appliedRootNode = applyManualNodePosition(
    rootNodeBase,
    input.manualNodePositions,
    "root",
    rootNodeBase.id,
  );
  const resolvedStructure = resolveRootScopeCollisions(
    appliedRootNode,
    appliedScopeNodes,
    input.manualNodePositions,
  );
  const rootNode = resolvedStructure.rootNode;
  const scopeNodes = resolvedStructure.scopeNodes;
  const activeScopeNode =
    scopeNodes.find(item => item.scope === input.scope) ?? activeScopeNodeBase;
  const scopeBottom = Math.max(
    activeScopeNode.y + activeScopeNode.height / 2,
    ...scopeNodes.map(item => item.y + item.height / 2),
  );
  const sectionSeeds = progressiveSectionSeeds(input, expandedScopeSet, progressiveOptions);
  const sectionPlacements = placeProgressiveSections(
    sectionSeeds,
    scopeNodes,
    scopeBottom + 150,
    progressiveOptions,
  );
  const initialFlowPositionsBase = new Map<string, LayoutNodePosition>();
  const flowPositionsBase = new Map<string, LayoutNodePosition>();
  const autoFlowDeltas = new Map<string, ManualNodePosition>();
  const inlineAnchorRecords: InlineAnchorRecord[] = [];
  const entryFlowIdsByScope = new Map<string, string[]>();
  const flowById = new Map<string, ProgressiveFlowNode>();

  sectionPlacements.forEach(section => {
    section.seed.flowById.forEach((flow, id) => flowById.set(id, flow));
    entryFlowIdsByScope.set(section.seed.scope, section.seed.entryFlowIds);
    const initialFlowPositions = new Map(
      [...section.seed.layout.positions.entries()].map(([id, position]) => [
        id,
        {
          ...position,
          x: position.x + section.offsetX,
          y: position.y + section.offsetY,
        },
      ]),
    );
    const initialInlineAnchors = new Map(
      section.seed.layout.inlineAnchors.map(anchor => [
        anchor.flowId,
        {
          ...anchor,
          bounds: offsetBounds(anchor.bounds, section.offsetX, section.offsetY),
          x: anchor.x + section.offsetX,
          y: anchor.y + section.offsetY,
        },
      ]),
    );
    const seededFlowPositions = new Map(
      [...initialFlowPositions.entries()].map(([id, position]) => [
        id,
        applyManualNodePosition(position, input.manualNodePositions, "flow", id),
      ]),
    );
    const seededInlineAnchors = new Map(
      [...initialInlineAnchors.entries()].map(([flowId, anchor]) => {
        const initial = initialFlowPositions.get(flowId);
        const seeded = seededFlowPositions.get(flowId);
        const dx = initial && seeded ? seeded.x - initial.x : 0;
        const dy = initial && seeded ? seeded.y - initial.y : 0;
        return [
          flowId,
          {
            ...anchor,
            bounds: offsetBounds(anchor.bounds, dx, dy),
            x: anchor.x + dx,
            y: anchor.y + dy,
          },
        ];
      }),
    );
    const sectionFlowPositionsBase = attachOpenedCallChildren({
      anchors: seededInlineAnchors,
      groups: section.seed.openedCallGroups,
      measures: input.expandedMeasures,
      options: progressiveOptions,
      positions: seededFlowPositions,
    });
    sectionFlowPositionsBase.forEach((position, id) => {
      const initial = initialFlowPositions.get(id);
      initialFlowPositionsBase.set(id, initial ?? position);
      flowPositionsBase.set(id, position);
      autoFlowDeltas.set(id, {
        x: initial ? position.x - initial.x : 0,
        y: initial ? position.y - initial.y : 0,
      });
    });
    section.seed.layout.inlineAnchors.forEach(anchor => {
      inlineAnchorRecords.push({
        anchor,
        offsetX: section.offsetX,
        offsetY: section.offsetY,
      });
    });
  });
  const flowPositionsSeed = new Map(
    [...flowPositionsBase.entries()].map(([id, position]) => [
      id,
      applyManualNodePosition(position, input.manualNodePositions, "flow", id),
    ]),
  );
  const flowDeltas = new Map(
    [...flowPositionsSeed.entries()].map(([id, position]) => {
      const base = flowPositionsBase.get(id);
      return [
        id,
        {
          x: base ? position.x - base.x : 0,
          y: base ? position.y - base.y : 0,
        },
      ];
    }),
  );
  const inlineAnchorsSeed = inlineAnchorRecords.map(({ anchor, offsetX, offsetY }) => {
    const delta = flowDeltas.get(anchor.flowId) ?? { x: 0, y: 0 };
    const autoDelta = autoFlowDeltas.get(anchor.flowId) ?? { x: 0, y: 0 };
    const reservedBounds = offsetBounds(anchor.bounds, offsetX, offsetY);
    const renderMeasure = input.expandedMeasures?.get(anchor.flowId);
    const renderAnchorX = anchor.x + offsetX + autoDelta.x + delta.x;
    const renderAnchorY = anchor.y + offsetY + autoDelta.y + delta.y;
    const renderBounds = renderMeasure
      ? offsetBounds(renderMeasure, renderAnchorX, renderAnchorY)
      : offsetBounds(reservedBounds, autoDelta.x + delta.x, autoDelta.y + delta.y);
    return {
      ...anchor,
      bounds: renderBounds,
      x: renderAnchorX,
      y: renderAnchorY,
    };
  });
  const resolvedDetailLayout = resolveDetailContentCollisions(
    flowPositionsSeed,
    inlineAnchorsSeed,
    layoutBoxesFromParts(rootNode, scopeNodes, new Map(), []),
    { skipFlowPairCollisions: expandedOverviewMode },
  );
  const flowPositions = resolvedDetailLayout.flowPositions;
  const inlineAnchors = resolvedDetailLayout.inlineAnchors;
  const topLevelObstacles = layoutBoxesFromParts(
    rootNode,
    scopeNodes,
    flowPositions,
    inlineAnchors,
  );
  const topLevelRoutingObstacles = layoutBoxesFromParts(
    rootNode,
    scopeNodes,
    flowPositions,
    [],
  );
  const rootEdges = rootScopeEdges(rootNode, scopeNodes, topLevelRoutingObstacles);
  const entryEdges = scopeNodes.flatMap(scopeNode =>
    (entryFlowIdsByScope.get(scopeNode.scope) ?? []).length
      ? routedScopeEntryEdges(
          scopeNode,
          (entryFlowIdsByScope.get(scopeNode.scope) ?? [])
            .map(id => flowPositions.get(id))
            .filter(isLayoutNodePosition),
          progressiveOptions.flowHeight,
          topLevelRoutingObstacles,
        )
      : [],
  );
  const flowCallEdges = progressiveFlowCallEdges(
    flowById,
    flowPositions,
    flowCallSourceExitYs(inlineAnchors, input.expandedMeasures),
    flowCallObstacles(flowPositions, inlineAnchors),
    { avoidObstacles: !expandedOverviewMode },
  );
  const viewBoxFlowCallBounds = boundsForFlowCallEdges(flowCallEdges);
  const viewBoxTopLevelEdgeBounds = boundsForTopLevelEdges(rootEdges, entryEdges);
  const viewBoxScopeBounds = boundsForRootAndScopes(rootNode, scopeNodes);
  const viewBoxContentBounds = boundsForLayoutBoxes(topLevelObstacles);

  return {
    activeScopeNode,
    entryEdges,
    flowCallEdges,
    flowById,
    flowPositions,
    inlineAnchors,
    rootEdges,
    rootNode,
    scopeNodes,
    viewBox: {
      minX: Math.min(
        0,
        viewBoxScopeBounds.minX - 120,
        viewBoxContentBounds.minX - 160,
        viewBoxFlowCallBounds.minX - 160,
        viewBoxTopLevelEdgeBounds.minX - 160,
      ),
      minY: Math.min(
        -80,
        viewBoxScopeBounds.minY - 120,
        viewBoxContentBounds.minY - 120,
        viewBoxFlowCallBounds.minY - 120,
        viewBoxTopLevelEdgeBounds.minY - 120,
      ),
      maxX: Math.max(
        viewBoxScopeBounds.maxX + 160,
        viewBoxContentBounds.maxX + 160,
        viewBoxFlowCallBounds.maxX + 160,
        viewBoxTopLevelEdgeBounds.maxX + 160,
      ),
      maxY: Math.max(
        viewBoxScopeBounds.maxY + 160,
        viewBoxContentBounds.maxY + 180,
        viewBoxFlowCallBounds.maxY + 180,
        viewBoxTopLevelEdgeBounds.maxY + 180,
      ),
    },
  };
}

function expandedScopesForInput(
  input: ViewerLayoutInput,
  scopeInputs: readonly { name: string }[],
): Set<string> {
  const available = new Set(scopeInputs.map(scope => scope.name));
  const requestedScopes = input.expandedScopes;
  const ordered = (requestedScopes === undefined ? [input.scope] : [...requestedScopes]).filter(
    scope => !available.size || available.has(scope) || scope === input.scope,
  );
  const expanded = new Set(ordered);
  if (!expanded.size && requestedScopes === undefined) expanded.add(input.scope);
  return expanded;
}

function progressiveSectionSeeds(
  input: ViewerLayoutInput,
  expandedScopes: ReadonlySet<string>,
  progressiveOptions: ProgressiveLayoutOptions,
): ProgressiveSectionSeed[] {
  if (!input.payload) {
    const layers = input.layers ?? [];
    if (!layers.flat().length) return [];
    const preliminaryFlowById = new Map(layers.flat().map(flow => [flow.id, flow]));
    const preliminaryLayerById = new Map(
      layers.flatMap((layer, layerIndex) => layer.map(flow => [flow.id, layerIndex] as const)),
    );
    const openedCallGroups = openedCallChildGroups(
      preliminaryFlowById,
      preliminaryLayerById,
      input.routeFlowIds ?? [],
      progressiveOptions,
    );
    const reservedExpandedMeasures = reserveOpenedCallChildSpace(
      input.expandedMeasures,
      openedCallGroups,
      progressiveOptions,
    );
    return [
      {
        entryFlowIds: layers[0]?.map(flow => flow.id) ?? [],
        flowById: preliminaryFlowById,
        layout: layoutProgressiveRows(layers, {
          ...progressiveOptions,
          expandedMeasures: reservedExpandedMeasures,
        }),
        openedCallGroups,
        scope: input.scope,
      },
    ];
  }

  const flowIndex = new Map(input.payload.flows.map(flow => [flow.id, flow]));
  return [...expandedScopes]
    .map(scope => {
      const routeFlowIds = routeFlowIdsForScope(
        input.routeFlowIds ?? [],
        flowIndex,
        scope,
      );
      const model = buildProgressiveModel(
        input.payload as LogicChartPayload,
        scope,
        routeFlowIds,
        contextFlowIdsForScope(input.contextFlowIds ?? [], flowIndex, scope),
      );
      const layers = model.layers;
      if (!layers.flat().length) return null;
      const preliminaryFlowById = new Map(layers.flat().map(flow => [flow.id, flow]));
      const preliminaryLayerById = new Map(
        layers.flatMap((layer, layerIndex) => layer.map(flow => [flow.id, layerIndex] as const)),
      );
      const openedCallGroups = openedCallChildGroups(
        preliminaryFlowById,
        preliminaryLayerById,
        routeFlowIds,
        progressiveOptions,
      );
      const reservedExpandedMeasures = reserveOpenedCallChildSpace(
        input.expandedMeasures,
        openedCallGroups,
        progressiveOptions,
      );
      return {
        entryFlowIds: model.entryFlowIds,
        flowById: preliminaryFlowById,
        layout: layoutProgressiveRows(layers, {
          ...progressiveOptions,
          expandedMeasures: reservedExpandedMeasures,
        }),
        openedCallGroups,
        scope,
      };
    })
    .filter((seed): seed is ProgressiveSectionSeed => seed !== null);
}

function contextFlowIdsForScope(
  contextFlowIds: readonly string[],
  flowIndex: ReadonlyMap<string, LogicChartFlow>,
  scope: string,
): string[] {
  return contextFlowIds.filter(flowId => {
    const flow = flowIndex.get(flowId);
    return flow ? scopeNamesForFlow(flow).includes(scope) : false;
  });
}

function routeFlowIdsForScope(
  routeFlowIds: readonly string[],
  flowIndex: ReadonlyMap<string, LogicChartFlow>,
  scope: string,
): string[] {
  return routeFlowIds.filter(flowId => {
    const flow = flowIndex.get(flowId);
    return flow ? scopeNamesForFlow(flow).includes(scope) : false;
  });
}

function placeProgressiveSections(
  seeds: readonly ProgressiveSectionSeed[],
  scopeNodes: readonly ScopeLayoutPosition[],
  topY: number,
  options: ProgressiveLayoutOptions,
): Array<{
  offsetX: number;
  offsetY: number;
  seed: ProgressiveSectionSeed;
}> {
  const scopeByName = new Map(scopeNodes.map(scope => [scope.scope, scope]));
  const gapX = Math.max(180, options.gapX * 2);
  const rowGapY = Math.max(220, options.layerGap * 0.7);
  const rows = progressiveSectionRows(seeds, scopeByName);
  const placements: Array<{
    offsetX: number;
    offsetY: number;
    seed: ProgressiveSectionSeed;
  }> = [];
  let cursorTop = topY;

  rows.forEach(row => {
    const rowTop = Math.max(
      cursorTop,
      topY,
      ...row.map(seed => {
        const scopeNode = scopeByName.get(seed.scope);
        return scopeNode ? scopeNode.y + scopeNode.height / 2 + 150 : topY;
      }),
    );
    let cursorRight = Number.NEGATIVE_INFINITY;
    let rowBottom = rowTop;

    row.forEach(seed => {
      const { bounds, localCenterX, sectionHeight, sectionWidth } =
        progressiveSectionGeometry(seed, options);
      const desiredCenter = scopeByName.get(seed.scope)?.x ?? localCenterX;
      const center =
        cursorRight === Number.NEGATIVE_INFINITY
          ? desiredCenter
          : Math.max(desiredCenter, cursorRight + gapX + sectionWidth / 2);
      cursorRight = center + sectionWidth / 2;
      rowBottom = Math.max(rowBottom, rowTop + sectionHeight);
      placements.push({
        offsetX: center - localCenterX,
        offsetY: rowTop - bounds.minY,
        seed,
      });
    });

    cursorTop = rowBottom + rowGapY;
  });

  return placements;
}

function progressiveSectionRows(
  seeds: readonly ProgressiveSectionSeed[],
  scopeByName: ReadonlyMap<string, ScopeLayoutPosition>,
): ProgressiveSectionSeed[][] {
  const sorted = [...seeds].sort((a, b) => {
    const scopeA = scopeByName.get(a.scope);
    const scopeB = scopeByName.get(b.scope);
    const ay = scopeA?.y ?? 0;
    const by = scopeB?.y ?? 0;
    const ax = scopeA?.x ?? 0;
    const bx = scopeB?.x ?? 0;
    return ay - by || ax - bx || a.scope.localeCompare(b.scope);
  });
  const rows: ProgressiveSectionSeed[][] = [];
  sorted.forEach(seed => {
    const scope = scopeByName.get(seed.scope);
    const y = scope?.y ?? 0;
    const existing = rows.find(row => {
      const rowScope = scopeByName.get(row[0]?.scope);
      return Math.abs((rowScope?.y ?? 0) - y) < 1;
    });
    if (existing) {
      existing.push(seed);
      existing.sort((a, b) => {
        const ax = scopeByName.get(a.scope)?.x ?? 0;
        const bx = scopeByName.get(b.scope)?.x ?? 0;
        return ax - bx || a.scope.localeCompare(b.scope);
      });
      return;
    }
    rows.push([seed]);
  });
  return rows;
}

function progressiveSectionGeometry(
  seed: ProgressiveSectionSeed,
  options: ProgressiveLayoutOptions,
): {
  bounds: Bounds;
  localCenterX: number;
  sectionHeight: number;
  sectionWidth: number;
} {
  const bounds = seed.layout.bounds;
  return {
    bounds,
    localCenterX: (bounds.minX + bounds.maxX) / 2,
    sectionHeight: Math.max(options.flowHeight, bounds.maxY - bounds.minY) + options.decisionPad * 2,
    sectionWidth: Math.max(options.flowWidth, bounds.maxX - bounds.minX) + options.decisionPad * 2,
  };
}

function layoutRootNode(
  scopes: readonly ScopeLayoutPosition[],
  inputs: readonly { flowCount: number }[],
): RootNodePosition {
  const scopeBounds = boundsForScopes(scopes);
  const width = 240;
  const height = 84;
  return {
    flowCount: inputs.reduce((sum, item) => sum + item.flowCount, 0),
    height,
    id: ROOT_NODE_ID,
    label: ROOT_NODE_ID,
    scopeCount: scopes.length,
    width,
    x: (scopeBounds.minX + scopeBounds.maxX) / 2,
    y: scopeBounds.minY - height / 2 - 80,
  };
}

function resolveRootScopeCollisions(
  rootNode: RootNodePosition,
  scopeNodes: readonly ScopeLayoutPosition[],
  manualNodePositions: ReadonlyMap<string, ManualNodePosition> | undefined,
): {
  rootNode: RootNodePosition;
  scopeNodes: ScopeLayoutPosition[];
} {
  const structuralNodes: StructuralCollisionNode[] = [
    {
      ...rootNode,
      id: rootNode.id,
      kind: "root",
      manual: manualNodePositions?.has(viewerNodeKey("root", rootNode.id)) ?? false,
    },
    ...scopeNodes.map((scope, scopeIndex) => ({
      ...scope,
      id: scope.scope,
      kind: "scope" as const,
      manual: manualNodePositions?.has(viewerNodeKey("scope", scope.scope)) ?? false,
      scopeIndex,
    })),
  ];

  for (let pass = 0; pass < STRUCTURAL_COLLISION_MAX_PASSES; pass += 1) {
    let changed = false;
    const sorted = [...structuralNodes].sort(
      (a, b) => a.y - b.y || a.x - b.x || structuralSortKey(a).localeCompare(structuralSortKey(b)),
    );

    for (let i = 0; i < sorted.length; i += 1) {
      for (let j = i + 1; j < sorted.length; j += 1) {
        const first = sorted[i];
        const second = sorted[j];
        if (
          !boxesOverlap(
            structuralLayoutBox(first),
            structuralLayoutBox(second),
            STRUCTURAL_COLLISION_GAP,
          )
        ) {
          continue;
        }
        const mover = structuralCollisionMover(first, second);
        const obstacle = mover === first ? second : first;
        if (moveStructuralNodePast(mover, obstacle)) changed = true;
      }
    }

    if (!changed) break;
  }

  const resolvedRoot = structuralNodes.find(node => node.kind === "root");
  const resolvedScopes = scopeNodes.map((scope, scopeIndex) => {
    const resolved = structuralNodes.find(
      node => node.kind === "scope" && node.scopeIndex === scopeIndex,
    );
    return resolved ? { ...scope, x: resolved.x, y: resolved.y } : scope;
  });

  return {
    rootNode: resolvedRoot ? { ...rootNode, x: resolvedRoot.x, y: resolvedRoot.y } : rootNode,
    scopeNodes: resolvedScopes,
  };
}

function structuralSortKey(node: StructuralCollisionNode): string {
  return `${node.kind}:${node.id}`;
}

function structuralCollisionMover(
  first: StructuralCollisionNode,
  second: StructuralCollisionNode,
): StructuralCollisionNode {
  if (first.kind !== second.kind) {
    if (first.kind === "root") return first.manual && !second.manual ? second : first;
    return second.manual && !first.manual ? first : second;
  }
  if (first.manual !== second.manual) return first.manual ? second : first;
  return first.y > second.y || (first.y === second.y && first.x >= second.x) ? first : second;
}

function moveStructuralNodePast(
  mover: StructuralCollisionNode,
  obstacle: StructuralCollisionNode,
): boolean {
  const obstacleBox = structuralLayoutBox(obstacle);
  const desiredY =
    mover.kind === "root"
      ? obstacleBox.minY - STRUCTURAL_COLLISION_GAP - mover.height / 2
      : obstacleBox.maxY + STRUCTURAL_COLLISION_GAP + mover.height / 2;
  if (Math.abs(desiredY - mover.y) <= 0.5) return false;
  mover.y = desiredY;
  return true;
}

function structuralLayoutBox(node: StructuralCollisionNode): LayoutBox {
  return {
    id: node.id,
    kind: node.kind,
    maxX: node.x + node.width / 2,
    maxY: node.y + node.height / 2,
    minX: node.x - node.width / 2,
    minY: node.y - node.height / 2,
  };
}

function rootScopeEdges(
  root: RootNodePosition,
  scopes: readonly ScopeLayoutPosition[],
  obstacles: readonly LayoutBox[] = [],
): RootScopeEdge[] {
  const startY = root.y + root.height / 2;
  return [...scopes]
    .sort((a, b) => a.x - b.x || a.scope.localeCompare(b.scope))
    .map((scope, index, sorted) => {
      const endY = scope.y - scope.height / 2;
      const available = Math.max(48, endY - startY);
      const fanoutOffset = (index - (sorted.length - 1) / 2) * 8;
      const startX = root.x + fanoutOffset;
      const preferredLaneY = startY + Math.min(84, Math.max(38, available * 0.5));
      const laneY = obstacleAwareElbowLane({
        endX: scope.x,
        endY,
        ignored: new Set([root.id, scope.scope]),
        maxLaneY: Math.max(startY, endY) - 24,
        minLaneY: Math.min(startY, endY) + 24,
        obstacles,
        preferredLaneY,
        startX,
        startY,
      });
      const ignored = new Set([root.id, scope.scope]);
      const elbowRoute = elbowPoints(startX, startY, scope.x, endY, laneY);
      const clearRoute =
        edgeObstacleHits(
          `${root.id}->${scope.scope}`,
          "root-scope",
          elbowRoute,
          obstacles,
          ignored,
          FLOW_CALL_OBSTACLE_GAP,
        ).length === 0
          ? elbowRoute
          : topLevelSideRoute(
              { x: startX, y: startY },
              { x: scope.x, y: endY },
              obstacles,
              ignored,
            ) ?? elbowRoute;
      const curveY = Math.max(54, available * 0.65);
      return {
        d: pathForPoints(clearRoute),
        focusD: `M ${startX} ${startY} C ${startX} ${startY + curveY}, ${scope.x} ${
          endY - curveY
        }, ${scope.x} ${endY}`,
        points: clearRoute,
        scope: scope.scope,
      };
    });
}

function routedScopeEntryEdges(
  scopeNode: ScopeNodePosition,
  entries: readonly LayoutNodePosition[],
  flowHeight: number,
  obstacles: readonly LayoutBox[],
): ScopeEntryEdge[] {
  const baseEdges = scopeEntryEdges(scopeNode, entries, flowHeight);
  const entryById = new Map(entries.map(entry => [entry.id, entry]));
  return baseEdges.map(edge => {
    const entry = entryById.get(edge.target);
    const start = edge.points[0];
    const end = edge.points[3];
    if (!entry || !start || !end) return edge;
    const preferredLaneY = edge.points[1]?.y ?? (start.y + end.y) / 2;
    const available = Math.max(80, Math.abs(end.y - start.y));
    const edgeId = `${scopeNode.scope}->${entry.id}`;
    const ignored = new Set([scopeNode.scope, entry.id, `${entry.id}:detail`]);
    const laneY = obstacleAwareElbowLane({
      endX: entry.x,
      endY: end.y,
      ignored,
      maxLaneY: Math.max(start.y, end.y) - 24,
      minLaneY: Math.min(start.y, end.y) + 24,
      obstacles,
      preferredLaneY,
      startX: start.x,
      startY: start.y,
    });
    const elbowRoute = elbowPoints(start.x, start.y, entry.x, end.y, laneY);
    const clearRoute =
      edgeObstacleHits(
        edgeId,
        "scope-entry",
        elbowRoute,
        obstacles,
        ignored,
        FLOW_CALL_OBSTACLE_GAP,
      ).length === 0
        ? elbowRoute
        : topLevelSideRoute(start, end, obstacles, ignored) ?? elbowRoute;
    const curveY = Math.max(70, available * 0.55);
    return {
      ...edge,
      d: pathForPoints(clearRoute),
      focusD: `M ${start.x} ${start.y} C ${start.x} ${start.y + curveY}, ${entry.x} ${
        end.y - curveY
      }, ${entry.x} ${end.y}`,
      points: clearRoute,
    };
  });
}

function progressiveFlowCallEdges(
  flowById: ReadonlyMap<string, ProgressiveFlowNode>,
  positions: ReadonlyMap<string, LayoutNodePosition>,
  sourceExitYs: ReadonlyMap<string, number>,
  obstacles: readonly LayoutBox[],
  options: { avoidObstacles?: boolean } = {},
): FlowCallEdge[] {
  const pairs: FlowCallPair[] = [];
  const visibleTargetsByCaller = visibleCallTargetsByCaller(flowById);
  flowById.forEach(flow => {
    if (!isLogicChartFlow(flow)) return;
    const source = positions.get(flow.id);
    if (!source) return;
    visibleCallTargetIds(flow, flowById, visibleTargetsByCaller).forEach(targetId => {
      const target = positions.get(targetId);
      if (!target) return;
      const sourceBottomY = source.y + source.height / 2;
      const targetTopY = target.y - target.height / 2;
      const sourceExitY = Math.max(sourceBottomY, sourceExitYs.get(flow.id) ?? sourceBottomY);
      pairs.push({
        source,
        startY: sourceExitY,
        target,
        targetTopY,
      });
    });
  });
  const sortedPairs = pairs.sort(
    (a, b) =>
      a.startY - b.startY ||
      a.targetTopY - b.targetTopY ||
      a.source.x - b.source.x ||
      a.target.x - b.target.x ||
      a.source.id.localeCompare(b.source.id) ||
      a.target.id.localeCompare(b.target.id),
  );
  if (options.avoidObstacles === false) {
    return sortedPairs.map(routeOverviewFlowCallEdge);
  }
  const verticalGroups = new Map<string, typeof sortedPairs>();
  const lateralGroups = new Map<string, typeof sortedPairs>();
  sortedPairs.forEach(pair => {
    const group = isVerticalFlowCall(pair)
      ? verticalGroups
      : lateralGroups;
    const key = flowCallLaneKey(pair);
    const items = group.get(key) || [];
    items.push(pair);
    group.set(key, items);
  });

  const edges: FlowCallEdge[] = [];
  verticalGroups.forEach(group => {
    const lanes = verticalLaneYs(group, obstacles);
    group.forEach((pair, index) => {
      edges.push(routeVerticalFlowCallEdge(pair, lanes[index], obstacles));
    });
  });
  lateralGroups.forEach(group => {
    const lanes = lateralLaneYs(group, obstacles);
    group.forEach((pair, index) => {
      edges.push(routeLateralFlowCallEdge(pair, lanes[index], obstacles));
    });
  });
  return edges.sort(
    (a, b) =>
      (positions.get(a.source)?.y || 0) - (positions.get(b.source)?.y || 0) ||
      (positions.get(a.source)?.x || 0) - (positions.get(b.source)?.x || 0) ||
      a.target.localeCompare(b.target),
  );
}

function routeOverviewFlowCallEdge(pair: FlowCallPair): FlowCallEdge {
  const { source, startY, target, targetTopY } = pair;
  const endY = targetTopY > startY ? targetTopY : target.y + target.height / 2;
  const laneY =
    targetTopY > startY
      ? startY + Math.max(80, (targetTopY - startY) * 0.45)
      : (startY + endY) / 2;
  const points = elbowPoints(source.x, startY, target.x, endY, laneY);
  return {
    source: source.id,
    target: target.id,
    d: pathForPoints(points),
    focusD: `M ${source.x} ${startY} C ${source.x} ${laneY}, ${target.x} ${laneY}, ${target.x} ${endY}`,
    points,
  };
}

function visibleCallTargetIds(
  flow: LogicChartFlow,
  visibleFlowById: ReadonlyMap<string, ProgressiveFlowNode>,
  visibleTargetsByCaller: ReadonlyMap<string, ReadonlySet<string>>,
): string[] {
  const targetIds = new Set<string>();
  (flow.calls || []).forEach(targetId => {
    if (visibleFlowById.has(targetId) && targetId !== flow.id) targetIds.add(targetId);
  });
  visibleTargetsByCaller.get(flow.id)?.forEach(targetId => targetIds.add(targetId));
  return [...targetIds].sort();
}

function visibleCallTargetsByCaller(
  visibleFlowById: ReadonlyMap<string, ProgressiveFlowNode>,
): Map<string, Set<string>> {
  const targetsByCaller = new Map<string, Set<string>>();
  visibleFlowById.forEach(candidate => {
    if (!isLogicChartFlow(candidate)) return;
    (candidate.called_by || []).forEach(callerId => {
      if (callerId === candidate.id || !visibleFlowById.has(callerId)) return;
      const targets = targetsByCaller.get(callerId) || new Set<string>();
      targets.add(candidate.id);
      targetsByCaller.set(callerId, targets);
    });
  });
  return targetsByCaller;
}

function openedCallChildGroups(
  flowById: ReadonlyMap<string, ProgressiveFlowNode>,
  layerById: ReadonlyMap<string, number>,
  routeFlowIds: readonly string[],
  options: ProgressiveLayoutOptions,
): OpenedCallChildGroup[] {
  const claimedChildren = new Set<string>();
  const explicitlyOpened = new Set(routeFlowIds);
  return routeFlowIds
    .map(parentId => {
      const parent = flowById.get(parentId);
      if (!parent || !isLogicChartFlow(parent)) return null;
      const parentLayer = layerById.get(parentId) ?? 0;
      const children = (parent.calls || []).filter(childId => {
        const child = flowById.get(childId);
        if (!child || childId === parentId || claimedChildren.has(childId)) return false;
        // If the target is already opened as a first-class flow, keep that single block
        // in its progressive section and draw the call edge to it instead of nesting it.
        if (explicitlyOpened.has(childId)) return false;
        if ((layerById.get(childId) ?? 0) <= parentLayer) return false;
        return true;
      });
      children.forEach(childId => claimedChildren.add(childId));
      if (!children.length) return null;
      const rows = chunkChildren(children);
      return {
        children,
        parentId,
        rows,
        subtreeHeight: childRowsHeight(rows.length, options),
        subtreeWidth: Math.max(...rows.map(row => childRowWidth(row, options))),
      };
    })
    .filter((group): group is OpenedCallChildGroup => group !== null);
}

function reserveOpenedCallChildSpace(
  measures: ReadonlyMap<string, ExpandedFlowMeasure> | undefined,
  groups: readonly OpenedCallChildGroup[],
  options: ProgressiveLayoutOptions,
): ReadonlyMap<string, ExpandedFlowMeasure> | undefined {
  if (!groups.length) return measures;
  const next = new Map(measures ? [...measures] : []);
  groups.forEach(group => {
    const current = next.get(group.parentId);
    const base = current ?? {
      height: options.flowHeight,
      maxX: options.flowWidth / 2,
      maxY: options.flowHeight,
      minX: -options.flowWidth / 2,
      minY: 0,
      width: options.flowWidth,
    };
    const centerX = (base.minX + base.maxX) / 2;
    const width = Math.max(base.width, group.subtreeWidth);
    const halfWidth = width / 2;
    const minY = base.minY;
    const maxY = Math.max(
      base.maxY,
      base.maxY + CALL_CHILD_GAP_Y + group.subtreeHeight,
    );
    next.set(group.parentId, {
      height: maxY - minY,
      maxX: centerX + halfWidth,
      maxY,
      minX: centerX - halfWidth,
      minY,
      width,
    });
  });
  return next;
}

function attachOpenedCallChildren({
  anchors,
  groups,
  measures,
  options,
  positions,
}: {
  anchors: ReadonlyMap<string, AbsoluteInlineAnchor>;
  groups: readonly OpenedCallChildGroup[];
  measures: ReadonlyMap<string, ExpandedFlowMeasure> | undefined;
  options: ProgressiveLayoutOptions;
  positions: ReadonlyMap<string, LayoutNodePosition>;
}): Map<string, LayoutNodePosition> {
  if (!groups.length) return new Map(positions);
  const next = new Map(positions);
  groups.forEach(group => {
    const parentPosition = next.get(group.parentId);
    const anchor = anchors.get(group.parentId);
    if (!parentPosition || !anchor) return;
    const detailMeasure = measures?.get(group.parentId);
    const detailBottom = detailMeasure
      ? anchor.y + detailMeasure.maxY
      : parentPosition.y + parentPosition.height / 2;
    group.rows.forEach((row, rowIndex) => {
      const rowWidth = childRowWidth(row, options);
      const rowY =
        detailBottom +
        CALL_CHILD_GAP_Y +
        rowIndex * (options.flowHeight + CALL_CHILD_ROW_GAP_Y) +
        options.flowHeight / 2;
      let cursorX = parentPosition.x - rowWidth / 2;
      row.forEach(childId => {
        const child = next.get(childId);
        if (!child || child.layer <= parentPosition.layer) return;
        next.set(childId, {
          ...child,
          x: cursorX + options.flowWidth / 2,
          y: rowY,
        });
        cursorX += options.flowWidth + options.gapX;
      });
    });
  });
  return next;
}

function resolveDetailContentCollisions(
  positions: ReadonlyMap<string, LayoutNodePosition>,
  anchors: readonly InlineAnchor[],
  staticObstacles: readonly LayoutBox[] = [],
  options: { skipFlowPairCollisions?: boolean } = {},
): {
  flowPositions: Map<string, LayoutNodePosition>;
  inlineAnchors: InlineAnchor[];
} {
  if (!anchors.length && !staticObstacles.length) {
    return {
      flowPositions: new Map(positions),
      inlineAnchors: [...anchors],
    };
  }

  const nextPositions = new Map(positions);
  const nextAnchors = anchors.map(anchor => ({
    ...anchor,
    bounds: { ...anchor.bounds },
  }));
  const anchorByFlowId = new Map(nextAnchors.map(anchor => [anchor.flowId, anchor]));
  const shiftFlow = (flowId: string, dy: number): boolean => {
    if (dy <= 0.5) return false;
    const position = nextPositions.get(flowId);
    if (!position) return false;
    nextPositions.set(flowId, {
      ...position,
      y: position.y + dy,
    });
    const anchor = anchorByFlowId.get(flowId);
    if (anchor) {
      anchor.y += dy;
      anchor.bounds = offsetBounds(anchor.bounds, 0, dy);
    }
    return true;
  };

  for (let pass = 0; pass < DETAIL_CONTENT_COLLISION_MAX_PASSES; pass += 1) {
    let changed = false;
    const sortedAnchors = [...nextAnchors].sort(
      (a, b) =>
        a.bounds.minY - b.bounds.minY ||
        a.bounds.minX - b.bounds.minX ||
        a.flowId.localeCompare(b.flowId),
    );
    const flowIds = [...nextPositions.keys()].sort((a, b) => {
      const left = nextPositions.get(a);
      const right = nextPositions.get(b);
      return (
        (left?.y ?? 0) - (right?.y ?? 0) ||
        (left?.x ?? 0) - (right?.x ?? 0) ||
        a.localeCompare(b)
      );
    });
    const sortedStaticObstacles = [...staticObstacles].sort(
      (a, b) =>
        a.minY - b.minY ||
        a.minX - b.minX ||
        a.id.localeCompare(b.id),
    );

    sortedStaticObstacles.forEach(obstacle => {
      flowIds.forEach(flowId => {
        if (flowId === obstacle.id) return;
        const position = nextPositions.get(flowId);
        if (!position) return;
        const flowBox = flowLayoutBox(position);
        if (!boxesOverlap(obstacle, flowBox, DETAIL_CONTENT_COLLISION_GAP)) return;
        const dy =
          obstacle.maxY +
          DETAIL_CONTENT_COLLISION_GAP +
          position.height / 2 -
          position.y;
        if (shiftFlow(flowId, dy)) changed = true;
      });
    });

    sortedAnchors.forEach(anchor => {
      const detailBox = detailLayoutBox(anchor);
      flowIds.forEach(flowId => {
        if (flowId === anchor.flowId) return;
        const position = nextPositions.get(flowId);
        if (!position) return;
        const flowBox = flowLayoutBox(position);
        if (!boxesOverlap(detailBox, flowBox, DETAIL_CONTENT_COLLISION_GAP)) return;
        const dy =
          detailBox.maxY +
          DETAIL_CONTENT_COLLISION_GAP +
          position.height / 2 -
          position.y;
        if (shiftFlow(flowId, dy)) changed = true;
      });
    });

    for (let i = 0; i < sortedAnchors.length; i += 1) {
      for (let j = i + 1; j < sortedAnchors.length; j += 1) {
        const upper = sortedAnchors[i];
        const lower = sortedAnchors[j];
        if (upper.flowId === lower.flowId) continue;
        const upperBox = detailLayoutBox(upper);
        const lowerBox = detailLayoutBox(lower);
        if (!boxesOverlap(upperBox, lowerBox, DETAIL_CONTENT_COLLISION_GAP)) continue;
        const dy =
          upperBox.maxY +
          DETAIL_CONTENT_COLLISION_GAP -
          lowerBox.minY;
        if (shiftFlow(lower.flowId, dy)) changed = true;
      }
    }

    if (!options.skipFlowPairCollisions) {
      const sortedFlowIds = [...nextPositions.keys()].sort((a, b) => {
        const left = nextPositions.get(a);
        const right = nextPositions.get(b);
        return (
          (left?.y ?? 0) - (right?.y ?? 0) ||
          (left?.x ?? 0) - (right?.x ?? 0) ||
          a.localeCompare(b)
        );
      });
      for (let i = 0; i < sortedFlowIds.length; i += 1) {
        for (let j = i + 1; j < sortedFlowIds.length; j += 1) {
          const upper = nextPositions.get(sortedFlowIds[i]);
          const lower = nextPositions.get(sortedFlowIds[j]);
          if (!upper || !lower) continue;
          const upperBox = flowLayoutBox(upper);
          const lowerBox = flowLayoutBox(lower);
          if (!boxesOverlap(upperBox, lowerBox, DETAIL_CONTENT_COLLISION_GAP)) continue;
          const dy =
            upperBox.maxY +
            DETAIL_CONTENT_COLLISION_GAP +
            lower.height / 2 -
            lower.y;
          if (shiftFlow(lower.id, dy)) changed = true;
        }
      }
    }

    if (!changed) break;
  }

  return {
    flowPositions: nextPositions,
    inlineAnchors: nextAnchors,
  };
}

function detailLayoutBox(anchor: InlineAnchor): LayoutBox {
  return {
    id: `${anchor.flowId}:detail`,
    kind: "detail",
    maxX: anchor.bounds.maxX,
    maxY: anchor.bounds.maxY,
    minX: anchor.bounds.minX,
    minY: anchor.bounds.minY,
  };
}

function flowLayoutBox(position: LayoutNodePosition): LayoutBox {
  return {
    id: position.id,
    kind: "flow",
    maxX: position.x + position.width / 2,
    maxY: position.y + position.height / 2,
    minX: position.x - position.width / 2,
    minY: position.y - position.height / 2,
  };
}

function chunkChildren(children: readonly string[]): string[][] {
  const perRow = Math.max(1, Math.min(MAX_CALL_CHILDREN_PER_ROW, children.length));
  const rows: string[][] = [];
  for (let index = 0; index < children.length; index += perRow) {
    rows.push([...children.slice(index, index + perRow)]);
  }
  return rows;
}

function childRowWidth(row: readonly string[], options: ProgressiveLayoutOptions): number {
  if (!row.length) return 0;
  return (
    row.length * options.flowWidth +
    Math.max(0, row.length - 1) * options.gapX
  );
}

function childRowsHeight(rowCount: number, options: ProgressiveLayoutOptions): number {
  if (rowCount <= 0) return 0;
  return (
    rowCount * options.flowHeight +
    Math.max(0, rowCount - 1) * CALL_CHILD_ROW_GAP_Y
  );
}

function routeVerticalFlowCallEdge(
  pair: FlowCallPair,
  laneY: number,
  obstacles: readonly LayoutBox[] = [],
): FlowCallEdge {
  const { source, startY, target, targetTopY: endY } = pair;
  const curveY = Math.max(70, (endY - startY) * 0.5);
  const points = clearFlowCallPoints(
    source.id,
    target.id,
    elbowPoints(source.x, startY, target.x, endY, laneY),
    obstacles,
  );
  return {
    source: source.id,
    target: target.id,
    d: pathForPoints(points),
    focusD: `M ${source.x} ${startY} C ${source.x} ${startY + curveY}, ${target.x} ${
      endY - curveY
    }, ${target.x} ${endY}`,
    points,
  };
}

function routeLateralFlowCallEdge(
  pair: FlowCallPair,
  laneY: number,
  obstacles: readonly LayoutBox[] = [],
): FlowCallEdge {
  const { source, startY, target } = pair;
  const endY = target.y + target.height / 2;
  const points = clearFlowCallPoints(
    source.id,
    target.id,
    elbowPoints(source.x, startY, target.x, endY, laneY),
    obstacles,
  );
  return {
    source: source.id,
    target: target.id,
    d: pathForPoints(points),
    focusD: `M ${source.x} ${startY} C ${source.x} ${laneY}, ${target.x} ${laneY}, ${target.x} ${endY}`,
    points,
  };
}

function clearFlowCallPoints(
  sourceId: string,
  targetId: string,
  points: Array<{ x: number; y: number }>,
  obstacles: readonly LayoutBox[],
): Array<{ x: number; y: number }> {
  if (!obstacles.length) return points;
  const ignored = new Set([sourceId, `${sourceId}:detail`, targetId]);
  const edgeId = `${sourceId}->${targetId}`;
  if (
    !edgeObstacleHits(
      edgeId,
      "flow-call",
      points,
      obstacles,
      ignored,
      FLOW_CALL_OBSTACLE_GAP,
    ).length
  ) {
    return points;
  }
  const start = points[0];
  const end = points[points.length - 1];
  return (
    topLevelSideRoute(start, end, obstacles, ignored) ??
    orthogonalFlowCallRoute(sourceId, targetId, start, end, obstacles, ignored) ??
    outerFlowCallRoute(sourceId, targetId, start, end, obstacles, ignored) ??
    points
  );
}

function orthogonalFlowCallRoute(
  sourceId: string,
  targetId: string,
  start: { x: number; y: number },
  end: { x: number; y: number },
  obstacles: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
): Array<{ x: number; y: number }> | null {
  const boxes = relevantFlowCallRoutingBoxes(start, end, obstacles, ignored);
  if (!boxes.length) return null;
  const padding = FLOW_CALL_OBSTACLE_GAP + 44;
  const xs = routeAxisCandidates(start.x, end.x, boxes, "x", padding);
  const ys = routeAxisCandidates(start.y, end.y, boxes, "y", padding);
  const startKey = routePointKey(start.x, start.y);
  const endKey = routePointKey(end.x, end.y);
  const edgeId = `${sourceId}->${targetId}`;
  const best = new Map<
    string,
    {
      cost: number;
      direction?: RouteDirection;
      point: { x: number; y: number };
      previous?: string;
    }
  >();
  const queue: string[] = [startKey];
  best.set(startKey, { cost: 0, point: start });

  while (queue.length) {
    queue.sort((left, right) => (best.get(left)?.cost ?? 0) - (best.get(right)?.cost ?? 0));
    const key = queue.shift();
    if (!key) break;
    const current = best.get(key);
    if (!current) continue;
    if (key === endKey) return compressRoutePoints(reconstructRoute(best, endKey));

    routeNeighbors(current.point, xs, ys).forEach(nextPoint => {
      const direction: RouteDirection = nextPoint.x === current.point.x ? "v" : "h";
      if (
        edgeObstacleHits(
          edgeId,
          "flow-call",
          [current.point, nextPoint],
          obstacles,
          ignored,
          FLOW_CALL_OBSTACLE_GAP,
        ).length
      ) {
        return;
      }
      const nextKey = routePointKey(nextPoint.x, nextPoint.y);
      const distance = Math.abs(nextPoint.x - current.point.x) + Math.abs(nextPoint.y - current.point.y);
      const bendPenalty = current.direction && current.direction !== direction ? 180 : 0;
      const nextCost = current.cost + distance + bendPenalty;
      const existing = best.get(nextKey);
      if (existing && existing.cost <= nextCost) return;
      best.set(nextKey, {
        cost: nextCost,
        direction,
        point: nextPoint,
        previous: key,
      });
      if (!queue.includes(nextKey)) queue.push(nextKey);
    });
  }

  return null;
}

function relevantFlowCallRoutingBoxes(
  start: { x: number; y: number },
  end: { x: number; y: number },
  obstacles: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
): LayoutBox[] {
  const margin = 900;
  const minX = Math.min(start.x, end.x) - margin;
  const maxX = Math.max(start.x, end.x) + margin;
  const minY = Math.min(start.y, end.y) - margin;
  const maxY = Math.max(start.y, end.y) + margin;
  const boxes = obstacles.filter(
    box =>
      !ignored.has(box.id) &&
      rangesOverlap(minX, maxX, box.minX, box.maxX) &&
      rangesOverlap(minY, maxY, box.minY, box.maxY),
  );
  return boxes.length ? boxes : obstacles.filter(box => !ignored.has(box.id));
}

function routeAxisCandidates(
  start: number,
  end: number,
  boxes: readonly LayoutBox[],
  axis: "x" | "y",
  padding: number,
): number[] {
  const values = [start, end];
  boxes.forEach(box => {
    if (axis === "x") {
      values.push(box.minX - padding, box.maxX + padding);
    } else {
      values.push(box.minY - padding, box.maxY + padding);
    }
  });
  return uniqueSortedNumbers(values);
}

function routeNeighbors(
  point: { x: number; y: number },
  xs: readonly number[],
  ys: readonly number[],
): Array<{ x: number; y: number }> {
  const neighbors: Array<{ x: number; y: number }> = [];
  const xIndex = indexOfRouteAxis(xs, point.x);
  const yIndex = indexOfRouteAxis(ys, point.y);
  if (xIndex > 0) neighbors.push({ x: xs[xIndex - 1], y: point.y });
  if (xIndex >= 0 && xIndex < xs.length - 1) neighbors.push({ x: xs[xIndex + 1], y: point.y });
  if (yIndex > 0) neighbors.push({ x: point.x, y: ys[yIndex - 1] });
  if (yIndex >= 0 && yIndex < ys.length - 1) neighbors.push({ x: point.x, y: ys[yIndex + 1] });
  return neighbors;
}

function indexOfRouteAxis(values: readonly number[], value: number): number {
  return values.findIndex(item => Math.abs(item - value) < 0.5);
}

function reconstructRoute(
  records: ReadonlyMap<
    string,
    {
      point: { x: number; y: number };
      previous?: string;
    }
  >,
  endKey: string,
): Array<{ x: number; y: number }> {
  const points: Array<{ x: number; y: number }> = [];
  let currentKey: string | undefined = endKey;
  while (currentKey) {
    const current = records.get(currentKey);
    if (!current) break;
    points.unshift(current.point);
    currentKey = current.previous;
  }
  return points;
}

function compressRoutePoints(
  points: readonly { x: number; y: number }[],
): Array<{ x: number; y: number }> {
  if (points.length <= 2) return [...points];
  const compressed: Array<{ x: number; y: number }> = [];
  points.forEach(point => {
    const previous = compressed[compressed.length - 1];
    if (previous && Math.abs(previous.x - point.x) < 0.5 && Math.abs(previous.y - point.y) < 0.5) {
      return;
    }
    compressed.push(point);
    while (compressed.length >= 3) {
      const a = compressed[compressed.length - 3];
      const b = compressed[compressed.length - 2];
      const c = compressed[compressed.length - 1];
      const horizontal = Math.abs(a.y - b.y) < 0.5 && Math.abs(b.y - c.y) < 0.5;
      const vertical = Math.abs(a.x - b.x) < 0.5 && Math.abs(b.x - c.x) < 0.5;
      if (!horizontal && !vertical) break;
      compressed.splice(compressed.length - 2, 1);
    }
  });
  return compressed;
}

function uniqueSortedNumbers(values: readonly number[]): number[] {
  const seen = new Set<string>();
  return [...values]
    .filter(Number.isFinite)
    .sort((left, right) => left - right)
    .filter(value => {
      const key = laneKey(value);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function routePointKey(x: number, y: number): string {
  return `${laneKey(x)}:${laneKey(y)}`;
}

function outerFlowCallRoute(
  sourceId: string,
  targetId: string,
  start: { x: number; y: number },
  end: { x: number; y: number },
  obstacles: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
): Array<{ x: number; y: number }> | null {
  const relevant = obstacles.filter(box => !ignored.has(box.id));
  if (!relevant.length) return null;
  const padding = FLOW_CALL_OBSTACLE_GAP + 80;
  const topY = Math.min(start.y, end.y, ...relevant.map(box => box.minY)) - padding;
  const bottomY = Math.max(start.y, end.y, ...relevant.map(box => box.maxY)) + padding;
  const minX = Math.min(start.x, end.x, ...relevant.map(box => box.minX)) - padding;
  const maxX = Math.max(start.x, end.x, ...relevant.map(box => box.maxX)) + padding;
  const edgeId = `${sourceId}->${targetId}`;
  const routeCandidates = [
    [
      start,
      { x: minX, y: start.y },
      { x: minX, y: end.y },
      end,
    ],
    [
      start,
      { x: maxX, y: start.y },
      { x: maxX, y: end.y },
      end,
    ],
    [
      start,
      { x: start.x, y: topY },
      { x: end.x, y: topY },
      end,
    ],
    [
      start,
      { x: start.x, y: bottomY },
      { x: end.x, y: bottomY },
      end,
    ],
    [
      start,
      { x: minX, y: start.y },
      { x: minX, y: topY },
      { x: end.x, y: topY },
      end,
    ],
    [
      start,
      { x: maxX, y: start.y },
      { x: maxX, y: topY },
      { x: end.x, y: topY },
      end,
    ],
    [
      start,
      { x: minX, y: start.y },
      { x: minX, y: bottomY },
      { x: end.x, y: bottomY },
      end,
    ],
    [
      start,
      { x: maxX, y: start.y },
      { x: maxX, y: bottomY },
      { x: end.x, y: bottomY },
      end,
    ],
    [
      start,
      { x: start.x, y: topY },
      { x: minX, y: topY },
      { x: minX, y: end.y },
      end,
    ],
    [
      start,
      { x: start.x, y: topY },
      { x: maxX, y: topY },
      { x: maxX, y: end.y },
      end,
    ],
    [
      start,
      { x: start.x, y: bottomY },
      { x: minX, y: bottomY },
      { x: minX, y: end.y },
      end,
    ],
    [
      start,
      { x: start.x, y: bottomY },
      { x: maxX, y: bottomY },
      { x: maxX, y: end.y },
      end,
    ],
  ];

  return (
    routeCandidates.find(
      candidate =>
        !edgeObstacleHits(
          edgeId,
          "flow-call",
          candidate,
          obstacles,
          ignored,
          FLOW_CALL_OBSTACLE_GAP,
        ).length,
    ) ?? null
  );
}

function lateralLaneYs(
  group: readonly FlowCallPair[],
  obstacles: readonly LayoutBox[],
): number[] {
  const usedLanes = new Set<string>();
  return group.map((pair, index) => {
    const endY = lateralTargetEndY(pair);
    const minLane = Math.max(pair.startY, endY) + 48;
    const preferred = minLane + 30 + index * 30;
    const candidates = lateralLaneCandidates(pair, preferred, minLane, obstacles);
    const clear = candidates.find(candidate => {
      const key = laneKey(candidate);
      return (
        !usedLanes.has(key) &&
        !flowCallEdgeObstacleHits(
          routeLateralFlowCallEdge(pair, candidate),
          obstacles,
          FLOW_CALL_OBSTACLE_GAP,
        ).length
      );
    });
    const available = clear ?? candidates.find(candidate => !usedLanes.has(laneKey(candidate)));
    const lane = available ?? preferred;
    usedLanes.add(laneKey(lane));
    return lane;
  });
}

function lateralLaneCandidates(
  pair: FlowCallPair,
  preferred: number,
  minLane: number,
  obstacles: readonly LayoutBox[],
): number[] {
  const values: number[] = [preferred];
  const minX = Math.min(pair.source.x, pair.target.x) - FLOW_CALL_OBSTACLE_GAP;
  const maxX = Math.max(pair.source.x, pair.target.x) + FLOW_CALL_OBSTACLE_GAP;
  const ignored = new Set([pair.source.id, `${pair.source.id}:detail`, pair.target.id]);
  const relevantObstacles = obstacles.filter(box => {
    if (ignored.has(box.id)) return false;
    return (
      rangesOverlap(minX, maxX, box.minX, box.maxX) &&
      box.maxY >= minLane - FLOW_CALL_OBSTACLE_GAP
    );
  });
  relevantObstacles.forEach(box => {
    values.push(box.maxY + FLOW_CALL_OBSTACLE_GAP + FLOW_CALL_LANE_STEP);
  });
  const maxRelevantY = Math.max(
    preferred + 240,
    minLane + 240,
    ...relevantObstacles.map(box => box.maxY + FLOW_CALL_OBSTACLE_GAP + 160),
  );
  for (let lane = minLane; lane <= maxRelevantY; lane += FLOW_CALL_LANE_STEP) {
    values.push(lane);
  }
  const seen = new Set<string>();
  return values
    .filter(value => value >= minLane)
    .sort((a, b) => Math.abs(a - preferred) - Math.abs(b - preferred) || a - b)
    .filter(value => {
      const key = laneKey(value);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function lateralTargetEndY(pair: FlowCallPair): number {
  return pair.target.y + pair.target.height / 2;
}

function isVerticalFlowCall(pair: FlowCallPair): boolean {
  return pair.targetTopY - pair.startY > 24;
}

function flowCallLaneKey(pair: FlowCallPair): string {
  if (isVerticalFlowCall(pair)) {
    return `v:${Math.round(pair.startY)}:${Math.round(pair.targetTopY)}`;
  }
  return `l:${Math.round(Math.max(pair.startY, pair.target.y))}`;
}

function verticalLaneYs(
  group: readonly FlowCallPair[],
  obstacles: readonly LayoutBox[],
): number[] {
  if (!group.length) return [];
  if (group.length === 1) {
    const startY = group[0].startY;
    const endY = group[0].targetTopY;
    const minLane = startY + 14;
    const maxLane = endY - 14;
    const preferred = (startY + endY) / 2;
    const lane =
      laneCandidates(preferred, minLane, maxLane).find(
        candidate => !flowCallRouteBlocked(group[0], candidate, obstacles),
      ) ?? preferred;
    return [lane];
  }
  const startY = Math.max(...group.map(pair => pair.startY));
  const endY = Math.min(...group.map(pair => pair.targetTopY));
  const minimumSpacing = 8;
  let minLane = startY + 30;
  let maxLane = endY - 30;
  if (maxLane - minLane < (group.length - 1) * minimumSpacing) {
    minLane = startY + 14;
    maxLane = endY - 14;
  }
  const span = maxLane - minLane;
  if (span <= 0) {
    const fallbackStep = Math.max(1, (endY - startY) / (group.length + 1));
    return group.map((_pair, index) => startY + fallbackStep * (index + 1));
  }
  const preferred = group.map(
    (_pair, index) => minLane + (span * index) / Math.max(1, group.length - 1),
  );
  const usedLanes = new Set<string>();
  return group.map((pair, index) => {
    const candidates = laneCandidates(preferred[index], minLane, maxLane);
    const clear = candidates.find(candidate => {
      const key = laneKey(candidate);
      return !usedLanes.has(key) && !flowCallRouteBlocked(pair, candidate, obstacles);
    });
    const available = clear ?? candidates.find(candidate => !usedLanes.has(laneKey(candidate)));
    const lane = available ?? preferred[index];
    usedLanes.add(laneKey(lane));
    return lane;
  });
}

function obstacleAwareElbowLane({
  endX,
  endY,
  ignored,
  maxLaneY,
  minLaneY,
  obstacles,
  preferredLaneY,
  startX,
  startY,
}: {
  endX: number;
  endY: number;
  ignored: ReadonlySet<string>;
  maxLaneY: number;
  minLaneY: number;
  obstacles: readonly LayoutBox[];
  preferredLaneY: number;
  startX: number;
  startY: number;
}): number {
  const lower = Math.min(minLaneY, maxLaneY);
  const upper = Math.max(minLaneY, maxLaneY);
  if (upper <= lower) return preferredLaneY;
  const preferred = clampNumber(lower, preferredLaneY, upper);
  return (
    elbowLaneCandidates(startX, endX, preferred, lower, upper, obstacles, ignored).find(
      lane =>
        !edgeObstacleHits(
          "__candidate__",
          "scope-entry",
          elbowPoints(startX, startY, endX, endY, lane),
          obstacles,
          ignored,
          FLOW_CALL_OBSTACLE_GAP,
        ).length,
    ) ?? preferred
  );
}

function elbowLaneCandidates(
  startX: number,
  endX: number,
  preferred: number,
  minLane: number,
  maxLane: number,
  obstacles: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
): number[] {
  const values: number[] = [preferred, minLane, maxLane, (minLane + maxLane) / 2];
  const minX = Math.min(startX, endX) - FLOW_CALL_OBSTACLE_GAP;
  const maxX = Math.max(startX, endX) + FLOW_CALL_OBSTACLE_GAP;
  obstacles.forEach(box => {
    if (ignored.has(box.id)) return;
    if (!rangesOverlap(minX, maxX, box.minX, box.maxX)) return;
    values.push(
      box.minY - FLOW_CALL_OBSTACLE_GAP - FLOW_CALL_LANE_STEP,
      box.maxY + FLOW_CALL_OBSTACLE_GAP + FLOW_CALL_LANE_STEP,
    );
  });
  for (let offset = FLOW_CALL_LANE_STEP; offset <= maxLane - minLane + FLOW_CALL_LANE_STEP; offset += FLOW_CALL_LANE_STEP) {
    values.push(preferred - offset, preferred + offset);
  }
  const seen = new Set<string>();
  return values
    .filter(value => value >= minLane && value <= maxLane)
    .sort((a, b) => Math.abs(a - preferred) - Math.abs(b - preferred) || a - b)
    .filter(value => {
      const key = laneKey(value);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function elbowPoints(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  laneY: number,
): Array<{ x: number; y: number }> {
  return [
    { x: startX, y: startY },
    { x: startX, y: laneY },
    { x: endX, y: laneY },
    { x: endX, y: endY },
  ];
}

function topLevelSideRoute(
  start: { x: number; y: number },
  end: { x: number; y: number },
  obstacles: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
): Array<{ x: number; y: number }> | null {
  const minY = Math.min(start.y, end.y);
  const maxY = Math.max(start.y, end.y);
  const minRouteX = Math.min(start.x, end.x);
  const maxRouteX = Math.max(start.x, end.x);
  const relevant = obstacles.filter(box => {
    if (ignored.has(box.id)) return false;
    return (
      rangesOverlap(minY, maxY, box.minY, box.maxY) ||
      rangesOverlap(minRouteX, maxRouteX, box.minX, box.maxX)
    );
  });
  const padding = FLOW_CALL_OBSTACLE_GAP + 56;
  const minX = Math.min(start.x, end.x, ...relevant.map(box => box.minX));
  const maxX = Math.max(start.x, end.x, ...relevant.map(box => box.maxX));
  const routeMinY = Math.min(minY, ...relevant.map(box => box.minY)) - padding;
  const routeMaxY = Math.max(maxY, ...relevant.map(box => box.maxY)) + padding;
  const sideXs =
    end.x >= start.x
      ? [maxX + padding, minX - padding]
      : [minX - padding, maxX + padding];
  const direction = end.y >= start.y ? 1 : -1;
  const exitYs = topLevelRouteYCandidates(
    start.y,
    start.y + direction * Math.min(30, Math.max(12, Math.abs(end.y - start.y) * 0.08)),
    routeMinY,
    routeMaxY,
    relevant,
    ignored,
  );
  const approachYs = topLevelRouteYCandidates(
    end.y,
    end.y - direction * 42,
    routeMinY,
    routeMaxY,
    relevant,
    ignored,
  );
  for (const sideX of sideXs) {
    for (const exitY of exitYs) {
      for (const approachY of approachYs) {
        const points = [
          start,
          { x: start.x, y: exitY },
          { x: sideX, y: exitY },
          { x: sideX, y: approachY },
          { x: end.x, y: approachY },
          end,
        ];
        if (
          !edgeObstacleHits(
            "__candidate__",
            "scope-entry",
            points,
            obstacles,
            ignored,
            FLOW_CALL_OBSTACLE_GAP,
          ).length
        ) {
          return points;
        }
      }
    }
  }
  return null;
}

function topLevelRouteYCandidates(
  anchorY: number,
  preferred: number,
  minY: number,
  maxY: number,
  obstacles: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
): number[] {
  const values = [
    preferred,
    anchorY,
    anchorY - 42,
    anchorY + 42,
    (minY + maxY) / 2,
  ];
  obstacles.forEach(box => {
    if (ignored.has(box.id)) return;
    values.push(
      box.minY - FLOW_CALL_OBSTACLE_GAP - FLOW_CALL_LANE_STEP,
      box.maxY + FLOW_CALL_OBSTACLE_GAP + FLOW_CALL_LANE_STEP,
    );
  });
  const lower = minY - 260;
  const upper = maxY + 260;
  const seen = new Set<string>();
  return values
    .filter(value => value >= lower && value <= upper)
    .sort((a, b) => Math.abs(a - preferred) - Math.abs(b - preferred) || a - b)
    .filter(value => {
      const key = laneKey(value);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function pathForPoints(points: readonly { x: number; y: number }[]): string {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
}

function boundsForFlowCallEdges(edges: readonly FlowCallEdge[]): Bounds {
  const points = edges.flatMap(edge => edge.points);
  if (!points.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
  return {
    minX: Math.min(...points.map(point => point.x)),
    maxX: Math.max(...points.map(point => point.x)),
    minY: Math.min(...points.map(point => point.y)),
    maxY: Math.max(...points.map(point => point.y)),
  };
}

function boundsForTopLevelEdges(
  rootEdges: readonly RootScopeEdge[],
  entryEdges: readonly ScopeEntryEdge[],
): Bounds {
  const points = [
    ...rootEdges.flatMap(edge => edge.points),
    ...entryEdges.flatMap(edge => edge.points),
  ];
  if (!points.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
  return {
    minX: Math.min(...points.map(point => point.x)),
    maxX: Math.max(...points.map(point => point.x)),
    minY: Math.min(...points.map(point => point.y)),
    maxY: Math.max(...points.map(point => point.y)),
  };
}

function flowCallObstacles(
  positions: ReadonlyMap<string, LayoutNodePosition>,
  anchors: readonly InlineAnchor[],
): LayoutBox[] {
  return [
    ...[...positions.values()].map(item => ({
      id: item.id,
      kind: "flow" as const,
      minX: item.x - item.width / 2,
      maxX: item.x + item.width / 2,
      minY: item.y - item.height / 2,
      maxY: item.y + item.height / 2,
    })),
    ...anchors.map(item => ({
      id: `${item.flowId}:detail`,
      kind: "detail" as const,
      minX: item.bounds.minX,
      maxX: item.bounds.maxX,
      minY: item.bounds.minY,
      maxY: item.bounds.maxY,
    })),
  ];
}

function flowCallSourceExitYs(
  anchors: readonly InlineAnchor[],
  measures: ReadonlyMap<string, ExpandedFlowMeasure> | undefined,
): Map<string, number> {
  if (!measures?.size) return new Map();
  return new Map(
    anchors
      .filter(anchor => measures.has(anchor.flowId))
      .map(anchor => [
        anchor.flowId,
        anchor.bounds.maxY +
          Math.min(64, Math.max(34, (anchor.bounds.maxY - anchor.bounds.minY) * 0.06)),
      ]),
  );
}

function laneCandidates(preferred: number, min: number, max: number): number[] {
  const values: number[] = [preferred];
  const span = max - min;
  for (let offset = FLOW_CALL_LANE_STEP; offset <= span + FLOW_CALL_LANE_STEP; offset += FLOW_CALL_LANE_STEP) {
    values.push(preferred - offset, preferred + offset);
  }
  for (let value = min; value <= max; value += FLOW_CALL_LANE_STEP) {
    values.push(value);
  }
  values.push(max);
  const seen = new Set<string>();
  return values
    .filter(value => value >= min && value <= max)
    .filter(value => {
      const key = laneKey(value);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function flowCallRouteBlocked(
  pair: FlowCallPair,
  laneY: number,
  obstacles: readonly LayoutBox[],
): boolean {
  const edge: FlowCallEdge = {
    source: pair.source.id,
    target: pair.target.id,
    d: "",
    focusD: "",
    points: [
      { x: pair.source.x, y: pair.startY },
      { x: pair.source.x, y: laneY },
      { x: pair.target.x, y: laneY },
      { x: pair.target.x, y: pair.targetTopY },
    ],
  };
  return flowCallEdgeObstacleHits(edge, obstacles, FLOW_CALL_OBSTACLE_GAP).length > 0;
}

export function flowCallEdgeObstacleHits(
  edge: FlowCallEdge,
  boxes: readonly LayoutBox[],
  gap = FLOW_CALL_OBSTACLE_GAP,
): Array<{ edge: string; obstacle: string }> {
  const ignored = new Set([edge.source, `${edge.source}:detail`, edge.target]);
  const edgeId = `${edge.source}->${edge.target}`;
  return edgeObstacleHits(edgeId, "flow-call", edge.points, boxes, ignored, gap).map(
    hit => ({
      edge: hit.edge,
      obstacle: hit.obstacle,
    }),
  );
}

export function flowCallLayoutObstacleHits(
  layout: ViewerLayout,
  gap = FLOW_CALL_OBSTACLE_GAP,
): Array<{ edge: string; obstacle: string }> {
  const boxes = viewerLayoutBoxes(layout).filter(box => box.kind !== "scope");
  return layout.flowCallEdges.flatMap(edge => flowCallEdgeObstacleHits(edge, boxes, gap));
}

export function topLevelLayoutObstacleHits(
  layout: ViewerLayout,
  gap = FLOW_CALL_OBSTACLE_GAP,
): ViewerLayoutEdgeObstacleHit[] {
  const boxes = viewerLayoutBoxes(layout).filter(box => box.kind !== "detail");
  const rootHits = layout.rootEdges.flatMap(edge =>
    edgeObstacleHits(
      `${layout.rootNode.id}->${edge.scope}`,
      "root-scope",
      edge.points,
      boxes,
      new Set([layout.rootNode.id, edge.scope]),
      gap,
    ),
  );
  const entryHits = layout.entryEdges.flatMap(edge =>
    edgeObstacleHits(
      `${edge.scope}->${edge.target}`,
      "scope-entry",
      edge.points,
      boxes,
      new Set([edge.scope, edge.target, `${edge.target}:detail`]),
      gap,
    ),
  );
  return [...rootHits, ...entryHits];
}

export function viewerLayoutEdgeObstacleHits(
  layout: ViewerLayout,
  gap = FLOW_CALL_OBSTACLE_GAP,
): ViewerLayoutEdgeObstacleHit[] {
  const boxes = viewerLayoutBoxes(layout);
  const flowCallBoxes = boxes.filter(box => box.kind !== "scope");
  return [
    ...topLevelLayoutObstacleHits(layout, gap),
    ...layout.flowCallEdges.flatMap(edge =>
      edgeObstacleHits(
        `${edge.source}->${edge.target}`,
        "flow-call",
        edge.points,
        flowCallBoxes,
        new Set([edge.source, `${edge.source}:detail`, edge.target]),
        gap,
      ),
    ),
  ];
}

function edgeObstacleHits(
  edgeId: string,
  kind: ViewerLayoutEdgeKind,
  points: readonly { x: number; y: number }[],
  boxes: readonly LayoutBox[],
  ignored: ReadonlySet<string>,
  gap: number,
): ViewerLayoutEdgeObstacleHit[] {
  const segments = segmentsForPoints(points);
  const hits: ViewerLayoutEdgeObstacleHit[] = [];
  boxes.forEach(box => {
    if (ignored.has(box.id)) return;
    if (segments.some(segment => segmentIntersectsBox(segment, box, gap))) {
      hits.push({ edge: edgeId, kind, obstacle: box.id });
    }
  });
  return hits;
}

function segmentsForPoints(points: readonly { x: number; y: number }[]): Segment[] {
  const segments: Segment[] = [];
  for (let index = 1; index < points.length; index += 1) {
    segments.push({
      x1: points[index - 1].x,
      y1: points[index - 1].y,
      x2: points[index].x,
      y2: points[index].y,
    });
  }
  return segments;
}

function segmentIntersectsBox(segment: Segment, box: LayoutBox, gap: number): boolean {
  const minX = Math.min(segment.x1, segment.x2);
  const maxX = Math.max(segment.x1, segment.x2);
  const minY = Math.min(segment.y1, segment.y2);
  const maxY = Math.max(segment.y1, segment.y2);
  const padded = {
    minX: box.minX - gap,
    maxX: box.maxX + gap,
    minY: box.minY - gap,
    maxY: box.maxY + gap,
  };
  if (segment.y1 === segment.y2) {
    const y = segment.y1;
    return y >= padded.minY && y <= padded.maxY && rangesOverlap(minX, maxX, padded.minX, padded.maxX);
  }
  if (segment.x1 === segment.x2) {
    const x = segment.x1;
    return x >= padded.minX && x <= padded.maxX && rangesOverlap(minY, maxY, padded.minY, padded.maxY);
  }
  return rangesOverlap(minX, maxX, padded.minX, padded.maxX) && rangesOverlap(minY, maxY, padded.minY, padded.maxY);
}

function rangesOverlap(aMin: number, aMax: number, bMin: number, bMax: number): boolean {
  return aMin <= bMax && bMin <= aMax;
}

function laneKey(value: number): string {
  return value.toFixed(3);
}

function clampNumber(min: number, value: number, max: number): number {
  return Math.max(min, Math.min(value, max));
}

function applyManualNodePosition<T extends { x: number; y: number }>(
  item: T,
  positions: ReadonlyMap<string, ManualNodePosition> | undefined,
  kind: ViewerNodeKind,
  id: string,
): T {
  const manual = positions?.get(viewerNodeKey(kind, id));
  return manual ? { ...item, x: manual.x, y: manual.y } : item;
}

export function viewerLayoutBoxes(layout: ViewerLayout): LayoutBox[] {
  return layoutBoxesFromParts(
    layout.rootNode,
    layout.scopeNodes,
    layout.flowPositions,
    layout.inlineAnchors,
  );
}

function layoutBoxesFromParts(
  rootNode: RootNodePosition,
  scopeNodes: readonly ScopeLayoutPosition[],
  flowPositions: ReadonlyMap<string, LayoutNodePosition>,
  inlineAnchors: readonly InlineAnchor[],
): LayoutBox[] {
  return [
    {
      id: rootNode.id,
      kind: "root" as const,
      minX: rootNode.x - rootNode.width / 2,
      maxX: rootNode.x + rootNode.width / 2,
      minY: rootNode.y - rootNode.height / 2,
      maxY: rootNode.y + rootNode.height / 2,
    },
    ...scopeNodes.map(item => ({
      id: item.scope,
      kind: "scope" as const,
      minX: item.x - item.width / 2,
      maxX: item.x + item.width / 2,
      minY: item.y - item.height / 2,
      maxY: item.y + item.height / 2,
    })),
    ...[...flowPositions.values()].map(item => ({
      id: item.id,
      kind: "flow" as const,
      minX: item.x - item.width / 2,
      maxX: item.x + item.width / 2,
      minY: item.y - item.height / 2,
      maxY: item.y + item.height / 2,
    })),
    ...inlineAnchors.map(item => ({
      id: `${item.flowId}:detail`,
      kind: "detail" as const,
      minX: item.bounds.minX,
      maxX: item.bounds.maxX,
      minY: item.bounds.minY,
      maxY: item.bounds.maxY,
    })),
  ];
}

export function overlappingLayoutBoxes(boxes: readonly LayoutBox[], gap = 0): Array<[string, string]> {
  const overlaps: Array<[string, string]> = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      if (boxesOverlap(boxes[i], boxes[j], gap)) overlaps.push([boxes[i].id, boxes[j].id]);
    }
  }
  return overlaps;
}

export function viewerLayoutQualityReport(
  layout: ViewerLayout,
  options: ViewerLayoutQualityOptions = {},
): ViewerLayoutQualityReport {
  const boxes = viewerLayoutBoxes(layout);
  const overlaps = overlappingLayoutBoxes(boxes, options.overlapGap ?? 0);
  const edgeObstacleHits = viewerLayoutEdgeObstacleHits(
    layout,
    options.edgeGap ?? FLOW_CALL_OBSTACLE_GAP,
  );
  const structureIssues = viewerLayoutStructureIssues(layout);
  const bounds = boundsForLayoutBoxes(boxes);
  const contentArea = areaForBounds(bounds);
  const viewBoxArea = areaForBounds(layout.viewBox);
  return {
    bounds,
    boxCount: boxes.length,
    contentArea,
    density: viewBoxArea > 0 ? contentArea / viewBoxArea : 0,
    detailRegionCount: layout.inlineAnchors.length,
    edgeCount: layout.rootEdges.length + layout.entryEdges.length + layout.flowCallEdges.length,
    edgeObstacleHits,
    flowCallEdgeCount: layout.flowCallEdges.length,
    flowNodeCount: layout.flowPositions.size,
    isClear: overlaps.length === 0 && edgeObstacleHits.length === 0 && structureIssues.length === 0,
    overlapCount: overlaps.length,
    overlaps,
    rootEdgeCount: layout.rootEdges.length,
    scopeEntryEdgeCount: layout.entryEdges.length,
    scopeNodeCount: layout.scopeNodes.length,
    structureIssueCount: structureIssues.length,
    structureIssues,
    viewBoxArea,
  };
}

export function viewerLayoutStructureIssues(
  layout: ViewerLayout,
  options: ViewerLayoutStructureOptions = {},
): ViewerLayoutStructureIssue[] {
  const tolerance = options.tolerance ?? 2;
  const issues: ViewerLayoutStructureIssue[] = [];
  const flowPositions = layout.flowPositions;

  layout.rootEdges.forEach(edge => {
    const start = edge.points[0];
    const end = edge.points[edge.points.length - 1];
    if (start && end && end.y <= start.y + tolerance) {
      issues.push({
        id: `${layout.rootNode.id}->${edge.scope}`,
        kind: "root-scope-reversed",
      });
    }
  });

  layout.entryEdges.forEach(edge => {
    const start = edge.points[0];
    const end = edge.points[edge.points.length - 1];
    if (start && end && end.y <= start.y + tolerance) {
      issues.push({
        id: `${edge.scope}->${edge.target}`,
        kind: "scope-entry-reversed",
      });
    }
  });

  layout.inlineAnchors.forEach(anchor => {
    const host = flowPositions.get(anchor.flowId);
    if (!host) return;
    const hostBottom = host.y + host.height / 2;
    const detailCenterX = (anchor.bounds.minX + anchor.bounds.maxX) / 2;
    if (anchor.bounds.minY < hostBottom - tolerance) {
      issues.push({
        id: `${anchor.flowId}:detail`,
        kind: "detail-above-host",
      });
    }
    if (Math.abs(detailCenterX - host.x) > tolerance) {
      issues.push({
        id: `${anchor.flowId}:detail`,
        kind: "detail-detached-from-host",
      });
    }
  });

  const anchorsByFlowId = new Map(layout.inlineAnchors.map(anchor => [anchor.flowId, anchor]));
  layout.flowCallEdges.forEach(edge => {
    const source = flowPositions.get(edge.source);
    const target = flowPositions.get(edge.target);
    const start = edge.points[0];
    const end = edge.points[edge.points.length - 1];
    const edgeId = `${edge.source}->${edge.target}`;
    if (source && target && start && end) {
      const sourceExitY = anchorsByFlowId.get(edge.source)?.bounds.maxY ?? source.y + source.height / 2;
      const targetIsBelowSourceDetail = end.y > sourceExitY + tolerance;
      if (targetIsBelowSourceDetail && start.y < sourceExitY - tolerance) {
        issues.push({
          id: edgeId,
          kind: "flow-call-detached-from-source",
        });
      }
    }
    if (target && end && Math.abs(end.x - target.x) > tolerance) {
      issues.push({
        id: edgeId,
        kind: "flow-call-detached-from-target",
      });
    }
  });

  const reachable = reachableLayoutNodeIds(layout);
  flowPositions.forEach((_position, id) => {
    if (reachable.has(id)) return;
    issues.push({
      id,
      kind: "visible-flow-unreachable",
    });
  });

  return issues;
}

function reachableLayoutNodeIds(layout: ViewerLayout): Set<string> {
  const graph = new Map<string, Set<string>>();
  const add = (source: string, target: string) => {
    const targets = graph.get(source) || new Set<string>();
    targets.add(target);
    graph.set(source, targets);
  };

  layout.rootEdges.forEach(edge => add(layout.rootNode.id, edge.scope));
  layout.entryEdges.forEach(edge => add(edge.scope, edge.target));
  layout.flowCallEdges.forEach(edge => add(edge.source, edge.target));

  const reachable = new Set<string>();
  const queue: string[] = [layout.rootNode.id];
  while (queue.length) {
    const current = queue.shift() as string;
    if (reachable.has(current)) continue;
    reachable.add(current);
    (graph.get(current) || []).forEach(next => {
      if (!reachable.has(next)) queue.push(next);
    });
  }
  return reachable;
}

export function isLogicChartFlow(flow: ProgressiveFlowNode): flow is LogicChartFlow {
  return "location" in flow || "entry_kind" in flow || "language" in flow;
}

function boundsForScopes(positions: readonly ScopeNodePosition[]): Bounds {
  if (!positions.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
  return {
    minX: Math.min(...positions.map(item => item.x - item.width / 2)),
    maxX: Math.max(...positions.map(item => item.x + item.width / 2)),
    minY: Math.min(...positions.map(item => item.y - item.height / 2)),
    maxY: Math.max(...positions.map(item => item.y + item.height / 2)),
  };
}

function boundsForRootAndScopes(
  root: RootNodePosition,
  positions: readonly ScopeNodePosition[],
): Bounds {
  return {
    minX: Math.min(root.x - root.width / 2, ...positions.map(item => item.x - item.width / 2)),
    maxX: Math.max(root.x + root.width / 2, ...positions.map(item => item.x + item.width / 2)),
    minY: Math.min(root.y - root.height / 2, ...positions.map(item => item.y - item.height / 2)),
    maxY: Math.max(root.y + root.height / 2, ...positions.map(item => item.y + item.height / 2)),
  };
}

function boundsForLayoutBoxes(boxes: readonly LayoutBox[]): Bounds {
  if (!boxes.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
  return {
    minX: Math.min(...boxes.map(box => box.minX)),
    maxX: Math.max(...boxes.map(box => box.maxX)),
    minY: Math.min(...boxes.map(box => box.minY)),
    maxY: Math.max(...boxes.map(box => box.maxY)),
  };
}

function offsetBounds(bounds: Bounds, x: number, y: number): Bounds {
  return {
    maxX: bounds.maxX + x,
    maxY: bounds.maxY + y,
    minX: bounds.minX + x,
    minY: bounds.minY + y,
  };
}

function areaForBounds(bounds: Bounds): number {
  return Math.max(0, bounds.maxX - bounds.minX) * Math.max(0, bounds.maxY - bounds.minY);
}

function boxesOverlap(a: LayoutBox, b: LayoutBox, gap: number): boolean {
  return !(
    a.maxX + gap <= b.minX ||
    b.maxX + gap <= a.minX ||
    a.maxY + gap <= b.minY ||
    b.maxY + gap <= a.minY
  );
}

function isLayoutNodePosition(value: LayoutNodePosition | undefined): value is LayoutNodePosition {
  return value !== undefined;
}
