import { describe, expect, it } from "vitest";

import {
  buildProgressiveModel,
  buildScopeIndex,
  entryFlowsForScope,
  payloadToReactFlowModel,
  scopeNamesForFlow,
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
      calls: ["status-label"],
      called_by: ["orders-route"],
      metadata: { scope: ["frontend"] },
    },
    {
      id: "status-label",
      name: "statusLabel",
      language: "javascript",
      entry_kind: "function",
      location: { path: "lib/status.js", start_line: 3 },
      calls: [],
      called_by: ["load-order"],
      metadata: {},
    },
    {
      id: "backend-test",
      name: "test helper",
      location: { path: "backend/test_auth.py", start_line: 1 },
      metadata: { test: true },
    },
  ],
};

describe("LogicChart payload model", () => {
  it("derives universal scopes from explicit metadata or stable path fallback", () => {
    expect(scopeNamesForFlow(payload.flows[0])).toEqual(["frontend"]);
    expect(scopeNamesForFlow(payload.flows[3])).toEqual(["lib"]);

    const scopes = buildScopeIndex(payload);
    expect([...scopes.keys()]).toEqual(["frontend", "lib"]);
    expect(scopes.get("frontend")).toEqual(["orders-route", "users-route", "load-order"]);
    expect(scopes.has("backend")).toBe(false);
  });

  it("keeps first-layer entrypoints rooted and unlocks downstream calls progressively", () => {
    expect(entryFlowsForScope(payload, "frontend").map(flow => flow.id)).toEqual([
      "orders-route",
      "users-route",
    ]);

    const model = buildProgressiveModel(payload, "frontend", ["orders-route", "load-order"]);

    expect(model.entryFlowIds).toEqual(["orders-route", "users-route"]);
    expect(model.layers.map(layer => layer.map(flow => flow.id))).toEqual([
      ["orders-route", "users-route"],
      ["load-order"],
    ]);
  });

  it("opens directly selected internal flows through their visible caller chain", () => {
    const model = buildProgressiveModel(payload, "frontend", ["load-order"]);

    expect(model.entryFlowIds).toEqual(["orders-route", "users-route"]);
    expect(model.layers.map(layer => layer.map(flow => flow.id))).toEqual([
      ["orders-route", "users-route"],
      ["load-order"],
    ]);
  });

  it("keeps cross-scope targets in their owning scope instead of duplicating them", () => {
    const frontendModel = buildProgressiveModel(payload, "frontend", [
      "orders-route",
      "load-order",
      "status-label",
    ]);
    const libModel = buildProgressiveModel(payload, "lib", [], ["status-label"]);

    expect(frontendModel.layers.flat().map(flow => flow.id)).toEqual([
      "orders-route",
      "users-route",
      "load-order",
    ]);
    expect(libModel.layers.map(layer => layer.map(flow => flow.id))).toEqual([
      ["status-label"],
    ]);
  });

  it("uses called_by metadata as a deterministic fallback for progressive call links", () => {
    const calledByOnlyPayload: LogicChartPayload = {
      flows: [
        {
          id: "entry",
          name: "Entry",
          language: "typescript",
          entry_kind: "route",
          is_entrypoint: true,
          location: { path: "frontend/app/api/entry/route.ts", start_line: 1 },
          calls: [],
          called_by: [],
          metadata: { scope: ["frontend"] },
        },
        {
          id: "load-user",
          name: "loadUser",
          language: "typescript",
          entry_kind: "function",
          location: { path: "frontend/lib/load-user.ts", start_line: 8 },
          calls: [],
          called_by: ["entry"],
          metadata: { scope: ["frontend"] },
        },
      ],
    };

    const model = buildProgressiveModel(calledByOnlyPayload, "frontend", ["load-user"]);

    expect(model.layers.map(layer => layer.map(flow => flow.id))).toEqual([
      ["entry"],
      ["load-user"],
    ]);
  });

  it("projects payload-derived flowcharts into React Flow nodes and edges", () => {
    const graph = payloadToReactFlowModel(
      payload,
      { scope: "frontend", x: 420, y: 80, width: 220, height: 108 },
      {
        flowWidth: 238,
        flowHeight: 68,
        gapX: 70,
        rowGap: 150,
        layerGap: 360,
        chipY: 27,
        decisionPad: 90,
      },
      ["orders-route"],
    );

    expect(graph.nodes.map(node => node.id)).toContain("scope:frontend");
    expect(graph.nodes.find(node => node.id === "orders-route")?.data.label).toBe("GET");
    expect(graph.edges.map(edge => edge.id)).toEqual([
      "scope:frontend->orders-route",
      "scope:frontend->users-route",
    ]);
  });
});
