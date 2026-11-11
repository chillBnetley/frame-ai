"use client";

import { useCallback, useReducer } from "react";

import {
  CANVAS_ZOOM_STEP,
  fitCanvasView,
  panCanvasView,
  zoomCanvasView,
  type CanvasView,
} from "@/lib/generative-canvas";
import type { OutpaintFormValues } from "../components/outpaint-params-form";
import type { GenerativeTaskType } from "@/types/generative";

export type StudioCapability = Extract<GenerativeTaskType, "outpaint" | "remove" | "local_edit">;
export type StudioBaseLayer = "current" | "original";
export type StudioCompareMode = "off" | "slider" | "side";

export interface StudioState {
  capability: StudioCapability;
  instruction: string;
  outpaint: OutpaintFormValues;
  baseLayer: StudioBaseLayer;
  maskOverlayVisible: boolean;
  resultVisible: boolean;
  compare: StudioCompareMode;
  comparePosition: number;
  view: CanvasView;
}

export const INITIAL_OUTPAINT_VALUES: OutpaintFormValues = {
  aspectRatio: null,
  alignment: "center",
  margins: { top: 0, bottom: 0, left: 0, right: 0 },
};

export const PAN_STEP_PX = 48;

type StudioAction =
  | { type: "capability"; capability: StudioCapability }
  | { type: "instruction"; instruction: string }
  | { type: "outpaint"; values: OutpaintFormValues }
  | { type: "base-layer"; baseLayer: StudioBaseLayer }
  | { type: "toggle-mask" }
  | { type: "result-visible"; resultVisible: boolean }
  | { type: "compare"; compare: StudioCompareMode }
  | { type: "compare-position"; position: number }
  | { type: "view"; view: CanvasView }
  | { type: "zoom"; factor: number; pointerX: number; pointerY: number }
  | { type: "pan"; deltaX: number; deltaY: number }
  | { type: "fit"; boxWidth: number; boxHeight: number; contentWidth: number; contentHeight: number };

export function createInitialStudioState(): StudioState {
  return {
    capability: "outpaint",
    instruction: "",
    outpaint: INITIAL_OUTPAINT_VALUES,
    baseLayer: "current",
    maskOverlayVisible: true,
    resultVisible: true,
    compare: "off",
    comparePosition: 50,
    view: { scale: 1, offsetX: 0, offsetY: 0 },
  };
}

export function studioReducer(state: StudioState, action: StudioAction): StudioState {
  switch (action.type) {
    case "capability":
      return { ...state, capability: action.capability, compare: "off" };
    case "instruction":
      return { ...state, instruction: action.instruction };
    case "outpaint":
      return { ...state, outpaint: action.values };
    case "base-layer":
      return { ...state, baseLayer: action.baseLayer };
    case "toggle-mask":
      return { ...state, maskOverlayVisible: !state.maskOverlayVisible };
    case "result-visible":
      return { ...state, resultVisible: action.resultVisible };
    case "compare":
      return {
        ...state,
        compare: action.compare,
        resultVisible: action.compare === "off" ? state.resultVisible : true,
      };
    case "compare-position":
      return { ...state, comparePosition: Math.min(100, Math.max(0, action.position)) };
    case "view":
      return { ...state, view: action.view };
    case "zoom":
      return {
        ...state,
        view: zoomCanvasView(state.view, action.factor, action.pointerX, action.pointerY),
      };
    case "pan":
      return { ...state, view: panCanvasView(state.view, action.deltaX, action.deltaY) };
    case "fit":
      return {
        ...state,
        view: fitCanvasView(
          action.boxWidth,
          action.boxHeight,
          action.contentWidth,
          action.contentHeight,
          16,
        ),
      };
    default:
      return state;
  }
}

export interface StudioController {
  state: StudioState;
  setCapability: (capability: StudioCapability) => void;
  setInstruction: (instruction: string) => void;
  setOutpaint: (values: OutpaintFormValues) => void;
  setBaseLayer: (baseLayer: StudioBaseLayer) => void;
  toggleMaskOverlay: () => void;
  setResultVisible: (resultVisible: boolean) => void;
  setCompare: (compare: StudioCompareMode) => void;
  setComparePosition: (position: number) => void;
  zoomBy: (factor: number, pointerX?: number, pointerY?: number) => void;
  panBy: (deltaX: number, deltaY: number) => void;
  panStep: (direction: "up" | "down" | "left" | "right") => void;
  fitTo: (
    boxWidth: number,
    boxHeight: number,
    contentWidth: number,
    contentHeight: number,
  ) => void;
  resetView: () => void;
}

export function useStudioState(): StudioController & { state: StudioState } {
  const [state, dispatch] = useReducer(studioReducer, undefined, createInitialStudioState);

  const setCapability = useCallback(
    (capability: StudioCapability) => dispatch({ type: "capability", capability }),
    [],
  );
  const setInstruction = useCallback(
    (instruction: string) => dispatch({ type: "instruction", instruction }),
    [],
  );
  const setOutpaint = useCallback(
    (values: OutpaintFormValues) => dispatch({ type: "outpaint", values }),
    [],
  );
  const setBaseLayer = useCallback(
    (baseLayer: StudioBaseLayer) => dispatch({ type: "base-layer", baseLayer }),
    [],
  );
  const toggleMaskOverlay = useCallback(() => dispatch({ type: "toggle-mask" }), []);
  const setResultVisible = useCallback(
    (resultVisible: boolean) => dispatch({ type: "result-visible", resultVisible }),
    [],
  );
  const setCompare = useCallback(
    (compare: StudioCompareMode) => dispatch({ type: "compare", compare }),
    [],
  );
  const setComparePosition = useCallback(
    (position: number) => dispatch({ type: "compare-position", position }),
    [],
  );
  const zoomBy = useCallback(
    (factor: number, pointerX = 0, pointerY = 0) =>
      dispatch({ type: "zoom", factor, pointerX, pointerY }),
    [],
  );
  const panBy = useCallback(
    (deltaX: number, deltaY: number) => dispatch({ type: "pan", deltaX, deltaY }),
    [],
  );
  const panStep = useCallback((direction: "up" | "down" | "left" | "right") => {
    const deltas: Record<typeof direction, [number, number]> = {
      up: [0, PAN_STEP_PX],
      down: [0, -PAN_STEP_PX],
      left: [PAN_STEP_PX, 0],
      right: [-PAN_STEP_PX, 0],
    };
    const [deltaX, deltaY] = deltas[direction];
    dispatch({ type: "pan", deltaX, deltaY });
  }, []);
  const fitTo = useCallback(
    (boxWidth: number, boxHeight: number, contentWidth: number, contentHeight: number) =>
      dispatch({ type: "fit", boxWidth, boxHeight, contentWidth, contentHeight }),
    [],
  );
  const resetView = useCallback(
    () => dispatch({ type: "view", view: { scale: 1, offsetX: 0, offsetY: 0 } }),
    [],
  );

  return {
    state,
    setCapability,
    setInstruction,
    setOutpaint,
    setBaseLayer,
    toggleMaskOverlay,
    setResultVisible,
    setCompare,
    setComparePosition,
    zoomBy,
    panBy,
    panStep,
    fitTo,
    resetView,
  };
}

export { CANVAS_ZOOM_STEP };
