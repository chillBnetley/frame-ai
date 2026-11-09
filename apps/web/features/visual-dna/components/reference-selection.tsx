"use client";

import { useRef, useState } from "react";

import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError, originalImageUrl, uploadImage } from "@/lib/api/client";
import { formatDimensions } from "@/lib/format";
import { FILE_ACCEPT_ATTRIBUTE, validateUploadFile } from "@/lib/upload-validation";

import { useImageLibrary } from "../use-image-library";

export interface SelectedReference {
  id: string;
  originalName: string;
  width: number;
  height: number;
  source: "library" | "upload";
}

const SUGGESTED_MIN = 5;
const SUGGESTED_MAX = 12;
const HARD_MAX = 20;

export function ReferenceSelection({
  selected,
  onChange,
  consent,
  onConsentChange,
  existingIds,
}: {
  selected: SelectedReference[];
  onChange: (next: SelectedReference[]) => void;
  consent: boolean;
  onConsentChange: (value: boolean) => void;
  existingIds?: ReadonlySet<string>;
}) {
  const library = useImageLibrary();
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const selectedIds = new Set(selected.map((item) => item.id));

  function toggleFromLibrary(image: { id: string; originalName: string; width: number; height: number }) {
    if (existingIds?.has(image.id)) return;
    if (selectedIds.has(image.id)) {
      onChange(selected.filter((item) => item.id !== image.id));
      return;
    }
    if (selected.length >= HARD_MAX) {
      setUploadError(`最多选择 ${HARD_MAX} 张参考照片。`);
      return;
    }
    setUploadError(null);
    onChange([
      ...selected,
      {
        id: image.id,
        originalName: image.originalName,
        width: image.width,
        height: image.height,
        source: "library",
      },
    ]);
  }

  async function handleFiles(files: FileList | null) {
    if (files === null || files.length === 0) return;
    setUploadError(null);
    setUploadNotice(null);
    const accepted: File[] = [];
    for (const file of Array.from(files)) {
      const validation = validateUploadFile(file);
      if (!validation.ok) {
        setUploadError(`${file.name}：${validation.message}`);
        continue;
      }
      accepted.push(file);
    }
    if (accepted.length === 0) return;
    const remaining = HARD_MAX - selected.length;
    if (remaining <= 0) {
      setUploadError(`最多选择 ${HARD_MAX} 张参考照片。`);
      return;
    }
    const queue = accepted.slice(0, remaining);
    if (queue.length < accepted.length) {
      setUploadError(`本次仅上传前 ${remaining} 张，已达到 ${HARD_MAX} 张上限。`);
    }
    setUploading(true);
    const next = [...selected];
    const failed: string[] = [];
    for (const file of queue) {
      try {
        const uploaded = await uploadImage(file);
        if (next.some((item) => item.id === uploaded.imageId)) continue;
        next.push({
          id: uploaded.imageId,
          originalName: uploaded.originalName,
          width: uploaded.width,
          height: uploaded.height,
          source: "upload",
        });
        onChange([...next]);
      } catch (reason: unknown) {
        failed.push(
          `${file.name}：${
            reason instanceof ApiClientError ? reason.message : "上传失败，请稍后重试。"
          }`,
        );
      }
    }
    setUploading(false);
    if (failed.length > 0) {
      setUploadError(failed.join("；"));
    } else {
      setUploadNotice(`已上传 ${queue.length} 张照片。`);
    }
    if (fileInputRef.current !== null) {
      fileInputRef.current.value = "";
    }
  }

  const countTone =
    selected.length === 0
      ? "text-[#8a9690]"
      : selected.length < SUGGESTED_MIN
        ? "text-[#8a6228]"
        : "text-[#277a68]";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#e4e8e5] bg-[#f9fbf9] px-4 py-3">
        <div>
          <p className={`text-xs font-semibold ${countTone}`}>
            已选择 {selected.length} 张
            <span className="ml-2 font-normal text-[#8a9690]">
              建议 {SUGGESTED_MIN}–{SUGGESTED_MAX} 张，最多 {HARD_MAX} 张
            </span>
          </p>
          <p className="mt-1 text-[11px] text-[#8a9690]">
            照片只用于提取视觉特征；分析结果可以修改，参考照片可以随时移除。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={FILE_ACCEPT_ATTRIBUTE}
            className="sr-only"
            aria-label="上传参考照片"
            onChange={(event) => void handleFiles(event.target.files)}
          />
          <button
            type="button"
            disabled={uploading || selected.length >= HARD_MAX}
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#277a68] hover:bg-[#f1f7f4] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
          >
            {uploading ? "上传中…" : "上传新照片"}
          </button>
        </div>
      </div>

      {uploadError !== null && (
        <MasterVisionStatus tone="error" title="部分照片未加入">
          {uploadError}
        </MasterVisionStatus>
      )}
      {uploadNotice !== null && uploadError === null && (
        <MasterVisionStatus tone="success" title="上传完成">
          {uploadNotice}
        </MasterVisionStatus>
      )}

      {selected.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="已选择的参考照片">
          {selected.map((item) => (
            <li
              key={item.id}
              className="flex items-center gap-2 rounded-xl border border-[#dfe5e1] bg-white py-1 pl-1 pr-2"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- local originals are served by the API */}
              <img
                src={originalImageUrl(item.id)}
                alt=""
                className="size-10 rounded-lg object-cover"
              />
              <span className="max-w-36 truncate text-[11px] text-[#4a574f]" title={item.originalName}>
                {item.originalName}
              </span>
              <button
                type="button"
                aria-label={`移除 ${item.originalName}`}
                onClick={() => onChange(selected.filter((entry) => entry.id !== item.id))}
                className="grid size-6 place-items-center rounded-full text-[#8a9690] hover:bg-[#f1f4f2] hover:text-[#8a3a2e] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <fieldset className="rounded-xl border border-[#dfe5e1] bg-white p-4">
        <legend className="px-1 text-xs font-semibold text-[#33413a]">从图片库选择</legend>
        {library.error !== null ? (
          <div className="mt-2">
            <MasterVisionStatus
              tone="error"
              title="图片库加载失败"
              action={
                <button
                  type="button"
                  onClick={library.reload}
                  className="min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  重试
                </button>
              }
            >
              {library.error}
            </MasterVisionStatus>
          </div>
        ) : library.loading ? (
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" aria-hidden="true">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="h-28 animate-pulse rounded-xl bg-[#f0f4f1]" />
            ))}
          </div>
        ) : library.images.length === 0 ? (
          <p className="mt-3 text-xs text-[#8a9690]">图片库还没有照片，可以先上传新照片。</p>
        ) : (
          <>
            <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {library.images.map((image) => {
                const active = selectedIds.has(image.id);
                const existing = existingIds?.has(image.id) ?? false;
                return (
                  <li key={image.id}>
                    <button
                      type="button"
                      aria-pressed={active}
                      aria-label={`${active ? "取消选择" : "选择"} ${image.originalName}`}
                      disabled={existing}
                      onClick={() => toggleFromLibrary(image)}
                      className="group relative block w-full overflow-hidden rounded-xl border border-[#e4e8e5] bg-[#f6f8f6] text-left transition-colors hover:border-[#b9cdc2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#277a68] aria-pressed:ring-2 aria-pressed:ring-[#277a68]/25 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element -- local originals are served by the API */}
                      <img
                        src={originalImageUrl(image.id)}
                        alt=""
                        className="aspect-[4/3] w-full object-cover"
                      />
                      <span className="block px-2 py-1.5">
                        <span className="block truncate text-[10px] font-medium text-[#4a574f]">
                          {image.originalName}
                        </span>
                        <span className="mt-0.5 block text-[9px] text-[#8a9690]">
                          {formatDimensions(image.width, image.height)}
                          {existing ? " · 已添加" : ""}
                        </span>
                      </span>
                      {active && (
                        <span className="absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full bg-[#277a68] text-[11px] font-semibold text-white">
                          ✓
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
            {library.nextOffset !== null && (
              <button
                type="button"
                onClick={library.loadMore}
                disabled={library.loadingMore}
                className="mt-3 inline-flex min-h-9 items-center rounded-lg border border-[#d7dfda] bg-white px-3 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              >
                {library.loadingMore ? "加载中…" : "加载更多照片"}
              </button>
            )}
          </>
        )}
      </fieldset>

      <label className="flex items-start gap-3 rounded-xl border border-[#dfe5e1] bg-[#fbfcfa] px-4 py-3">
        <input
          type="checkbox"
          checked={consent}
          onChange={(event) => onConsentChange(event.target.checked)}
          className="mt-0.5 size-4 accent-[#277a68]"
        />
        <span className="text-xs leading-relaxed text-[#55625b]">
          我确认这些照片仅用于本次个人风格分析，不用于模型训练，也不会自动公开。我可以随时移除参考照片或撤回授权。
        </span>
      </label>
    </div>
  );
}
