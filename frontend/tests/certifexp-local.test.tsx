import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  mountStandaloneLogicChartViewer,
  type LogicChartPayload,
  type MountedStandaloneLogicChartViewer,
} from "../src";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const CERTIFEXP_MODEL_PATH = join(
  process.cwd(),
  "examples",
  "Certifexp",
  "logicchart-out",
  "logic-flow.json",
);

const describeIfCertifexp = existsSync(CERTIFEXP_MODEL_PATH) ? describe : describe.skip;

describeIfCertifexp("Certifexp local viewer performance", () => {
  let container: HTMLDivElement;
  let mounted: MountedStandaloneLogicChartViewer | undefined;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal("localStorage", memoryStorage());
    window.localStorage.clear();
    window.history.replaceState(null, "", "/viewer.html#root");
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  afterEach(() => {
    mounted?.unmount();
    container.remove();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("expands the large canvas without rendering every inline detail chart", async () => {
    const payload = loadCertifexpPayload();

    mounted = mountStandaloneLogicChartViewer(container, payload);

    const expandStart = performance.now();
    await act(async () => {
      mounted?.expandAll();
      await flushAsyncTimers(6);
    });
    const expandElapsed = performance.now() - expandStart;

    const flowNodeCount = container.querySelectorAll(".flow-node").length;
    expect(flowNodeCount).toBeGreaterThan(Math.floor(payload.flows.length * 0.3));
    expect(container.querySelectorAll(".flow-detail")).toHaveLength(0);
    expect(expandElapsed).toBeLessThan(5000);

    const detailedFlow = payload.flows.find(flow => (flow.nodes?.length ?? 0) > 1);
    expect(detailedFlow).toBeDefined();

    const detailStart = performance.now();
    await act(async () => {
      mounted?.selectFlow(detailedFlow?.id ?? "");
      await flushAsyncTimers(6);
    });
    const detailElapsed = performance.now() - detailStart;

    expect(container.querySelectorAll(".flow-detail").length).toBeGreaterThan(0);
    expect(detailElapsed).toBeLessThan(2500);
  }, 20000);
});

function loadCertifexpPayload(): LogicChartPayload {
  return JSON.parse(readFileSync(CERTIFEXP_MODEL_PATH, "utf8")) as LogicChartPayload;
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
