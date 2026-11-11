"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  createGenerativeMask,
  deleteGenerativeMask,
  listGenerativeMasks,
} from "@/lib/api/generative";
import type {
  GenerativeMaskCreate,
  GenerativeMaskKind,
  GenerativeMaskPoint,
  GenerativeMaskQuality,
  GenerativeMaskRegion,
  GenerativeMaskStroke,
  GenerativeMaskView,
} from "@/types/generative";

export type GenerativeEditorTool = "brush" | "eraser" | "rect" | "ellipse";

export interface GenerativeMaskEditorProps {
  sessionId: string;
  imageUrl?: string | null;
  previewWidth?: number;
  previewHeight?: number;
  disabled?: boolean;
  onMaskCreated?: (mask: GenerativeMaskView) => void;
  onClose?: () => void;
  className?: string;
}

interface HistoryState {
  strokes: GenerativeMaskStroke[];
  region: GenerativeMaskRegion | null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function roundTo4(val: number): number {
  return Math.round(val * 10000) / 10000;
}

export function GenerativeMaskEditor({
  sessionId,
  imageUrl,
  previewWidth = 800,
  previewHeight = 600,
  disabled = false,
  onMaskCreated,
  onClose,
  className = "",
}: GenerativeMaskEditorProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Tools & parameters
  const [tool, setTool] = useState<GenerativeEditorTool>("brush");
  const [brushRadius, setBrushRadius] = useState<number>(0.05); // normalized 0..1
  const [brushHardness, setBrushHardness] = useState<number>(100);
  const [feather, setFeather] = useState<number>(0);
  const [expand, setExpand] = useState<number>(0);
  const [inverted, setInverted] = useState<boolean>(false);

  // Stroke / shape state
  const [strokes, setStrokes] = useState<GenerativeMaskStroke[]>([]);
  const [region, setRegion] = useState<GenerativeMaskRegion | null>(null);

  // Undo / Redo history
  const [undoStack, setUndoStack] = useState<HistoryState[]>([]);
  const [redoStack, setRedoStack] = useState<HistoryState[]>([]);

  // Pointer drag state
  const isDrawingRef = useRef(false);
  const currentPointsRef = useRef<GenerativeMaskPoint[]>([]);
  const dragStartRef = useRef<GenerativeMaskPoint | null>(null);

  // API operations
  const [submitting, setSubmitting] = useState(false);
  const [semanticBusy, setSemanticBusy] = useState<"person" | "sky" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastQuality, setLastQuality] = useState<GenerativeMaskQuality | null>(null);
  const [savedMasks, setSavedMasks] = useState<GenerativeMaskView[]>([]);

  // Load saved masks for this session
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    listGenerativeMasks(sessionId, { limit: 10 }, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setSavedMasks(res.items);
        }
      })
      .catch(() => {});

    return () => controller.abort();
  }, [sessionId]);

  const refreshSavedMasks = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await listGenerativeMasks(sessionId, { limit: 10 });
      setSavedMasks(res.items);
    } catch {
      // silently ignore refresh errors
    }
  }, [sessionId]);

  // Redraw the canvas overlay
  const renderCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const w = canvas.width;
    const h = canvas.height;

    // Draw region if geometric tool
    if (region) {
      ctx.save();
      ctx.fillStyle = "rgba(239, 68, 68, 0.45)";
      ctx.strokeStyle = "rgba(239, 68, 68, 0.9)";
      ctx.lineWidth = 2;
      const rx = region.x * w;
      const ry = region.y * h;
      const rw = region.width * w;
      const rh = region.height * h;

      if (tool === "rect" || (!strokes.length && tool !== "ellipse")) {
        ctx.fillRect(rx, ry, rw, rh);
        ctx.strokeRect(rx, ry, rw, rh);
      } else {
        ctx.beginPath();
        ctx.ellipse(rx + rw / 2, ry + rh / 2, rw / 2, rh / 2, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      ctx.restore();
    }

    // Draw strokes
    for (const stroke of strokes) {
      if (!stroke.points.length) continue;
      ctx.save();
      const radiusPx = stroke.radius * Math.min(w, h);
      ctx.lineWidth = radiusPx * 2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";

      if (stroke.mode === "erase") {
        ctx.globalCompositeOperation = "destination-out";
        ctx.strokeStyle = "rgba(0, 0, 0, 1)";
      } else {
        ctx.globalCompositeOperation = "source-over";
        ctx.strokeStyle = "rgba(239, 68, 68, 0.5)";
      }

      ctx.beginPath();
      const first = stroke.points[0];
      ctx.moveTo(first.x * w, first.y * h);
      for (let i = 1; i < stroke.points.length; i++) {
        const pt = stroke.points[i];
        ctx.lineTo(pt.x * w, pt.y * h);
      }
      ctx.stroke();
      ctx.restore();
    }
  }, [strokes, region, tool]);

  useEffect(() => {
    renderCanvas();
  }, [renderCanvas]);

  // Pointer event helpers
  const getNormPoint = (e: ReactPointerEvent<HTMLCanvasElement>): GenerativeMaskPoint => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const x = clamp((e.clientX - rect.left) / rect.width, 0, 1);
    const y = clamp((e.clientY - rect.top) / rect.height, 0, 1);
    return { x: roundTo4(x), y: roundTo4(y) };
  };

  const pushHistory = () => {
    setUndoStack((prev) => [...prev, { strokes, region }]);
    setRedoStack([]);
  };

  const handlePointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (disabled || submitting) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    isDrawingRef.current = true;
    const pt = getNormPoint(e);
    dragStartRef.current = pt;
    pushHistory();

    if (tool === "brush" || tool === "eraser") {
      currentPointsRef.current = [pt];
      const newStroke: GenerativeMaskStroke = {
        points: [pt],
        radius: brushRadius,
        hardness: brushHardness,
        mode: tool === "eraser" ? "erase" : "add",
      };
      setStrokes((prev) => [...prev, newStroke]);
    } else {
      setRegion({
        x: pt.x,
        y: pt.y,
        width: 0.001,
        height: 0.001,
      });
    }
  };

  const handlePointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!isDrawingRef.current) return;
    const pt = getNormPoint(e);

    if (tool === "brush" || tool === "eraser") {
      currentPointsRef.current.push(pt);
      setStrokes((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        const updated: GenerativeMaskStroke = {
          ...last,
          points: [...last.points, pt],
        };
        return [...prev.slice(0, -1), updated];
      });
    } else if (dragStartRef.current) {
      const start = dragStartRef.current;
      const x = Math.min(start.x, pt.x);
      const y = Math.min(start.y, pt.y);
      const width = Math.max(0.001, Math.abs(pt.x - start.x));
      const height = Math.max(0.001, Math.abs(pt.y - start.y));
      setRegion({
        x: roundTo4(x),
        y: roundTo4(y),
        width: roundTo4(width),
        height: roundTo4(height),
      });
    }
  };

  const handlePointerUp = () => {
    if (!isDrawingRef.current) return;
    isDrawingRef.current = false;
    currentPointsRef.current = [];
    dragStartRef.current = null;
  };

  // Undo / Redo
  const handleUndo = () => {
    if (!undoStack.length) return;
    const previous = undoStack[undoStack.length - 1];
    setUndoStack((prev) => prev.slice(0, -1));
    setRedoStack((prev) => [...prev, { strokes, region }]);
    setStrokes(previous.strokes);
    setRegion(previous.region);
  };

  const handleRedo = () => {
    if (!redoStack.length) return;
    const next = redoStack[redoStack.length - 1];
    setRedoStack((prev) => prev.slice(0, -1));
    setUndoStack((prev) => [...prev, { strokes, region }]);
    setStrokes(next.strokes);
    setRegion(next.region);
  };

  const handleClear = () => {
    pushHistory();
    setStrokes([]);
    setRegion(null);
    setLastQuality(null);
    setError(null);
  };

  // Submit manual mask
  const handleSubmit = async () => {
    setError(null);
    const kind: GenerativeMaskKind =
      tool === "rect" ? "rect" : tool === "ellipse" ? "ellipse" : "brush";

    if (kind === "brush" && !strokes.length) {
      setError("请先在画面上绘制画笔区域。");
      return;
    }
    if ((kind === "rect" || kind === "ellipse") && !region) {
      setError("请先在画面上拖拽选择几何区域。");
      return;
    }

    setSubmitting(true);
    try {
      const payload: GenerativeMaskCreate = {
        sessionId,
        kind,
        definition: {
          strokes: kind === "brush" ? strokes : [],
          region: kind === "rect" || kind === "ellipse" ? region : null,
          expand,
        },
        feather,
        inverted,
      };
      const created = await createGenerativeMask(payload);
      setLastQuality(created.quality);
      onMaskCreated?.(created);
      await refreshSavedMasks();
    } catch (err: unknown) {
      const errObj = err as { details?: { reasons?: string[] }; message?: string };
      const reasonMsg = errObj?.details?.reasons?.join("；");
      setError(reasonMsg || errObj?.message || "创建蒙版失败，请检查参数后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  // Submit semantic mask
  const handleCreateSemantic = async (semanticClass: "person" | "sky") => {
    setError(null);
    setSemanticBusy(semanticClass);
    try {
      const payload: GenerativeMaskCreate = {
        sessionId,
        kind: "semantic",
        definition: {
          semanticClass,
          expand,
        },
        feather,
        inverted,
      };
      const created = await createGenerativeMask(payload);
      setLastQuality(created.quality);
      onMaskCreated?.(created);
      await refreshSavedMasks();
    } catch (err: unknown) {
      const errObj = err as { message?: string };
      setError(errObj?.message || `${semanticClass === "person" ? "人物" : "天空"}语义识别不可用。`);
    } finally {
      setSemanticBusy(null);
    }
  };

  // Delete saved mask
  const handleDeleteMask = async (maskId: string) => {
    try {
      await deleteGenerativeMask(maskId);
      setSavedMasks((prev) => prev.filter((m) => m.maskId !== maskId));
    } catch (err: unknown) {
      const errObj = err as { message?: string };
      setError(errObj?.message || "删除蒙版失败");
    }
  };

  const hasContent = strokes.length > 0 || region !== null;

  return (
    <section
      aria-label="生成式蒙版编辑器"
      className={`grid gap-3 rounded-xl border border-white/8 bg-white/[0.015] p-4 ${className}`}
    >
      {/* Header & Tool switcher */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/8 pb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white/90">
            蒙版绘制
          </h3>
          <span className="rounded bg-rose-500/10 px-1.5 py-0.5 font-mono text-[10px] text-rose-400">
            V6.3
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="画笔工具"
            aria-pressed={tool === "brush"}
            onClick={() => setTool("brush")}
            disabled={disabled}
            className={`rounded px-2.5 py-1 text-xs font-medium transition ${
              tool === "brush"
                ? "bg-rose-500 text-[#ffffff]"
                : "bg-white/5 text-white/70 hover:bg-white/10"
            }`}
          >
            画笔
          </button>
          <button
            type="button"
            aria-label="橡皮擦工具"
            aria-pressed={tool === "eraser"}
            onClick={() => setTool("eraser")}
            disabled={disabled}
            className={`rounded px-2.5 py-1 text-xs font-medium transition ${
              tool === "eraser"
                ? "bg-rose-500 text-[#ffffff]"
                : "bg-white/5 text-white/70 hover:bg-white/10"
            }`}
          >
            橡皮擦
          </button>
          <button
            type="button"
            aria-label="矩形选区"
            aria-pressed={tool === "rect"}
            onClick={() => setTool("rect")}
            disabled={disabled}
            className={`rounded px-2.5 py-1 text-xs font-medium transition ${
              tool === "rect"
                ? "bg-rose-500 text-[#ffffff]"
                : "bg-white/5 text-white/70 hover:bg-white/10"
            }`}
          >
            矩形
          </button>
          <button
            type="button"
            aria-label="椭圆选区"
            aria-pressed={tool === "ellipse"}
            onClick={() => setTool("ellipse")}
            disabled={disabled}
            className={`rounded px-2.5 py-1 text-xs font-medium transition ${
              tool === "ellipse"
                ? "bg-rose-500 text-[#ffffff]"
                : "bg-white/5 text-white/70 hover:bg-white/10"
            }`}
          >
            椭圆
          </button>
        </div>
      </div>

      {/* Main Canvas Stage */}
      <div
        ref={containerRef}
        className="relative flex aspect-[4/3] w-full items-center justify-center overflow-hidden rounded-lg border border-white/10 bg-black/40"
      >
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl}
            alt="编辑基准图像"
            className="pointer-events-none absolute inset-0 h-full w-full object-contain"
          />
        ) : (
          <div className="p-8 text-center text-xs text-white/40">
            基准画面载入中或未提供预览图
          </div>
        )}

        <canvas
          ref={canvasRef}
          width={previewWidth}
          height={previewHeight}
          aria-label="蒙版绘制画布"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          className={`absolute inset-0 h-full w-full touch-none ${
            disabled ? "cursor-not-allowed" : "cursor-crosshair"
          }`}
        />
      </div>

      {/* Sliders & Fine tuning */}
      <div className="grid gap-2 text-xs">
        {(tool === "brush" || tool === "eraser") && (
          <div className="grid grid-cols-2 gap-3">
            <label className="flex items-center justify-between text-white/70">
              <span>画笔半径: {Math.round(brushRadius * 100)}%</span>
              <input
                type="range"
                min="0.01"
                max="0.30"
                step="0.01"
                aria-label="画笔半径"
                value={brushRadius}
                onChange={(e) => setBrushRadius(parseFloat(e.target.value))}
                disabled={disabled}
                className="w-28 accent-rose-500"
              />
            </label>
            <label className="flex items-center justify-between text-white/70">
              <span>硬度: {brushHardness}%</span>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                aria-label="硬度"
                value={brushHardness}
                onChange={(e) => setBrushHardness(parseInt(e.target.value, 10))}
                disabled={disabled}
                className="w-28 accent-rose-500"
              />
            </label>
          </div>
        )}

        <div className="grid grid-cols-3 gap-2">
          <label className="flex items-center justify-between text-white/70">
            <span>羽化: {feather}px</span>
            <input
              type="range"
              min="0"
              max="50"
              step="1"
              aria-label="羽化"
              value={feather}
              onChange={(e) => setFeather(parseInt(e.target.value, 10))}
              disabled={disabled}
              className="w-20 accent-rose-500"
            />
          </label>
          <label className="flex items-center justify-between text-white/70">
            <span>扩展: {expand}px</span>
            <input
              type="range"
              min="0"
              max="50"
              step="1"
              aria-label="扩展"
              value={expand}
              onChange={(e) => setExpand(parseInt(e.target.value, 10))}
              disabled={disabled}
              className="w-20 accent-rose-500"
            />
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-white/70">
            <input
              type="checkbox"
              aria-label="反向蒙版"
              checked={inverted}
              onChange={(e) => setInverted(e.target.checked)}
              disabled={disabled}
              className="accent-rose-500"
            />
            <span>反转蒙版</span>
          </label>
        </div>
      </div>

      {/* History and AI Assist Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-2">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="撤销"
            onClick={handleUndo}
            disabled={disabled || !undoStack.length}
            className="rounded border border-white/10 px-2 py-1 text-xs font-medium text-white/70 hover:bg-white/5 disabled:opacity-40"
          >
            撤销
          </button>
          <button
            type="button"
            aria-label="重做"
            onClick={handleRedo}
            disabled={disabled || !redoStack.length}
            className="rounded border border-white/10 px-2 py-1 text-xs font-medium text-white/70 hover:bg-white/5 disabled:opacity-40"
          >
            重做
          </button>
          <button
            type="button"
            aria-label="清除所有"
            onClick={handleClear}
            disabled={disabled || !hasContent}
            className="rounded border border-white/10 px-2 py-1 text-xs font-medium text-white/70 hover:bg-white/5 disabled:opacity-40"
          >
            清空
          </button>
        </div>

        {/* AI semantic shortcuts */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] uppercase text-white/40">AI 辅助:</span>
          <button
            type="button"
            aria-label="生成人物蒙版"
            onClick={() => handleCreateSemantic("person")}
            disabled={disabled || semanticBusy !== null}
            className="rounded bg-indigo-500/20 px-2.5 py-1 text-xs font-medium text-indigo-300 hover:bg-indigo-500/30 disabled:opacity-40"
          >
            {semanticBusy === "person" ? "识别中…" : "人物"}
          </button>
          <button
            type="button"
            aria-label="生成天空蒙版"
            onClick={() => handleCreateSemantic("sky")}
            disabled={disabled || semanticBusy !== null}
            className="rounded bg-sky-500/20 px-2.5 py-1 text-xs font-medium text-sky-300 hover:bg-sky-500/30 disabled:opacity-40"
          >
            {semanticBusy === "sky" ? "识别中…" : "天空"}
          </button>
        </div>
      </div>

      {/* Quality indicator and feedback */}
      {lastQuality && (
        <div
          role="status"
          aria-label="蒙版质量报告"
          className="flex items-center gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-1.5 text-xs text-emerald-400"
        >
          <span>覆盖率: {(lastQuality.coverage * 100).toFixed(2)}%</span>
          <span>连通区: {lastQuality.componentCount}</span>
          {lastQuality.touchesBorder && <span className="text-amber-400">触碰边缘</span>}
          {lastQuality.warnings && lastQuality.warnings.length > 0 && (
            <span className="text-amber-400">
              警告: {lastQuality.warnings.join(", ")}
            </span>
          )}
        </div>
      )}

      {/* Error display */}
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300"
        >
          {error}
        </div>
      )}

      {/* Submit / Action Bar */}
      <div className="flex items-center justify-between border-t border-white/8 pt-3">
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded px-3 py-1.5 text-xs font-medium text-white/60 hover:text-white"
          >
            取消
          </button>
        )}
        <button
          type="button"
          aria-label="保存蒙版"
          onClick={handleSubmit}
          disabled={disabled || submitting || !hasContent}
          className="ml-auto rounded-lg bg-rose-500 px-4 py-1.5 text-xs font-medium text-[#ffffff] shadow transition hover:bg-rose-600 disabled:opacity-50"
        >
          {submitting ? "正在保存…" : "保存蒙版"}
        </button>
      </div>

      {/* Saved masks in session */}
      {savedMasks.length > 0 && (
        <div className="mt-2 border-t border-white/8 pt-3">
          <h4 className="mb-2 text-[11px] font-medium text-white/60">
            已存蒙版 ({savedMasks.length})
          </h4>
          <div className="grid gap-1.5">
            {savedMasks.map((m) => (
              <div
                key={m.maskId}
                className="flex items-center justify-between rounded border border-white/5 bg-white/[0.02] px-2 py-1 text-xs"
              >
                <div className="flex items-center gap-2">
                  <span className="rounded bg-white/10 px-1 py-0.5 font-mono text-[9px] uppercase text-white/80">
                    {m.kind}
                  </span>
                  <span className="text-[10px] text-white/40">
                    {(m.quality.coverage * 100).toFixed(1)}% 覆盖
                  </span>
                </div>
                <button
                  type="button"
                  aria-label={`删除蒙版 ${m.maskId}`}
                  onClick={() => handleDeleteMask(m.maskId)}
                  className="text-white/40 hover:text-rose-400"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
