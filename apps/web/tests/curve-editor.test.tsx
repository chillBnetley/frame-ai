import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CurveEditor } from "@/features/editor/components/curve-editor";
import { KEYBOARD_COMMIT_DEBOUNCE_MS } from "@/features/editor/components/slider-field";
import { normalizeCurveSet } from "@/lib/recipe";
import type { CurvePoint, CurveSet } from "@/types/session";

const IDENTITY: CurvePoint[] = [
  { x: 0, y: 0 },
  { x: 1, y: 1 },
];

interface HarnessProps {
  initial?: Partial<CurveSet>;
  disabled?: boolean;
  onChange?: (curve: CurveSet) => void;
  onCommit?: () => void;
}

function Harness({ initial, disabled, onChange, onCommit }: HarnessProps) {
  const [curve, setCurve] = useState<CurveSet>(() => normalizeCurveSet(initial));
  return (
    <CurveEditor
      curve={curve}
      disabled={disabled}
      onChange={(next) => {
        setCurve(next);
        onChange?.(next);
      }}
      onCommit={onCommit ?? (() => {})}
    />
  );
}

function lastCurve(spy: ReturnType<typeof vi.fn>): CurveSet {
  const calls = spy.mock.calls;
  return calls[calls.length - 1][0] as CurveSet;
}

const RECT = {
  left: 0,
  top: 0,
  right: 100,
  bottom: 100,
  width: 100,
  height: 100,
  x: 0,
  y: 0,
  toJSON: () => ({}),
} as DOMRect;

beforeEach(() => {
  vi.spyOn(SVGSVGElement.prototype, "getBoundingClientRect").mockReturnValue(RECT);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("CurveEditor", () => {
  it("renders four channels and a neutral identity curve", () => {
    render(<Harness />);

    for (const label of ["主曲线", "红", "绿", "蓝"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "主曲线" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("curve-line").getAttribute("d")).toContain("M4.00 96.00");
    expect(screen.queryByTestId("curve-node-0")).not.toBeInTheDocument();
  });

  it("adds a node where the curve surface is clicked and commits", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(<Harness onChange={onChange} onCommit={onCommit} />);

    fireEvent.click(screen.getByTestId("curve-surface"), { clientX: 50, clientY: 50 });

    const curve = lastCurve(onChange);
    expect(curve.master).toHaveLength(3);
    expect(curve.master[0]).toEqual({ x: 0, y: 0 });
    expect(curve.master[1]?.x).toBeCloseTo(0.5, 6);
    expect(curve.master[1]?.y).toBeCloseTo(0.5, 6);
    expect(curve.master[2]).toEqual({ x: 1, y: 1 });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("curve-node-1")).toBeInTheDocument();
  });

  it("drags a node and commits on pointer release", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(
      <Harness
        initial={{ master: [...IDENTITY, { x: 0.5, y: 0.5 }] }}
        onChange={onChange}
        onCommit={onCommit}
      />,
    );

    const node = screen.getByTestId("curve-node-1");
    fireEvent.pointerDown(node, { pointerId: 1, clientX: 50, clientY: 50 });
    fireEvent.pointerMove(screen.getByTestId("curve-svg"), {
      pointerId: 1,
      clientX: 54.6,
      clientY: 27,
    });
    expect(lastCurve(onChange).master[1]?.y).toBeCloseTo(0.75, 2);
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.pointerUp(screen.getByTestId("curve-svg"), { pointerId: 1 });
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("keeps endpoint drags vertical", () => {
    const onChange = vi.fn();
    render(<Harness initial={{ master: [...IDENTITY] }} onChange={onChange} />);

    fireEvent.pointerDown(screen.getByTestId("curve-node-0"), {
      pointerId: 1,
      clientX: 4,
      clientY: 96,
    });
    fireEvent.pointerMove(screen.getByTestId("curve-svg"), {
      pointerId: 1,
      clientX: 50,
      clientY: 27,
    });

    const first = lastCurve(onChange).master[0];
    expect(first?.x).toBe(0);
    expect(first?.y).toBeCloseTo(0.75, 2);
  });

  it("nudges nodes with the keyboard and commits with a debounce", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(
      <Harness
        initial={{ master: [...IDENTITY, { x: 0.5, y: 0.5 }] }}
        onChange={onChange}
        onCommit={onCommit}
      />,
    );

    const node = screen.getByTestId("curve-node-1");
    fireEvent.keyDown(node, { key: "ArrowUp" });
    expect(lastCurve(onChange).master[1]?.y).toBeCloseTo(0.51, 6);
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.keyDown(node, { key: "ArrowRight", shiftKey: true });
    expect(lastCurve(onChange).master[1]?.x).toBeCloseTo(0.55, 6);
    expect(onCommit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(KEYBOARD_COMMIT_DEBOUNCE_MS);
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("deletes internal nodes with the keyboard and via the button", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(
      <Harness
        initial={{ master: [...IDENTITY, { x: 0.4, y: 0.6 }] }}
        onChange={onChange}
        onCommit={onCommit}
      />,
    );

    fireEvent.keyDown(screen.getByTestId("curve-node-1"), { key: "Delete" });
    expect(lastCurve(onChange).master).toEqual(IDENTITY);
    expect(onCommit).toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("curve-surface"), { clientX: 50, clientY: 50 });
    expect(screen.getByTestId("curve-node-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "删除节点" }));
    expect(lastCurve(onChange).master).toHaveLength(2);
  });

  it("disables deletion for endpoints", () => {
    render(<Harness initial={{ master: [...IDENTITY, { x: 0.5, y: 0.5 }] }} />);

    fireEvent.focus(screen.getByTestId("curve-node-0"));
    expect(screen.getByRole("button", { name: "删除节点" })).toBeDisabled();

    fireEvent.focus(screen.getByTestId("curve-node-1"));
    expect(screen.getByRole("button", { name: "删除节点" })).not.toBeDisabled();
  });

  it("resets the active channel and then all channels", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(
      <Harness
        initial={{
          master: [...IDENTITY, { x: 0.5, y: 0.7 }],
          red: [...IDENTITY, { x: 0.5, y: 0.4 }],
        }}
        onChange={onChange}
        onCommit={onCommit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重置通道" }));
    let curve = lastCurve(onChange);
    expect(curve.master).toEqual([]);
    expect(curve.red).toHaveLength(3);
    expect(onCommit).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "重置全部" }));
    curve = lastCurve(onChange);
    expect(curve).toEqual({ master: [], red: [], green: [], blue: [] });
    expect(onCommit).toHaveBeenCalledTimes(2);
  });

  it("switches channels and renders that channel's points", () => {
    render(
      <Harness
        initial={{
          master: [...IDENTITY, { x: 0.5, y: 0.7 }],
          red: [...IDENTITY, { x: 0.3, y: 0.5 }, { x: 0.7, y: 0.6 }],
        }}
      />,
    );

    expect(screen.getAllByTestId(/curve-node-/)).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "红" }));

    expect(screen.getByRole("button", { name: "红" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getAllByTestId(/curve-node-/)).toHaveLength(4);
    expect(screen.getByLabelText(/红节点 2/)).toBeInTheDocument();
  });

  it("blocks all interaction when disabled", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(
      <Harness
        initial={{ master: [...IDENTITY, { x: 0.5, y: 0.5 }] }}
        disabled
        onChange={onChange}
        onCommit={onCommit}
      />,
    );

    expect(screen.getByRole("button", { name: "主曲线" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置全部" })).toBeDisabled();

    fireEvent.click(screen.getByTestId("curve-surface"), { clientX: 50, clientY: 20 });
    fireEvent.pointerDown(screen.getByTestId("curve-node-1"), {
      pointerId: 1,
      clientX: 50,
      clientY: 50,
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });
});
