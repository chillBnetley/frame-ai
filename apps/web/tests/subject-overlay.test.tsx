import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SubjectOverlay } from "@/features/analysis/components/subject-overlay";
import {
  bboxToRect,
  clampBBox,
  containRect,
} from "@/features/analysis/overlay-geometry";

describe("overlay geometry", () => {
  it("letterboxes a landscape image inside a squarer container", () => {
    expect(containRect(400, 300, 1600, 900)).toEqual({
      left: 0,
      top: 37.5,
      width: 400,
      height: 225,
    });
  });

  it("pillarboxes a portrait image inside a landscape container", () => {
    expect(containRect(300, 300, 100, 200)).toEqual({
      left: 75,
      top: 0,
      width: 150,
      height: 300,
    });
  });

  it("rejects empty or invalid dimensions", () => {
    expect(containRect(0, 300, 100, 200)).toBeNull();
    expect(containRect(300, 300, 0, 200)).toBeNull();
    expect(containRect(Number.NaN, 300, 100, 200)).toBeNull();
  });

  it("clips boxes that cross the image boundary", () => {
    const clipped = clampBBox({ x: 0.9, y: 0.8, width: 0.4, height: 0.4 });
    expect(clipped).not.toBeNull();
    expect(clipped!.x).toBeCloseTo(0.9);
    expect(clipped!.y).toBeCloseTo(0.8);
    expect(clipped!.width).toBeCloseTo(0.1);
    expect(clipped!.height).toBeCloseTo(0.2);

    expect(clampBBox({ x: -0.2, y: -0.1, width: 0.5, height: 0.5 })).toEqual({
      x: 0,
      y: 0,
      width: 0.5,
      height: 0.5,
    });
    expect(clampBBox({ x: 1, y: 0.5, width: 0.2, height: 0.2 })).toBeNull();
  });

  it("projects normalized boxes into the displayed image rectangle", () => {
    expect(
      bboxToRect(
        { x: 0.25, y: 0.5, width: 0.5, height: 0.25 },
        { left: 10, top: 20, width: 200, height: 100 },
      ),
    ).toEqual({ left: 60, top: 70, width: 100, height: 25 });
  });
});

describe("SubjectOverlay", () => {
  it("renders the original image and accessible subject region labels", () => {
    render(
      <SubjectOverlay
        imageId="22222222-2222-4222-8222-222222222222"
        imageWidth={1600}
        imageHeight={1200}
        subjects={[
          {
            id: "subject_001",
            type: "person",
            role: "primary",
            confidence: 0.8,
            bbox: { x: 0.2, y: 0.1, width: 0.4, height: 0.7 },
            regionId: "region_001",
          },
        ]}
      />,
    );

    expect(screen.getByAltText("原图主体框叠加预览")).toBeInTheDocument();
    expect(
      screen.getByAltText("原图主体框叠加预览").getAttribute("src"),
    ).toContain("/api/v1/images/22222222-2222-4222-8222-222222222222/original");
  });

  it("opens an enlarged preview on click and closes it with the × button", () => {
    render(
      <SubjectOverlay
        imageId="22222222-2222-4222-8222-222222222222"
        imageWidth={1600}
        imageHeight={1200}
        subjects={[]}
      />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "放大查看主体框" }));

    expect(
      screen.getByRole("dialog", { name: "主体框放大预览" }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("主体框放大预览图")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "关闭主体框放大预览" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "主体框放大预览" }),
    ).not.toBeInTheDocument();
  });

  it("opens the enlarged preview from the keyboard and closes it with Escape", () => {
    render(
      <SubjectOverlay
        imageId="22222222-2222-4222-8222-222222222222"
        imageWidth={1600}
        imageHeight={1200}
        subjects={[]}
      />,
    );

    fireEvent.keyDown(screen.getByRole("button", { name: "放大查看主体框" }), {
      key: "Enter",
    });
    expect(
      screen.getByRole("dialog", { name: "主体框放大预览" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "主体框放大预览" }),
    ).not.toBeInTheDocument();
  });
});