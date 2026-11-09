"use client";

import { useState } from "react";

import { ApiClientError } from "@/lib/api/client";
import { addPersonalStyleReferences } from "@/lib/api/personal-style";
import type { PersonalStyleReference } from "@/types/personal-style";

import { ReferenceSelection, type SelectedReference } from "./reference-selection";

export function AddReferencesSection({
  styleId,
  references,
  onAdded,
}: {
  styleId: string;
  references: PersonalStyleReference[];
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<SelectedReference[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const existingIds = new Set(
    references
      .map((reference) => reference.imageId)
      .filter((imageId): imageId is string => imageId !== null),
  );
  const canSubmit = selected.length > 0 && consent && !busy;

  async function handleAdd() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await addPersonalStyleReferences(
        styleId,
        selected.map((item) => item.id),
      );
      setSelected([]);
      setConsent(false);
      setOpen(false);
      onAdded();
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiClientError ? reason.message : "添加参考照片失败，请稍后重试。",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-[#dfe5e1] bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-[#202522]">添加参考照片</h2>
          <p className="mt-1 text-[11px] text-[#8a9690]">
            新增照片后重新分析，会生成新的风格版本；旧版本仍然保留。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#277a68] hover:bg-[#f4f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {open ? "收起" : "添加照片"}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-3 border-t border-[#eef1ef] pt-4">
          <ReferenceSelection
            selected={selected}
            onChange={setSelected}
            consent={consent}
            onConsentChange={setConsent}
            existingIds={existingIds}
          />
          {error !== null && (
            <div role="alert" className="rounded-xl border border-[#efc9c4] bg-[#fdf4f2] px-4 py-3 text-xs text-[#8a3a2e]">
              {error}
            </div>
          )}
          <div className="flex justify-end">
            <button
              type="button"
              disabled={!canSubmit}
              onClick={() => void handleAdd()}
              className="inline-flex min-h-10 items-center rounded-xl bg-[#277a68] px-4 text-xs font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "正在添加…" : "添加所选照片"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
