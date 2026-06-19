import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  mountStandaloneLogicChartViewer,
  propsFromLocation,
  type LogicChartPayload,
  type MountedStandaloneLogicChartViewer,
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

describe("standalone viewer bridge", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("derives scope and route from hash values", () => {
    expect(propsFromLocation(payload, { location: { hash: "#scope=backend" } })).toMatchObject({
      routeFlowIds: [],
      scope: "backend",
    });

    expect(propsFromLocation(payload, { location: { hash: "#flow=orders-route" } })).toMatchObject({
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });

    expect(propsFromLocation(payload, { location: { hash: "#path=edge/native" } })).toMatchObject({
      routeFlowIds: [],
      scope: "edge",
    });

    expect(
      propsFromLocation(payload, {
        initialScope: "frontend",
        location: { hash: "#root" },
      }),
    ).toMatchObject({
      expandedScopes: [],
      routeFlowIds: [],
      scope: "frontend",
    });

    expect(
      propsFromLocation(payload, {
        initialScope: "frontend",
        location: { hash: "#node=codebase" },
      }),
    ).toMatchObject({
      routeFlowIds: [],
      scope: "frontend",
      selectedRoot: true,
    });

    expect(
      propsFromLocation(payload, {
        location: {
          hash: `#edge=${encodeURIComponent(
            JSON.stringify({ scope: "frontend", target: "orders-route" }),
          )}`,
        },
      }),
    ).toMatchObject({
      routeFlowIds: [],
      scope: "frontend",
      selectedConnection: {
        kind: "scope-entry",
        scope: "frontend",
        target: "orders-route",
      },
    });

    expect(
      propsFromLocation(payload, {
        location: {
          hash: `#edge=${encodeURIComponent(
            JSON.stringify({ kind: "root-scope", scope: "frontend" }),
          )}`,
        },
      }),
    ).toMatchObject({
      routeFlowIds: [],
      scope: "frontend",
      selectedConnection: {
        kind: "root-scope",
        scope: "frontend",
      },
    });

    expect(
      propsFromLocation(payload, {
        location: {
          hash: `#edge=${encodeURIComponent(
            JSON.stringify({
              kind: "flow-call",
              source: "orders-route",
              target: "load-order",
            }),
          )}`,
        },
      }),
    ).toMatchObject({
      routeFlowIds: ["orders-route"],
      scope: "frontend",
      selectedConnection: {
        kind: "flow-call",
        source: "orders-route",
        target: "load-order",
      },
    });
  });

  it("decodes edge hash values without relying on browser URI globals", () => {
    vi.stubGlobal("decodeURIComponent", undefined);

    expect(
      propsFromLocation(payload, {
        location: {
          hash: `#edge=${encodeURIComponent(
            JSON.stringify({ scope: "frontend", target: "orders-route" }),
          )}`,
        },
      }),
    ).toMatchObject({
      selectedConnection: {
        kind: "scope-entry",
        scope: "frontend",
        target: "orders-route",
      },
    });
  });

  it("mounts the React viewer into an existing generated HTML host", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);

    let mounted: MountedStandaloneLogicChartViewer | undefined;
    await act(async () => {
      mounted = mountStandaloneLogicChartViewer(container, payload, {
        location: { hash: "#scope=frontend" },
      });
    });

    expect(container.querySelector(".logicchart-viewer")).not.toBeNull();
    expect(container.querySelectorAll("[data-scope]")).toHaveLength(2);
    expect(container.querySelector('[data-flow-id="orders-route"]')).not.toBeNull();

    await act(async () => {
      mounted?.unmount();
    });
    container.remove();
  });

  it("mounts with a selected edge from the hash", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload, {
      location: {
        hash: `#edge=${encodeURIComponent(
          JSON.stringify({ scope: "frontend", target: "orders-route" }),
        )}`,
      },
    });

    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "scope-entry",
    );
    expect(container.querySelectorAll(".scope-entry-link.selected-link")).toHaveLength(1);
    expect(container.querySelectorAll(".node.edge-source")).toHaveLength(1);
    expect(container.querySelectorAll(".node.edge-target")).toHaveLength(1);

    mounted.unmount();
    container.remove();
  });

  it("mounts directly to a selected cross-scope call edge", async () => {
    const edgeHash = `#edge=${encodeURIComponent(
      JSON.stringify({
        kind: "flow-call",
        source: "client-entry",
        target: "service-gateway",
      }),
    )}`;
    expect(
      propsFromLocation(crossScopePayload, {
        location: { hash: edgeHash },
      }),
    ).toMatchObject({
      routeFlowIds: ["client-entry"],
      scope: "client-app",
      selectedConnection: {
        kind: "flow-call",
        source: "client-entry",
        target: "service-gateway",
      },
    });
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, crossScopePayload, {
      location: { hash: edgeHash },
    });

    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "flow-call",
    );
    expect(container.querySelector('[data-scope="client-app"]')).not.toBeNull();
    expect(container.querySelector('[data-scope="service-mesh"]')).not.toBeNull();
    expect(container.querySelector('[data-scope="shared-core"]')?.getAttribute("class")).not.toContain(
      "expanded",
    );
    expect(container.querySelector('[data-flow-id="client-entry"]')?.getAttribute("class")).toContain(
      "edge-source",
    );
    expect(
      container.querySelector('[data-flow-id="service-gateway"]')?.getAttribute("class"),
    ).toContain("edge-target");
    expect(
      container.querySelector(
        '.flow-call-link.selected-link[data-source-flow-id="client-entry"][data-called-flow-id="service-gateway"]',
      ),
    ).not.toBeNull();

    mounted.unmount();
    container.remove();
  });

  it("opens direct caller and callee scopes when a cross-scope internal flow is selected", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);

    let mounted: MountedStandaloneLogicChartViewer | undefined;
    await act(async () => {
      mounted = mountStandaloneLogicChartViewer(container, crossScopePayload, {
        location: { hash: "#flow=service-gateway" },
      });
    });

    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "flow",
    );
    expect(container.querySelector('[data-scope="client-app"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(container.querySelector('[data-scope="service-mesh"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(container.querySelector('[data-scope="shared-core"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(
      container.querySelector('[data-flow-id="service-gateway"]')?.getAttribute("class"),
    ).toContain("selected");
    expect(container.querySelector('[data-flow-id="client-entry"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector('[data-flow-id="shared-entry"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="shared-policy"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(
      container.querySelector(
        '.flow-call-link[data-source-flow-id="client-entry"][data-called-flow-id="service-gateway"]',
      ),
    ).not.toBeNull();
    expect(
      container.querySelector(
        '.flow-call-link[data-source-flow-id="service-gateway"][data-called-flow-id="shared-policy"]',
      ),
    ).not.toBeNull();

    mounted?.unmount();
    container.remove();
  });

  it("selects root-to-scope edges as first-class flowchart connections", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    const rootEdge = container.querySelector(".root-scope-link[data-target-scope='frontend']");
    expect(rootEdge).not.toBeNull();

    await act(async () => {
      rootEdge?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toContain("#edge=");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "root-scope",
    );
    expect(container.querySelectorAll(".root-scope-link.selected-link")).toHaveLength(1);
    expect(container.querySelector('[data-root-id="codebase"]')?.getAttribute("class")).toContain(
      "edge-source",
    );
    expect(container.querySelector('[data-scope="frontend"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelectorAll(".flow-node.dimmed").length).toBeGreaterThan(0);
    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: null,
      findingId: null,
      flowId: null,
      line: null,
      nodeId: null,
      path: null,
      scope: "frontend",
    });
    expect(openDetails).toHaveBeenCalled();

    mounted.unmount();
    container.remove();
  });

  it("highlights all scopes connected to the root node", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-root-id="codebase"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(window.location.hash).toBe("#node=codebase");
    expect(container.querySelector('[data-root-id="codebase"]')?.getAttribute("class")).toContain(
      "selected",
    );
    expect(container.querySelectorAll(".root-scope-link.incident")).toHaveLength(2);
    expect(container.querySelectorAll(".scope-node.edge-target")).toHaveLength(2);
    expect(container.querySelector('[data-flow-id="orders-route"]')).not.toBeNull();
    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: null,
      findingId: null,
      flowId: null,
      line: null,
      nodeId: null,
      path: null,
      scope: null,
    });
    expect(openDetails).toHaveBeenCalled();

    mounted.unmount();
    container.remove();
  });

  it("selects the codebase root from the collapsed root route without expanding a scope", async () => {
    window.history.replaceState(null, "", "/#root");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);
    expect(container.querySelectorAll(".scope-node.expanded")).toHaveLength(0);

    await act(async () => {
      container
        .querySelector('[data-root-id="codebase"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toBe("#node=codebase");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "root",
    );
    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);
    expect(container.querySelectorAll(".scope-node.expanded")).toHaveLength(0);
    expect(container.querySelectorAll(".root-scope-link.incident")).toHaveLength(2);
    expect(container.querySelectorAll(".scope-node.edge-target")).toHaveLength(2);

    mounted.unmount();
    container.remove();
  });

  it("selects root-to-scope edges from the collapsed root without expanding the scope", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const seedContainer = document.createElement("div");
    document.body.appendChild(seedContainer);
    const seeded = mountStandaloneLogicChartViewer(seedContainer, payload);

    expect(seedContainer.querySelectorAll(".flow-node").length).toBeGreaterThan(0);

    seeded.unmount();
    seedContainer.remove();

    window.history.replaceState(null, "", "/#root");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);
    expect(container.querySelectorAll(".scope-node.expanded")).toHaveLength(0);

    await act(async () => {
      container
        .querySelector('.root-scope-link[data-target-scope="frontend"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toContain("#edge=");
    expect(decodeURIComponent(window.location.hash)).toContain('"rootOnly":true');
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "root-scope",
    );
    expect(container.querySelectorAll(".root-scope-link.selected-link")).toHaveLength(1);
    expect(container.querySelector('[data-root-id="codebase"]')?.getAttribute("class")).toContain(
      "edge-source",
    );
    expect(container.querySelector('[data-scope="frontend"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);
    expect(container.querySelectorAll(".scope-node.expanded")).toHaveLength(0);

    mounted.unmount();
    container.remove();
  });

  it("syncs edge selection and blank-canvas clear back to the hash", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector(".scope-entry-link")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(window.location.hash).toContain("#edge=");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "scope-entry",
    );

    const svg = container.querySelector(".logicchart-viewer");
    const hitZone = container.querySelector(".canvas-hit-zone");
    if (!svg || !hitZone) throw new Error("expected viewer hit zone");

    await act(async () => {
      hitZone.dispatchEvent(pointerEvent("pointerdown", { clientX: 200, clientY: 200 }));
      svg.dispatchEvent(pointerEvent("pointerup", { clientX: 201, clientY: 201 }));
    });

    expect(window.location.hash).toBe("#scope=frontend");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "none",
    );

    mounted.unmount();
    container.remove();
  });

  it("keeps connection selection while panning and clears it only on a blank click", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const callEdge = container.querySelector(".flow-call-link");
    expect(callEdge).not.toBeNull();

    await act(async () => {
      callEdge?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    const hitZone = container.querySelector(".canvas-hit-zone");
    if (!svg || !hitZone) throw new Error("expected viewer hit zone");
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: 1000 });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: 700 });
    const selectedHash = window.location.hash;
    const initialViewBox = svg.getAttribute("viewBox");

    await act(async () => {
      hitZone.dispatchEvent(pointerEvent("pointerdown", { clientX: 240, clientY: 220 }));
      svg.dispatchEvent(pointerEvent("pointermove", { clientX: 320, clientY: 270 }));
      svg.dispatchEvent(pointerEvent("pointerup", { clientX: 320, clientY: 270 }));
    });

    expect(window.location.hash).toBe(selectedHash);
    expect(svg.getAttribute("viewBox")).not.toBe(initialViewBox);
    expect(svg.getAttribute("data-selected-kind")).toBe("flow-call");
    expect(container.querySelectorAll(".flow-call-link.selected-link")).toHaveLength(1);

    await act(async () => {
      hitZone.dispatchEvent(pointerEvent("pointerdown", { clientX: 300, clientY: 260 }));
      svg.dispatchEvent(pointerEvent("pointerup", { clientX: 301, clientY: 261 }));
    });

    expect(window.location.hash).toBe("#scope=frontend");
    expect(svg.getAttribute("data-selected-kind")).toBe("none");
    expect(container.querySelectorAll(".flow-call-link.selected-link")).toHaveLength(0);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const flowHash = window.location.hash;
    const flowViewBox = svg.getAttribute("viewBox");
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "selected",
    );

    await act(async () => {
      hitZone.dispatchEvent(pointerEvent("pointerdown", { clientX: 260, clientY: 260 }));
      svg.dispatchEvent(pointerEvent("pointermove", { clientX: 220, clientY: 310 }));
      svg.dispatchEvent(pointerEvent("pointerup", { clientX: 220, clientY: 310 }));
    });

    expect(window.location.hash).toBe(flowHash);
    expect(svg.getAttribute("viewBox")).not.toBe(flowViewBox);
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "selected",
    );

    mounted.unmount();
    container.remove();
  });

  it("syncs flow-call edge selection and publishes target details", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const callEdge = container.querySelector(".flow-call-link");
    expect(callEdge).not.toBeNull();

    await act(async () => {
      callEdge?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toContain("#edge=");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "flow-call",
    );
    expect(container.querySelectorAll(".flow-call-link.selected-link")).toHaveLength(1);
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "edge-source",
    );
    expect(container.querySelector('[data-flow-id="load-order"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: 18,
      findingId: null,
      flowId: "load-order",
      line: 18,
      nodeId: null,
      path: "frontend/app/api/orders/route.ts",
    });
    expect(openDetails).toHaveBeenCalled();

    mounted.unmount();
    container.remove();
  });

  it("opens a flow detail chart when an entrypoint node is selected", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toBe("#flow=orders-route");
    expect(container.querySelector(".flow-detail")).not.toBeNull();
    expect(container.textContent).toContain("Switch on order.state");

    mounted.unmount();
    container.remove();
  });

  it("publishes source details when opened from a flow deep link", async () => {
    window.history.replaceState(null, "", "/#flow=orders-route");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);
    await act(async () => {});

    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "selected",
    );
    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: 3,
      findingId: null,
      flowId: "orders-route",
      line: 3,
      nodeId: null,
      path: "frontend/app/api/orders/route.ts",
    });
    expect(openDetails).toHaveBeenCalled();

    mounted.unmount();
    container.remove();
  });

  it("opens directly selected internal flows as connected caller chains", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      mounted.selectFlow("load-order");
      await flushAsyncTimers(3);
    });

    expect(window.location.hash).toBe("#flow=load-order");
    expect(container.querySelector('[data-flow-id="orders-route"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="load-order"]')).not.toBeNull();
    expect(
      container.querySelector(
        '.flow-call-link[data-source-flow-id="orders-route"][data-called-flow-id="load-order"]',
      ),
    ).not.toBeNull();
    expect(container.querySelector('[data-flow-id="load-order"]')?.getAttribute("class")).toContain(
      "selected",
    );
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector(".scope-entry-link.incident")).not.toBeNull();

    mounted.unmount();
    container.remove();
  });

  it("selects a flow neighborhood and publishes source details when a flow node is clicked", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toBe("#flow=orders-route");
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "selected",
    );
    expect(container.querySelector('[data-flow-id="load-order"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector(".flow-call-link.incident")).not.toBeNull();
    expect(container.querySelector(".scope-entry-link.incident")).not.toBeNull();
    expect(container.querySelectorAll(".flow-node.dimmed").length).toBeGreaterThan(0);
    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: 3,
      findingId: null,
      flowId: "orders-route",
      line: 3,
      nodeId: null,
      path: "frontend/app/api/orders/route.ts",
    });
    expect(openDetails).toHaveBeenCalled();

    mounted.unmount();
    container.remove();
  });

  it("publishes expanded detail-node selections to the shared source panels", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('.flow-node[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const detailNode = container.querySelector('[data-detail-node-id="orders-route:n2"]');
    expect(detailNode).not.toBeNull();

    await act(async () => {
      detailNode?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: 6,
      findingId: null,
      flowId: "orders-route",
      line: 6,
      nodeId: "orders-route:n2",
      path: "frontend/app/api/orders/route.ts",
    });
    expect(openDetails).toHaveBeenCalled();
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "detail-node",
    );
    expect(container.querySelectorAll(".detail-node.selected").length).toBeGreaterThan(1);
    expect(container.querySelectorAll(".flow-detail-edge.incident")).toHaveLength(2);
    expect(container.querySelector('.flow-node[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "edge-source",
    );

    mounted.unmount();
    container.remove();
  });

  it("publishes expanded start-edge selections to the shared source panels", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('.flow-node[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const startEdge = container.querySelector(".flow-detail-start-edge");
    const startEdgeHit = container.querySelector(
      '.flow-detail-edge-hit[data-edge-id="start->orders-route:n2"]',
    );
    const startEdgeId = startEdge?.parentElement?.getAttribute("data-edge-id");
    expect(startEdge).not.toBeNull();
    expect(startEdgeHit).not.toBeNull();
    expect(startEdgeId).toBe("start->orders-route:n2");

    await act(async () => {
      startEdgeHit?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(startEdge?.getAttribute("class")).toContain("selected-link");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "detail-edge",
    );
    expect(container.querySelector('[data-detail-node-id="orders-route:n2"]')?.getAttribute("class")).toContain(
      "selected",
    );
    expect(container.querySelector('[data-detail-node-id="orders-route:n3"]')?.getAttribute("class")).toContain(
      "dimmed",
    );
    expect(select).toHaveBeenLastCalledWith({
      edgeId: "start->orders-route:n2",
      endLine: 6,
      findingId: null,
      flowId: "orders-route",
      line: 6,
      nodeId: "orders-route:n2",
      path: "frontend/app/api/orders/route.ts",
    });
    expect(openDetails).toHaveBeenCalled();

    mounted.unmount();
    container.remove();
  });

  it("keeps opened flow charts expanded until reset", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toBe("#flow=orders-route");
    expect(container.querySelector(".flow-detail")).not.toBeNull();

    const svg = container.querySelector(".logicchart-viewer");
    const hitZone = container.querySelector(".canvas-hit-zone");
    if (!svg || !hitZone) throw new Error("expected viewer hit zone");

    await act(async () => {
      hitZone.dispatchEvent(pointerEvent("pointerdown", { clientX: 200, clientY: 200 }));
      svg.dispatchEvent(pointerEvent("pointerup", { clientX: 200, clientY: 200 }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(window.location.hash).toBe("#scope=frontend");
    expect(container.querySelector(".logicchart-viewer")?.getAttribute("data-selected-kind")).toBe(
      "none",
    );
    expect(container.querySelector(".flow-detail")).not.toBeNull();

    await act(async () => {
      mounted.resetView();
    });

    expect(window.location.hash).toBe("#root");
    expect(container.querySelector(".flow-detail")).toBeNull();
    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);

    await act(async () => {
      hitZone.dispatchEvent(pointerEvent("pointerdown", { clientX: 260, clientY: 220 }));
      svg.dispatchEvent(pointerEvent("pointerup", { clientX: 261, clientY: 221 }));
    });

    expect(window.location.hash).toBe("#root");
    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);

    mounted.unmount();
    container.remove();
  });

  it("expands every scope and flow from the collapsed root until reset", async () => {
    window.history.replaceState(null, "", "/#root");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);

    await act(async () => {
      mounted.expandAll();
      await flushAsyncTimers(2);
    });

    const progress = container.querySelector<HTMLElement>(".logicchart-expand-progress");
    expect(progress).not.toBeNull();
    expect(progress?.hidden).toBe(false);
    expect(progress?.textContent).toContain("Expanding canvas");

    await act(async () => {
      await flushAsyncTimers(1);
    });

    expect(window.location.hash).toBe("#scope=backend");
    expect(container.querySelector('[data-scope="backend"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(container.querySelector('[data-scope="frontend"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(container.querySelector('[data-flow-id="backend-auth"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="orders-route"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="users-route"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="load-order"]')).not.toBeNull();
    expect(container.querySelector(".flow-detail")).toBeNull();

    await act(async () => {
      await flushAsyncTimers(3);
    });

    expect(progress?.hidden).toBe(true);

    await act(async () => {
      mounted.selectFlow("orders-route");
      await flushAsyncTimers(3);
    });

    expect(container.querySelector(".flow-detail")).not.toBeNull();

    await act(async () => {
      mounted.resetView();
    });

    expect(window.location.hash).toBe("#root");
    expect(container.querySelectorAll(".flow-node")).toHaveLength(0);
    expect(container.querySelector(".flow-detail")).toBeNull();

    mounted.unmount();
    container.remove();
  });

  it("keeps previously opened scopes visible while expanding another scope", async () => {
    window.history.replaceState(null, "", "/#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const select = vi.fn();
    const openDetails = vi.fn();
    (window as typeof window & { LC?: unknown }).LC = { openDetails, select };

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    expect(container.querySelector('[data-flow-id="orders-route"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="backend-auth"]')).toBeNull();

    await act(async () => {
      mounted.selectScope("backend");
      await flushAsyncTimers(3);
    });

    expect(window.location.hash).toBe("#scope=backend");
    expect(container.querySelector('[data-scope="frontend"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(container.querySelector('[data-scope="backend"]')?.getAttribute("class")).toContain(
      "expanded",
    );
    expect(container.querySelector('[data-flow-id="orders-route"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="backend-auth"]')).not.toBeNull();
    expect(select).toHaveBeenLastCalledWith({
      edgeId: null,
      endLine: null,
      findingId: null,
      flowId: null,
      line: null,
      nodeId: null,
      path: null,
      scope: "backend",
    });
    expect(openDetails).toHaveBeenCalled();
    expect(
      [...container.querySelectorAll(".scope-entry-link")]
        .map(edge => [
          edge.getAttribute("data-source-scope"),
          edge.getAttribute("data-target-flow-id"),
        ].join("->"))
        .sort(),
    ).toEqual(["backend->backend-auth", "frontend->orders-route", "frontend->users-route"]);

    await act(async () => {
      mounted.resetView();
    });

    expect(window.location.hash).toBe("#root");
    expect(container.querySelector('[data-scope="backend"]')?.getAttribute("class")).not.toContain(
      "expanded",
    );
    expect(container.querySelector('[data-scope="frontend"]')?.getAttribute("class")).not.toContain(
      "expanded",
    );
    expect(container.querySelector('[data-flow-id="backend-auth"]')).toBeNull();
    expect(container.querySelector('[data-flow-id="orders-route"]')).toBeNull();

    mounted.unmount();
    container.remove();
  });

  it("persists opened flow charts and manual positions until reset", async () => {
    window.history.replaceState(null, "", "/viewer.html#scope=frontend");
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    const flowNode = container.querySelector('[data-flow-id="orders-route"]');
    const flowShape = container.querySelector('[data-flow-id="orders-route"] .shape');
    if (!flowNode || !flowShape) throw new Error("expected flow node shape");
    const initialTransform = flowNode.getAttribute("transform");

    await act(async () => {
      flowShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 420, clientY: 260 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 500, clientY: 300 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 500, clientY: 300 }));
    });

    const movedTransform = flowNode.getAttribute("transform");
    expect(movedTransform).not.toBe(initialTransform);
    expect(container.querySelector(".flow-detail")).not.toBeNull();

    const detailNode = container.querySelector('[data-detail-node-id="orders-route:n2"]');
    const detailShape = container.querySelector(
      '[data-detail-node-id="orders-route:n2"] .detail-shape',
    );
    if (!detailNode || !detailShape) throw new Error("expected flow detail node shape");
    const initialDetailTransform = detailNode.getAttribute("transform");

    await act(async () => {
      detailShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 520, clientY: 390 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 610, clientY: 455 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 610, clientY: 455 }));
    });

    const movedDetailTransform = detailNode.getAttribute("transform");
    expect(movedDetailTransform).not.toBe(initialDetailTransform);

    await act(async () => {
      mounted.unmount();
    });
    container.replaceChildren();
    window.history.replaceState(null, "", "/viewer.html#scope=frontend");

    let remounted: MountedStandaloneLogicChartViewer | undefined;
    await act(async () => {
      remounted = mountStandaloneLogicChartViewer(container, payload);
    });
    expect(container.querySelector(".flow-detail")).not.toBeNull();
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("transform")).toBe(
      movedTransform,
    );
    expect(
      container.querySelector('[data-detail-node-id="orders-route:n2"]')?.getAttribute("transform"),
    ).toBe(movedDetailTransform);

    await act(async () => {
      remounted?.resetView();
    });

    expect(container.querySelector(".flow-detail")).toBeNull();
    expect(container.querySelector('[data-flow-id="orders-route"]')).toBeNull();

    await act(async () => {
      remounted?.unmount();
    });
    container.replaceChildren();
    window.history.replaceState(null, "", "/viewer.html#scope=frontend");

    let cleanMount: MountedStandaloneLogicChartViewer | undefined;
    await act(async () => {
      cleanMount = mountStandaloneLogicChartViewer(container, payload);
    });
    expect(container.querySelector(".flow-detail")).toBeNull();
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("transform")).toBe(
      initialTransform,
    );

    await act(async () => {
      container
        .querySelector('[data-flow-id="orders-route"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(
      container.querySelector('[data-detail-node-id="orders-route:n2"]')?.getAttribute("transform"),
    ).toBe(initialDetailTransform);

    cleanMount?.unmount();
    container.remove();
  });

  it("coalesces manual node drag updates and flushes the final position on release", async () => {
    window.history.replaceState(null, "", "/viewer.html#scope=frontend");
    const frames = new Map<number, FrameRequestCallback>();
    let nextFrameId = 1;
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        const id = nextFrameId;
        nextFrameId += 1;
        frames.set(id, callback);
        return id;
      }),
    );
    vi.stubGlobal(
      "cancelAnimationFrame",
      vi.fn((id: number) => {
        frames.delete(id);
      }),
    );
    const runFrames = () => {
      const queued = [...frames.values()];
      frames.clear();
      queued.forEach(callback => callback(16));
    };
    const container = document.createElement("div");
    document.body.appendChild(container);

    const mounted = mountStandaloneLogicChartViewer(container, payload);
    const flowNode = container.querySelector('[data-flow-id="orders-route"]');
    const flowShape = container.querySelector('[data-flow-id="orders-route"] .shape');
    if (!flowNode || !flowShape) throw new Error("expected flow node shape");
    const initialTransform = flowNode.getAttribute("transform");

    await act(async () => {
      flowShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 420, clientY: 260 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 500, clientY: 300 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 540, clientY: 330 }));
    });

    expect(frames.size).toBe(1);
    expect(flowNode.getAttribute("transform")).toBe(initialTransform);

    await act(async () => {
      runFrames();
    });

    const framedTransform = flowNode.getAttribute("transform");
    expect(framedTransform).not.toBe(initialTransform);

    await act(async () => {
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 560, clientY: 350 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 560, clientY: 350 }));
    });

    expect(frames.size).toBe(0);
    expect(flowNode.getAttribute("transform")).not.toBe(framedTransform);

    mounted.unmount();
    container.remove();
  });
});

function pointerEvent(
  type: string,
  options: {
    button?: number;
    clientX: number;
    clientY: number;
    pointerId?: number;
  },
): PointerEvent {
  const event = new MouseEvent(type, {
    bubbles: true,
    button: options.button ?? 0,
    cancelable: true,
    clientX: options.clientX,
    clientY: options.clientY,
  }) as PointerEvent;
  Object.defineProperty(event, "pointerId", {
    configurable: true,
    value: options.pointerId ?? 1,
  });
  return event;
}

async function flushAsyncTimers(count: number): Promise<void> {
  for (let index = 0; index < count; index += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 0));
  }
}

function memoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key) ?? null : null;
    },
    key(index: number) {
      return [...store.keys()][index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
  };
}
