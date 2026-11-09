"use client";

import Link from "next/link";

import { RefreshIcon, SparkleIcon, UploadCloudIcon } from "@/components/icons";
import { UploadDropzone } from "@/features/editor/upload-dropzone";
import { formatBytes } from "@/lib/format";
import { MAX_UPLOAD_BYTES } from "@/lib/upload-validation";

import {
  CONVERSION_MODE_LABELS,
  FIT_DIMENSION_LABELS,
  FIT_LEVEL_LABELS,
  STYLE_KIND_LABELS,
  sceneLabel,
} from "../../presentation";
import { MasterVisionNav } from "../master-vision-nav";
import { MasterVisionStatus } from "../status";
import { StyleVisual } from "../style-visual";
import { MasterVisionCompare } from "./compare-stage";
import { useMasterVisionWorkspace } from "./use-master-vision-workspace";

function stageLabel(stage: string | null): string {
  switch (stage) {
    case "queued":
      return "排队中";
    case "measurements":
      return "测量画面";
    case "vision":
      return "理解场景";
    case "decision":
      return "整理诊断";
    case "finalizing":
      return "生成报告";
    default:
      return "处理中";
  }
}

export function MasterVisionWorkspace({ initialStyleId }: { initialStyleId: string }) {
  const workspace = useMasterVisionWorkspace(initialStyleId);
  const {
    styles,
    stylesLoading,
    stylesError,
    styleId,
    style,
    detail,
    detailLoading,
    selectStyle,
    conversionModes,
    conversionModesError,
    uploading,
    uploadError,
    upload,
    analysis,
    fit,
    fitLoading,
    fitError,
    mode,
    setMode,
    strength,
    setStrength,
    plan,
    planLoading,
    planError,
    planStale,
    generate,
    originalUrl,
    resultUrl,
    renderLoading,
    renderError,
    retryRender,
    handleImageError,
    saveState,
    saveError,
    save,
  } = workspace;

  const analysisReady = analysis.report !== null;
  const busy =
    uploading ||
    analysis.running ||
    fitLoading ||
    planLoading ||
    renderLoading ||
    saveState === "saving";
  const modeInfo = conversionModes.find((item) => item.mode === mode) ?? null;
  const recommendedMode = fit?.recommendedMode ?? null;
  const generationDisabled =
    !analysisReady || planLoading || uploading || uploadError !== null;
  const saveDisabled = plan === null || planStale || saveState !== "idle";
  const masters = styles.filter((item) => item.kind === "master");
  const genres = styles.filter((item) => item.kind === "genre");

  const statusText = uploading
    ? "正在上传照片并建立编辑会话…"
    : analysis.running
      ? `正在分析照片（${stageLabel(analysis.stage)}）…`
      : fitLoading
        ? "正在评估照片与风格的适配度…"
        : planLoading
          ? "AI 正在根据这张照片制定后期方案…"
          : renderLoading
            ? "正在渲染真实预览…"
            : saveState === "saving"
              ? "正在保存 AI 创作版本…"
              : saveState === "saved"
                ? "已保存为 AI 创作版本。"
                : plan
                  ? "方案已就绪，可对比后应用。"
                  : analysisReady
                    ? "照片已理解，选择模式与强度后开始生成。"
                    : "上传照片后开始。";
  const statusTone =
    saveState === "saved" ? "success" : planError || renderError || fitError ? "error" : "info";

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8">
      <MasterVisionNav />

      <header className="mt-6 flex flex-wrap items-end justify-between gap-3 border-b border-[#e4e8e5] pb-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            STYLE WORKSPACE
          </p>
          <h1 className="mt-1.5 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521] sm:text-4xl">
            风格创作工作台
          </h1>
          <p className="mt-1.5 text-sm text-[#68746e]">
            先理解照片，再让 AI 决定风格如何落到这张画面上。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="rounded-full border border-[#dfe5e1] bg-white px-3 py-1.5 text-[#69716c]">
            {style ? `${STYLE_KIND_LABELS[style.kind]} · ${style.name}` : "未选择风格"}
          </span>
          {plan?.isMock && (
            <span className="rounded-full border border-[#ead9bd] bg-[#fdf8ee] px-3 py-1.5 text-[#7d6338]">
              模拟 Provider
            </span>
          )}
        </div>
      </header>

      <div className="mt-4">
        <MasterVisionStatus
          tone={statusTone}
          title={statusText}
          action={
            busy ? (
              <span className="inline-flex items-center gap-2 text-[11px] opacity-70">
                <span className="size-3 animate-spin rounded-full border-2 border-current border-r-transparent" />
                处理中
              </span>
            ) : undefined
          }
        >
          {analysis.error ? (
            <span>
              {analysis.error.message}{" "}
              <button
                type="button"
                onClick={analysis.retry}
                className="underline underline-offset-2"
              >
                重新分析
              </button>
            </span>
          ) : saveError ? (
            saveError
          ) : planError ? (
            planError
          ) : renderError ? (
            renderError
          ) : fitError ? (
            fitError
          ) : uploadError ? (
            uploadError
          ) : plan?.degraded ? (
            "模型输出不可用，已回退到确定性规则方案。"
          ) : null}
        </MasterVisionStatus>
        {busy && (
          <div
            role="progressbar"
            aria-label="任务进行中"
            aria-valuetext={statusText}
            className="mt-2 h-1 overflow-hidden rounded-full bg-[#e8eeea]"
          >
            <div className="h-full w-1/3 animate-pulse rounded-full bg-[#4c9b83]" />
          </div>
        )}
        {analysis.isMock && analysisReady && (
          <p className="mt-2 text-[10px] text-[#8a9690]">
            本页使用模拟分析数据；真实 Provider 可在模型设置中切换。
          </p>
        )}
      </div>

      {stylesError && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="风格库加载失败">
            {stylesError}
          </MasterVisionStatus>
        </div>
      )}
      {conversionModesError && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="转换模式加载失败">
            {conversionModesError}
          </MasterVisionStatus>
        </div>
      )}

      <div className="mt-5 grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_350px]">
        <aside className="order-1 space-y-4 xl:order-1">
          <section className="rounded-2xl border border-[#dfe5e1] bg-white p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-xs font-semibold text-[#40544a]">照片</h2>
              {originalUrl && (
                <span className="font-mono text-[9px] text-[#9aa5a0]">
                  {workspace.imageId?.slice(0, 8)}
                </span>
              )}
            </div>
            <div className="mt-3">
              {originalUrl ? (
                // eslint-disable-next-line @next/next/no-img-element -- content-addressed previews are served by the API
                <img
                  src={originalUrl}
                  alt="当前照片"
                  className="aspect-[4/3] w-full rounded-xl border border-[#e4e8e5] object-contain"
                />
              ) : (
                <div className="grid aspect-[4/3] place-items-center rounded-xl border border-dashed border-[#d9e2dd] bg-[#f8faf8] text-center">
                  <span className="px-4 text-xs text-[#8a9690]">
                    {uploading ? "正在上传…" : "尚未选择照片"}
                  </span>
                </div>
              )}
            </div>
            <div className="mt-3">
              <UploadDropzone onFileSelected={(file) => void upload(file)} disabled={uploading} compact />
              <p className="mt-2 text-[10px] leading-relaxed text-[#98a39e]">
                支持 JPEG / PNG / WebP / TIFF，最大 {formatBytes(MAX_UPLOAD_BYTES)}。原图始终保留。
              </p>
            </div>
          </section>

          <section className="rounded-2xl border border-[#dfe5e1] bg-white p-4">
            <h2 className="text-xs font-semibold text-[#40544a]">选择风格</h2>
            {stylesLoading ? (
              <div className="mt-3 h-11 animate-pulse rounded-xl bg-[#f0f3f1]" />
            ) : (
              <select
                aria-label="选择大师或流派风格"
                value={styleId}
                onChange={(event) => selectStyle(event.target.value)}
                className="mt-3 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3 text-xs text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
              >
                <optgroup label="大师风格">
                  {masters.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="摄影流派">
                  {genres.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </optgroup>
              </select>
            )}

            {style && (
              <div className="mt-3 overflow-hidden rounded-xl border border-[#e4e8e5]">
                <StyleVisual styleId={style.id} kind={style.kind} className="aspect-[16/9]" />
                <div className="space-y-2 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-semibold text-[#35473e]">{style.name}</p>
                    <span className="shrink-0 text-[9px] text-[#98a39e]">v{style.version}</span>
                  </div>
                  <p className="line-clamp-3 text-[11px] leading-relaxed text-[#7a8680]">
                    {detail?.style.philosophy ?? style.description}
                  </p>
                  <p className="text-[10px] text-[#8a9690]">
                    适合：{style.suitableScenes.map(sceneLabel).join(" · ")}
                  </p>
                  <Link
                    href={`/master-vision/styles/${encodeURIComponent(style.id)}`}
                    className="inline-flex text-[11px] font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    查看完整档案
                  </Link>
                </div>
              </div>
            )}
            {detailLoading && <p className="mt-2 text-[10px] text-[#98a39e]">正在读取档案…</p>}
          </section>
        </aside>

        <section className="order-2 min-w-0 xl:order-2">
          <div className="rounded-2xl border border-[#dfe5e1] bg-white p-4 sm:p-5">
            <MasterVisionCompare
              originalUrl={originalUrl}
              resultUrl={resultUrl}
              loading={renderLoading}
              error={renderError}
              hint={
                plan
                  ? `已按 ${CONVERSION_MODE_LABELS[mode]} · 强度 ${strength} 渲染。${
                      planStale ? "当前参数已变化，请重新生成后再应用。" : ""
                    }`
                  : undefined
              }
              onRetry={() => void retryRender()}
              onImageError={handleImageError}
            />
          </div>
          {analysisReady && !plan && !planLoading && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-[#e4e8e5] bg-white px-4 py-3 text-[11px] text-[#7a8680]">
              <SparkleIcon className="size-4 shrink-0 text-[#277a68]" />
              分析已完成。检查右侧适配度与模式，然后点击“生成风格方案”。
            </div>
          )}
          {plan && plan.changes.length > 0 && (
            <div className="mt-3 rounded-xl border border-[#e4e8e5] bg-white p-4">
              <h3 className="text-xs font-semibold text-[#40544a]">本方案改动</h3>
              <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
                {plan.changes.slice(0, 8).map((change) => (
                  <li key={change.path} className="truncate text-[10px] text-[#7a8680]">
                    <span className="font-mono text-[#50625a]">{change.path}</span>{" "}
                    {String(change.previous)} → {String(change.proposed)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <aside className="order-3 space-y-4">
          <section className="rounded-2xl border border-[#dfe5e1] bg-white p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-[#40544a]">适配度分析</h2>
              {fit?.isMock && <span className="text-[9px] text-[#98a39e]">模拟</span>}
            </div>
            {fitLoading ? (
              <p className="mt-4 animate-pulse text-xs text-[#98a39e]">正在评估…</p>
            ) : fit ? (
              <div className="mt-3 space-y-3">
                <div className="flex items-end gap-2">
                  <span className="font-mono text-3xl font-semibold tracking-[-0.05em] text-[#1d2521]">
                    {Math.round(fit.overallScore)}
                  </span>
                  <span className="mb-1 text-[11px] text-[#8a9690]">/ 100 · {FIT_LEVEL_LABELS[fit.overallLevel]}</span>
                </div>
                <p className="text-[11px] leading-relaxed text-[#66716b]">{fit.summary}</p>
                <ul className="space-y-1.5">
                  {fit.dimensions.map((dimension) => (
                    <li key={dimension.dimension} className="grid grid-cols-[3.25rem_1fr_2.5rem] items-center gap-2">
                      <span className="text-[10px] text-[#7a8680]">
                        {FIT_DIMENSION_LABELS[dimension.dimension]}
                      </span>
                      <span className="h-1.5 overflow-hidden rounded-full bg-[#eef1ef]">
                        <span
                          className="block h-full rounded-full bg-[#5c9a84]"
                          style={{ width: `${Math.max(0, Math.min(100, dimension.score))}%` }}
                        />
                      </span>
                      <span className="text-right font-mono text-[9px] text-[#98a39e]">
                        {Math.round(dimension.score)}
                      </span>
                    </li>
                  ))}
                </ul>
                {fit.conflicts.length > 0 && (
                  <div className="rounded-xl border border-[#eadfd6] bg-[#fdf9f6] p-2.5">
                    <p className="text-[10px] font-medium text-[#6b4d3a]">需要注意</p>
                    <ul className="mt-1 space-y-1">
                      {fit.conflicts.slice(0, 3).map((conflict) => (
                        <li key={conflict.description} className="text-[10px] leading-relaxed text-[#7a6254]">
                          {conflict.description}
                          {!conflict.improvable && "（拍摄条件限制）"}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {fit.alternatives.length > 0 && (
                  <div>
                    <p className="text-[10px] font-medium text-[#7a8680]">更合适的风格</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {fit.alternatives.slice(0, 3).map((alternative) => (
                        <button
                          key={alternative.styleId}
                          type="button"
                          onClick={() => selectStyle(alternative.styleId)}
                          className="rounded-full border border-[#dfe5e1] bg-white px-2.5 py-1 text-[10px] text-[#5f6d66] hover:bg-[#f5f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                          title={alternative.reason}
                        >
                          {alternative.name} · {Math.round(alternative.score)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="mt-4 text-[11px] leading-relaxed text-[#8a9690]">
                {analysisReady ? "当前风格暂未完成适配评估。" : "上传并分析照片后显示照片级适配度。"}
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-[#dfe5e1] bg-white p-4">
            <h2 className="text-xs font-semibold text-[#40544a]">创作控制</h2>
            <fieldset className="mt-3">
              <legend className="text-[10px] text-[#7a8680]">转换模式</legend>
              <div className="mt-1.5 grid grid-cols-3 gap-1">
                {(["natural", "style", "creative"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={mode === value}
                    onClick={() => setMode(value)}
                    className="relative min-h-9 rounded-lg border border-[#dfe5e1] bg-white px-1 text-[10px] text-[#5f6d66] transition-colors hover:bg-[#f5f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#9dbdaf] aria-pressed:bg-[#eaf3ef] aria-pressed:text-[#1f6a5a]"
                  >
                    {CONVERSION_MODE_LABELS[value].split(" ")[0]}
                    {recommendedMode === value && (
                      <span className="absolute -right-1 -top-1 size-2 rounded-full bg-[#e0a34a]" title="推荐模式" />
                    )}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[10px] leading-relaxed text-[#8a9690]">
                {modeInfo?.description ?? "转换模式会约束风格强度与允许的调整方向。"}
              </p>
              {modeInfo && (
                <p className="mt-1 text-[9px] text-[#9aa5a0]">
                  推荐强度 {Math.round(modeInfo.recommendedStrengthMin * 100)}–
                  {Math.round(modeInfo.recommendedStrengthMax * 100)}
                </p>
              )}
            </fieldset>
            <div className="mt-3">
              <div className="flex items-center justify-between text-[10px] text-[#7a8680]">
                <label htmlFor="style-strength">风格强度</label>
                <span className="font-mono text-[#40544a]">{strength}</span>
              </div>
              <input
                id="style-strength"
                type="range"
                min={0}
                max={100}
                step={1}
                value={strength}
                onChange={(event) => setStrength(Number(event.target.value))}
                className="mt-1.5 w-full accent-[#277a68]"
              />
              {fit && (
                <p className="text-[9px] text-[#9aa5a0]">
                  启发式推荐 {Math.round(fit.recommendedStrength.minimum * 100)}–
                  {Math.round(fit.recommendedStrength.maximum * 100)}
                </p>
              )}
            </div>
            {planStale && (
              <p className="mt-3 rounded-lg border border-[#ead9bd] bg-[#fdf8ee] px-2.5 py-2 text-[10px] text-[#7d6338]">
                模式或强度已改变，请重新生成方案后再应用。
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-[#dfe5e1] bg-white p-4">
            <h2 className="text-xs font-semibold text-[#40544a]">AI 创作说明</h2>
            {plan ? (
              <div className="mt-3 space-y-2">
                <p className="text-[11px] leading-relaxed text-[#4f5f57]">{plan.direction.description}</p>
                <ul className="space-y-1.5">
                  {Array.from(new Set(plan.changes.map((change) => change.reason)))
                    .slice(0, 5)
                    .map((item) => (
                      <li key={item} className="text-[10px] leading-relaxed text-[#7a8680]">
                        · {item}
                      </li>
                    ))}
                </ul>
                {plan.warnings.length > 0 && (
                  <div className="rounded-lg bg-[#fbf7ee] px-2.5 py-2">
                    {plan.warnings.slice(0, 3).map((item) => (
                      <p key={item} className="text-[10px] leading-relaxed text-[#7d6338]">
                        {item}
                      </p>
                    ))}
                  </div>
                )}
                {plan.limitations.length > 0 && (
                  <div className="rounded-lg bg-[#f7f9f8] px-2.5 py-2">
                    {plan.limitations.slice(0, 3).map((item) => (
                      <p key={item} className="text-[10px] leading-relaxed text-[#7a8680]">
                        {item}
                      </p>
                    ))}
                  </div>
                )}
                <p className="font-mono text-[9px] text-[#9aa5a0]">
                  {plan.provider.name} / {plan.provider.model} · {plan.provider.promptVersion}
                </p>
              </div>
            ) : (
              <p className="mt-3 text-[11px] leading-relaxed text-[#8a9690]">
                生成后，这里会说明 AI 为什么这样处理这张照片。
              </p>
            )}
          </section>

          <div className="space-y-2 rounded-2xl border border-[#d7dfda] bg-[rgba(255,255,255,0.95)] p-3 shadow-[0_18px_44px_-30px_rgba(25,48,38,.5)]">
            <button
              type="button"
              onClick={() => void generate()}
              disabled={generationDisabled}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#277a68] px-4 text-sm font-medium text-[#f7faf8] transition-colors hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-[#a8bdb4]"
            >
              {planLoading ? (
                <>
                  <span className="size-4 animate-spin rounded-full border-2 border-[#f7faf8] border-r-transparent" />
                  生成中…
                </>
              ) : (
                <>
                  <SparkleIcon className="size-4" />
                  {plan ? "重新生成" : "生成风格方案"}
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saveDisabled}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-[#c9d8d0] bg-[#f4f9f6] px-4 text-sm font-medium text-[#1f6a5a] transition-colors hover:bg-[#eaf3ef] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-45"
            >
              {saveState === "saving" ? (
                <>
                  <span className="size-4 animate-spin rounded-full border-2 border-[#1f6a5a] border-r-transparent" />
                  保存中…
                </>
              ) : saveState === "saved" ? (
                "已保存为 AI 创作"
              ) : (
                <>
                  <UploadCloudIcon className="size-4 rotate-180" />
                  应用并保存
                </>
              )}
            </button>
            <div className="flex items-center justify-between gap-2 text-[9px] text-[#9aa5a0]">
              <span>{analysis.report ? sceneLabel(analysis.report.scene.primary) : "等待分析"}</span>
              {plan && (
                <span>
                  {plan.changes.length} 项改动 · {CONVERSION_MODE_LABELS[plan.conversionMode ?? mode].split(" ")[0]}
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <RefreshIcon className="size-3" />
                {plan ? "可重新生成" : "参数可调"}
              </span>
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
