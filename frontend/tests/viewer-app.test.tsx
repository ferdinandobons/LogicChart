import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";

import { ViewerApp } from "../src/ViewerApp";
import type { LogicChartPayload } from "../src/logicchart-model";
import { viewerNodeKey } from "../src/viewer-layout";
import { useViewerStore } from "../src/viewer-store";

const payload: LogicChartPayload = {
  flows: [
    {
      id: "orders-route",
      name: "GET",
      language: "typescript",
      entry_kind: "route",
      is_entrypoint: true,
      location: { path: "frontend/app/api/orders/route.ts", start_line: 3 },
      calls: ["load-order"],
      called_by: [],
      metadata: { scope: ["frontend"] },
      nodes: [
        { id: "orders-route:n1", kind: "entry", label: "Route: GET", location: { path: "frontend/app/api/orders/route.ts", start_line: 3 } },
        { id: "orders-route:n2", kind: "decision", label: "Switch on order.state", location: { path: "frontend/app/api/orders/route.ts", start_line: 6 } },
        { id: "orders-route:n3", kind: "terminal", label: "Return Response.json(order)", location: { path: "frontend/app/api/orders/route.ts", start_line: 8 } },
      ],
      edges: [
        { source: "orders-route:n1", target: "orders-route:n2" },
        { source: "orders-route:n2", target: "orders-route:n3", label: "\"open\"" },
      ],
    },
    {
      id: "users-route",
      name: "POST",
      language: "typescript",
      entry_kind: "route",
      is_entrypoint: true,
      location: { path: "frontend/app/api/users/route.ts", start_line: 4 },
      calls: [],
      called_by: [],
      metadata: { scope: ["frontend"] },
    },
    {
      id: "load-order",
      name: "loadOrder",
      language: "typescript",
      entry_kind: "function",
      location: { path: "frontend/app/api/orders/route.ts", start_line: 18 },
      calls: [],
      called_by: ["orders-route"],
      metadata: { scope: ["frontend"] },
    },
    {
      id: "edge-admission",
      name: "AdmissionControl.route",
      language: "cpp",
      entry_kind: "function",
      is_entrypoint: true,
      location: { path: "edge/native/admission.cpp", start_line: 23 },
      calls: [],
      called_by: [],
      metadata: { scope: ["edge"] },
    },
    {
      id: "backend-auth",
      name: "AuthService.CanAccess",
      language: "csharp",
      entry_kind: "method",
      is_entrypoint: true,
      location: { path: "backend/auth/AuthService.cs", start_line: 12 },
      calls: [],
      called_by: [],
      metadata: { scope: ["backend"] },
    },
  ],
};

describe("ViewerApp", () => {
  beforeEach(() => {
    useViewerStore.getState().clearSelection();
  });

  it("renders a scope node connected to every first-layer entrypoint", () => {
    const html = renderToStaticMarkup(
      <ViewerApp scope="frontend" payload={payload} routeFlowIds={["orders-route"]} />,
    );

    expect(html).toContain('data-scope="frontend"');
    expect(html).toContain('data-root-id="codebase"');
    expect(html).toContain('class="root-scope-edge-group"');
    expect(html).toContain('class="root-scope-hit"');
    expect(html).toContain('class="edge root-scope-link"');
    expect(html.match(/class="edge-link-group"/g)).toHaveLength(2);
    expect(html).toContain('data-target-flow-id="orders-route"');
    expect(html).toContain('data-target-flow-id="users-route"');
    expect(html).toContain('class="flow-call-edge-group"');
    expect(html).toContain('data-source-flow-id="orders-route"');
    expect(html).toContain('data-called-flow-id="load-order"');
    expect(html).toContain('class="flow-call-hit"');
    expect(html).toContain('class="edge flow-call-link"');
    expect(html).toContain(
      'aria-label="GET · route in typescript · 3 nodes · 1 decision · 1 call · 0 callers · frontend/app/api/orders/route.ts:3"',
    );
    expect(html).toContain(
      'data-flow-summary="GET · route in typescript · 3 nodes · 1 decision · 1 call · 0 callers · frontend/app/api/orders/route.ts:3"',
    );
    expect(html).toContain('class="node flow-node movable flow-kind-route flow-open"');
    expect(html).toContain('class="node flow-node movable flow-kind-function"');
    expect(html).toContain('href="#edge=');
    expect(html).toContain('class="edge-hit-path"');
    expect(html).toContain('class="edge-link-group"');
    expect(html).toContain('id="typedNodeShadow"');
    expect(html).toContain('id="typedArrow"');
    expect(html.match(/<rect class="shape"/g)).toHaveLength(7);
    expect(html.match(/vector-effect="non-scaling-stroke"/g)?.length).toBeGreaterThanOrEqual(8);
    expect(html).toContain("loadOrder");
    expect(html).toContain("Switch on order.state");
    expect(html).toContain('class="flow-detail"');
    expect(html).toContain('class="flow-detail-edge flow-detail-start-edge"');
    expect(html).toContain('class="flow-detail-edge-hit"');
    expect(html).toContain('class="detail-node movable decision"');
    expect(html).toContain('data-detail-node-id="orders-route:n2"');
    expect(html).not.toContain("Route: GET");
    expect(html).toContain("route · typescript");
    expect(html).toContain('class="node entry scope-node movable expanded"');
    expect(html).not.toContain('scope-node dimmed');
  });

  it("dims unrelated flow nodes when a scope-entry connection is selected", () => {
    useViewerStore.getState().setSelectedConnection({
      kind: "scope-entry",
      scope: "frontend",
      target: "orders-route",
    });

    const html = renderToStaticMarkup(<ViewerApp scope="frontend" payload={payload} />);

    expect(html).toContain('data-selected-kind="scope-entry"');
    expect(html).toContain('class="node entry scope-node movable expanded edge-source"');
    expect(html).toContain('class="node flow-node movable flow-kind-route edge-target"');
    expect(html).toContain('class="node flow-node movable flow-kind-route dimmed"');
    expect(html).toContain('class="edge scope-entry-link selected-link"');
    expect(html).toContain('class="edge scope-entry-link dimmed"');
  });

  it("accepts a selected connection from the current route", () => {
    const html = renderToStaticMarkup(
      <ViewerApp
        scope="frontend"
        payload={payload}
        selectedConnection={{
          kind: "scope-entry",
          scope: "frontend",
          target: "orders-route",
        }}
      />,
    );

    expect(html).toContain('data-selected-kind="scope-entry"');
    expect(html).toContain('class="edge scope-entry-link selected-link"');
    expect(html).toContain('class="node entry scope-node movable expanded edge-source"');
    expect(html).toContain('class="node flow-node movable flow-kind-route edge-target"');
  });

  it("renders and selects flow-call connections between visible flow layers", () => {
    useViewerStore.getState().setSelectedConnection({
      kind: "flow-call",
      source: "orders-route",
      target: "load-order",
    });

    const html = renderToStaticMarkup(
      <ViewerApp scope="frontend" payload={payload} routeFlowIds={["orders-route"]} />,
    );

    expect(html).toContain('data-selected-kind="flow-call"');
    expect(html).toContain('class="edge flow-call-link selected-link"');
    expect(html).toContain('class="node flow-node movable flow-kind-route flow-open edge-source"');
    expect(html).toContain('class="node flow-node movable flow-kind-function edge-target"');
    expect(html).toContain('class="node flow-node movable flow-kind-route dimmed"');
    expect(html).toContain('class="node entry scope-node movable expanded dimmed"');
  });

  it("assigns semantic classes to method flows in backend scopes", () => {
    const html = renderToStaticMarkup(<ViewerApp scope="backend" payload={payload} />);

    expect(html).toContain('class="node flow-node movable flow-kind-method"');
    expect(html).toContain("AuthService.CanAccess");
  });

  it("keeps all top-level scope nodes at distinct positions in a multi-scope payload", () => {
    const html = renderToStaticMarkup(<ViewerApp scope="frontend" payload={payload} />);
    const transforms = new Map<string, string>();
    const tones = new Map<string, string>();
    const scopePattern = /<g(?=[^>]*class="[^"]*scope-node[^"]*")[^>]*>/g;

    for (const match of html.matchAll(scopePattern)) {
      const tag = match[0];
      const scope = tag.match(/data-scope="([^"]+)"/)?.[1];
      const transform = tag.match(/transform="translate\(([^)]+)\)"/)?.[1];
      const style = tag.match(/style="([^"]+)"/)?.[1];
      if (scope && transform) transforms.set(scope, transform);
      if (scope && style) tones.set(scope, style);
    }

    expect([...transforms.keys()].sort()).toEqual(["backend", "edge", "frontend"]);
    expect(new Set(transforms.values()).size).toBe(3);
    expect(transforms.get("frontend")).not.toBe(transforms.get("edge"));
    expect([...tones.keys()].sort()).toEqual(["backend", "edge", "frontend"]);
    tones.forEach(style => {
      expect(style).toContain("--scope-hue:");
    });
    expect(new Set(tones.values()).size).toBe(3);
  });

  it("assigns distinct scope hues for arbitrary codebase scope names", () => {
    const customPayload: LogicChartPayload = {
      flows: ["api-gateway", "mobile-app", "shared_kernel", "worker.jobs"].map(
        (scope, index) => ({
          id: `${scope}-entry`,
          name: `${scope} entry`,
          language: index % 2 ? "typescript" : "python",
          entry_kind: index % 2 ? "route" : "handler",
          is_entrypoint: true,
          location: { path: `${scope}/entry.${index % 2 ? "ts" : "py"}`, start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: [scope] },
        }),
      ),
    };
    const html = renderToStaticMarkup(<ViewerApp scope="api-gateway" payload={customPayload} />);
    const hues = [...html.matchAll(/data-scope="([^"]+)"[\s\S]*?style="--scope-hue:([^"]+)"/g)]
      .map(match => [match[1], Number(match[2])] as const);

    expect(hues.map(([scope]) => scope).sort()).toEqual([
      "api-gateway",
      "mobile-app",
      "shared_kernel",
      "worker.jobs",
    ]);
    expect(hues.map(([, hue]) => hue).every(Number.isFinite)).toBe(true);
    expect(new Set(hues.map(([, hue]) => hue)).size).toBe(4);
  });

  it("routes expanded flowchart edges around manually moved detail blocks", () => {
    const obstaclePayload: LogicChartPayload = {
      flows: [
        {
          id: "review-flow",
          name: "reviewFlow",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "frontend/app/api/review/route.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["frontend"] },
          nodes: [
            {
              id: "review-flow:source",
              kind: "action",
              label: "Prepare request",
              location: { path: "frontend/app/api/review/route.ts", start_line: 2 },
            },
            {
              id: "review-flow:blocker",
              kind: "action",
              label: "Independent audit",
              location: { path: "frontend/app/api/review/route.ts", start_line: 3 },
            },
            {
              id: "review-flow:spacer",
              kind: "action",
              label: "Parallel branch",
              location: { path: "frontend/app/api/review/route.ts", start_line: 4 },
            },
            {
              id: "review-flow:target",
              kind: "terminal",
              label: "Return result",
              location: { path: "frontend/app/api/review/route.ts", start_line: 5 },
            },
          ],
          edges: [
            {
              source: "review-flow:source",
              target: "review-flow:target",
            },
          ],
        },
      ],
    };

    const baseHtml = renderToStaticMarkup(
      <ViewerApp scope="frontend" payload={obstaclePayload} routeFlowIds={["review-flow"]} />,
    );
    const anchor = extractTranslate(baseHtml.match(/class="flow-detail"[^>]*transform="([^"]+)"/)?.[1]);
    const baseEdgePath = extractFirstDetailEdgePath(baseHtml);
    const baseLaneY = extractLaneY(baseEdgePath);
    const [sourceX, , , , targetX] = extractPathNumbers(baseEdgePath);

    const movedBlockerX = (sourceX + targetX) / 2;
    const movedBlockerY = baseLaneY;
    const reroutedHtml = renderToStaticMarkup(
      <ViewerApp
        scope="frontend"
        payload={obstaclePayload}
        routeFlowIds={["review-flow"]}
        initialManualNodePositions={
          new Map([
            [
              viewerNodeKey("detail", "review-flow:review-flow:blocker"),
              {
                x: anchor.x + movedBlockerX,
                y: anchor.y + movedBlockerY,
              },
            ],
          ])
        }
      />,
    );

    const reroutedLaneY = extractLaneY(extractFirstDetailEdgePath(reroutedHtml));

    expect(reroutedLaneY).not.toBeCloseTo(baseLaneY);
    expect(Math.abs(reroutedLaneY - movedBlockerY)).toBeGreaterThan(57);
  });

  it("routes expanded flowchart start edges around manually moved detail blocks", () => {
    const obstaclePayload: LogicChartPayload = {
      flows: [
        {
          id: "start-flow",
          name: "startFlow",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "frontend/app/api/start/route.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["frontend"] },
          nodes: [
            {
              id: "start-flow:source",
              kind: "action",
              label: "Prepare request",
              location: { path: "frontend/app/api/start/route.ts", start_line: 2 },
            },
            {
              id: "start-flow:blocker",
              kind: "action",
              label: "Independent audit",
              location: { path: "frontend/app/api/start/route.ts", start_line: 3 },
            },
            {
              id: "start-flow:spacer",
              kind: "action",
              label: "Parallel branch",
              location: { path: "frontend/app/api/start/route.ts", start_line: 4 },
            },
            {
              id: "start-flow:target",
              kind: "terminal",
              label: "Return result",
              location: { path: "frontend/app/api/start/route.ts", start_line: 5 },
            },
          ],
          edges: [
            {
              source: "start-flow:source",
              target: "start-flow:target",
            },
          ],
        },
      ],
    };

    const baseHtml = renderToStaticMarkup(
      <ViewerApp scope="frontend" payload={obstaclePayload} routeFlowIds={["start-flow"]} />,
    );
    const anchor = extractTranslate(baseHtml.match(/class="flow-detail"[^>]*transform="([^"]+)"/)?.[1]);
    const baseStartPath = extractDetailEdgePath(
      baseHtml,
      "start->start-flow:source",
      "flow-detail-start-edge",
    );
    const baseLaneY = extractLaneY(baseStartPath);
    const sourceX = extractPathNumbers(baseStartPath)[4];
    const movedBlockerX = sourceX / 2;
    const movedBlockerY = baseLaneY;

    const reroutedHtml = renderToStaticMarkup(
      <ViewerApp
        scope="frontend"
        payload={obstaclePayload}
        routeFlowIds={["start-flow"]}
        initialManualNodePositions={
          new Map([
            [
              viewerNodeKey("detail", "start-flow:start-flow:blocker"),
              {
                x: anchor.x + movedBlockerX,
                y: anchor.y + movedBlockerY,
              },
            ],
          ])
        }
      />,
    );
    const reroutedLaneY = extractLaneY(
      extractDetailEdgePath(reroutedHtml, "start->start-flow:source", "flow-detail-start-edge"),
    );

    expect(reroutedLaneY).not.toBeCloseTo(baseLaneY);
    expect(Math.abs(reroutedLaneY - movedBlockerY)).toBeGreaterThan(57);
  });
});

function extractFirstDetailEdgePath(html: string): string {
  const match = html.match(/<path class="flow-detail-edge" d="([^"]+)"/);
  if (!match) throw new Error("expected a routed flow-detail edge path");
  return match[1];
}

function extractDetailEdgePath(html: string, edgeId: string, edgeClassName: string): string {
  const serializedEdgeId = escapeHtmlAttribute(edgeId);
  const group = html.match(
    new RegExp(
      `<g class="flow-detail-edge-group" data-edge-id="${escapeRegExp(serializedEdgeId)}"[\\s\\S]*?</g>`,
    ),
  );
  if (!group) throw new Error(`expected detail edge group for ${edgeId}`);
  const path = group[0].match(
    new RegExp(`<path class="[^"]*${escapeRegExp(edgeClassName)}[^"]*" d="([^"]+)"`),
  );
  if (!path) throw new Error(`expected detail edge path for ${edgeId}`);
  return path[1];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtmlAttribute(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/>/g, "&gt;")
    .replace(/</g, "&lt;");
}

function extractPathNumbers(path: string): number[] {
  return [...path.matchAll(/-?\d+(?:\.\d+)?/g)].map(match => Number(match[0]));
}

function extractLaneY(path: string): number {
  const numbers = extractPathNumbers(path);
  if (numbers.length < 8) throw new Error(`unexpected detail edge path: ${path}`);
  return numbers[3];
}

function extractTranslate(value: string | undefined): { x: number; y: number } {
  if (!value) throw new Error("expected translate transform");
  const match = value.match(/translate\((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\)/);
  if (!match) throw new Error(`unexpected translate transform: ${value}`);
  return {
    x: Number(match[1]),
    y: Number(match[2]),
  };
}
