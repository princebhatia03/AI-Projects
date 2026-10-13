"use client";

import { useCallback, useRef, useState, type ReactNode, type WheelEvent, type PointerEvent } from "react";
import { Minus, Plus, Maximize2, Move } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type Props = {
  children: ReactNode;
  className?: string;
  minScale?: number;
  maxScale?: number;
  /** Initial / reset zoom level (1 = 100%). */
  initialScale?: number;
};

const MIN = 0.4;
const MAX = 2.5;
const DEFAULT = 0.6;
const STEP = 0.15;

export function ZoomPanViewport({
  children,
  className,
  minScale = MIN,
  maxScale = MAX,
  initialScale = DEFAULT,
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(() =>
    Math.min(maxScale, Math.max(minScale, initialScale)),
  );
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const drag = useRef<{
    active: boolean;
    moved: boolean;
    pointerId: number | null;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  }>({
    active: false,
    moved: false,
    pointerId: null,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
  });

  const clampScale = useCallback(
    (value: number) => Math.min(maxScale, Math.max(minScale, value)),
    [minScale, maxScale],
  );

  const zoomBy = useCallback(
    (delta: number, anchor?: { x: number; y: number }) => {
      setScale((prev) => {
        const next = clampScale(prev + delta);
        if (next === prev) return prev;
        if (anchor && viewportRef.current) {
          const rect = viewportRef.current.getBoundingClientRect();
          const ax = anchor.x - rect.left;
          const ay = anchor.y - rect.top;
          // Keep point under cursor stable with transform-origin: center.
          const cx = rect.width / 2;
          const cy = rect.height / 2;
          const ratio = next / prev;
          setOffset((o) => ({
            x: (1 - ratio) * (ax - cx) + ratio * o.x,
            y: (1 - ratio) * (ay - cy) + ratio * o.y,
          }));
        }
        return next;
      });
    },
    [clampScale],
  );

  const reset = useCallback(() => {
    setScale(clampScale(initialScale));
    setOffset({ x: 0, y: 0 });
  }, [clampScale, initialScale]);

  function onWheel(e: WheelEvent<HTMLDivElement>) {
    // Pinch-zoom / ctrl+wheel → zoom; otherwise let native scroll work.
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -STEP : STEP;
      zoomBy(delta, { x: e.clientX, y: e.clientY });
      return;
    }
    // Plain wheel pans vertically inside the viewport when content overflows.
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      e.preventDefault();
      setOffset((o) => ({ x: o.x, y: o.y - e.deltaY }));
    } else if (e.deltaX) {
      e.preventDefault();
      setOffset((o) => ({ x: o.x - e.deltaX, y: o.y }));
    }
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    // Ignore clicks on the toolbar.
    if ((e.target as HTMLElement).closest("[data-zoom-controls]")) return;
    // Do not capture yet — capturing here steals clicks from hex cells.
    drag.current = {
      active: true,
      moved: false,
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originX: offset.x,
      originY: offset.y,
    };
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (!drag.current.active || drag.current.pointerId !== e.pointerId) return;
    const dx = e.clientX - drag.current.startX;
    const dy = e.clientY - drag.current.startY;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
      if (!drag.current.moved) {
        drag.current.moved = true;
        setPanning(true);
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
          /* ignore */
        }
      }
    }
    if (drag.current.moved) {
      setOffset({
        x: drag.current.originX + dx,
        y: drag.current.originY + dy,
      });
    }
  }

  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    if (drag.current.pointerId !== e.pointerId) return;
    const wasDrag = drag.current.moved;
    drag.current.active = false;
    drag.current.pointerId = null;
    setPanning(false);
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
    }
    // Suppress click on hexes after a pan.
    if (wasDrag) {
      const block = (ev: Event) => {
        ev.stopPropagation();
        ev.preventDefault();
        window.removeEventListener("click", block, true);
      };
      window.addEventListener("click", block, true);
    }
  }

  return (
    <div className={cn("zoom-pan-root", className)}>
      <div className="zoom-pan-toolbar" data-zoom-controls>
        <Badge variant="secondary" className="font-[family-name:var(--font-mono)]">
          {Math.round(scale * 100)}%
        </Badge>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="Zoom out"
              onClick={() => zoomBy(-STEP)}
              disabled={scale <= minScale}
            >
              <Minus className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Zoom out</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="Zoom in"
              onClick={() => zoomBy(STEP)}
              disabled={scale >= maxScale}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Zoom in</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button type="button" variant="outline" size="sm" aria-label="Reset view" onClick={reset}>
              <Maximize2 className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Reset view</TooltipContent>
        </Tooltip>
        <span className="zoom-pan-hint">
          <Move className="h-3.5 w-3.5" aria-hidden />
          Drag to pan · Scroll to move · ⌘/Ctrl+scroll to zoom
        </span>
      </div>

      <div
        ref={viewportRef}
        className={cn("zoom-pan-viewport", panning && "is-panning")}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          className="zoom-pan-stage"
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
