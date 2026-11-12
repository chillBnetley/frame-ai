"use client";

import { useRef, useState, type DragEvent } from "react";

import { UploadCloudIcon } from "@/components/icons";
import { formatBytes } from "@/lib/format";
import { FILE_ACCEPT_ATTRIBUTE, MAX_UPLOAD_BYTES } from "@/lib/upload-validation";

interface UploadDropzoneProps {
  onFileSelected: (file: File) => void;
  disabled?: boolean;
  compact?: boolean;
  maxUploadBytes?: number;
}

export function UploadDropzone({
  onFileSelected,
  disabled = false,
  compact = false,
  maxUploadBytes = MAX_UPLOAD_BYTES,
}: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);

  function openPicker() {
    if (!disabled) {
      inputRef.current?.click();
    }
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (disabled) return;
    dragDepth.current += 1;
    setDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) {
      setDragging(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files.item(0);
    if (file) {
      onFileSelected(file);
    }
  }

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = disabled ? "none" : "copy";
      }}
      onDrop={handleDrop}
      data-testid="dropzone"
      className={[
        "rounded-2xl border border-dashed transition-colors duration-200",
        dragging
          ? "border-accent/70 bg-accent/[0.06]"
          : "border-white/12 bg-white/[0.02] hover:border-white/25 hover:bg-white/[0.035]",
        disabled ? "cursor-wait" : "",
      ].join(" ")}
    >
      <input
        ref={inputRef}
        type="file"
        accept={FILE_ACCEPT_ATTRIBUTE}
        aria-label="选择图片文件"
        className="sr-only"
        tabIndex={-1}
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.item(0);
          event.target.value = "";
          if (file) {
            onFileSelected(file);
          }
        }}
        data-testid="file-input"
      />

      {compact ? (
        <button
          type="button"
          onClick={openPicker}
          disabled={disabled}
          aria-busy={disabled}
          className="flex min-h-11 w-full items-center gap-3 rounded-2xl p-4 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait"
        >
          <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[0.04] text-accent">
            {disabled ? <Spinner /> : <UploadCloudIcon className="size-5" />}
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium text-white/85">
              {disabled ? "正在处理照片…" : "更换照片"}
            </span>
            <span className="mt-0.5 block text-xs text-white/40">
              拖入新文件，或点击选择
            </span>
          </span>
        </button>
      ) : (
        <button
          type="button"
          onClick={openPicker}
          disabled={disabled}
          aria-busy={disabled}
          className="flex min-h-72 w-full flex-col items-center justify-center gap-4 rounded-2xl px-6 py-10 text-center focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait sm:min-h-80"
        >
          <span className="relative grid size-16 place-items-center rounded-2xl border border-white/10 bg-white/[0.04] text-accent">
            {disabled ? <Spinner className="size-6" /> : <UploadCloudIcon className="size-7" />}
            {!disabled && (
              <span className="absolute -right-1 -top-1 size-2.5 rounded-full bg-accent shadow-[0_0_14px_var(--color-accent)]" />
            )}
          </span>
          <span className="space-y-1.5">
            <span className="block text-lg font-medium tracking-tight text-white">
              {disabled ? "正在校验并保存原图" : dragging ? "松开即可上传" : "拖入一张照片"}
            </span>
            <span className="block text-sm text-white/45">
              {disabled ? "请稍候，原图仅写入本机数据目录" : "或点击选择文件"}
            </span>
          </span>
          <span className="inline-flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-full border border-white/8 bg-black/20 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-white/35">
            <span>JPG/JPEG · PNG · WebP · TIFF</span>
            <span aria-hidden="true">/</span>
            <span>最大 {formatBytes(maxUploadBytes)}</span>
          </span>
        </button>
      )}
    </div>
  );
}

function Spinner({ className = "size-5" }: { className?: string }) {
  return (
    <span
      className={`${className} animate-spin rounded-full border-2 border-current border-r-transparent`}
      role="status"
      aria-label="加载中"
    />
  );
}
