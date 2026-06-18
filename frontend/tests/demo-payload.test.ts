import { describe, expect, it } from "vitest";

import demoPayloadJson from "../../examples/demo/logicchart-out/logic-flow.json";
import {
  buildProgressiveModel,
  buildScopeIndex,
  createViewerLayout,
  scopeSummaries,
  viewerLayoutQualityReport,
  viewerLayoutStructureIssues,
  type ExpandedFlowMeasure,
  type LogicChartPayload,
} from "../src";
import { layoutFlowDetail } from "../src/flow-detail-layout";

const demoPayload = demoPayloadJson as LogicChartPayload;

describe("generated demo payload", () => {
  it("derives the visible top-level codebase scopes from real LogicChart output", () => {
    const scopes = buildScopeIndex(demoPayload);

    expect([...scopes.keys()]).toEqual(["backend", "frontend"]);
    expect(scopeSummaries(demoPayload)).toEqual([
      { name: "backend", flowIds: expect.any(Array) },
      { name: "frontend", flowIds: expect.any(Array) },
    ]);
  });

  it("builds first-layer entrypoints for every real demo scope", () => {
    for (const scope of ["backend", "frontend"]) {
      const model = buildProgressiveModel(demoPayload, scope);

      expect(model.scope).toBe(scope);
      expect(model.layers.length).toBeGreaterThan(0);
      expect(model.entryFlowIds.length).toBeGreaterThan(0);
      expect(new Set(model.entryFlowIds).size).toBe(model.entryFlowIds.length);
    }
  });

  it("keeps the real dense demo clear when every scope and entrypoint is open", () => {
    const scopes = scopeSummaries(demoPayload).map(scope => scope.name);
    const entryFlowIds = demoPayload.flows
      .filter(flow => flow.is_entrypoint)
      .map(flow => flow.id);
    const layout = createViewerLayout({
      expandedMeasures: estimatedExpandedMeasures(demoPayload, entryFlowIds),
      expandedScopes: scopes,
      payload: demoPayload,
      routeFlowIds: entryFlowIds,
      scope: "frontend",
    });
    const report = viewerLayoutQualityReport(layout, {
      edgeGap: 10,
      overlapGap: 16,
    });

    expect(entryFlowIds.length).toBeGreaterThan(20);
    expect(layout.scopeNodes.filter(node => node.expanded).map(node => node.scope).sort()).toEqual(
      scopes.sort(),
    );
    expect(report).toMatchObject({
      edgeObstacleHits: [],
      isClear: true,
      overlapCount: 0,
    });
    expect(report.flowNodeCount).toBeGreaterThan(entryFlowIds.length);
    expect(report.detailRegionCount).toBe(entryFlowIds.length);
    expect(viewerLayoutStructureIssues(layout)).toEqual([]);
  });

  it("uses the host entrypoint as the expanded flowchart start block", () => {
    const entryFlowsWithEntryNodes = demoPayload.flows.filter(
      flow => flow.is_entrypoint && flow.nodes?.some(node => node.kind === "entry"),
    );

    expect(entryFlowsWithEntryNodes.length).toBeGreaterThan(0);
    entryFlowsWithEntryNodes.forEach(flow => {
      const detail = layoutFlowDetail(flow, { omitEntryNode: true });

      expect(detail).not.toBeNull();
      expect(
        [...(detail?.nodePositions.values() ?? [])].some(
          position => position.node.kind === "entry",
        ),
      ).toBe(false);
      expect(detail?.startRoutes.length).toBeGreaterThan(0);
    });
  });
});

function estimatedExpandedMeasures(
  payload: LogicChartPayload,
  flowIds: readonly string[],
): Map<string, ExpandedFlowMeasure> {
  const selected = new Set(flowIds);
  return new Map(
    payload.flows
      .filter(flow => selected.has(flow.id))
      .map(flow => {
        const nodeCount = Math.max(1, flow.nodes?.length ?? 1);
        const decisionCount = flow.nodes?.filter(node => node.kind === "decision").length ?? 0;
        const branchCount = Math.max(1, flow.edges?.filter(edge => edge.label).length ?? 1);
        const width = Math.min(1180, Math.max(360, 280 + branchCount * 78));
        const height = Math.min(1220, Math.max(260, 150 + nodeCount * 72 + decisionCount * 60));
        return [
          flow.id,
          {
            height,
            maxX: width / 2,
            maxY: height,
            minX: -width / 2,
            minY: 0,
            width,
          },
        ];
      }),
  );
}
