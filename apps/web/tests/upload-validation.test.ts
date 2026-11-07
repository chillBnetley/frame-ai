import { describe, expect, it } from "vitest";

import { MAX_UPLOAD_BYTES, validateUploadFile } from "@/lib/upload-validation";

function makeFile(size: number, type: string, name = "photo.png"): File {
  const bytes = new Uint8Array(size);
  return new File([bytes], name, { type });
}

describe("validateUploadFile", () => {
  it("accepts supported image types within the size limit", () => {
    expect(validateUploadFile(makeFile(1024, "image/png"))).toEqual({ ok: true });
    expect(validateUploadFile(makeFile(1024, "image/tiff", "photo.tiff"))).toEqual({
      ok: true,
    });
  });

  it("accepts a file with an empty MIME type and lets the server inspect it", () => {
    expect(validateUploadFile(makeFile(1024, ""))).toEqual({ ok: true });
  });

  it("rejects empty files", () => {
    const result = validateUploadFile(makeFile(0, "image/png"));
    expect(result).toMatchObject({ ok: false, code: "empty_file" });
  });

  it("rejects unsupported declared MIME types", () => {
    const result = validateUploadFile(makeFile(1024, "image/gif"));
    expect(result).toMatchObject({ ok: false, code: "unsupported_media_type" });
  });

  it("rejects files above the limit without silently clamping", () => {
    const oversized = new File([new Uint8Array(MAX_UPLOAD_BYTES + 1)], "large.png", {
      type: "image/png",
    });
    const result = validateUploadFile(oversized);
    expect(result).toMatchObject({ ok: false, code: "file_too_large" });
  });

  it("applies limits returned by the runtime config endpoint", () => {
    const limits = { maxUploadBytes: 4096, allowedMimeTypes: ["image/png"] };

    expect(validateUploadFile(makeFile(4096, "image/png"), limits)).toEqual({ ok: true });
    expect(validateUploadFile(makeFile(4097, "image/png"), limits)).toMatchObject({
      ok: false,
      code: "file_too_large",
    });
    expect(validateUploadFile(makeFile(1024, "image/webp"), limits)).toMatchObject({
      ok: false,
      code: "unsupported_media_type",
    });
  });
});
