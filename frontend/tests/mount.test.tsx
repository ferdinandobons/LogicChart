import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mountLogicChartViewer, type LogicChartPayload } from "../src";
import { rasterExportSizeForBounds } from "../src/mount";

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

describe("mountLogicChartViewer", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("mounts, updates, and unmounts the viewer in a DOM container", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    expect(container.querySelector(".logicchart-viewer")).not.toBeNull();
    expect(container.querySelector('[data-scope="frontend"]')).not.toBeNull();
    expect(container.querySelector('[data-flow-id="load-order"]')).not.toBeNull();
    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    const flowDetailsLayer = container.querySelector(".flow-details");
    const flowNodesLayer = container.querySelector(".flow-nodes");
    expect(
      flowDetailsLayer && flowNodesLayer
        ? [...(flowDetailsLayer.parentElement?.children ?? [])].indexOf(flowDetailsLayer) <
            [...(flowNodesLayer.parentElement?.children ?? [])].indexOf(flowNodesLayer)
        : false,
    ).toBe(true);
    const initialViewBox = svg?.getAttribute("viewBox");

    mounted.zoom(0.5);
    expect(svg?.getAttribute("viewBox")).not.toBe(initialViewBox);

    if (!svg) throw new Error("expected mounted viewer svg");
    const originalGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, "getBBox");
    Object.defineProperty(SVGElement.prototype, "getBBox", {
      configurable: true,
      value() {
        return {
          height: 220,
          width: 320,
          x: 40,
          y: 60,
        } as DOMRect;
      },
    });
    mounted.fitView();
    expect(svg.getAttribute("viewBox")).toBe("-50 -30 500 400");
    if (originalGetBBox) {
      Object.defineProperty(SVGElement.prototype, "getBBox", originalGetBBox);
    } else {
      delete (SVGElement.prototype as { getBBox?: unknown }).getBBox;
    }

    mounted.resetView();
    expect(svg?.getAttribute("viewBox")).toBe(initialViewBox);
    expect(typeof mounted.exportImage).toBe("function");

    Object.defineProperty(svg, "clientWidth", { configurable: true, value: 1000 });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: 700 });

    svg.dispatchEvent(pointerEvent("pointerdown", { clientX: 240, clientY: 220 }));
    svg.dispatchEvent(pointerEvent("pointermove", { clientX: 320, clientY: 260 }));
    svg.dispatchEvent(pointerEvent("pointerup", { clientX: 320, clientY: 260 }));
    expect(svg.getAttribute("viewBox")).not.toBe(initialViewBox);

    mounted.resetView();
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);

    const rootNode = container.querySelector('[data-root-id="codebase"]');
    const rootShape = container.querySelector('[data-root-id="codebase"] .shape');
    if (!rootShape) throw new Error("expected root node shape");
    const initialRootTransform = rootNode?.getAttribute("transform");
    await act(async () => {
      rootShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 260, clientY: 60 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 340, clientY: 100 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 340, clientY: 100 }));
    });
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    expect(rootNode?.getAttribute("transform")).not.toBe(initialRootTransform);

    await act(async () => {
      mounted.resetView();
    });
    expect(rootNode?.getAttribute("transform")).toBe(initialRootTransform);

    const flowNode = container.querySelector('[data-flow-id="orders-route"]');
    const flowShape = container.querySelector('[data-flow-id="orders-route"] .shape');
    if (!flowShape) throw new Error("expected flow node shape");
    const initialFlowTransform = flowNode?.getAttribute("transform");
    await act(async () => {
      flowShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 420, clientY: 260 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 500, clientY: 300 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 500, clientY: 300 }));
    });
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    expect(flowNode?.getAttribute("transform")).not.toBe(initialFlowTransform);

    await act(async () => {
      mounted.resetView();
    });
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    expect(flowNode?.getAttribute("transform")).toBe(initialFlowTransform);

    const scopeNode = container.querySelector('[data-scope="frontend"]');
    const scopeShape = container.querySelector('[data-scope="frontend"] .shape');
    if (!scopeShape) throw new Error("expected scope node shape");
    const initialScopeTransform = scopeNode?.getAttribute("transform");
    await act(async () => {
      scopeShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 300, clientY: 120 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 360, clientY: 150 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 360, clientY: 150 }));
    });
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    expect(scopeNode?.getAttribute("transform")).not.toBe(initialScopeTransform);

    await act(async () => {
      mounted.resetView();
    });
    expect(scopeNode?.getAttribute("transform")).toBe(initialScopeTransform);

    const detailNode = container.querySelector('[data-detail-node-id="orders-route:n2"]');
    const detailShape = container.querySelector('[data-detail-node-id="orders-route:n2"] .detail-shape');
    if (!detailShape) throw new Error("expected expanded detail node shape");
    const initialDetailTransform = detailNode?.getAttribute("transform");
    await act(async () => {
      detailShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 520, clientY: 430 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 590, clientY: 470 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 590, clientY: 470 }));
    });
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    expect(detailNode?.getAttribute("transform")).not.toBe(initialDetailTransform);

    await act(async () => {
      mounted.resetView();
    });
    expect(detailNode?.getAttribute("transform")).toBe(initialDetailTransform);

    await act(async () => {
      mounted.update({
        payload,
        scope: "backend",
      });
    });

    expect(container.querySelector('[data-scope="backend"]')?.getAttribute("class")).toContain(
      "expanded",
    );

    await act(async () => {
      mounted.unmount();
    });

    expect(container.innerHTML).toBe("");
    container.remove();
  });

  it("focuses a selected open flow instead of shrinking it into the whole scope", async () => {
    const crowdedPayload: LogicChartPayload = {
      flows: [
        ...payload.flows,
        ...Array.from({ length: 14 }, (_, index) => ({
          id: `extra-route-${index}`,
          name: `Route ${index}`,
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: {
            path: `frontend/app/api/extra-${index}/route.ts`,
            start_line: 3,
          },
          calls: [],
          called_by: [],
          metadata: { scope: ["frontend"] },
        })),
      ],
    };
    const container = document.createElement("main");
    document.body.appendChild(container);

    let mounted!: ReturnType<typeof mountLogicChartViewer>;
    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload: crowdedPayload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    if (!svg) throw new Error("expected mounted viewer svg");
    const broadViewBox = parseViewBox(svg);

    await act(async () => {
      mounted.update({
        payload: crowdedPayload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
        selectedFlowId: "orders-route",
      });
    });

    const focusedViewBox = parseViewBox(svg);
    expect(focusedViewBox[2]).toBeLessThan(broadViewBox[2] * 0.75);
    expect(container.querySelector('[data-flow-id="orders-route"]')?.getAttribute("class")).toContain(
      "selected",
    );

    await act(async () => {
      mounted.update({
        payload: crowdedPayload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
        selectedFlowId: null,
      });
    });

    expect(parseViewBox(svg)).toEqual(focusedViewBox);

    mounted.unmount();
    container.remove();
  });

  it("keeps viewport controls on the main canvas without mounting a minimap", async () => {
    const originalGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, "getBBox");
    Object.defineProperty(SVGElement.prototype, "getBBox", {
      configurable: true,
      value() {
        return {
          height: 260,
          width: 420,
          x: 80,
          y: 120,
        } as DOMRect;
      },
    });
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    if (!svg) throw new Error("expected mounted viewer svg");
    expect(container.querySelector(".logicchart-viewer-frame")).not.toBeNull();
    expect(container.querySelector(".logicchart-overview")).toBeNull();
    expect(container.querySelector(".logicchart-overview-map")).toBeNull();

    await act(async () => {
      mounted.fitView();
    });
    expect(svg.getAttribute("viewBox")).toBe("-10 30 600 440");

    const fittedViewBox = parseViewBox(svg);
    mounted.zoom(0.5);
    const zoomedViewBox = parseViewBox(svg);
    expect(zoomedViewBox[2]).toBeLessThan(fittedViewBox[2]);
    expect(zoomedViewBox[3]).toBeLessThan(fittedViewBox[3]);

    Object.defineProperty(svg, "clientWidth", { configurable: true, value: 1000 });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: 700 });

    await act(async () => {
      svg.dispatchEvent(pointerEvent("pointerdown", { clientX: 240, clientY: 220, pointerId: 12 }));
      window.dispatchEvent(
        pointerEvent("pointermove", { clientX: 320, clientY: 260, pointerId: 12 }),
      );
      window.dispatchEvent(
        pointerEvent("pointerup", { clientX: 320, clientY: 260, pointerId: 12 }),
      );
    });
    const draggedViewBox = parseViewBox(svg);
    expect(draggedViewBox[0]).toBeLessThan(zoomedViewBox[0]);
    expect(draggedViewBox[1]).toBeLessThan(zoomedViewBox[1]);
    expect(draggedViewBox[2]).toBeCloseTo(zoomedViewBox[2]);
    expect(draggedViewBox[3]).toBeCloseTo(zoomedViewBox[3]);

    await act(async () => {
      mounted.unmount();
    });
    expect(container.innerHTML).toBe("");
    container.remove();

    if (originalGetBBox) {
      Object.defineProperty(SVGElement.prototype, "getBBox", originalGetBBox);
    } else {
      delete (SVGElement.prototype as { getBBox?: unknown }).getBBox;
    }
  });

  it("keeps scope selection connected to root and entrypoint links", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const frontendScope = container.querySelector('[data-scope="frontend"] .shape');
    if (!frontendScope) throw new Error("expected frontend scope node");

    await act(async () => {
      frontendScope.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const svg = container.querySelector(".logicchart-viewer");
    const selectedScope = container.querySelector('[data-scope="frontend"]');
    const unrelatedScope = container.querySelector('[data-scope="backend"]');
    const connectedFlow = container.querySelector('[data-flow-id="orders-route"]');
    const connectedChildFlow = container.querySelector('[data-flow-id="load-order"]');
    const connectedDetail = container.querySelector('[data-detail-node-id="orders-route:n2"]');

    expect(svg?.getAttribute("data-selected-kind")).toBe("scope");
    expect(selectedScope?.getAttribute("class")).toContain("selected");
    expect(unrelatedScope?.getAttribute("class")).toContain("dimmed");
    expect(connectedFlow?.getAttribute("class")).toContain("edge-target");
    expect(connectedChildFlow?.getAttribute("class")).toContain("edge-target");
    expect(connectedDetail?.getAttribute("class")).not.toContain("dimmed");
    expect(container.querySelector(".root-scope-link.incident")).not.toBeNull();
    expect(container.querySelector(".scope-entry-link.incident")).not.toBeNull();
    expect(container.querySelector(".flow-call-link.incident")).not.toBeNull();

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("highlights the full visible call component when a scope is selected", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload: callChainPayload(),
        routeFlowIds: ["entry", "load-user", "validate-user"],
        scope: "frontend",
      });
    });

    const frontendScope = container.querySelector('[data-scope="frontend"] .shape');
    if (!frontendScope) throw new Error("expected frontend scope node");

    await act(async () => {
      frontendScope.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector('[data-flow-id="entry"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector('[data-flow-id="load-user"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector('[data-flow-id="validate-user"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector('[data-flow-id="write-audit"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelectorAll(".flow-call-link.incident")).toHaveLength(3);
    expect(container.querySelectorAll(".flow-node.dimmed")).toHaveLength(0);

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("highlights the full visible call component when a flow node is selected", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload: callChainPayload(),
        routeFlowIds: ["entry", "load-user", "validate-user"],
        scope: "frontend",
      });
    });

    const middleFlow = container.querySelector('[data-flow-id="load-user"] .shape');
    if (!middleFlow) throw new Error("expected middle flow node");

    await act(async () => {
      middleFlow.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector('[data-flow-id="entry"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector('[data-flow-id="load-user"]')?.getAttribute("class")).toContain(
      "selected",
    );
    expect(container.querySelector('[data-flow-id="validate-user"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelector('[data-flow-id="write-audit"]')?.getAttribute("class")).toContain(
      "edge-target",
    );
    expect(container.querySelectorAll(".flow-call-link.incident")).toHaveLength(3);
    expect(container.querySelectorAll(".flow-node.dimmed")).toHaveLength(0);

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("dims flow and detail content when the root node is selected", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const rootShape = container.querySelector('[data-root-id="codebase"] .shape');
    if (!rootShape) throw new Error("expected root node");

    await act(async () => {
      rootShape.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const svg = container.querySelector(".logicchart-viewer");
    const flow = container.querySelector('[data-flow-id="orders-route"]');
    const detailNode = container.querySelector('[data-detail-node-id="orders-route:n2"]');

    expect(svg?.getAttribute("data-selected-kind")).toBe("root");
    expect(container.querySelector(".root-scope-link.incident")).not.toBeNull();
    expect(flow?.getAttribute("class")).toContain("dimmed");
    expect(detailNode?.getAttribute("class")).toContain("dimmed");
    expect(container.querySelector(".flow-call-link.dimmed")).not.toBeNull();
    expect(container.querySelector(".flow-detail-edge.dimmed")).not.toBeNull();

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("keeps node drag responsive and stops dragging on global abort", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;
    const manualPositionsChange = vi.fn();
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

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
        onManualNodePositionsChange: manualPositionsChange,
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    const flowNode = container.querySelector<SVGGElement>('[data-flow-id="orders-route"]');
    const flowShape = container.querySelector<SVGElement>('[data-flow-id="orders-route"] .shape');
    if (!svg || !flowNode || !flowShape) throw new Error("expected draggable flow node");
    const [viewBoxX, viewBoxY, viewBoxWidth, viewBoxHeight] = parseViewBox(svg);
    expect(Number.isFinite(viewBoxX + viewBoxY)).toBe(true);
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: viewBoxWidth });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: viewBoxHeight });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      domRect({ height: viewBoxHeight / 2, width: viewBoxWidth / 2 }),
    );

    const initialTranslate = parseTranslate(flowNode.getAttribute("transform"));

    await act(async () => {
      flowShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 100 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 150, clientY: 100 }));
    });

    expect(frames.size).toBe(1);
    expect(parseTranslate(flowNode.getAttribute("transform")).x).toBeCloseTo(
      initialTranslate.x,
      1,
    );

    await act(async () => {
      runFrames();
    });

    const movedTranslate = parseTranslate(flowNode.getAttribute("transform"));
    expect(movedTranslate.x - initialTranslate.x).toBeCloseTo(100, 1);
    expect(manualPositionsChange).not.toHaveBeenCalled();

    await act(async () => {
      window.dispatchEvent(new Event("blur"));
    });
    const afterAbortTransform = flowNode.getAttribute("transform");
    expect(manualPositionsChange).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 260, clientY: 100 }));
    });

    expect(flowNode.getAttribute("transform")).toBe(afterAbortTransform);
    expect(flowNode.getAttribute("class")).not.toContain("dragging");

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("flushes the final node drag position from pointerup", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;
    const manualPositionsChange = vi.fn();

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
        onManualNodePositionsChange: manualPositionsChange,
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    const flowNode = container.querySelector<SVGGElement>('[data-flow-id="orders-route"]');
    const flowShape = container.querySelector<SVGElement>('[data-flow-id="orders-route"] .shape');
    if (!svg || !flowNode || !flowShape) throw new Error("expected draggable flow node");
    const [, , viewBoxWidth, viewBoxHeight] = parseViewBox(svg);
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: viewBoxWidth });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: viewBoxHeight });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      domRect({ height: viewBoxHeight / 2, width: viewBoxWidth / 2 }),
    );

    const initialTranslate = parseTranslate(flowNode.getAttribute("transform"));

    await act(async () => {
      flowShape.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 100 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 150, clientY: 100 }));
    });

    const movedTranslate = parseTranslate(flowNode.getAttribute("transform"));
    expect(movedTranslate.x - initialTranslate.x).toBeCloseTo(100, 1);
    expect(manualPositionsChange).toHaveBeenCalledTimes(1);
    expect(flowNode.getAttribute("class")).not.toContain("dragging");

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("keeps canvas pan responsive and stops panning on global abort", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    if (!svg) throw new Error("expected viewer svg");
    const [, , viewBoxWidth, viewBoxHeight] = parseViewBox(svg);
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: viewBoxWidth });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: viewBoxHeight });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      domRect({ height: viewBoxHeight / 2, width: viewBoxWidth / 2 }),
    );
    const initialViewBox = parseViewBox(svg);

    await act(async () => {
      svg.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 100 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 260, clientY: 100, pointerId: 2 }));
    });

    expect(parseViewBox(svg)).toEqual(initialViewBox);

    await act(async () => {
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 150, clientY: 100 }));
    });

    const movedViewBox = parseViewBox(svg);
    expect(initialViewBox[0] - movedViewBox[0]).toBeCloseTo(100, 1);

    await act(async () => {
      window.dispatchEvent(new Event("blur"));
    });
    const afterAbortViewBox = svg.getAttribute("viewBox");

    await act(async () => {
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 260, clientY: 100 }));
    });

    expect(svg.getAttribute("viewBox")).toBe(afterAbortViewBox);
    expect(svg.getAttribute("class")).not.toContain("dragging");

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("flushes the final canvas pan position from pointerup", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    if (!svg) throw new Error("expected viewer svg");
    const [, , viewBoxWidth, viewBoxHeight] = parseViewBox(svg);
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: viewBoxWidth });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: viewBoxHeight });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      domRect({ height: viewBoxHeight / 2, width: viewBoxWidth / 2 }),
    );
    const initialViewBox = parseViewBox(svg);

    await act(async () => {
      svg.dispatchEvent(pointerEvent("pointerdown", { clientX: 100, clientY: 100 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 150, clientY: 100 }));
    });

    const movedViewBox = parseViewBox(svg);
    expect(initialViewBox[0] - movedViewBox[0]).toBeCloseTo(100, 1);
    expect(svg.getAttribute("class")).not.toContain("dragging");

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("keeps infinite-canvas viewport operations finite and resettable", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    if (!svg) throw new Error("expected viewer svg");
    const initialViewBox = svg.getAttribute("viewBox");
    const [, , viewBoxWidth, viewBoxHeight] = parseViewBox(svg);
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: viewBoxWidth });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: viewBoxHeight });

    mounted.zoom(0);
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    mounted.zoom(Number.POSITIVE_INFINITY);
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
    mounted.zoom(-1);
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);

    await act(async () => {
      svg.dispatchEvent(pointerEvent("pointerdown", { clientX: 0, clientY: 0 }));
      window.dispatchEvent(pointerEvent("pointermove", { clientX: 100000, clientY: -80000 }));
      window.dispatchEvent(pointerEvent("pointerup", { clientX: 100000, clientY: -80000 }));
    });

    const farViewBox = parseViewBox(svg);
    expect(farViewBox.every(Number.isFinite)).toBe(true);
    expect(svg.getAttribute("viewBox")).not.toBe(initialViewBox);

    mounted.resetView();
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("zooms with the wheel around the cursor without bubbling to the shell", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    let mounted!: ReturnType<typeof mountLogicChartViewer>;
    const bubbledWheel = vi.fn();
    container.addEventListener("wheel", bubbledWheel);

    await act(async () => {
      mounted = mountLogicChartViewer(container, {
        payload,
        routeFlowIds: ["orders-route"],
        scope: "frontend",
      });
    });

    const svg = container.querySelector<SVGSVGElement>(".logicchart-viewer");
    if (!svg) throw new Error("expected viewer svg");
    const before = parseViewBox(svg);
    Object.defineProperty(svg, "clientWidth", { configurable: true, value: 1000 });
    Object.defineProperty(svg, "clientHeight", { configurable: true, value: 700 });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(domRect({ height: 700, width: 1000 }));
    const clientX = 250;
    const clientY = 175;
    const anchorBefore = {
      x: before[0] + (clientX / 1000) * before[2],
      y: before[1] + (clientY / 700) * before[3],
    };

    await act(async () => {
      svg.dispatchEvent(wheelEvent({ clientX, clientY, deltaY: -80 }));
    });

    const after = parseViewBox(svg);
    const anchorAfter = {
      x: after[0] + (clientX / 1000) * after[2],
      y: after[1] + (clientY / 700) * after[3],
    };
    expect(after[2]).toBeLessThan(before[2]);
    expect(after[3]).toBeLessThan(before[3]);
    expect(anchorAfter.x).toBeCloseTo(anchorBefore.x, 4);
    expect(anchorAfter.y).toBeCloseTo(anchorBefore.y, 4);
    expect(bubbledWheel).not.toHaveBeenCalled();

    await act(async () => {
      mounted.unmount();
    });
    container.remove();
  });

  it("exports the current SVG as a raster image without invisible hit paths", async () => {
    const container = document.createElement("main");
    document.body.appendChild(container);
    const objectUrlBlobs: Blob[] = [];
    const downloads: Array<{ download: string; href: string }> = [];
    let rasterMime = "";

    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        objectUrlBlobs.push(blob);
        return `blob:logicchart-${objectUrlBlobs.length}`;
      }),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });

    class FakeImage {
      onerror: (() => void) | null = null;
      onload: (() => void) | null = null;

      set src(_value: string) {
        this.onload?.();
      }
    }

    vi.stubGlobal("Image", FakeImage);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
      fillRect: vi.fn(),
      fillStyle: "",
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback, type) => {
      rasterMime = type || "";
      callback(new Blob(["raster"], { type: type || "image/png" }));
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function clickStub(
      this: HTMLAnchorElement,
    ) {
      downloads.push({ download: this.download, href: this.href });
    });

    const mounted = mountLogicChartViewer(container, {
      payload,
      routeFlowIds: ["orders-route"],
      scope: "frontend",
    });

    expect(container.querySelector(".edge-hit-path")).not.toBeNull();
    expect(container.querySelector(".root-scope-hit")).not.toBeNull();
    expect(container.querySelector(".flow-detail-edge-hit")).not.toBeNull();
    expect(container.querySelector(".flow-call-hit")).not.toBeNull();
    expect(container.querySelector(".canvas-hit-zone")).not.toBeNull();

    mounted.exportImage("jpg");

    expect(rasterMime).toBe("image/jpeg");
    expect(downloads).toHaveLength(1);
    expect(downloads[0].download).toMatch(/^logicchart-flowchart-.*\.jpg$/);
    expect(objectUrlBlobs).toHaveLength(2);
    await expect(readBlobText(objectUrlBlobs[0])).resolves.not.toContain("edge-hit-path");
    await expect(readBlobText(objectUrlBlobs[0])).resolves.not.toContain("root-scope-hit");
    await expect(readBlobText(objectUrlBlobs[0])).resolves.not.toContain(
      '<path class="flow-detail-edge-hit',
    );
    await expect(readBlobText(objectUrlBlobs[0])).resolves.not.toContain(
      '<path class="flow-call-hit',
    );
    await expect(readBlobText(objectUrlBlobs[0])).resolves.not.toContain("canvas-hit-zone");

    mounted.unmount();
    container.remove();
  });

  it("sizes raster exports from graph bounds instead of a fixed low-resolution cap", () => {
    const small = rasterExportSizeForBounds({ height: 440, width: 600 });
    expect(small).toMatchObject({ height: 880, scale: 2, width: 1200 });

    const large = rasterExportSizeForBounds({ height: 2400, width: 9000 });
    expect(large.width).toBeGreaterThan(4096);
    expect(large.width).toBeLessThanOrEqual(16384);
    expect(large.height).toBeGreaterThan(2400);

    const huge = rasterExportSizeForBounds({ height: 20000, width: 40000 });
    expect(huge.width).toBeGreaterThan(4096);
    expect(huge.width).toBeLessThanOrEqual(16384);
    expect(huge.width * huge.height).toBeLessThanOrEqual(96_100_000);
  });
});

function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(blob);
  });
}

function callChainPayload(): LogicChartPayload {
  return {
    flows: [
      {
        id: "entry",
        name: "GET",
        language: "typescript",
        entry_kind: "route",
        is_entrypoint: true,
        location: { path: "frontend/app/api/chain/route.ts", start_line: 1 },
        calls: ["load-user"],
        called_by: [],
        metadata: { scope: ["frontend"] },
      },
      {
        id: "load-user",
        name: "loadUser",
        language: "typescript",
        entry_kind: "function",
        location: { path: "frontend/lib/load-user.ts", start_line: 1 },
        calls: ["validate-user"],
        called_by: ["entry"],
        metadata: { scope: ["frontend"] },
      },
      {
        id: "validate-user",
        name: "validateUser",
        language: "typescript",
        entry_kind: "function",
        location: { path: "frontend/lib/validate-user.ts", start_line: 1 },
        calls: ["write-audit"],
        called_by: ["load-user"],
        metadata: { scope: ["frontend"] },
      },
      {
        id: "write-audit",
        name: "writeAudit",
        language: "typescript",
        entry_kind: "function",
        location: { path: "frontend/lib/write-audit.ts", start_line: 1 },
        calls: [],
        called_by: ["validate-user"],
        metadata: { scope: ["frontend"] },
      },
    ],
  };
}

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

function wheelEvent({
  clientX,
  clientY,
  deltaY,
}: {
  clientX: number;
  clientY: number;
  deltaY: number;
}): WheelEvent {
  const event = new Event("wheel", {
    bubbles: true,
    cancelable: true,
  }) as WheelEvent;
  Object.defineProperty(event, "clientX", { configurable: true, value: clientX });
  Object.defineProperty(event, "clientY", { configurable: true, value: clientY });
  Object.defineProperty(event, "deltaY", { configurable: true, value: deltaY });
  return event;
}

function parseViewBox(svg: SVGSVGElement): [number, number, number, number] {
  const values = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
  if (values.length !== 4 || values.some(value => !Number.isFinite(value))) {
    throw new Error(`invalid viewBox: ${svg.getAttribute("viewBox")}`);
  }
  return values as [number, number, number, number];
}

function parseTranslate(value: string | null): { x: number; y: number } {
  const match = /translate\(([-\d.]+)[,\s]+([-\d.]+)\)/.exec(value || "");
  if (!match) throw new Error(`invalid translate: ${value}`);
  return { x: Number(match[1]), y: Number(match[2]) };
}

function domRect({ height, width }: { height: number; width: number }): DOMRect {
  return {
    bottom: height,
    height,
    left: 0,
    right: width,
    top: 0,
    width,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
}
