# ADR-0004：色彩管理策略与依赖边界

- 状态：已接受并实现（2026-11-04，阶段四 Task 7）；2026-11-07 B5a 追加 D8（8-bit alpha 保留）；同日 B5b 追加 D9（16-bit 输入/输出与矩阵/TRC ICC）
- 适用：`services/api/app/imaging/loader.py`、`icc.py`、`geometry.py`、`pipeline.py`、`output.py`、`params_map.py`、`services/api/app/services/export_service.py` 及所有渲染/导出/预览路径
- 相关文档：[色彩管理](../color-management.md)、[架构](../architecture.md)、[API 契约](../api-contract.md)、[已知问题](../known-issues.md)、[ADR-0002](ADR-0002-phase-2-decisions.md)、[实施计划](../plans/phase-4-task-7-color-management.md)、[设计限制整改执行计划](../plans/design-limitations-remediation-execution-plan.md)
- 本文 D1–D7 数值均为 2026-11-04 本机项目 venv 实测（Pillow 12.3.0 / OpenCV 4.14.0 headless / NumPy 2.5.4 / Python 3.14.7），不含估计值；D8 为 2026-11-07 B5a 的实现记录，D9 为同日 B5b 的实现与实测记录

## 背景

阶段四任务书 Task 7 要求核对 8 项：EXIF 方向、ICC Profile、输入格式、输入色彩空间、输入位深、工作色彩空间、输出色彩空间、配置文件嵌入，并明确要求"不能无条件把所有输入当作同一色彩空间""评估是否有不必要的位深降低""避免过早转成低精度""先独立验证再决定是否引入依赖"。

阶段 2.1 的 F2-02 已经把嵌入 ICC 转换落地并配了测试，所以本任务的性质是**核对 + 补缺口 + 文档化 + 依赖评估**，不是重写管线。核对发现：8 项里 6 项已满足，真正的缺口只有一个——ICC 管理发生在模式归一**之前**，因此 `_apply_embedded_profile` 的 `image.mode not in {"RGB", "RGBA"}` 早退条件把 `P`/`PA`/`1`/`L`/`LA` 全部排除在外。实测：带 Display-P3 配置的调色板图 `(204,51,51)` 被按 sRGB 直接读出，正确转换应为 `(224,14,36)`，**色差 37 级**——这是"把所有输入无条件当作同一色彩空间"的字面实例。

同时，`docs/known-issues.md` 与 `README.md` 把若干**刻意的取舍**（8-bit 代理、16-bit RGB 解码降位、去噪强制 uint8）与**真实的限制**混在一起描述，没有人给出实测证据说明这些取舍是否可接受。

## 决策

### D1 输入色彩空间写成显式默认策略，而不是隐含行为

三条规则，全部进文档 + 全部有测试：

1. 有嵌入配置且设备空间为 RGB → 转 sRGB（`RELATIVE_COLORIMETRIC` + `BLACKPOINTCOMPENSATION`，保持现状参数）；配置本身已是 sRGB 则跳过。
2. 有嵌入配置但设备空间非 RGB（灰度 / CMYK / Lab），或配置为空 / 垃圾 / 截断 → **回退按 sRGB 解释**，不抛错。
3. 无嵌入配置 → **按 sRGB 解释**（与浏览器和大多数相机/手机的缺省一致）。

不引入色域标记字段、不改数据库、不给 API 增加"是否检测到 ICC"之类的新响应字段；观测性另议。

**理由**：任务书要求"无 ICC 的图片必须有明确的默认策略"，隐含行为无法被后续任务守卫。选择回退而不是报错，保证配置损坏的图片仍能出图。

### D2 把 ICC 管理移到模式归一之后（本任务唯一像素行为变更，已获确认）

**做法**：`load_image` 不再在 `exif_transpose` 之后单独调用 `_apply_embedded_profile`；改为在 `_to_float_rgb` 内部、模式归一形成 RGB/RGBA 之后调用。`_apply_embedded_profile` 自身逻辑（非 RGB 设备空间跳过、sRGB 跳过、异常回退、RGBA 补 alpha）不变。

**为什么这是纯顺序调整**：实测确认 Pillow 的 `convert("RGB")` / `convert("RGBA")` 会原样保留 `info["icc_profile"]` 字节（`P`/`1`/`L` 三种模式均验证）。因此 `RGB`/`RGBA` 输入路径上的调用结果与改动前完全一致。

**保留的顺序差异**：`RGBA`/`LA`/带 `transparency` 的输入仍在**合成白底之前**转换配置，因此 `RGB` 与不透明 `RGBA` 同像素的结果仍然一致（`test_opaque_rgba_matches_the_same_pixels_as_rgb`）。

**影响面**：仅携带有效 RGB 嵌入配置的非 RGB 模式输入。`I;16*`/`I`/`F` 分支原样（没有 RGB 通道可管理）；`CMYK` 分支原样（`_cmyk_to_rgb` 已带配置优先路径）。

**验证**：重跑 `scripts/generate_golden.py` 后，`tests/golden/` 下全部 30 个 PNG（源图与期望输出）**逐字节不变**，只有 `manifest.json` 的 `engineVersion` 更新。这直接证明影响面判断正确——无配置输入与 RGB/RGBA 输入的输出零变化。

**备选方案（未采纳）**：只把缺口写进 `docs/known-issues.md` 并加一条锁定现状的测试。用户明确要求"先修缺口，再往下执行任务"，故执行修复。

### D3 位深：原“16-bit RGB 解码降位”结论已被 D9 取代

- 2026-11-04 的实测事实仍然成立：Pillow 没有 16-bit RGB 模式，直接 `Image.open(...).load()` 会把 16-bit RGB 截断到 8-bit（实测最大偏差 0.72 级）。当时因此把“不支持 16-bit RGB”记为限制。
- B5b（D9）改变的是**取像素的路径**，不是 Pillow 的行为：16-bit PNG 用 OpenCV、16-bit TIFF 用 tifffile 解码，Pillow 只读 ICC/EXIF/方向。因此 16-bit RGB 输入现以 `bit_depth=16`、float32 进入管线，不再降位；旧的“截断期望”测试已改写为保真断言。
- 16-bit **灰度**（`I;16*`/`I`）仍按 `/65535` 归一直接进 float32，不经过 8-bit 中间步骤（实测误差 ≤1e-6）。
- 8-bit 预览代理仍是**刻意取舍**：源可 8-bit 表示时代理逐值相同；在强配方（+0.7 EV、对比 40、5 点 S 形主曲线）下 float 源与 8-bit 源渲染差 **max 4 级 / mean 0.33 级**，且输出不同级数 **112 vs 112** 未减少——强曲线会放大约 1 级输入误差到 ≤4 级，但不产生色带。**因此预览/代理仍不升级为 16-bit**，16-bit 只发生在导出；16-bit 源使用带 `|b16` 的独立代理键（D9）。

### D4 工作空间与"过早低精度转换"用可维护性测试守卫

- 工作空间是 float32 `[0,1]` sRGB 编码值，`to_uint8`/`to_uint16` 只在管线末端一次；`srgb_to_linear` ↔ `linear_to_srgb` 全 256 级往返最大偏差 **1.5e-5 级**，无可测损失。
- 唯一的强制降位站点是 OpenCV NL-means 去噪（库限制）：`denoise(float)` 与 `denoise(已量化)` 差 **max 0.00 / mean 0.000 级**，量化幂等，不引入额外损失。
- 处理方式：把"渲染阶段模块不出现中间量化"写成测试（`test_render_stages_keep_float32`，扫描 `pipeline/tone/color_ops/curves/hsl/color_grading/local/local_masks/geometry` 九个模块）；`app/imaging` 内允许 `astype(np.uint8)` 的站点固定为 4 处并各自注明理由——`output.py`（末端量化）、`detail.py`（OpenCV 去噪只收 8-bit）、`loader.py`（8-bit 代理，D3 取舍）、`analyzer.py`（仅分析用边缘检测，不在渲染路径）。新增站点必须显式改白名单。

### D5 输出策略：sRGB 固定，位深 8/16 由请求选择（B5b 扩展）

- 所有输出（预览 JPEG、对比图、导出 JPEG/PNG/TIFF）目标空间恒为 sRGB、嵌入固定 sRGB ICC、剥离全部元数据。ICC 头部创建时间 pin 死，保证跨进程逐字节一致。
- 导出位深为 8 或 16（PNG/TIFF），JPEG 固定 8；预览与对比图始终 8-bit。16-bit 量化在管线末端一次完成，编码容器见 D9。
- 本任务只补**预览侧**的直接断言（此前只有单元侧与导出侧覆盖）：`tests/test_previews_api.py::test_preview_jpeg_embeds_srgb_profile_and_carries_no_metadata`。
- `output.colorSpace` 是 `Literal["sRGB"]`，不参与导出决策；导出尺寸/并发/作业化属于后续 Task 8（`docs/plans/phase-4-task-8-preview-export-performance.md`）。
- 同步核对（只读）：`GET /api/v1/images/{id}/original` 用 `FileResponse` 返回上传时保存的原始字节，保留原 ICC 与原 EXIF/GPS；导出与预览才是"重编码 + 剥离元数据 + 嵌入 sRGB"。

### D6 依赖评估：8-bit 路径不新增依赖（B5b 追加 tifffile，见 D9）

任务书要求"评估 Pillow/OpenCV 在高位深、ICC 管理、RAW 解码、大图、高精度转换上的边界，先独立验证再决定引入"。验证过程与结果：

| 能力 | 独立验证方式 | 结果 |
| --- | --- | --- |
| 高位深 RGB | 用 OpenCV 写 16-bit RGB PNG，再用 Pillow 打开 | `mode == "RGB"`（Pillow 无 16-bit RGB 模式），偏差 ≤0.72 级 → 需自写解码或新依赖 |
| ICC 管理 | `hasattr(cv2, "iccread")`；用 `cv2.imread` 读 P3 标记 PNG | `False`；返回原始像素 `(200,30,30)` 不转换 → ICC 必须留在 Pillow/lcms 侧，现有分工正确 |
| RAW 解码 | `import rawpy` | 失败（未安装）；任务书已豁免 RAW → 不引入 |
| 大图 | 触发 `Image.DecompressionBombWarning` | loader 已转成 413；`max_image_pixels=40_000_000` + 代理缓存覆盖 → 无需新依赖 |
| 高精度转换 | 8-bit 输入下 `ImageCms` 输出模式 | 仍为 8-bit，无浮点中转 API → 需 `colorio` 一类依赖，超范围 |
| 其他容器 | `import pillow_heif`；TIFF 经 `load_image` | HEIF 失败（未安装）；TIFF 可解码但入口闸门不暴露 |

结论（2026-11-04）：现有栈（Pillow + lcms2 + OpenCV + NumPy float32）满足当时全部已承诺行为；需要新依赖的项要么被任务书豁免（RAW），要么是明确不支持（高位深管线）。**未引入 `rawpy`、`pillow-heif`、`colorio` 或任何 lcms 绑定类依赖**，符合"不得一次性引入大量依赖"。

B5b 按已确认决策只追加 **`tifffile==2026.3.3`（BSD-3-Clause）**，用于 16-bit TIFF 输入读取与输出写入（含 ICC tag 34675）；**未引入 `imagecodecs`**，因此 LZW/JPEG 压缩 TIFF 被入口闸门显式拒绝。OpenCV 已是既有依赖，其 `IMREAD_UNCHANGED` 用于 16-bit PNG 像素；NumPy 已用于工作空间，矩阵/TRC ICC 没有新增依赖。

### D7 预览与导出共用同一管线，作为不变量守卫

现状已成立：两者都走 `render_image` → `render()`，差异只在 `quality` / `max_edge` / 是否使用代理。本任务把它写成不变量并记录在 `docs/color-management.md` §4，确保 D2 这类输入侧改动不会只覆盖一侧。

### D8 8-bit alpha 保留（B5a，2026-11-07）

关闭 `docs/known-issues.md` 的"导出 PNG 没有 alpha 通道"。范围严格限定在 8-bit 默认路径；16-bit、`bitDepth` 与 TIFF 属于 B5b，本次未做。

- **loader**：`LoadedImage` 增加可选 `alpha`（float32 `[0,1]`）与 `has_alpha`。`load_image(..., preserve_alpha=True)` 为默认，`RGBA`/`LA`/带 `transparency` 的 `P` 走 `_to_float_rgba`：`convert("RGBA")` → 既有 `_apply_embedded_profile`（ICC 行为不变）→ 拆 RGB 与 alpha，**不再先合成白底**。`preserve_alpha=False` 保留原白底合成路径。
- **消费方**：预览、代理（含缓存未命中写代理）、AI 分析显式传 `preserve_alpha=False`。因此代理仍是 RGB PNG、`PROXY_VERSION` 仍是 `loader/3`，历史代理与预览缓存继续命中；D1=A 的"预览保持白底"决策不变。分析沿用既有 `ALPHA_LIMITATION`。
- **几何**：新增 `apply_geometry(rgb, alpha, ...) -> (rgb, alpha)` 与 `resize_exact_alpha`。旋转/裁切/缩放对 RGB 与 alpha 使用同一矩阵与目标尺寸；缩放与旋转在预乘空间进行再反预乘，避免透明区域颜色渗入边缘；alpha≈0 处 RGB 统一置 0（确定性，有测试）；alpha 旋转边界为常量 0（透明），RGB 无 alpha 路径仍用 `BORDER_REFLECT_101`。原 RGB-only `rotate_inscribed` / `crop_pixels` / `resize_exact` 签名保留。
- **管线**：调色/曲线/HSL/局部/清晰度/细节只处理 RGB，alpha 原样透传；`RenderedImage` 增加 `alpha: uint8 | None` 与 `bit_depth: Literal[8,16] = 8`（B5b 复用，当前恒 8）。alpha 量化放在 `output.to_uint8_alpha`，避免在渲染阶段模块引入 `astype(np.uint8)`，既有量化白名单测试不需要放宽。
- **输出**：`encode_image(..., alpha=None, bit_depth=8)`。PNG + alpha 写 RGBA 并嵌入同一份 pinned sRGB ICC；JPEG + alpha 用 `round(rgb*a + 255*(1-a))` 确定性合成白底；无 alpha 的路径输出字节不变；alpha 形状/dtype 不符抛 `ValueError`；`bit_depth=16` 抛 `ValueError("16-bit output is not enabled yet")`。
- **导出**：`export_service` 全程携带 alpha（源缩放与画布收敛都用 `resize_exact_alpha`），不再用 `LoadedImage(rgb=...)` 丢弃 alpha；PNG 传 alpha，JPEG 由编码器合成。同步与异步作业共用 `_render` 路径。内存准入对 PNG/WebP 输入加 `EXPORT_BYTES_PER_PIXEL_ALPHA = 4` B/px（解码与渲染各一条 float32 覆盖平面），JPEG 输入阈值不变；用 mime 判断而非头部探测，保守覆盖调色板/colour-key 透明。
- **版本与缓存**：**不提升** `ENGINE_VERSION`（保持 `frame-engine/10`）与 `PROXY_VERSION`（`loader/3`）。缓存覆盖的预览/代理路径输出逐字节不变，alpha 只影响导出结果且导出不进入持久缓存；提升版本会无差别清空历史缓存而无像素收益。这是对 ADR-0002 "像素变化即提升"规则的有意收窄，理由记录在此与 `docs/color-management.md` §8。
- **验证**：新增 9 张 alpha 黄金图（1 张 RGBA 源图 × 9 个配方）与对应源图 `sources/alpha.png`，原有 30 张 PNG 重生成后逐字节不变；loader/geometry/pipeline/output/export API/异步作业各有定向测试；E2E 用真实透明 PNG 走 UI 导出 PNG 断言 RGBA 与透明度分布、再导出 JPEG 断言白底。

### D9 16-bit 输入/输出与矩阵/TRC ICC（B5b，2026-11-07）

关闭 `docs/known-issues.md` 的 L10（16-bit RGB 降位）与“16-bit 输出未启用”。范围：16-bit RGB PNG/TIFF 输入、16-bit PNG/TIFF 导出；8-bit 默认路径的像素与编码字节不变。

- **解码**：PNG 用 `cv2.imdecode(..., IMREAD_UNCHANGED)`（IHDR 位深 24/25），TIFF 用 `tifffile.imread`；uint16 BGR(A) → RGB(A) → `/65535` float32。Pillow 只读 ICC/EXIF 与方向标签，方向 1–8 由 NumPy 逆变换烘焙（有逐方向测试）。TIFF 只接受单页、压缩值 1/8/32946；LZW/JPEG → 415 `unsupported_tiff_compression`，多页 → 415 `tiff_multipage_not_supported`。20 MiB 上传上限不变，大 TIFF 需无损压缩（文档说明）。
- **ICC**：`app/imaging/icc.py` 用纯 NumPy 解析 `rXYZ/gXYZ/bXYZ` 与 `rTRC/gTRC/bTRC`（`curv`、`para` 类型 0–4），经 D50 PCS 转到 sRGB；float32、256 行分块，避免整图临时数组。sRGB 或未标记输入走快速路径。LUT 类（`mft1/mft2/mAB/mBA`）与 ICC v4 结构化 LUT（`D2B*`/`B2D*`）、非 RGB/XYZ 设备空间、越界/截断配置抛 `UnsupportedProfileError` → 422 `unsupported_icc_profile`，**不静默降级**；解析器对 tag 数量/偏移/长度做上界检查。8-bit 路径继续 Pillow/ImageCms。**sRGB 恒等捷径的界**：元素级矩阵/TRC 容差只作预筛，最终还要求合成变换在 17³ RGB 采样上与恒等输出相差 ≤1 个 8-bit 级（lcms sRGB 实测 0.64 级；旧容差下最坏对抗矩阵约 16 级，现转为真实转换而非报错）。**associated（预乘）alpha**：TIFF tag 338 含 1 时返回 415 `associated_alpha_not_supported`，只接受 unassociated alpha。**16-bit CMYK TIFF**：`mode` 为 CMYK，不进入 16-bit RGB 解码路径，回退到 8-bit Pillow/lcms 组合并沿用 CMYK 配置的既有回退限制（不保留 16-bit 精度）。
- **精度验证**：16-bit AdobeRGB-like 渐变（`curv`/`para`）全图 62,946 个不同级、可被 257 整除 0.84%、相邻行最大台阶 2；同一渐变强制 8-bit 中间步骤只剩 245 级、100% 为 257 倍数、最大台阶 514。与 lcms 8-bit 参考在 AdobeRGB-like（curv/para）与 Display P3-like 配置上差 ≤1 级。
- **管线**：`render(bit_depth=16)` 全程 float32，只在末端量化；16-bit + `denoise>0` 跳过降噪并返回 `denoise_skipped_for_16bit`，不生成 8-bit 中间；alpha 以 float32 透传。
- **输出**：`to_uint16`/`to_uint16_alpha`；16-bit PNG 用 OpenCV 写 BGR/BGRA，IHDR 位深 16，并在 IHDR 后手工插入 pinned sRGB `iCCP`；16-bit TIFF 用 tifffile Deflate、`iccprofile=`（tag 34675）、`extrasamples=["unassalpha"]`，关闭 software/datetime 元数据；同一输入重复编码逐字节一致。JPEG + 16 在请求模型校验阶段返回 422 `validation_error`，作业不会创建；服务层另保留 `unsupported_bit_depth` 保护。
- **API/前端**：`bitDepth: 8|16 = 8` 贯穿同步导出、异步作业响应与 `X-Export-Bit-Depth`；`format` 增加 `tiff`。前端提供 JPEG/PNG/TIFF 与 8/16 位选择器，JPEG 锁定 8-bit；契约 `openapi.json`/`api.d.ts` 已重新生成。
- **预览/代理**：预览与代理恒为 8-bit RGB；`PROXY_VERSION` 保持 `loader/3`，8-bit 源键 `sha256|loader/3|edge` 不变，仅 16-bit 源追加 `|b16`，避免复用旧截断代理。
- **内存**：`estimate_export_peak_mb` 对 16-bit 源与输出各加 18 B/px（解码 uint16 + float32 转换；输出 uint16 + 编码器工作副本）。24/40 MP 实测：满配方 16-bit 峰值 2801/4616 MB，与同配方 8-bit 的 2801/4617 MB 基本相同（渲染阶段主导）；中性 16-bit 比 8-bit 高 60/109 MB。36 B/px 附加项明显保守，无需调低。详见 `docs/performance.md`。
- **偏差**：16-bit 预览/代理未做；降噪在 16-bit 导出跳过而非升级为 16-bit 实现；ICC 只支持矩阵/TRC，LUT 配置 fail-closed；TIFF 不支持 LZW/JPEG 与多页；未引入 `imagecodecs`。这些都写入 `docs/color-management.md` §7 与 `docs/known-issues.md`。
- **版本**：不提升 `ENGINE_VERSION`（`frame-engine/10`）或 `PROXY_VERSION`（`loader/3`）；8-bit 输出字节由 `test_explicit_8_bit_matches_the_default_export_bytes` 逐字节守卫。

## 后果

- `ENGINE_VERSION` 在阶段四 Task 7 升 `frame-engine/7 → frame-engine/8`，`PROXY_VERSION` 升 `loader/2 → loader/3`。按 ADR-0002 的规则，像素行为变化必须提升引擎版本并重新生成黄金图；后续 `frame-engine/9`、`frame-engine/10` 继续按该规则提升。B5a/B5b 的例外与理由见 D8/D9。
- **全部历史预览磁盘缓存与代理缓存自动失效**（阶段四 Task 7 的版本提升）：用户再次打开历史会话时首次渲染需要重建。已保存的配方、revision 历史与原图字节不受影响，不需要迁移。
- `docs/known-issues.md` 的"P/1-bit 输入的配置暂不转换"一条关闭；B5a 关闭"导出 PNG 没有 alpha 通道"，B5b 关闭 L10（16-bit RGB 解码降位）与"16-bit 输出未启用"。保留灰度设备空间配置、CMYK 配置两条 8-bit 真实限制，并新增"16-bit 预览/代理仍 8-bit""16-bit LUT ICC fail-closed""压缩/多页 TIFF 不受支持"三条明确边界。
- 新增 `docs/color-management.md` 作为色彩策略权威文档；B5b 新增 `tests/icc_support.py` 构造器与 `tests/test_color_management.py` 的 16-bit/ICC 用例，E2E 增加真实 16-bit PNG 导出。
- 历史测试计数（阶段四 Task 7）：后端从 781 + 1 skipped 增至 810 passed, 1 skipped；黄金图 27 例逐字节不变。B5a/B5b 的最终计数见交付记录与 `scripts/verify.py`。

## 未采纳的方案

- **给 API 增加 `inputColorSpace` / `hasIccProfile` 响应字段**：属于观测性扩展，会改契约与前端类型，且本任务无需求驱动 → 不做。
- **16-bit 继续经 Pillow / lcms**：Pillow 没有 16-bit RGB 模式会直接截断；lcms 的 Pillow 绑定输出仍为 8-bit，无法保真 → 改用 cv2/tifffile 取像素 + NumPy 矩阵/TRC 转换。
- **LUT/mAB ICC 静默按 sRGB 处理**：16-bit 宽色域照片若静默降级会产生不可见但真实的色偏；按已确认决策返回 422，让调用方显式处理 → 不做静默回退。
- **改用 16-bit 代理**：实测收益低于 4 级，代价是代理缓存体积翻倍与全部代理缓存重建 → 不做（D3）。
- **`convert("RGB")` 之前先做 lcms（保持原顺序，只对 P 模式特判）**：会形成第二条色彩路径和更多分支，且无法覆盖 `1`/`L`/`LA`；顺序调整方案更短且已由黄金图证明安全 → 不做。
- **CMYK 走 lcms 组合配置**：`CMYK` + RGB 设备空间配置的 lcms 组合实测不合法（抛 `PyCMSError`），且这本身就是错误输入；保留静默回退并在文档中记为限制 → 不修。
