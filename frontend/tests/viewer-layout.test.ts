import { describe, expect, it } from "vitest";

import {
  createViewerLayout,
  flowCallLayoutObstacleHits,
  overlappingLayoutBoxes,
  topLevelLayoutObstacleHits,
  viewerLayoutEdgeObstacleHits,
  viewerLayoutQualityReport,
  viewerLayoutStructureIssues,
  viewerNodeKey,
  viewerLayoutBoxes,
  type ExpandedFlowMeasure,
  type LogicChartPayload,
} from "../src";

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
        {
          id: "orders-route:n1",
          kind: "entry",
          label: "Route: GET",
          location: { path: "frontend/app/api/orders/route.ts", start_line: 3 },
        },
        {
          id: "orders-route:n2",
          kind: "decision",
          label: "Switch on order.state",
          location: { path: "frontend/app/api/orders/route.ts", start_line: 6 },
        },
        {
          id: "orders-route:n3",
          kind: "terminal",
          label: "Return Response.json(order)",
          location: { path: "frontend/app/api/orders/route.ts", start_line: 8 },
        },
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
      calls: ["load-user"],
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
      id: "load-user",
      name: "loadUser",
      language: "typescript",
      entry_kind: "function",
      location: { path: "frontend/app/api/users/route.ts", start_line: 18 },
      calls: [],
      called_by: ["users-route"],
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

describe("viewer layout composition", () => {
  it("keeps top-level scopes and visible flow nodes separated", () => {
    const layout = createViewerLayout({
      expandedMeasures,
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });

    expect(layout.rootNode.id).toBe("codebase");
    expect(layout.rootNode.y).toBeLessThan(Math.min(...layout.scopeNodes.map(node => node.y)));
    expect(layout.rootEdges.map(edge => edge.scope)).toEqual(["backend", "edge", "frontend"]);
    expect(layout.scopeNodes.map(node => node.scope)).toEqual(["backend", "edge", "frontend"]);
    expect(layout.activeScopeNode.scope).toBe("frontend");
    expect(layout.entryEdges.map(edge => edge.target)).toEqual(["orders-route", "users-route"]);
    expect(layout.flowCallEdges.map(edge => `${edge.source}->${edge.target}`)).toEqual([
      "orders-route->load-order",
    ]);
    expect(layout.inlineAnchors.map(anchor => anchor.flowId)).toEqual(["orders-route"]);
    expect(layout.flowPositions.get("load-order")?.y).toBeGreaterThan(
      layout.flowPositions.get("orders-route")?.y ?? 0,
    );
    expect(viewerLayoutBoxes(layout).some(box => box.kind === "detail")).toBe(true);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(topLevelLayoutObstacleHits(layout)).toEqual([]);
    expect(viewerLayoutQualityReport(layout, { edgeGap: 12, overlapGap: 24 })).toMatchObject({
      edgeObstacleHits: [],
      isClear: true,
      overlapCount: 0,
    });
  });

  it("keeps multiple codebase scopes expanded in the same progressive canvas", () => {
    const layout = createViewerLayout({
      expandedMeasures,
      expandedScopes: ["backend", "frontend"],
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });

    expect(
      layout.scopeNodes
        .filter(node => node.expanded)
        .map(node => node.scope)
        .sort(),
    ).toEqual(["backend", "frontend"]);
    expect(layout.activeScopeNode.scope).toBe("frontend");
    expect(layout.flowPositions.has("backend-auth")).toBe(true);
    expect(layout.flowPositions.has("orders-route")).toBe(true);
    expect(layout.flowPositions.has("users-route")).toBe(true);
    expect(layout.entryEdges.map(edge => `${edge.scope}->${edge.target}`).sort()).toEqual([
      "backend->backend-auth",
      "frontend->orders-route",
      "frontend->users-route",
    ]);
    expect(layout.flowCallEdges.map(edge => `${edge.source}->${edge.target}`)).toEqual([
      "orders-route->load-order",
    ]);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(topLevelLayoutObstacleHits(layout)).toEqual([]);
    expect(flowCallLayoutObstacleHits(layout)).toEqual([]);
  });

  it("allows an explicit root-only canvas with no expanded scopes", () => {
    const layout = createViewerLayout({
      expandedMeasures,
      expandedScopes: [],
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });

    expect(layout.scopeNodes.filter(node => node.expanded)).toEqual([]);
    expect(layout.flowPositions.size).toBe(0);
    expect(layout.entryEdges).toEqual([]);
    expect(layout.flowCallEdges).toEqual([]);
    expect(layout.inlineAnchors).toEqual([]);
    expect(layout.rootEdges.map(edge => edge.scope)).toEqual(["backend", "edge", "frontend"]);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(topLevelLayoutObstacleHits(layout)).toEqual([]);
  });

  it("keeps multiple expanded entrypoint flowcharts attached to their row", () => {
    const layout = createViewerLayout({
      expandedMeasures: new Map([
        ...expandedMeasures,
        [
          "users-route",
          {
            height: 520,
            maxX: 180,
            maxY: 520,
            minX: -180,
            minY: 0,
            width: 360,
          },
        ],
      ]),
      payload,
      routeFlowIds: ["orders-route", "users-route"],
      scope: "frontend",
    });

    const anchors = new Map(layout.inlineAnchors.map(anchor => [anchor.flowId, anchor]));
    const ordersAnchor = anchors.get("orders-route");
    const usersAnchor = anchors.get("users-route");
    const ordersFlow = layout.flowPositions.get("orders-route");
    const usersFlow = layout.flowPositions.get("users-route");
    const loadOrderFlow = layout.flowPositions.get("load-order");
    const loadUserFlow = layout.flowPositions.get("load-user");

    expect(ordersAnchor).toBeDefined();
    expect(usersAnchor).toBeDefined();
    expect(ordersAnchor?.y).toBe(usersAnchor?.y);
    expect(ordersAnchor?.x).toBeCloseTo(ordersFlow?.x ?? 0);
    expect(usersAnchor?.x).toBeCloseTo(usersFlow?.x ?? 0);
    expect(loadOrderFlow?.x).toBeCloseTo(ordersFlow?.x ?? 0);
    expect(loadUserFlow?.x).toBeCloseTo(usersFlow?.x ?? 0);
    expect(loadOrderFlow?.y).toBeGreaterThan(ordersAnchor?.bounds.maxY ?? 0);
    expect(loadUserFlow?.y).toBeGreaterThan(usersAnchor?.bounds.maxY ?? 0);
    expect(layout.flowCallEdges.map(edge => `${edge.source}->${edge.target}`)).toEqual([
      "orders-route->load-order",
      "users-route->load-user",
    ]);
    expect(layout.flowCallEdges.find(edge => edge.source === "orders-route")?.points[0].y).toBeGreaterThan(
      ordersAnchor?.bounds.maxY ?? 0,
    );
    expect(layout.flowCallEdges.find(edge => edge.source === "users-route")?.points[0].y).toBeGreaterThan(
      usersAnchor?.bounds.maxY ?? 0,
    );
    expect(layout.flowCallEdges.find(edge => edge.source === "users-route")?.points[2].x).toBe(
      loadUserFlow?.x,
    );
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(flowCallLayoutObstacleHits(layout)).toEqual([]);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
  });

  it("pushes pre-existing flow nodes below newly expanded detail content", () => {
    const base = createViewerLayout({
      expandedMeasures,
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });
    const ordersDetail = base.inlineAnchors.find(anchor => anchor.flowId === "orders-route");
    if (!ordersDetail) throw new Error("expected orders detail anchor");

    const layout = createViewerLayout({
      expandedMeasures,
      manualNodePositions: new Map([
        [
          viewerNodeKey("flow", "users-route"),
          {
            x: (ordersDetail.bounds.minX + ordersDetail.bounds.maxX) / 2,
            y: (ordersDetail.bounds.minY + ordersDetail.bounds.maxY) / 2,
          },
        ],
      ]),
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });
    const resolvedDetail = layout.inlineAnchors.find(anchor => anchor.flowId === "orders-route");
    const usersRoute = layout.flowPositions.get("users-route");

    expect(resolvedDetail).toBeDefined();
    expect(usersRoute).toBeDefined();
    expect(usersRoute?.y).toBeGreaterThan(
      (resolvedDetail?.bounds.maxY ?? 0) + usersRoute!.height / 2,
    );
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
  });

  it("separates overlapping expanded detail regions after manual node movement", () => {
    const expandedBoth = new Map<string, ExpandedFlowMeasure>([
      ...expandedMeasures,
      [
        "users-route",
        {
          height: 520,
          maxX: 180,
          maxY: 520,
          minX: -180,
          minY: 0,
          width: 360,
        },
      ],
    ]);
    const base = createViewerLayout({
      expandedMeasures: expandedBoth,
      payload,
      routeFlowIds: ["orders-route", "users-route"],
      scope: "frontend",
    });
    const ordersDetail = base.inlineAnchors.find(anchor => anchor.flowId === "orders-route");
    const usersRoute = base.flowPositions.get("users-route");
    if (!ordersDetail || !usersRoute) {
      throw new Error("expected orders detail and users route");
    }

    const layout = createViewerLayout({
      expandedMeasures: expandedBoth,
      manualNodePositions: new Map([
        [
          viewerNodeKey("flow", "users-route"),
          {
            x: (ordersDetail.bounds.minX + ordersDetail.bounds.maxX) / 2,
            y: ordersDetail.bounds.minY + usersRoute.height / 2,
          },
        ],
      ]),
      payload,
      routeFlowIds: ["orders-route", "users-route"],
      scope: "frontend",
    });
    const resolvedAnchors = new Map(layout.inlineAnchors.map(anchor => [anchor.flowId, anchor]));
    const resolvedOrders = resolvedAnchors.get("orders-route");
    const resolvedUsers = resolvedAnchors.get("users-route");

    expect(resolvedOrders).toBeDefined();
    expect(resolvedUsers).toBeDefined();
    expect(resolvedUsers?.bounds.minY).toBeGreaterThan(resolvedOrders?.bounds.maxY ?? 0);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
  });

  it("keeps directly opened internal flowcharts reachable from the codebase root", () => {
    const callChainPayload: LogicChartPayload = {
      flows: [
        {
          id: "entry",
          name: "GET",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "frontend/app/api/users/route.ts", start_line: 1 },
          calls: ["load-user"],
          called_by: [],
          metadata: { scope: ["frontend"] },
        },
        {
          id: "load-user",
          name: "loadUser",
          language: "typescript",
          entry_kind: "function",
          location: { path: "frontend/lib/load-user.ts", start_line: 9 },
          calls: ["audit-user"],
          called_by: ["entry"],
          metadata: { scope: ["frontend"] },
        },
        {
          id: "audit-user",
          name: "auditUser",
          language: "typescript",
          entry_kind: "function",
          location: { path: "frontend/lib/audit-user.ts", start_line: 21 },
          calls: [],
          called_by: ["load-user"],
          metadata: { scope: ["frontend"] },
        },
      ],
    };
    const layout = createViewerLayout({
      expandedMeasures: new Map([
        [
          "audit-user",
          {
            height: 280,
            maxX: 150,
            maxY: 280,
            minX: -150,
            minY: 0,
            width: 300,
          },
        ],
      ]),
      payload: callChainPayload,
      routeFlowIds: ["audit-user"],
      scope: "frontend",
    });
    const report = viewerLayoutQualityReport(layout, { edgeGap: 12, overlapGap: 20 });

    expect(layout.entryEdges.map(edge => `${edge.scope}->${edge.target}`)).toEqual([
      "frontend->entry",
    ]);
    expect(layout.flowPositions.has("entry")).toBe(true);
    expect(layout.flowPositions.has("load-user")).toBe(true);
    expect(layout.flowPositions.has("audit-user")).toBe(true);
    expect(layout.flowCallEdges.map(edge => `${edge.source}->${edge.target}`)).toEqual([
      "entry->load-user",
      "load-user->audit-user",
    ]);
    expect(layout.inlineAnchors.map(anchor => anchor.flowId)).toEqual(["audit-user"]);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
    expect(report).toMatchObject({
      isClear: true,
      structureIssueCount: 0,
      structureIssues: [],
    });
    expect(viewerLayoutStructureIssues({ ...layout, flowCallEdges: [] })).toEqual([
      { id: "load-user", kind: "visible-flow-unreachable" },
      { id: "audit-user", kind: "visible-flow-unreachable" },
    ]);
  });

  it("preserves explicit active scope overrides without moving sibling scopes", () => {
    const layout = createViewerLayout({
      payload,
      scope: "frontend",
      scopeNode: { scope: "frontend", x: 520, y: 80, width: 220, height: 108 },
    });
    const positions = new Map(layout.scopeNodes.map(node => [node.scope, node.x]));

    expect(positions.get("frontend")).toBe(520);
    expect(positions.get("edge")).not.toBe(520);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
  });

  it("applies manual positions through the same node override map for root, scopes, and flows", () => {
    const base = createViewerLayout({
      expandedMeasures,
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });
    const baseOrdersRoute = base.flowPositions.get("orders-route");
    const baseUsersRoute = base.flowPositions.get("users-route");
    const baseOrdersAnchor = base.inlineAnchors.find(anchor => anchor.flowId === "orders-route");
    const baseScopeBottom = Math.max(
      ...base.scopeNodes.map(node => node.y + node.height / 2),
    );

    const layout = createViewerLayout({
      expandedMeasures,
      manualNodePositions: new Map([
        [viewerNodeKey("root", "codebase"), { x: -460, y: -180 }],
        [viewerNodeKey("scope", "frontend"), { x: 390, y: 120 }],
        [viewerNodeKey("flow", "orders-route"), { x: 40, y: 360 }],
      ]),
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });

    expect(layout.rootNode.x).toBe(-460);
    expect(layout.rootNode.y).toBe(-180);
    expect(layout.activeScopeNode.x).toBe(390);
    expect(layout.activeScopeNode.y).toBe(120);
    expect(layout.flowPositions.get("orders-route")?.x).toBe(40);
    expect(layout.flowPositions.get("orders-route")?.y).toBe(360);
    const scopeDx = layout.activeScopeNode.x - base.activeScopeNode.x;
    const scopeBottom = Math.max(...layout.scopeNodes.map(node => node.y + node.height / 2));
    expect(layout.flowPositions.get("users-route")?.x).toBeCloseTo(
      (baseUsersRoute?.x ?? 0) + scopeDx,
    );
    expect(layout.flowPositions.get("users-route")?.y).toBeCloseTo(
      (baseUsersRoute?.y ?? 0) + scopeBottom - baseScopeBottom,
    );
    expect(layout.entryEdges.map(edge => edge.d)).not.toEqual(base.entryEdges.map(edge => edge.d));
    expect(layout.inlineAnchors.find(anchor => anchor.flowId === "orders-route")?.x).toBeCloseTo(
      (baseOrdersAnchor?.x ?? 0) + 40 - (baseOrdersRoute?.x ?? 0),
    );
  });

  it("keeps unlocked call children attached when an expanded host flow is manually moved", () => {
    const base = createViewerLayout({
      expandedMeasures,
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });
    const baseHost = base.flowPositions.get("orders-route");
    const baseChild = base.flowPositions.get("load-order");
    const baseAnchor = base.inlineAnchors.find(anchor => anchor.flowId === "orders-route");
    if (!baseHost || !baseChild || !baseAnchor) {
      throw new Error("expected expanded host, anchor, and child");
    }

    const dx = 180;
    const dy = 96;
    const layout = createViewerLayout({
      expandedMeasures,
      manualNodePositions: new Map([
        [
          viewerNodeKey("flow", "orders-route"),
          {
            x: baseHost.x + dx,
            y: baseHost.y + dy,
          },
        ],
      ]),
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });
    const movedHost = layout.flowPositions.get("orders-route");
    const movedChild = layout.flowPositions.get("load-order");
    const movedAnchor = layout.inlineAnchors.find(anchor => anchor.flowId === "orders-route");
    const movedEdge = layout.flowCallEdges.find(edge => edge.source === "orders-route");

    expect(movedHost?.x).toBeCloseTo(baseHost.x + dx);
    expect(movedHost?.y).toBeCloseTo(baseHost.y + dy);
    expect(movedAnchor?.x).toBeCloseTo(movedHost?.x ?? 0);
    expect(movedAnchor?.y).toBeCloseTo(baseAnchor.y + dy);
    expect(movedChild?.x).toBeCloseTo(baseChild.x + dx);
    expect(movedChild?.y).toBeCloseTo(baseChild.y + dy);
    expect(movedEdge?.points[0].x).toBeCloseTo(movedHost?.x ?? 0);
    expect(movedEdge?.points[2].x).toBeCloseTo(movedChild?.x ?? 0);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(flowCallLayoutObstacleHits(layout)).toEqual([]);
  });

  it("wraps large codebase entrypoint sets while preserving scope fan-out", () => {
    const largePayload: LogicChartPayload = {
      flows: Array.from({ length: 26 }, (_, index) => ({
        id: `api-entry-${index}`,
        name: `GET /resource/${index}`,
        language: "typescript",
        entry_kind: "route",
        is_entrypoint: true,
        location: {
          path: `frontend/app/api/resource-${index}/route.ts`,
          start_line: 1,
        },
        calls: [],
        called_by: [],
        metadata: { scope: ["frontend"] },
      })),
    };
    const layout = createViewerLayout({
      payload: largePayload,
      scope: "frontend",
    });

    expect(layout.entryEdges).toHaveLength(26);
    expect(layout.flowPositions).toHaveLength(26);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 24)).toEqual([]);
    expect(topLevelLayoutObstacleHits(layout)).toEqual([]);
    expect(layout.viewBox.maxX - layout.viewBox.minX).toBeLessThan(3000);
  });

  it("keeps dense multi-scope expanded codebase flows connected and collision-free", () => {
    const densePayload = denseCodebasePayload();
    const denseScopes = ["api-gateway", "mobile-app", "shared_kernel"];
    const routeFlowIds = densePayload.flows
      .filter(flow => flow.id.includes("-entry-") || flow.id.includes("-service-"))
      .map(flow => flow.id);
    const denseMeasures = new Map<string, ExpandedFlowMeasure>(
      routeFlowIds.map((id, index) => [
        id,
        {
          height: 360 + (index % 3) * 76,
          maxX: 180 + (index % 2) * 48,
          maxY: 360 + (index % 3) * 76,
          minX: -180 - (index % 2) * 48,
          minY: 0,
          width: 360 + (index % 2) * 96,
        },
      ]),
    );
    const layout = createViewerLayout({
      expandedMeasures: denseMeasures,
      expandedScopes: denseScopes,
      payload: densePayload,
      routeFlowIds,
      scope: "mobile-app",
    });

    expect(layout.scopeNodes.filter(node => node.expanded).map(node => node.scope).sort()).toEqual([
      "api-gateway",
      "mobile-app",
      "shared_kernel",
    ]);
    expect(layout.flowPositions.size).toBeGreaterThan(60);
    expect(layout.inlineAnchors).toHaveLength(routeFlowIds.length);
    expect(layout.flowCallEdges.length).toBeGreaterThan(45);
    expect(overlappingLayoutBoxes(viewerLayoutBoxes(layout), 20)).toEqual([]);
    expect(viewerLayoutEdgeObstacleHits(layout, 12)).toEqual([]);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
    const report = viewerLayoutQualityReport(layout, { edgeGap: 12, overlapGap: 20 });
    expect(report).toMatchObject({
      detailRegionCount: routeFlowIds.length,
      edgeObstacleHits: [],
      flowNodeCount: layout.flowPositions.size,
      isClear: true,
      overlapCount: 0,
    });
    expect(report.edgeCount).toBe(
      report.rootEdgeCount + report.scopeEntryEdgeCount + report.flowCallEdgeCount,
    );
    expect(report.density).toBeGreaterThan(0);
    expect(report.density).toBeLessThanOrEqual(1);
    expect(layout.viewBox.maxX - layout.viewBox.minX).toBeGreaterThan(3000);
    expect(layout.viewBox.maxY - layout.viewBox.minY).toBeGreaterThan(1800);
  });

  it("keeps cross-scope calls connected as one codebase graph", () => {
    const crossScopePayload: LogicChartPayload = {
      flows: [
        {
          id: "client-entry",
          name: "Render profile",
          language: "kotlin",
          entry_kind: "screen",
          is_entrypoint: true,
          location: { path: "client-app/profile-screen.kt", start_line: 7 },
          calls: ["service-gateway"],
          called_by: [],
          metadata: { scope: ["client-app"] },
        },
        {
          id: "client-cache",
          name: "cacheProfile",
          language: "kotlin",
          entry_kind: "function",
          location: { path: "client-app/profile-cache.kt", start_line: 14 },
          calls: [],
          called_by: ["client-entry"],
          metadata: { scope: ["client-app"] },
        },
        {
          id: "service-health",
          name: "Health",
          language: "go",
          entry_kind: "handler",
          is_entrypoint: true,
          location: { path: "service-mesh/health.go", start_line: 3 },
          calls: [],
          called_by: [],
          metadata: { scope: ["service-mesh"] },
        },
        {
          id: "service-gateway",
          name: "profileGateway",
          language: "go",
          entry_kind: "function",
          location: { path: "service-mesh/profile.go", start_line: 22 },
          calls: ["shared-policy"],
          called_by: ["client-entry"],
          metadata: { scope: ["service-mesh"] },
        },
        {
          id: "shared-entry",
          name: "Shared policy job",
          language: "rust",
          entry_kind: "job",
          is_entrypoint: true,
          location: { path: "shared-core/job.rs", start_line: 3 },
          calls: ["shared-policy"],
          called_by: [],
          metadata: { scope: ["shared-core"] },
        },
        {
          id: "shared-policy",
          name: "EvaluatePolicy",
          language: "rust",
          entry_kind: "function",
          location: { path: "shared-core/policy.rs", start_line: 41 },
          calls: [],
          called_by: ["service-gateway", "shared-entry"],
          metadata: { scope: ["shared-core"] },
        },
      ],
    };
    const layout = createViewerLayout({
      expandedMeasures: new Map([
        [
          "service-gateway",
          {
            height: 440,
            maxX: 220,
            maxY: 440,
            minX: -220,
            minY: 0,
            width: 440,
          },
        ],
      ]),
      expandedScopes: ["client-app", "service-mesh", "shared-core"],
      contextFlowIds: ["client-entry", "shared-policy"],
      payload: crossScopePayload,
      routeFlowIds: ["service-gateway"],
      scope: "service-mesh",
    });
    const report = viewerLayoutQualityReport(layout, { edgeGap: 12, overlapGap: 20 });

    expect(layout.scopeNodes.filter(node => node.expanded).map(node => node.scope).sort()).toEqual([
      "client-app",
      "service-mesh",
      "shared-core",
    ]);
    expect([...layout.flowPositions.keys()].sort()).toEqual([
      "client-cache",
      "client-entry",
      "service-gateway",
      "service-health",
      "shared-entry",
      "shared-policy",
    ]);
    expect(layout.inlineAnchors.map(anchor => anchor.flowId)).toEqual(["service-gateway"]);
    expect(layout.entryEdges.map(edge => `${edge.scope}->${edge.target}`).sort()).toEqual([
      "client-app->client-entry",
      "service-mesh->service-health",
      "shared-core->shared-entry",
    ]);
    expect(layout.flowCallEdges.map(edge => `${edge.source}->${edge.target}`).sort()).toEqual([
      "client-entry->client-cache",
      "client-entry->service-gateway",
      "service-gateway->shared-policy",
      "shared-entry->shared-policy",
    ]);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
    expect(report).toMatchObject({
      edgeObstacleHits: [],
      isClear: true,
      overlapCount: 0,
      structureIssues: [],
    });
  });

  it("routes root scope elbows around manually moved scope blocks", () => {
    const base = createViewerLayout({
      payload,
      scope: "frontend",
    });
    const targetEdge = base.rootEdges.find(edge => edge.scope === "frontend");
    const blockerScope = base.scopeNodes.find(scope => scope.scope === "edge");
    if (!targetEdge || !blockerScope) throw new Error("expected root scope edge and blocker");
    const fixedLaneY = targetEdge.points[1].y;
    const layout = createViewerLayout({
      manualNodePositions: new Map([
        [
          viewerNodeKey("scope", "edge"),
          {
            x: (targetEdge.points[0].x + targetEdge.points[2].x) / 2,
            y: fixedLaneY,
          },
        ],
      ]),
      payload,
      scope: "frontend",
    });
    const routedEdge = layout.rootEdges.find(edge => edge.scope === "frontend");
    const movedBlocker = layout.scopeNodes.find(scope => scope.scope === "edge");

    expect(routedEdge).toBeDefined();
    expect(movedBlocker).toBeDefined();
    expect(routedEdge?.points[1].y).not.toBeCloseTo(fixedLaneY);
    expect(topLevelLayoutObstacleHits(layout)).toEqual([]);
  });

  it("routes scope entrypoint elbows around manually moved entry blocks", () => {
    const entryObstaclePayload: LogicChartPayload = {
      flows: [
        {
          id: "source-entry",
          name: "Source",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "platform/a-source.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["platform"] },
        },
        {
          id: "blocker-entry",
          name: "Blocker",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "platform/b-blocker.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["platform"] },
        },
        {
          id: "target-entry",
          name: "Target",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "platform/c-target.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["platform"] },
        },
      ],
    };
    const base = createViewerLayout({
      payload: entryObstaclePayload,
      scope: "platform",
    });
    const targetEdge = base.entryEdges.find(edge => edge.target === "target-entry");
    if (!targetEdge) throw new Error("expected target entry edge");
    const fixedLaneY = targetEdge.points[1].y;
    const layout = createViewerLayout({
      manualNodePositions: new Map([
        [
          viewerNodeKey("flow", "blocker-entry"),
          {
            x: (targetEdge.points[0].x + targetEdge.points[2].x) / 2,
            y: fixedLaneY,
          },
        ],
      ]),
      payload: entryObstaclePayload,
      scope: "platform",
    });
    const routedEdge = layout.entryEdges.find(edge => edge.target === "target-entry");

    expect(routedEdge).toBeDefined();
    expect(routedEdge?.points[1].y).not.toBeCloseTo(fixedLaneY);
    expect(topLevelLayoutObstacleHits(layout)).toEqual([]);
  });

  it("assigns separate elbow lanes to high fan-out flow-call edges", () => {
    const fanoutPayload: LogicChartPayload = {
      flows: [
        {
          id: "entry",
          name: "Entry",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "frontend/app/api/entry/route.ts", start_line: 1 },
          calls: ["target-0", "target-1", "target-2", "target-3", "target-4"],
          called_by: [],
          metadata: { scope: ["frontend"] },
        },
        ...Array.from({ length: 5 }, (_, index) => ({
          id: `target-${index}`,
          name: `target${index}`,
          language: "typescript",
          entry_kind: "function",
          location: { path: `frontend/lib/target-${index}.ts`, start_line: index + 1 },
          calls: [],
          called_by: ["entry"],
          metadata: { scope: ["frontend"] },
        })),
      ],
    };
    const layout = createViewerLayout({
      payload: fanoutPayload,
      routeFlowIds: ["entry"],
      scope: "frontend",
    });

    expect(layout.flowCallEdges).toHaveLength(5);
    const laneGroups = new Map<string, number[]>();
    layout.flowCallEdges.forEach(edge => {
      const key = `${edge.points[0].y}:${edge.points[3].y}`;
      laneGroups.set(key, [...(laneGroups.get(key) || []), edge.points[1].y]);
      expect(edge.points[1].y).toBeGreaterThan(edge.points[0].y);
      expect(edge.points[1].y).toBeLessThan(edge.points[3].y);
    });
    laneGroups.forEach(lanes => {
      expect(new Set(lanes).size).toBe(lanes.length);
    });
    expect(flowCallLayoutObstacleHits(layout)).toEqual([]);
  });

  it("routes lateral flow-call elbows around intervening blocks", () => {
    const lateralPayload: LogicChartPayload = {
      flows: [
        {
          id: "source-entry",
          name: "Source",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "platform/a-source.ts", start_line: 1 },
          calls: ["target-entry"],
          called_by: [],
          metadata: { scope: ["platform"] },
        },
        {
          id: "blocker-entry",
          name: "Blocker",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "platform/b-blocker.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["platform"] },
        },
        {
          id: "target-entry",
          name: "Target",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "platform/c-target.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["platform"] },
        },
      ],
    };
    const base = createViewerLayout({
      payload: lateralPayload,
      routeFlowIds: ["source-entry"],
      scope: "platform",
    });
    const source = base.flowPositions.get("source-entry");
    const target = base.flowPositions.get("target-entry");
    if (!source || !target) throw new Error("expected lateral source and target");
    const fixedLaneY = Math.max(
      source.y + source.height / 2,
      target.y + target.height / 2,
    ) + 78;
    const layout = createViewerLayout({
      manualNodePositions: new Map([
        [
          viewerNodeKey("flow", "blocker-entry"),
          {
            x: (source.x + target.x) / 2,
            y: fixedLaneY,
          },
        ],
      ]),
      payload: lateralPayload,
      routeFlowIds: ["source-entry"],
      scope: "platform",
    });
    const edge = layout.flowCallEdges.find(edge => edge.source === "source-entry");
    const blocker = layout.flowPositions.get("blocker-entry");

    expect(edge).toBeDefined();
    expect(blocker).toBeDefined();
    expect(edge?.points[1].y).toBeGreaterThan((blocker?.y ?? 0) + (blocker?.height ?? 0) / 2 + 18);
    expect(flowCallLayoutObstacleHits(layout)).toEqual([]);
  });
});

const expandedMeasures = new Map<string, ExpandedFlowMeasure>([
  [
    "orders-route",
    {
      height: 398,
      maxX: 150,
      maxY: 398,
      minX: -150,
      minY: 0,
      width: 300,
    },
  ],
]);

function denseCodebasePayload(): LogicChartPayload {
  const scopeSpecs = [
    {
      entryKind: "handler",
      extension: "go",
      language: "go",
      scope: "api-gateway",
    },
    {
      entryKind: "screen",
      extension: "kt",
      language: "kotlin",
      scope: "mobile-app",
    },
    {
      entryKind: "job",
      extension: "rs",
      language: "rust",
      scope: "shared_kernel",
    },
  ];
  const flows = scopeSpecs.flatMap(({ entryKind, extension, language, scope }) => {
    const entries = Array.from({ length: 8 }, (_, index) => {
      const entryId = `${scope}-entry-${index}`;
      const serviceId = `${scope}-service-${index}`;
      const sharedId = `${scope}-shared-${index % 4}`;
      return {
        id: entryId,
        name: `${scope} entry ${index}`,
        language,
        entry_kind: entryKind,
        is_entrypoint: true,
        location: {
          path: `${scope}/entry-${index}.${extension}`,
          start_line: index + 1,
        },
        calls: [serviceId, sharedId],
        called_by: [],
        metadata: { scope: [scope] },
      };
    });
    const services = Array.from({ length: 8 }, (_, index) => {
      const serviceId = `${scope}-service-${index}`;
      const sharedId = `${scope}-shared-${index % 4}`;
      const terminalId = `${scope}-terminal-${index % 3}`;
      return {
        id: serviceId,
        name: `${scope} service ${index}`,
        language,
        entry_kind: "function",
        location: {
          path: `${scope}/service-${index}.${extension}`,
          start_line: index + 10,
        },
        calls: [sharedId, terminalId],
        called_by: [`${scope}-entry-${index}`],
        metadata: { scope: [scope] },
      };
    });
    const shared = Array.from({ length: 4 }, (_, index) => {
      const sharedId = `${scope}-shared-${index}`;
      return {
        id: sharedId,
        name: `${scope} shared ${index}`,
        language,
        entry_kind: "function",
        location: {
          path: `${scope}/shared-${index}.${extension}`,
          start_line: index + 30,
        },
        calls: [`${scope}-terminal-${index % 3}`],
        called_by: [
          `${scope}-entry-${index}`,
          `${scope}-entry-${index + 4}`,
          `${scope}-service-${index}`,
          `${scope}-service-${index + 4}`,
        ],
        metadata: { scope: [scope] },
      };
    });
    const terminals = Array.from({ length: 3 }, (_, index) => {
      const terminalId = `${scope}-terminal-${index}`;
      return {
        id: terminalId,
        name: `${scope} terminal ${index}`,
        language,
        entry_kind: "function",
        location: {
          path: `${scope}/terminal-${index}.${extension}`,
          start_line: index + 50,
        },
        calls: [],
        called_by: [
          `${scope}-service-${index}`,
          `${scope}-service-${index + 3}`,
          `${scope}-shared-${index}`,
        ],
        metadata: { scope: [scope] },
      };
    });
    return [...entries, ...services, ...shared, ...terminals];
  });

  return { flows };
}
