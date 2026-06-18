import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";

import { ViewerApp, type ViewerAppProps } from "./ViewerApp";

export type ExportImageFormat = "png" | "jpg";

export interface MountedLogicChartViewer {
  exportImage: (format: ExportImageFormat) => void;
  fitView: () => void;
  resetView: () => void;
  update: (props: ViewerAppProps) => void;
  zoom: (factor: number) => void;
  unmount: () => void;
}

export function mountLogicChartViewer(
  container: Element,
  props: ViewerAppProps,
): MountedLogicChartViewer {
  const frame = container.ownerDocument.createElement("div");
  frame.className = "logicchart-viewer-frame";
  container.appendChild(frame);

  const root = createRoot(frame);
  let baseViewBox: ViewBox | null = null;
  let cleanupPan: (() => void) | null = null;
  let cleanupOverview: (() => void) | null = null;
  let panSvg: SVGSVGElement | null = null;
  let refreshOverview: (() => void) | null = null;
  let resetToken = props.resetToken ?? 0;
  let currentProps: ViewerAppProps = { ...props, resetToken };

  const captureBaseViewBox = () => {
    const svg = findViewerSvg(frame);
    baseViewBox = svg ? readViewBox(svg) : null;
  };
  const bindViewportControls = () => {
    const svg = findViewerSvg(frame);
    if (svg === panSvg) {
      refreshOverview?.();
      return;
    }
    cleanupPan?.();
    cleanupOverview?.();
    panSvg = svg;
    cleanupPan = svg ? bindSvgPan(svg) : null;
    const overview = svg ? bindCanvasOverview(container, svg) : null;
    cleanupOverview = overview?.cleanup ?? null;
    refreshOverview = overview?.refresh ?? null;
  };

  render(root, currentProps);
  bindViewportControls();
  captureBaseViewBox();

  return {
    exportImage(format) {
      const svg = findViewerSvg(frame);
      if (svg) exportSvgImage(svg, format);
    },
    fitView() {
      const svg = findViewerSvg(frame);
      if (!svg) return;
      const bounds = svgContentBounds(svg) ?? readViewBox(svg);
      if (bounds) writeViewBox(svg, bounds);
    },
    resetView() {
      const targetViewBox = baseViewBox;
      resetToken += 1;
      currentProps = { ...currentProps, resetToken };
      render(root, currentProps);
      bindViewportControls();
      const svg = findViewerSvg(frame);
      if (svg && targetViewBox) writeViewBox(svg, targetViewBox);
      captureBaseViewBox();
    },
    update(nextProps) {
      currentProps = { ...nextProps, resetToken };
      render(root, currentProps);
      bindViewportControls();
      captureBaseViewBox();
    },
    zoom(factor) {
      const svg = findViewerSvg(frame);
      if (!svg) return;
      zoomSvgViewBox(svg, factor);
    },
    unmount() {
      cleanupPan?.();
      cleanupOverview?.();
      cleanupPan = null;
      cleanupOverview = null;
      panSvg = null;
      refreshOverview = null;
      root.unmount();
      frame.remove();
    },
  };
}

function render(root: Root, props: ViewerAppProps) {
  flushSync(() => {
    root.render(<ViewerApp {...props} />);
  });
}

interface ViewBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

function findViewerSvg(container: Element): SVGSVGElement | null {
  return container.querySelector<SVGSVGElement>(".logicchart-viewer");
}

function readViewBox(svg: SVGSVGElement): ViewBox | null {
  const values = (svg.getAttribute("viewBox") || "")
    .trim()
    .split(/\s+/)
    .map(value => Number(value));
  if (values.length !== 4 || values.some(value => !Number.isFinite(value))) return null;
  const [x, y, width, height] = values;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function writeViewBox(svg: SVGSVGElement, viewBox: ViewBox) {
  if (!isValidViewBox(viewBox)) return;
  svg.setAttribute(
    "viewBox",
    `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`,
  );
  svg.dispatchEvent(new CustomEvent("logicchart:viewboxchange"));
}

function isValidViewBox(viewBox: ViewBox): boolean {
  return (
    Number.isFinite(viewBox.x) &&
    Number.isFinite(viewBox.y) &&
    Number.isFinite(viewBox.width) &&
    Number.isFinite(viewBox.height) &&
    viewBox.width > 0 &&
    viewBox.height > 0
  );
}

function bindSvgPan(svg: SVGSVGElement): () => void {
  let drag: {
    moved: number;
    origin: ViewBox;
    pointerId: number;
    startX: number;
    startY: number;
  } | null = null;
  let globalListenersAttached = false;
  let lastMoveEvent: PointerEvent | null = null;

  const attachGlobalListeners = () => {
    if (globalListenersAttached) return;
    globalListenersAttached = true;
    window.addEventListener("pointermove", onPointerMove, true);
    window.addEventListener("pointerup", onPointerEnd, true);
    window.addEventListener("pointercancel", onPointerEnd, true);
    window.addEventListener("mouseup", abortDrag, true);
    window.addEventListener("blur", abortDrag, true);
    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("pointerup", onPointerEnd, true);
    document.addEventListener("pointercancel", onPointerEnd, true);
    document.addEventListener("mouseup", abortDrag, true);
    document.addEventListener("visibilitychange", onVisibilityChange, true);
    svg.addEventListener("lostpointercapture", onPointerEnd as EventListener);
  };

  const detachGlobalListeners = () => {
    if (!globalListenersAttached) return;
    globalListenersAttached = false;
    window.removeEventListener("pointermove", onPointerMove, true);
    window.removeEventListener("pointerup", onPointerEnd, true);
    window.removeEventListener("pointercancel", onPointerEnd, true);
    window.removeEventListener("mouseup", abortDrag, true);
    window.removeEventListener("blur", abortDrag, true);
    document.removeEventListener("pointermove", onPointerMove, true);
    document.removeEventListener("pointerup", onPointerEnd, true);
    document.removeEventListener("pointercancel", onPointerEnd, true);
    document.removeEventListener("mouseup", abortDrag, true);
    document.removeEventListener("visibilitychange", onVisibilityChange, true);
    svg.removeEventListener("lostpointercapture", onPointerEnd as EventListener);
  };

  const onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return;
    const target = event.target;
    if (
      target instanceof Element &&
      target.closest(
        '[role="button"], a, .node, .detail-node, .flow-detail-edge-hit, .flow-detail-edge-group, .flow-call-hit, .flow-call-edge-group, .root-scope-hit, .root-scope-edge-group, .edge-hit-path, .scope-entry-link, .edge-link-group',
      )
    ) {
      return;
    }
    const origin = readViewBox(svg);
    if (!origin) return;
    finishDrag();
    drag = {
      moved: 0,
      origin,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
    };
    attachGlobalListeners();
    svg.classList.add("dragging");
    event.preventDefault();
    try {
      svg.setPointerCapture(event.pointerId);
    } catch {
      // JSDOM and some embedded renderers do not expose pointer capture.
    }
  };

  const writePanFromPointer = (event: PointerEvent) => {
    if (!drag) return;
    if (event.pointerId !== drag.pointerId) return;
    if (event === lastMoveEvent) return;
    lastMoveEvent = event;
    const viewport = svgViewportSize(svg, drag.origin);
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
    writeViewBox(svg, {
      ...drag.origin,
      x: drag.origin.x - dx * (drag.origin.width / viewport.width),
      y: drag.origin.y - dy * (drag.origin.height / viewport.height),
    });
  };

  const onPointerMove = (event: PointerEvent) => {
    writePanFromPointer(event);
    event.preventDefault();
  };

  const onPointerEnd = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    writePanFromPointer(event);
    finishDrag(event);
  };

  const abortDrag = (event: Event) => {
    finishDrag(event);
  };

  const onVisibilityChange = () => {
    if (document.visibilityState === "hidden") finishDrag();
  };

  const finishDrag = (event?: Event) => {
    if (!drag) return;
    const pointerId = drag.pointerId;
    drag = null;
    lastMoveEvent = null;
    detachGlobalListeners();
    svg.classList.remove("dragging");
    try {
      svg.releasePointerCapture(pointerId);
    } catch {
      // See setPointerCapture fallback above.
    }
    event?.preventDefault();
  };

  svg.addEventListener("pointerdown", onPointerDown);
  svg.addEventListener("pointermove", onPointerMove);
  svg.addEventListener("pointerup", onPointerEnd);
  svg.addEventListener("pointercancel", onPointerEnd);
  svg.addEventListener("wheel", onWheel, { passive: false });

  return () => {
    finishDrag();
    detachGlobalListeners();
    svg.removeEventListener("pointerdown", onPointerDown);
    svg.removeEventListener("pointermove", onPointerMove);
    svg.removeEventListener("pointerup", onPointerEnd);
    svg.removeEventListener("pointercancel", onPointerEnd);
    svg.removeEventListener("wheel", onWheel);
  };

  function onWheel(event: WheelEvent) {
    const factor = event.deltaY > 0 ? 1.08 : 0.92;
    zoomSvgViewBox(svg, factor, { clientX: event.clientX, clientY: event.clientY });
    event.preventDefault();
    event.stopPropagation();
  }
}

function svgViewportSize(svg: SVGSVGElement, fallback: ViewBox): Pick<ViewBox, "height" | "width"> {
  const rect = svg.getBoundingClientRect();
  return {
    height: rect.height || svg.clientHeight || Number(svg.getAttribute("height")) || fallback.height,
    width: rect.width || svg.clientWidth || Number(svg.getAttribute("width")) || fallback.width,
  };
}

function zoomSvgViewBox(
  svg: SVGSVGElement,
  factor: number,
  anchor?: { clientX: number; clientY: number },
) {
  if (!Number.isFinite(factor) || factor <= 0) return;
  const current = readViewBox(svg);
  if (!current) return;
  const anchorPoint = anchor
    ? clientPointToViewBoxPoint(svg, current, anchor.clientX, anchor.clientY)
    : {
        x: current.x + current.width / 2,
        y: current.y + current.height / 2,
      };
  const nextWidth = current.width * factor;
  const nextHeight = current.height * factor;
  writeViewBox(svg, {
    x: anchorPoint.x - (anchorPoint.x - current.x) * factor,
    y: anchorPoint.y - (anchorPoint.y - current.y) * factor,
    width: nextWidth,
    height: nextHeight,
  });
}

function clientPointToViewBoxPoint(
  svg: SVGSVGElement,
  viewBox: ViewBox,
  clientX: number,
  clientY: number,
): { x: number; y: number } {
  const rect = svg.getBoundingClientRect();
  const viewport = svgViewportSize(svg, viewBox);
  return {
    x: viewBox.x + ((clientX - rect.left) / Math.max(1, viewport.width)) * viewBox.width,
    y: viewBox.y + ((clientY - rect.top) / Math.max(1, viewport.height)) * viewBox.height,
  };
}

function exportSvgImage(svg: SVGSVGElement, format: ExportImageFormat) {
  const bounds = svgContentBounds(svg) ?? readViewBox(svg);
  if (!bounds) return;

  const maxPixelSide = 4096;
  const scale = Math.min(2, maxPixelSide / Math.max(bounds.width, bounds.height));
  const width = Math.max(1, Math.round(bounds.width * scale));
  const height = Math.max(1, Math.round(bounds.height * scale));
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.setAttribute("viewBox", `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`);
  clone.setAttribute("data-theme", document.documentElement.dataset.theme || "light");
  clone
    .querySelectorAll(
      ".canvas-hit-zone, .root-scope-hit, .edge-hit-path, .flow-detail-edge-hit, .flow-call-hit",
    )
    .forEach(node => node.remove());

  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = [...document.querySelectorAll("style")]
    .map(node => node.textContent || "")
    .join("\n");
  clone.prepend(style);

  const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  background.setAttribute("x", String(bounds.x));
  background.setAttribute("y", String(bounds.y));
  background.setAttribute("width", String(bounds.width));
  background.setAttribute("height", String(bounds.height));
  background.setAttribute("fill", cssVar("--paper", "#ffffff"));
  clone.insertBefore(background, style.nextSibling);

  const serialized = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" });
  const imageUrl = URL.createObjectURL(svgBlob);
  const image = new Image();
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) {
      URL.revokeObjectURL(imageUrl);
      return;
    }
    context.fillStyle = cssVar("--paper", "#ffffff");
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    URL.revokeObjectURL(imageUrl);
    const mime = format === "jpg" ? "image/jpeg" : "image/png";
    canvas.toBlob(blob => {
      if (!blob) return;
      downloadBlob(blob, `logicchart-flowchart-${timestamp()}.${format}`);
    }, mime, format === "jpg" ? 0.92 : undefined);
  };
  image.onerror = () => URL.revokeObjectURL(imageUrl);
  image.src = imageUrl;
}

function svgContentBounds(svg: SVGSVGElement): ViewBox | null {
  const hitPaths = [
    ...svg.querySelectorAll<SVGElement>(
      ".canvas-hit-zone, .root-scope-hit, .edge-hit-path, .flow-detail-edge-hit, .flow-call-hit",
    ),
  ];
  const previousDisplays = hitPaths.map(node => node.style.display);
  hitPaths.forEach(node => {
    node.style.display = "none";
  });

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  try {
    [...svg.children].forEach(node => {
      if (node.tagName.toLowerCase() === "defs" || !hasBBox(node)) return;
      try {
        const box = node.getBBox();
        if (!box || !Number.isFinite(box.width) || !Number.isFinite(box.height)) return;
        minX = Math.min(minX, box.x);
        minY = Math.min(minY, box.y);
        maxX = Math.max(maxX, box.x + box.width);
        maxY = Math.max(maxY, box.y + box.height);
      } catch {
        // Some test DOMs do not implement SVG geometry APIs; export falls back to viewBox.
      }
    });
  } finally {
    hitPaths.forEach((node, index) => {
      node.style.display = previousDisplays[index] || "";
    });
  }

  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
  const padding = 90;
  return {
    x: minX - padding,
    y: minY - padding,
    width: Math.max(1, maxX - minX + padding * 2),
    height: Math.max(1, maxY - minY + padding * 2),
  };
}

function hasBBox(node: Element): node is Element & { getBBox: () => DOMRect } {
  return typeof (node as { getBBox?: unknown }).getBBox === "function";
}

interface OverviewBinding {
  cleanup: () => void;
  refresh: () => void;
}

function bindCanvasOverview(container: Element, svg: SVGSVGElement): OverviewBinding {
  const document = container.ownerDocument;
  const namespace = "http://www.w3.org/2000/svg";
  container.querySelectorAll(":scope > .logicchart-overview").forEach(node => node.remove());

  const overview = document.createElement("button");
  overview.className = "logicchart-overview";
  overview.type = "button";
  overview.title = "Fit the full flowchart";
  overview.setAttribute("aria-label", "Canvas overview. Fit the full flowchart");

  const overviewSvg = document.createElementNS(namespace, "svg");
  overviewSvg.classList.add("logicchart-overview-map");
  overviewSvg.setAttribute("aria-hidden", "true");
  overviewSvg.setAttribute("focusable", "false");
  overviewSvg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  const contentRect = document.createElementNS(namespace, "rect");
  contentRect.classList.add("logicchart-overview-content");
  const nodeLayer = document.createElementNS(namespace, "g");
  nodeLayer.classList.add("logicchart-overview-nodes");
  const viewportRect = document.createElementNS(namespace, "rect");
  viewportRect.classList.add("logicchart-overview-viewport");

  overviewSvg.append(contentRect, nodeLayer, viewportRect);
  overview.appendChild(overviewSvg);
  container.appendChild(overview);

  let contentBounds: ViewBox | null = null;

  const sync = () => {
    const viewBox = readViewBox(svg);
    if (!viewBox || !contentBounds) {
      overview.hidden = true;
      return;
    }
    overview.hidden = false;
    overviewSvg.setAttribute(
      "viewBox",
      `${contentBounds.x} ${contentBounds.y} ${contentBounds.width} ${contentBounds.height}`,
    );
    setRectAttributes(contentRect, contentBounds);
    setRectAttributes(viewportRect, viewBox);
  };

  const refresh = () => {
    contentBounds = svgContentBounds(svg) ?? readViewBox(svg);
    nodeLayer.replaceChildren();
    if (contentBounds) {
      overviewNodeBounds(svg).forEach(box => {
        const node = document.createElementNS(namespace, "rect");
        node.classList.add("logicchart-overview-node");
        setRectAttributes(node, box);
        nodeLayer.appendChild(node);
      });
    }
    sync();
  };

  const fitOverview = () => {
    if (contentBounds) writeViewBox(svg, contentBounds);
  };

  svg.addEventListener("logicchart:viewboxchange", sync);
  overview.addEventListener("click", fitOverview);
  refresh();

  return {
    cleanup() {
      svg.removeEventListener("logicchart:viewboxchange", sync);
      overview.removeEventListener("click", fitOverview);
      overview.remove();
    },
    refresh,
  };
}

function overviewNodeBounds(svg: SVGSVGElement): ViewBox[] {
  const maxNodes = 240;
  return [...svg.querySelectorAll<Element>(".node, .detail-node")]
    .slice(0, maxNodes)
    .map(node => {
      if (!hasBBox(node)) return null;
      try {
        const box = node.getBBox();
        if (
          !box ||
          !Number.isFinite(box.x) ||
          !Number.isFinite(box.y) ||
          !Number.isFinite(box.width) ||
          !Number.isFinite(box.height) ||
          box.width <= 0 ||
          box.height <= 0
        ) {
          return null;
        }
        return { x: box.x, y: box.y, width: box.width, height: box.height };
      } catch {
        return null;
      }
    })
    .filter((box): box is ViewBox => box !== null);
}

function setRectAttributes(rect: SVGRectElement, box: ViewBox) {
  rect.setAttribute("x", String(box.x));
  rect.setAttribute("y", String(box.y));
  rect.setAttribute("width", String(box.width));
  rect.setAttribute("height", String(box.height));
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.download = fileName;
  link.href = url;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function timestamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}
