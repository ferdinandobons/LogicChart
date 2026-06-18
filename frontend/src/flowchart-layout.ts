export type FlowId = string;

export interface ProgressiveFlowNode {
  id: FlowId;
}

export interface ExpandedFlowMeasure {
  width: number;
  height: number;
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export interface LayoutNodePosition {
  id: FlowId;
  x: number;
  y: number;
  width: number;
  height: number;
  reservedWidth: number;
  layer: number;
}

export interface LayoutRow {
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
}

export interface InlineAnchor {
  flowId: FlowId;
  x: number;
  y: number;
  bounds: Bounds;
}

export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export interface ProgressiveLayoutOptions {
  flowWidth: number;
  flowHeight: number;
  gapX: number;
  rowGap: number;
  layerGap: number;
  chipY: number;
  decisionPad: number;
  detailTopPad?: number;
  maxNodesPerRow?: number;
  rowLabel?: (index: number) => string;
  expandedMeasures?: ReadonlyMap<FlowId, ExpandedFlowMeasure>;
}

export interface ProgressiveLayout {
  rows: LayoutRow[];
  positions: Map<FlowId, LayoutNodePosition>;
  inlineAnchors: InlineAnchor[];
  entryFlowIds: FlowId[];
  bounds: Bounds;
}

export interface ScopeNodePosition {
  scope: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ScopeLayoutInput {
  name: string;
  flowCount: number;
}

export interface ScopeLayoutPosition extends ScopeNodePosition {
  flowCount: number;
  expanded: boolean;
}

export interface ScopeLayoutOptions {
  scopeWidth: number;
  scopeHeight: number;
  gapX: number;
  gapY: number;
  maxColumns: number;
  topY: number;
}

export interface ScopeEntryEdge {
  scope: string;
  target: FlowId;
  d: string;
  focusD: string;
  points: Array<{ x: number; y: number }>;
}

export function reservedWidthForFlow(
  flow: ProgressiveFlowNode,
  options: ProgressiveLayoutOptions,
): number {
  const measure = options.expandedMeasures?.get(flow.id);
  return Math.max(
    options.flowWidth,
    measure ? measure.width + options.decisionPad * 2 : options.flowWidth,
  );
}

export function rowWidthForLayer(
  layer: readonly ProgressiveFlowNode[],
  options: ProgressiveLayoutOptions,
): number {
  const reserved = layer.reduce(
    (sum, flow) => sum + reservedWidthForFlow(flow, options),
    0,
  );
  return Math.max(
    options.flowWidth,
    reserved + Math.max(0, layer.length - 1) * options.gapX,
  );
}

export function layoutProgressiveRows(
  layers: readonly (readonly ProgressiveFlowNode[])[],
  options: ProgressiveLayoutOptions,
): ProgressiveLayout {
  const rowLabel =
    options.rowLabel ?? ((index: number) => (index === 0 ? "entrypoints" : `unlocked calls ${index}`));
  const visualRows = layers.flatMap((layer, layerIndex) =>
    splitLayerIntoRows(layer, options).map((row, rowIndex) => ({
      layer,
      layerIndex,
      row,
      rowIndex,
    })),
  );
  const maxWidth = Math.max(
    options.flowWidth,
    ...visualRows.map(item => rowWidthForLayer(item.row, options)),
  );
  const rows: LayoutRow[] = [];
  const positions = new Map<FlowId, LayoutNodePosition>();
  const inlineAnchors: InlineAnchor[] = [];
  const boundsItems: Bounds[] = [];

  let y = 0;
  visualRows.forEach(({ layerIndex, row, rowIndex }) => {
    const width = rowWidthForLayer(row, options);
    let cursorX = (maxWidth - width) / 2;
    rows.push({
      x: maxWidth / 2,
      y,
      width,
      height: options.flowHeight + options.chipY * 2,
      label: rowIndex === 0 ? rowLabel(layerIndex) : `${rowLabel(layerIndex)} ${rowIndex + 1}`,
    });

    row.forEach(flow => {
      const reservedWidth = reservedWidthForFlow(flow, options);
      const x = cursorX + reservedWidth / 2;
      cursorX += reservedWidth + options.gapX;
      const position: LayoutNodePosition = {
        id: flow.id,
        x,
        y,
        width: options.flowWidth,
        height: options.flowHeight,
        reservedWidth,
        layer: layerIndex,
      };
      positions.set(flow.id, position);
      boundsItems.push(rectBounds(position.x, position.y, position.width, position.height));
    });

    const expandedInRow = row.filter(flow => options.expandedMeasures?.has(flow.id));
    if (expandedInRow.length) {
      const bandTop = y + options.flowHeight / 2 + options.chipY;
      let maxReservedHeight = 0;
      expandedInRow.forEach(flow => {
        const measure = options.expandedMeasures?.get(flow.id);
        const host = positions.get(flow.id);
        if (!measure || !host) return;
        const reservedWidth = measure.width + options.decisionPad * 2;
        const reservedHeight = measure.height + options.decisionPad * 2;
        const bounds = {
          minX: host.x - reservedWidth / 2,
          maxX: host.x + reservedWidth / 2,
          minY: bandTop,
          maxY: bandTop + reservedHeight,
        };
        inlineAnchors.push({
          flowId: flow.id,
          x: host.x - (measure.minX + measure.maxX) / 2,
          y: bandTop + (options.detailTopPad ?? Math.min(36, options.decisionPad)) - measure.minY,
          bounds,
        });
        boundsItems.push(bounds);
        maxReservedHeight = Math.max(maxReservedHeight, reservedHeight);
      });
      y += options.flowHeight + options.rowGap + maxReservedHeight;
    } else {
      y += options.flowHeight + options.layerGap;
    }
  });

  return {
    rows,
    positions,
    inlineAnchors,
    entryFlowIds: layers[0]?.map(flow => flow.id) ?? [],
    bounds: mergeBounds(boundsItems),
  };
}

function splitLayerIntoRows(
  layer: readonly ProgressiveFlowNode[],
  options: ProgressiveLayoutOptions,
): readonly (readonly ProgressiveFlowNode[])[] {
  const maxNodes = options.maxNodesPerRow;
  if (!maxNodes || maxNodes <= 0 || layer.length <= maxNodes) return [layer];
  const rows: Array<readonly ProgressiveFlowNode[]> = [];
  for (let index = 0; index < layer.length; index += maxNodes) {
    rows.push([...layer.slice(index, index + maxNodes)]);
  }
  return rows;
}

export function scopeEntryEdges(
  scopeNode: ScopeNodePosition,
  entries: readonly LayoutNodePosition[],
  flowHeight: number,
): ScopeEntryEdge[] {
  return entries.map((entry, index) => {
    const startY = scopeNode.y + scopeNode.height / 2;
    const endY = entry.y - flowHeight / 2;
    const available = Math.max(80, endY - startY);
    const fanoutOffset = (index - (entries.length - 1) / 2) * 10;
    const startX = scopeNode.x + fanoutOffset;
    const laneY = startY + clamp(42, available * 0.42, Math.max(42, available - 46));
    const curveY = Math.max(70, available * 0.55);
    return {
      scope: scopeNode.scope,
      target: entry.id,
      d: `M ${startX} ${startY} L ${startX} ${laneY} L ${entry.x} ${laneY} L ${entry.x} ${endY}`,
      focusD: `M ${startX} ${startY} C ${startX} ${startY + curveY}, ${entry.x} ${
        endY - curveY
      }, ${entry.x} ${endY}`,
      points: [
        { x: startX, y: startY },
        { x: startX, y: laneY },
        { x: entry.x, y: laneY },
        { x: entry.x, y: endY },
      ],
    };
  });
}

export function layoutScopeNodes(
  scopes: readonly ScopeLayoutInput[],
  activeScope: string,
  options: ScopeLayoutOptions,
): ScopeLayoutPosition[] {
  const sorted = [...scopes].sort((a, b) => a.name.localeCompare(b.name));
  const columns = Math.max(1, Math.min(options.maxColumns, sorted.length || 1));
  const rowWidth = columns * options.scopeWidth + Math.max(0, columns - 1) * options.gapX;

  return sorted.map((scope, index) => {
    const col = index % columns;
    const row = Math.floor(index / columns);
    return {
      scope: scope.name,
      x: col * (options.scopeWidth + options.gapX) - rowWidth / 2 + options.scopeWidth / 2,
      y: options.topY + row * (options.scopeHeight + options.gapY),
      width: options.scopeWidth,
      height: options.scopeHeight,
      flowCount: scope.flowCount,
      expanded: scope.name === activeScope,
    };
  });
}

export function assertNoOverlaps(nodes: readonly LayoutNodePosition[], gap = 0): boolean {
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      if (rectsOverlap(nodes[i], nodes[j], gap)) return false;
    }
  }
  return true;
}

function rectBounds(x: number, y: number, width: number, height: number): Bounds {
  return {
    minX: x - width / 2,
    maxX: x + width / 2,
    minY: y - height / 2,
    maxY: y + height / 2,
  };
}

function mergeBounds(items: readonly Bounds[]): Bounds {
  if (!items.length) {
    return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
  }
  return {
    minX: Math.min(...items.map(item => item.minX)),
    maxX: Math.max(...items.map(item => item.maxX)),
    minY: Math.min(...items.map(item => item.minY)),
    maxY: Math.max(...items.map(item => item.maxY)),
  };
}

function rectsOverlap(a: LayoutNodePosition, b: LayoutNodePosition, gap: number): boolean {
  return !(
    a.x + a.width / 2 + gap <= b.x - b.width / 2 ||
    b.x + b.width / 2 + gap <= a.x - a.width / 2 ||
    a.y + a.height / 2 + gap <= b.y - b.height / 2 ||
    b.y + b.height / 2 + gap <= a.y - a.height / 2
  );
}

function clamp(min: number, value: number, max: number): number {
  return Math.max(min, Math.min(value, max));
}
