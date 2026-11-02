"use client";

import { useState } from "react";

import {
  DownloadIcon,
  FileIcon,
  ImageIcon,
  LockIcon,
  SparkleIcon,
  UploadCloudIcon,
} from "@/components/icons";
import { UploadDropzone } from "@/features/editor/upload-dropzone";
import { originalImageUrl } from "@/lib/api/client";
import { formatBytes, formatDimensions, formatImageFormat } from "@/lib/format";
import type { UploadedImage } from "@/types/image";

interface UploadResultProps {
  image: UploadedImage;
  uploading: boolean;
  onFileSelected: (file: File) => void;
}

export function UploadResult({ image, uploading, onFileSelected }: UploadResultProps) {
  const [previewFailed, setPreviewFailed] = useState(false);

  return (
    <div className="grid overflow-hidden rounded-2xl border border-white/8 lg:grid-cols-[minmax(0,1.6fr)_minmax(290px,0.9fr)]">
      <div className="preview-canvas p-3 sm:p-5">
        <div className="relative flex min-h-64 items-center justify-center overflow-hidden rounded-xl bg-black/35 ring-1 ring-white/8">
          {previewFailed ? (
            <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
              <ImageIcon className="size-8 text-white/25" />
              <p className="text-sm text-white/55">预览加载失败，但原图仍可下载。</p>
            </div>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- local originals are served by the API, not the image optimizer
            <img
              key={image.imageId}
              src={originalImageUrl(image.imageId)}
              alt={`原图预览：${image.originalName}`}
              className="max-h-[560px] w-full object-contain"
              onError={() => setPreviewFailed(true)}
            />
          )}
          <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-black/60 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/70 backdrop-blur-md">
            <LockIcon className="size-3" />
            原图 · 只读
          </span>
        </div>
        <p className="mt-3 flex items-center gap-2 px-1 text-[11px] text-white/35">
          <ImageIcon className="size-3.5" />
          以 API 原始字节预览；阶段 1 不修改任何像素
        </p>
      </div>

      <aside className="flex flex-col gap-6 border-t border-white/8 bg-white/[0.015] p-5 sm:p-6 lg:border-l lg:border-t-0">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-white/35">
            Selected original
          </p>
          <div className="mt-2 flex items-start gap-3">
            <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.04] text-white/55">
              <FileIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-medium text-white" title={image.originalName}>
                {image.originalName}
              </h2>
              <p className="mt-1 font-mono text-[10px] text-white/35">
                {image.imageId.slice(0, 8)}…{image.imageId.slice(-4)}
              </p>
            </div>
          </div>
        </div>

        <dl className="divide-y divide-white/6 rounded-xl border border-white/8 bg-black/20 px-4">
          <div className="flex items-center justify-between gap-4 py-3">
            <dt className="text-xs text-white/40">尺寸</dt>
            <dd className="font-mono text-xs text-white/80">{formatDimensions(image.width, image.height)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-3">
            <dt className="text-xs text-white/40">格式</dt>
            <dd className="font-mono text-xs text-white/80">{formatImageFormat(image.mimeType)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-3">
            <dt className="text-xs text-white/40">文件大小</dt>
            <dd className="font-mono text-xs text-white/80">{formatBytes(image.bytes)}</dd>
          </div>
        </dl>

        <div className="grid grid-cols-2 gap-2">
          <a
            href={originalImageUrl(image.imageId, true)}
            download={image.originalName}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2.5 text-xs font-semibold text-[#101208] transition-colors hover:bg-accent/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <DownloadIcon className="size-4" />
            下载原图
          </a>
          <a
            href={originalImageUrl(image.imageId)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-white/12 bg-white/[0.03] px-3 py-2.5 text-xs font-medium text-white/75 transition-colors hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            新窗口打开
          </a>
        </div>

        <UploadDropzone onFileSelected={onFileSelected} disabled={uploading} compact />

        <div className="mt-auto rounded-xl border border-white/8 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-2 text-xs font-medium text-white/70">
              <SparkleIcon className="size-4 text-accent" />
              下一步
            </span>
            <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-white/35">
              Phase 02
            </span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-white/40">
            图像特征分析、七种风格配方、手动参数与前后对比将从这里开始。
          </p>
          <p className="mt-3 flex items-center gap-1.5 text-[10px] text-white/30">
            <UploadCloudIcon className="size-3.5" />
            届时每次渲染都从这张原图重算
          </p>
        </div>
      </aside>
    </div>
  );
}
