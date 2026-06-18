import type { Bounds, ExpandedFlowMeasure } from "./flowchart-layout";
import type {
  LogicChartFlow,
  LogicChartFlowEdge,
  LogicChartFlowNode,
} from "./logicchart-model";

const GAP_X = 82;
const GAP_Y = 136;
const DEFAULT_NODE_WIDTH = 270;
const DEFAULT_NODE_HEIGHT = 78;
const START_EDGE_HEIGHT = 38;

export interface FlowDetailNodePosition {
  id: string;
  node: LogicChartFlowNode;
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
}

export interface FlowDetailEdgeRoute {
  id: string;
  edge: LogicChartFlowEdge;
  d: string;
  labelX: number;
  labelY: number;
}

export interface FlowDetailLayout {
  bounds: Bounds;
  edgeRoutes: FlowDetailEdgeRoute[];
  measure: ExpandedFlowMeasure;
  nodePositions: Map<string, FlowDetailNodePosition>;
  startRoutes: FlowDetailEdgeRoute[];
}

export interface FlowDetailLayoutOptions {
  omitEntryNode?: boolean;
}

export function layoutFlowDetail(
  flow: LogicChartFlow,
  options: FlowDetailLayoutOptions = {},
): FlowDetailLayout | null {
  const nodes = options.omitEntryNode
    ? (flow.nodes || []).filter(node => node.kind !== "entry")
    : flow.nodes || [];
  if (!nodes.length) return null;

  const nodeIds = new Set(nodes.map(node => node.id));
  const edges = (flow.edges || []).filter(
    edge => nodeIds.has(edge.source) && nodeIds.has(edge.target),
  );
  const depths = assignDepths(nodes, edges);
  const layers = groupByDepth(nodes, depths);
  const nodePositions = new Map<string, FlowDetailNodePosition>();
  const boundsItems: Bounds[] = [];

  let yCursor = 0;
  layers.forEach((layer, layerIndex) => {
    const sizes = layer.map(node => sizeForKind(node.kind));
    const rowWidth =
      sizes.reduce((sum, size) => sum + size.width, 0) +
      Math.max(0, sizes.length - 1) * GAP_X;
    const rowHeight = Math.max(...sizes.map(size => size.height), DEFAULT_NODE_HEIGHT);
    let xCursor = -rowWidth / 2;
    layer.forEach((node, index) => {
      const size = sizes[index];
      const x = xCursor + size.width / 2;
      const y = yCursor + rowHeight / 2;
      const position = {
        id: node.id,
        node,
        x,
        y,
        width: size.width,
        height: size.height,
        layer: layerIndex,
      };
      nodePositions.set(node.id, position);
      boundsItems.push(rectBounds(x, y, size.width, size.height));
      xCursor += size.width + GAP_X;
    });
    yCursor += rowHeight + GAP_Y;
  });

  const edgeRoutes = edges
    .map((edge, index) => routeEdge(edge, index, nodePositions))
    .filter((route): route is FlowDetailEdgeRoute => route !== null);
  const startRoutes = options.omitEntryNode ? routeStartEdges(nodePositions) : [];
  const bounds = mergeBounds(boundsItems);
  const width = Math.max(DEFAULT_NODE_WIDTH, bounds.maxX - bounds.minX);
  const height = Math.max(DEFAULT_NODE_HEIGHT, bounds.maxY - bounds.minY);

  return {
    bounds,
    edgeRoutes,
    measure: {
      height,
      maxX: bounds.maxX,
      maxY: bounds.maxY,
      minX: bounds.minX,
      minY: bounds.minY,
      width,
    },
    nodePositions,
    startRoutes,
  };
}

function assignDepths(
  nodes: readonly LogicChartFlowNode[],
  edges: readonly LogicChartFlowEdge[],
): Map<string, number> {
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, LogicChartFlowEdge[]>();
  nodes.forEach(node => {
    incoming.set(node.id, 0);
    outgoing.set(node.id, []);
  });
  edges.forEach(edge => {
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
    outgoing.get(edge.source)?.push(edge);
  });

  const roots = nodes.filter(
    node => node.kind === "entry" || (incoming.get(node.id) || 0) === 0,
  );
  const depth = new Map<string, number>();
  const queue = (roots.length ? roots : nodes.slice(0, 1)).map(node => node.id);
  queue.forEach(id => depth.set(id, 0));

  while (queue.length) {
    const id = queue.shift();
    if (!id) continue;
    const sourceDepth = depth.get(id) || 0;
    (outgoing.get(id) || []).forEach(edge => {
      const nextDepth = sourceDepth + 1;
      if ((depth.get(edge.target) ?? -1) < nextDepth) {
        depth.set(edge.target, nextDepth);
        queue.push(edge.target);
      }
    });
  }

  let fallbackDepth = Math.max(0, ...depth.values()) + 1;
  nodes.forEach(node => {
    if (!depth.has(node.id)) {
      depth.set(node.id, fallbackDepth);
      fallbackDepth += 1;
    }
  });
  return depth;
}

function groupByDepth(
  nodes: readonly LogicChartFlowNode[],
  depths: ReadonlyMap<string, number>,
): LogicChartFlowNode[][] {
  const groups = new Map<number, LogicChartFlowNode[]>();
  nodes.forEach(node => {
    const depth = depths.get(node.id) || 0;
    const group = groups.get(depth) || [];
    group.push(node);
    groups.set(depth, group);
  });
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, group]) =>
      group.sort((a, b) => {
        const line = (a.location?.start_line || 0) - (b.location?.start_line || 0);
        if (line) return line;
        return (a.label || a.id).localeCompare(b.label || b.id);
      }),
    );
}

function routeEdge(
  edge: LogicChartFlowEdge,
  index: number,
  positions: ReadonlyMap<string, FlowDetailNodePosition>,
): FlowDetailEdgeRoute | null {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  if (!source || !target) return null;
  const startY = source.y + source.height / 2;
  const endY = target.y - target.height / 2;
  const laneOffset = ((index % 3) - 1) * 8;
  const midY = (startY + endY) / 2 + laneOffset;
  return {
    id: edge.id || `${edge.source}->${edge.target}`,
    edge,
    d: `M ${source.x} ${startY} L ${source.x} ${midY} L ${target.x} ${midY} L ${target.x} ${endY}`,
    labelX: (source.x + target.x) / 2,
    labelY: midY - 8,
  };
}

function routeStartEdges(
  positions: ReadonlyMap<string, FlowDetailNodePosition>,
): FlowDetailEdgeRoute[] {
  return [...positions.values()]
    .filter(position => position.layer === 0)
    .map(position => {
      const endY = position.y - position.height / 2;
      const midY = -START_EDGE_HEIGHT / 2;
      return {
        id: `start->${position.id}`,
        edge: {
          source: "__flow_host__",
          target: position.id,
        },
        d: `M 0 ${-START_EDGE_HEIGHT} L 0 ${midY} L ${position.x} ${midY} L ${position.x} ${endY}`,
        labelX: position.x / 2,
        labelY: midY - 8,
      };
    });
}

function sizeForKind(kind: string | undefined): { width: number; height: number } {
  if (kind === "decision") return { width: 300, height: 104 };
  if (kind === "entry") return { width: 292, height: 82 };
  if (kind === "terminal") return { width: 284, height: 78 };
  return { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
}

function rectBounds(x: number, y: number, width: number, height: number): Bounds {
  return {
    maxX: x + width / 2,
    maxY: y + height / 2,
    minX: x - width / 2,
    minY: y - height / 2,
  };
}

function mergeBounds(items: readonly Bounds[]): Bounds {
  if (!items.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
  return {
    maxX: Math.max(...items.map(item => item.maxX)),
    maxY: Math.max(...items.map(item => item.maxY)),
    minX: Math.min(...items.map(item => item.minX)),
    minY: Math.min(...items.map(item => item.minY)),
  };
}
