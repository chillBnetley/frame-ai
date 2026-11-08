# 色彩管理

更新日期：2026-11-07（B5a 追加 8-bit alpha；B5b 追加 16-bit 输入/输出与矩阵/TRC ICC）。决策依据与实测过程见 [ADR-0004](decisions/ADR-0004-color-management.md)。

本文档是色彩策略的**权威描述**：代码与测试若与本文不一致，以本文为准并同步修正。§1–§4、§6 的 8-bit 数字都是 2026-11-04 在本机项目 venv（Pillow 12.3.0 / OpenCV 4.14.0 headless / NumPy 2.5.4 / Python 3.14.7）实测所得，不是估计值；§5 的 alpha 行为为 2026-11-07 B5a 实现，16-bit 行为与数字为同日 B5b 实现。

---

## 1. 输入色彩空间策略

三条规则，按顺序判定，全部有测试钉住（均在 `services/api/tests/test_color_management.py`，另有 `services/api/tests/test_loader_icc.py` 覆盖阶段 2.1 的既有行为）：

| 情形 | 处理 | 实现 | 测试 |
| --- | --- | --- | --- |
| 携带嵌入配置**且配置设备空间为 RGB** | 用 lcms2 转换到 sRGB，渲染意图 `RELATIVE_COLORIMETRIC` + `BLACKPOINTCOMPENSATION`；配置本身已是 sRGB 时跳过转换 | `services/api/app/imaging/loader.py:64-88` | `test_palette_embedded_profile_is_converted_to_srgb`、`test_loader_icc.py::test_p3_profile_is_converted_to_srgb` |
| 携带嵌入配置但设备空间非 RGB（灰度 / CMYK / Lab），或配置损坏 / 为空 / 截断 | **回退按 sRGB 解释**，不抛异常、不中断出图 | `loader.py:66-71, 82-88` | `test_non_rgb_device_profile_is_skipped_without_raising`、`test_invalid_profiles_fall_back_to_the_srgb_assumption` |
| 没有嵌入配置 | **按 sRGB 解释**（与浏览器、大多数相机与手机的缺省一致） | `loader.py:66`（无配置直接原样返回） | `test_untagged_input_defaults_to_srgb` |

关键点：

- **不存在"把所有输入无条件当作同一色彩空间"的分支。** 配置管理在模式归一（`convert("RGB")` / `convert("RGBA")` + alpha 拆分或白底合成）之后进行，所以 `RGB`、`RGBA`、`P`、`PA`、`1`、`L`、`LA` 都走同一条 lcms 路径。`P`/`1` 等在修复前被当作 sRGB 直接读取，实测色差 **37 级**（`test_palette_embedded_profile_is_converted_to_srgb` 同时断言"与参考转换差 ≤1 级"和"与不转换差 >20 级"，把修复本身钉成回归守卫）。
- 例外只有两处，且都是库限制而非策略选择：`I;16*`/`I`/`F` 高位深灰度（没有 RGB 通道可管理，见 §3）与 `CMYK`（见 §7）。
- 回退而不是报错是有意为之：配置损坏的图片仍要能出图，代价是颜色按 sRGB 解释。
- 不透明 `RGBA` 与同像素 `RGB` 的结果一致（`test_opaque_rgba_matches_the_same_pixels_as_rgb`）：转换发生在 alpha 拆分/白底合成之前，两条路径不会分叉。
- `preserve_alpha=True`（loader 默认）时 `RGBA`/`LA`/带 `transparency` 的 `P` 走 `_to_float_rgba`：`convert("RGBA")` → `_apply_embedded_profile` → 拆成 float32 RGB 与 `/255` 的 alpha，**不再先合成白底**。预览、代理与 AI 分析显式传 `preserve_alpha=False`，保持原有白底合成结果与缓存字节不变。
- **16-bit RGB 输入不走 lcms**：Pillow 没有 16-bit RGB 模式（会把像素截断到 8-bit），因此 16-bit PNG 用 OpenCV `IMREAD_UNCHANGED`、16-bit TIFF 用 `tifffile` 解码，Pillow 只负责读取 ICC/EXIF 与方向标签。ICC 转换由 `app/imaging/icc.py` 的纯 NumPy 矩阵/TRC 实现：支持 `rXYZ/gXYZ/bXYZ` + `rTRC/gTRC/bTRC`（`curv` 或 `para` 类型 0–4），经 D50 PCS 转到 sRGB；`lut8/lut16/mAB/mBA/mft` 以及 ICC v4 的 `D2B*`/`B2D*` 结构化 LUT 标签、非 RGB/XYZ 设备空间、损坏或越界配置一律返回 422 `unsupported_icc_profile`，**不静默降级**。已是 sRGB 的快速路径也先走同一套结构解析：只有 header/tag 边界有效、没有任何 LUT/结构化签名、矩阵与三条 TRC 在原子容差内接近标准 sRGB，且合成变换在 17³ RGB 采样上与恒等输出相差 ≤1 个 8-bit 级时才恒等返回（lcms sRGB 实测 0.64 级；旧容差下最坏对抗矩阵可达约 16 级，现在会被拒绝并走真实转换）；**profile description 不参与判断**，因此写着 "sRGB" 的 LUT 或非 sRGB 矩阵配置仍会进入转换并按需 422。无配置的 16-bit 输入走快速路径，不做数值转换。8-bit 路径的 lcms 行为完全不变。上传入口不校验 ICC；上述 422 发生在首次 preview/render/export 解码时。

## 2. 输入格式与入口闸门

理解色彩管理必须先区分**两层**，此前无人写清：

| 层 | 位置 | 接受范围 |
| --- | --- | --- |
| 上传入口闸门 | `app/imaging/decoder.py` | `image/jpeg`、`image/png`、`image/webp`、`image/tiff`；声明 MIME 与真实探测格式必须一致；动画（动图 WebP / APNG）拒绝；像素数与截断检查 |
| 解码与色彩管理 | `app/imaging/loader.py` | Pillow 能解码的都可以：实测 TIFF 可解码、`I;16` 可解码、HEIF 不可（未装 `pillow-heif`）。16-bit RGB PNG/TIFF 走 OpenCV/tifffile 像素路径 |

结论：

- TIFF 自 B5b 起是**正式输入格式**，但只支持单页、未压缩（1）或 Deflate（8/32946）；LZW/JPEG 压缩返回 415 `unsupported_tiff_compression`，多页返回 415 `tiff_multipage_not_supported`，associated（预乘）alpha（tag 338 含 1）返回 415 `associated_alpha_not_supported`——只接受 unassociated alpha，与输出端 `unassalpha` 一致，避免在几何/缩放阶段二次预乘。`PlanarConfiguration=2` 的 16-bit TIFF 按 tag 284 的 `(S,H,W)` 布局解码并与 tag 256/257 校验，不再从 shape 猜测。20 MiB 上传上限不变，因此大 TIFF 需要无损压缩后才可上传（`imagecodecs` 未引入，LZW 输入不支持）。前端 `accept` 与 `docs/api-contract.md` 已同步。
- 色彩管理**不依赖容器**：同一组像素 + 同一份 Display-P3 配置存成 PNG / JPEG(quality=100, subsampling=0) / 无损 WebP，`load_image` 结果一致（`test_containers_get_identical_colour_management`，对 PNG 基准偏差 ≤5 级，差异来自有损编码本身而非配置处理）。
- EXIF 方向在色彩管理之前烘焙进像素：`image.load()` → `ImageOps.exif_transpose` → `_to_float_rgb` / `_to_float_rgba`（`loader.py` 的 `load_image`）。方向 1–8 全覆盖（`test_loader.py`），且 JPEG 容器上"方向 + 配置"同时生效由 `test_jpeg_orientation_and_profile_are_applied_together` 钉住。
- 无法解码的载荷统一转成 `415 invalid_image`，不泄漏底层异常文本（`test_undecodable_payload_is_rejected`）。

## 3. 位深与精度

| 测量项 | 实测结果 | 结论 |
| --- | --- | --- |
| 16-bit RGB PNG（OpenCV 写入）经 `IMREAD_UNCHANGED` 解码 | `bit_depth == 16`，`float32`；511 与 512、1000 与 1001 在加载后仍可区分，误差 **≤1e-6** | Pillow 的 8-bit 截断路径**不再用于像素**；`test_16_bit_rgb_keeps_its_samples_instead_of_downconverting` 把保真钉成期望行为 |
| 16-bit AdobeRGB-like 渐变（`curv` 与 `para` 两种 TRC）经矩阵/TRC 转换 | 全图 **62,946** 个不同 16-bit 级；可被 257 整除的比例 **0.84%**；相邻行最大台阶 **2** | 16-bit 精度未在 ICC 转换或输出量化中塌陷；`test_16_bit_adobe_rgb_ramp_keeps_more_than_60000_levels`、参数化 `test_16_bit_profile_conversion_matches_lcms_within_one_level`（与 lcms 8-bit 参考差 ≤1 级） |
| 同一渐变若强制走 8-bit 中间步骤 | 只剩 **245** 个不同级；可被 257 整除比例 **100%**；最大台阶 **514** | 反例守卫 `test_eight_bit_intermediate_collapses_the_same_ramp_to_256_levels`，证明 16-bit 路径不是“8-bit 后换容器” |
| 16-bit TIFF（`tifffile`） | uint16 → float32，嵌入式配置按同一矩阵/TRC 转到 sRGB；`test_16_bit_tiff_profile_is_converted_to_srgb` | 输入容器不改变色彩策略 |
| 16-bit 灰度（`I;16*`） | `/65535` 归一后直接进 float32 工作空间，误差 **≤1e-6**，不经过 8-bit 中间步骤 | `test_16_bit_gray_keeps_float_precision_without_an_8_bit_step` |
| `srgb_to_linear` ↔ `linear_to_srgb` 全 256 级往返 | 最大偏差 **1.5e-5 级**，线性范围落在 `[0,1]` | 工作空间往返无可测精度损失，不构成"过早低精度转换"；`test_srgb_linear_round_trip_is_lossless_at_8_bit` 守卫 |
| OpenCV NL-means 去噪（`app/imaging/detail.py`） | 输入强制 `uint8`；`denoise(float)` 与 `denoise(已量化)` 差 **max 0.00 / mean 0.000 级** | 量化幂等：最终输出本来就要量化到 8-bit，去噪不引入额外损失 |
| 8-bit 预览代理（`loader.py` 的代理缓存） | 源可 8-bit 表示时代理逐值相同；float 源与 8-bit 代理源在同一强配方（+0.7 EV、对比 40、5 点 S 形主曲线）下渲染差 **max 4 级 / mean 0.33 级**，输出不同级数 **112 vs 112** 未减少 | 强曲线把约 1 级输入误差放大到 ≤4 级，但**不产生色带**；因此**不升级为 16-bit 代理**。边界由 `test_proxy_quantisation_stays_below_visible_banding`（max ≤6、mean ≤1.0，且只写出一份代理 PNG）与 `test_strong_curve_bounds_input_quantisation_to_six_levels`（放大倍率 ≤2× + 1）锁定 |

没有"不必要的位深降低"被留下不管：`app/imaging` 内出现 `astype(np.uint8)` 的站点只有 4 处，逐一注明理由——`output.py`（管线末端 8-bit 量化；16-bit 走 `to_uint16`）、`detail.py`（OpenCV 去噪只收 8-bit）、`loader.py`（8-bit 代理，上述刻意取舍）、`analyzer.py`（仅分析用边缘检测，不在渲染路径）。渲染阶段模块（`pipeline/tone/color_ops/curves/hsl/color_grading/local/local_masks/geometry`）禁止中间量化，由 `test_render_stages_keep_float32` 与 `test_only_the_documented_sites_quantise_to_uint8` 检查；新增站点必须显式改白名单并说明理由。

## 4. 工作色彩空间与管线中的色彩步骤

工作空间：**float32、`[0,1]`、sRGB 编码值**，贯穿整个渲染管线，只在最末端一次量化到 `uint8`（8-bit 输出）或 `uint16`（16-bit 输出）。16-bit 输入在解码后立即归一为同一 float32 工作空间，后续所有调整与 8-bit 路径完全一致；32-bit/HDR 仍未支持。

管线里的色彩相关步骤（完整顺序见 `docs/architecture.md` 的"渲染管线"）：

```text
原图字节
  → EXIF 方向烘焙（exif_transpose）
  → 模式归一 + 嵌入 ICC 转 sRGB + alpha 拆分（预览/代理/分析改为白底合成）   ← §1
  → float32 [0,1] sRGB 编码工作空间 + 可选 float32 alpha                        ← §4
  → 代理缩放（draft 960 / final 1600 / export 全分辨率；alpha 按预乘同步缩放）
  → 旋转内接 → 裁切（alpha 与 RGB 同矩阵、同目标尺寸）
  → sRGB → 线性光
  → 曝光 / 白平衡 / 高光 / 阴影 / 白色色阶 / 黑色色阶   （线性光）
  → 线性 → sRGB
  → 对比度 / 曲线 / HSL / 饱和度·自然饱和度 / 颜色分级  （sRGB 编码）
  → 局部调整（蒙版加权混合）→ 清晰度 / 暗角
  → 降噪（uint8 强制；16-bit 输出跳过并告警）/ 锐化 → 颗粒
  → RGB 与 alpha 各自量化到 uint8 或 uint16
  → 编码（JPEG 白底合成 8-bit / PNG RGBA 8-bit / PNG 16-bit RGBA / TIFF 16-bit RGBA，均嵌入 sRGB ICC）
```

- 线性光区段只覆盖全局调色的前四步；曲线、HSL、分级与局部混合都定义在 sRGB 编码值上，这是阶段四各任务的数学定义，不属于色彩管理改动范围。
- **alpha 是独立的覆盖平面**：调色/曲线/HSL/局部/清晰度/细节阶段只接收并返回 RGB，alpha 原样透传；旋转、裁切与两处缩放按预乘 alpha 处理，避免透明像素的颜色渗入边缘。alpha≈0 处的 RGB 统一置 0，保证结果确定（见 `tests/test_geometry.py` 与 `tests/test_pipeline.py`）。
- 预览与导出**共用同一条 `render()` 管线**，差异只在 `max_edge`、`quality`、是否使用代理、是否携带 alpha 与 `bit_depth`。因此本文件的每一条输入策略都同时作用于预览与导出，不存在"只修一侧"的可能；但预览以 `preserve_alpha=False`、`bit_depth=8` 读取，所以预览字节与历史缓存保持原样，16-bit 只发生在导出。

## 5. 输出色彩空间与嵌入

| 项 | 承诺 | 实现 | 测试 |
| --- | --- | --- | --- |
| 目标色彩空间 | 恒为 **sRGB**。两处声明都只是显式确认，不是可选项：配方里的 `output.colorSpace` 与导出请求体里的 `colorSpace` 都是 `Literal["sRGB"]`，其他值（含小写 `"srgb"`）返回 422；`recipe.output` 整体不参与导出渲染 | `app/models/recipe.py:42, 297`、`app/models/export.py:26`、`app/imaging/output.py` | `tests/test_output.py`、`tests/test_compare_export_api.py::test_export_output_declares_and_embeds_srgb`、`::test_export_rejects_any_output_colour_space_other_than_srgb`、契约测试 |
| 位深 | PNG 与 TIFF 支持 **8-bit 或 16-bit/通道**；JPEG 固定 8-bit（`bitDepth=16` 在请求模型校验阶段返回 422 `validation_error`）。16-bit 只在管线末端量化一次，输入 16-bit 样本不会先降 8-bit | `output.py::to_uint8`/`to_uint16`、`pipeline.py::render(bit_depth=...)`、`models/export.py` | `tests/test_output.py`、`tests/test_pipeline.py`、`tests/test_export_jobs_api.py` |
| Alpha | **PNG/TIFF 导出保留 alpha**：8-bit 写 RGBA，16-bit 写 RGBA16；`encode_image(..., alpha=...)` 与 RGB 同步量化。**JPEG 导出与所有预览**在最后一步用 `round(rgb*a + 255*(1-a))` 合成白底。alpha 缺失时 PNG/TIFF 仍是 RGB，8-bit 输出字节与 B5a 之前一致 | `output.py::encode_image`、`_composite_on_white`、`export_service.py` | `tests/test_output.py`、`tests/test_compare_export_api.py`、`tests/test_export_jobs_api.py`、`tests/e2e/editor.spec.ts` |
| 16-bit 容器 | PNG 用 OpenCV 编码 BGR/BGRA，按 IHDR 写入 bit depth 16，并在 IHDR 后手工插入 pinned sRGB `iCCP`；TIFF 用 `tifffile` Deflate、`iccprofile=`（tag 34675）、`extrasamples=["unassalpha"]`，不写 software/datetime | `output.py::_encode_png_sixteen`、`_encode_tiff`、`_insert_iccp` | `tests/test_output.py`、`tests/test_export_jobs_api.py`（IHDR 16/2、16/6、tag 258/34675、重复编码逐字节一致） |
| ICC 嵌入 | JPEG 与 8-bit PNG 用 Pillow 嵌入标准 sRGB 配置；16-bit PNG/TIFF 嵌入同一份 pinned sRGB 配置；配置头部创建时间被 pin 死（`profile[24:36]`），保证同一像素与参数跨进程编码逐字节一致 | `app/imaging/output.py` | `tests/test_output.py`、`tests/test_color_management.py`、`tests/test_previews_api.py` |
| 元数据 | 导出/预览剥离全部 EXIF/XMP/IPTC（含 GPS），不写 `eXIf`/`tEXt`/`iTXt`；16-bit TIFF 也不写 software/datetime；预览 JPEG 同样无 EXIF | `output.py::encode_image`（只带 `icc_profile`） | 同上 |
| 原图 | **不改写原图字节**：`GET /api/v1/images/{id}/original` 用 `FileResponse` 返回上传时保存的原始文件，因此保留原 ICC 配置与原 EXIF/GPS | `app/api/routes/images.py:80-95`、`app/services/image_service.py:160-212`（`sha256` 按原始字节计算并入库） | `tests/test_images.py` |

即："**原图不动、输出重编码**"。原图下载可能带出 GPS，只有导出会剥离——分享场景必须用导出。

## 6. Pillow / OpenCV 能力边界

| 能力 | Pillow 12.3.0 | OpenCV 4.14.0（headless） | 结论 |
| --- | --- | --- | --- |
| 高位深 RGB | Pillow 无 16-bit RGB 模式，解码即降 8-bit；`I;16` 仅灰度 | 有 `CV_16U`/`CV_32F`，但**不做色彩管理**；`tifffile` 读写 uint16 TIFF | 16-bit PNG 用 cv2、TIFF 用 tifffile 取像素；ICC 用自写矩阵/TRC，Pillow 只读元数据 |
| ICC 管理 | ✅ `ImageCms`（lcms2），8-bit 路径继续使用 | ❌ 实测 `cv2.iccread` 不存在；`cv2.imread` 读 P3 标记 PNG 返回原始像素，不转换 | 8-bit 留在 Pillow/lcms；16-bit 用 `app/imaging/icc.py`（仅矩阵/TRC） |
| RAW 解码 | ❌（`rawpy` 未安装，实测 import 失败） | ❌ | 范围外，任务书已豁免 |
| 大图 | 有 `DecompressionBomb` 防护，loader 转成 413 | 无自身限制，受内存约束 | 由 `max_image_pixels=40_000_000` + 代理缓存覆盖 |
| 高精度转换 | 8-bit 输入下 lcms 输出仍 8-bit，无浮点中转 API | 纯浮点但不管理色彩 | 16-bit 矩阵/TRC 在 float32 中完成，256 行分块；不引入 colorio |
| 其他容器 | TIFF 实测可解码；HEIF 需 `pillow-heif`（未安装） | — | 入口闸门放 JPEG/PNG/WebP/TIFF；TIFF 限单页、未压缩/Deflate |

**依赖结论（B5b 更新）**：新增 `tifffile==2026.3.3`（BSD-3-Clause，仅用于 16-bit TIFF 读写与 ICC tag 34675），未引入 `imagecodecs`（因此不支持 LZW/JPEG 压缩 TIFF）或 `colorio`。其余依赖版本与 2026-11-04 一致；逐项验证见 [ADR-0004](decisions/ADR-0004-color-management.md) D6/D9。

## 7. 明确不支持

不宣称、不伪装、界面也不提供入口的能力：

- **RAW 显影**（`.cr2/.nef/.arw/.dng` 等）。入口闸门直接拒绝，`rawpy` 未安装。
- **HDR / 32-bit 管线**：支持到 16-bit/通道（PNG/TIFF 输入与输出），不做 HDR 色调映射、RAW 显影或 32-bit 浮点容器。
- **16-bit JPEG**：JPEG 固定 8-bit；`bitDepth=16` + `format="jpeg"` 在请求模型校验阶段返回 422 `validation_error`，异步作业不会创建。
- **16-bit + 降噪**：16-bit 导出跳过降噪（该实现强制 uint8），返回 warning `denoise_skipped_for_16bit`，不生成 8-bit 中间结果；其余调整保持 float32。
- **预览/代理 16-bit**：预览 JPEG 与代理 PNG 恒为 8-bit；16-bit 源使用独立代理缓存键（追加 `|b16`），避免复用旧截断代理，8-bit 源的缓存键与像素不变。
- **LUT 类或非 RGB/XYZ ICC 配置（16-bit）**：`lut8/lut16/mAB/mBA/mft`、ICC v4 `D2B*`/`B2D*`、灰度/Lab 等配置返回 422 `unsupported_icc_profile`，不静默按 sRGB 处理；即使 profile description 含 "sRGB" 也不会绕过结构校验。8-bit 路径仍保持既有的"回退按 sRGB 解释"策略。16-bit CMYK TIFF 不满足 16-bit RGB 解码条件（`mode` 仍是 CMYK），因此回退到 Pillow 8-bit + lcms 组合路径，沿用 8-bit CMYK 的已知限制（不保留 16-bit 精度）。
- **TIFF associated alpha**：tag 338 含 1（预乘 alpha）的 8-bit/16-bit TIFF 返回 415 `associated_alpha_not_supported`；请先转换为 unassociated alpha。输出端写 `unassalpha`，不会产生该限制。
- **CMYK 正确显影**：带 RGB 设备空间配置的 CMYK 输入，lcms 组合不合法 → 回退按 Pillow 的 CMYK→RGB 近似转换，实测与参考转换差 **19–23 级**。这是错误输入的兜底，不是 CMYK 支持。
- **非 RGB 设备空间配置的转换（8-bit）**：灰度 / Lab 配置被显式跳过（`xcolor_space != "RGB"`），按 sRGB 解释。
- **压缩/多页 TIFF 输入**：LZW/JPEG 压缩返回 415 `unsupported_tiff_compression`，多页返回 415 `tiff_multipage_not_supported`；未引入 `imagecodecs`。
- **预览中的透明棋盘格**：预览恒为 8-bit JPEG 白底，代理是 RGB PNG；透明区域只在 PNG/TIFF 导出结果中可见。
- **色域标记 / ICC 观测性**：API 不返回"是否检测到配置""输入色域"等字段。
- **广色域输出与软打样**：输出恒为 sRGB；宽色域输入被收敛到 sRGB，超出部分截断。
- **镜头校正、色彩查找表、设备链接配置、感知/饱和度渲染意图**。

## 8. 版本与缓存

任何改变输出像素的改动（含 §1 的配置管理范围）都必须提升 `ENGINE_VERSION` 并重新生成黄金图，规则见 `docs/decisions/ADR-0002-phase-2-decisions.md`。

本次：`ENGINE_VERSION` `frame-engine/7` → **`frame-engine/8`**（`app/imaging/params_map.py:3`），`PROXY_VERSION` `loader/2` → **`loader/3`**（`app/imaging/loader.py:21`）。

复审整改（2026-11-05）把 `ENGINE_VERSION` 提升到 **`frame-engine/9`**（白平衡守恒对象改为全图均值、HSL 色相加单调上限、颜色分级越界改为等比缩放），随后 **`frame-engine/10`** 落地 G5 摄影语义决策（Blacks 方向与掩膜端点、HSL 分档门控、曲线端点线性外推、对比度色度回收 ±5%，并删除遗留 `/images/{id}/analyze`）；`PROXY_VERSION` 保持 `loader/3`。两次提升都不改变色彩管理本身；27 张黄金图按 `frame-engine/10` 重生成，G1 那轮 9 张变化（color/hsl/local），G5 这轮 7 张变化（tone/curve/hsl，含 11 个像素的曲线用例），其余 20 张逐字节不变，逐图实测见 `docs/plans/stage-3-4-review-remediation.md` §12。

**B5a（2026-11-07）没有提升 `ENGINE_VERSION` 或 `PROXY_VERSION`**：`ENGINE_VERSION` 保持 `frame-engine/10`，`PROXY_VERSION` 保持 `loader/3`。理由是缓存键覆盖的两条路径（预览 JPEG 与 RGB 代理）都以 `preserve_alpha=False` 读取，输出逐字节不变；alpha 保留只发生在导出路径，而导出结果不进入任何持久缓存。提升版本会无差别清空全部历史预览/代理缓存，却没有任何像素变化与之对应。新增的 9 张 alpha 黄金图（`alpha__neutral/tone/color/geometry/detail/curve/hsl/grading/local.png`）按 `frame-engine/10` 生成，原有 30 张 PNG 重生成后逐字节不变。

**B5b（2026-11-07）同样不提升 `ENGINE_VERSION` 或 `PROXY_VERSION`**：16-bit 输入/输出只作用于新请求，8-bit 默认路径的像素与编码字节不变（`test_explicit_8_bit_matches_the_default_export_bytes` 逐字节比对）；`ENGINE_VERSION` 保持 `frame-engine/10`，`PROXY_VERSION` 保持 `loader/3`。为避免 16-bit 源复用旧的 8-bit 截断代理，代理缓存键**仅在 16-bit 源**追加 `|b16`；8-bit 键仍是 `sha256|loader/3|edge`，历史代理继续命中。预览与代理本身始终是 8-bit RGB，因此不需要升级版本清空缓存。

后果：历史会话的预览磁盘缓存与代理缓存继续命中，无需重建；已保存的配方、revision 历史与原图字节不受影响。透明 PNG 的**新导出**会得到 RGBA 结果，之前导出的旧文件不会被改写。
