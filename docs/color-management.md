# 色彩管理

更新日期：2026-11-04（阶段四 Task 7）。决策依据与实测过程见 [ADR-0004](decisions/ADR-0004-color-management.md)。

本文档是色彩策略的**权威描述**：代码与测试若与本文不一致，以本文为准并同步修正。所有数字都是 2026-11-04 在本机项目 venv（Pillow 12.3.0 / OpenCV 4.14.0 headless / NumPy 2.5.4 / Python 3.14.7）实测所得，不是估计值。

---

## 1. 输入色彩空间策略

三条规则，按顺序判定，全部有测试钉住（均在 `services/api/tests/test_color_management.py`，另有 `services/api/tests/test_loader_icc.py` 覆盖阶段 2.1 的既有行为）：

| 情形 | 处理 | 实现 | 测试 |
| --- | --- | --- | --- |
| 携带嵌入配置**且配置设备空间为 RGB** | 用 lcms2 转换到 sRGB，渲染意图 `RELATIVE_COLORIMETRIC` + `BLACKPOINTCOMPENSATION`；配置本身已是 sRGB 时跳过转换 | `services/api/app/imaging/loader.py:64-88` | `test_palette_embedded_profile_is_converted_to_srgb`、`test_loader_icc.py::test_p3_profile_is_converted_to_srgb` |
| 携带嵌入配置但设备空间非 RGB（灰度 / CMYK / Lab），或配置损坏 / 为空 / 截断 | **回退按 sRGB 解释**，不抛异常、不中断出图 | `loader.py:66-71, 82-88` | `test_non_rgb_device_profile_is_skipped_without_raising`、`test_invalid_profiles_fall_back_to_the_srgb_assumption` |
| 没有嵌入配置 | **按 sRGB 解释**（与浏览器、大多数相机与手机的缺省一致） | `loader.py:66`（无配置直接原样返回） | `test_untagged_input_defaults_to_srgb` |

关键点：

- **不存在"把所有输入无条件当作同一色彩空间"的分支。** 配置管理在模式归一（`convert("RGB")` / `convert("RGBA")` + 白底合成）之后进行，所以 `RGB`、`RGBA`、`P`、`PA`、`1`、`L`、`LA` 都走同一条 lcms 路径。`P`/`1` 等在修复前被当作 sRGB 直接读取，实测色差 **37 级**（`test_palette_embedded_profile_is_converted_to_srgb` 同时断言"与参考转换差 ≤1 级"和"与不转换差 >20 级"，把修复本身钉成回归守卫）。
- 例外只有两处，且都是库限制而非策略选择：`I;16*`/`I`/`F` 高位深灰度（没有 RGB 通道可管理，见 §3）与 `CMYK`（见 §7）。
- 回退而不是报错是有意为之：配置损坏的图片仍要能出图，代价是颜色按 sRGB 解释。
- 不透明 `RGBA` 与同像素 `RGB` 的结果一致（`test_opaque_rgba_matches_the_same_pixels_as_rgb`）：转换发生在合成白底之前，两条路径不会分叉。

## 2. 输入格式与入口闸门

理解色彩管理必须先区分**两层**，此前无人写清：

| 层 | 位置 | 接受范围 |
| --- | --- | --- |
| 上传入口闸门 | `app/imaging/decoder.py:12-25` | 只有 `image/jpeg`、`image/png`、`image/webp`；声明 MIME 与真实探测格式必须一致；动画（动图 WebP / APNG）拒绝；像素数与截断检查 |
| 解码与色彩管理 | `app/imaging/loader.py` | Pillow 能解码的都可以：实测 TIFF 可解码、`I;16` 可解码、HEIF 不可（未装 `pillow-heif`）。但**入口闸门不暴露这些容器** |

结论：

- "loader 能解码 TIFF"不等于"应用支持 TIFF"。要新增输入格式，需要同时改 `decoder.py` 的 MIME/格式表、`docs/api-contract.md` 与前端 accept 属性。
- 色彩管理**不依赖容器**：同一组像素 + 同一份 Display-P3 配置存成 PNG / JPEG(quality=100, subsampling=0) / 无损 WebP，`load_image` 结果一致（`test_containers_get_identical_colour_management`，对 PNG 基准偏差 ≤5 级，差异来自有损编码本身而非配置处理）。
- EXIF 方向在色彩管理之前烘焙进像素：`image.load()` → `ImageOps.exif_transpose` → `_to_float_rgb`（`loader.py:141-143`）。方向 1–8 全覆盖（`test_loader.py`），且 JPEG 容器上"方向 + 配置"同时生效由 `test_jpeg_orientation_and_profile_are_applied_together` 钉住。
- 无法解码的载荷统一转成 `415 invalid_image`，不泄漏底层异常文本（`test_undecodable_payload_is_rejected`）。

## 3. 位深与精度

| 测量项 | 实测结果 | 结论 |
| --- | --- | --- |
| 16-bit RGB PNG（OpenCV 写入，64 个不同 16-bit 色）经 Pillow 打开 | `mode == "RGB"`；与 16-bit 参考最大偏差 **0.72 级**，64 个不同色仍为 64 | Pillow 没有 16-bit RGB 模式，**解码阶段即降位**，loader 无法挽回；`test_16_bit_rgb_is_downconverted_at_decode_within_one_level` 把该限制钉成期望行为 |
| 16-bit 灰度（`I;16*`） | `/65535` 归一后直接进 float32 工作空间，误差 **≤1e-6**，不经过 8-bit 中间步骤 | `test_16_bit_gray_keeps_float_precision_without_an_8_bit_step` |
| `srgb_to_linear` ↔ `linear_to_srgb` 全 256 级往返 | 最大偏差 **1.5e-5 级**，线性范围落在 `[0,1]` | 工作空间往返无可测精度损失，不构成"过早低精度转换"；`test_srgb_linear_round_trip_is_lossless_at_8_bit` 守卫 |
| OpenCV NL-means 去噪（`app/imaging/detail.py`） | 输入强制 `uint8`；`denoise(float)` 与 `denoise(已量化)` 差 **max 0.00 / mean 0.000 级** | 量化幂等：最终输出本来就要量化到 8-bit，去噪不引入额外损失 |
| 8-bit 预览代理（`loader.py` 的代理缓存） | 源可 8-bit 表示时代理逐值相同；float 源与 8-bit 代理源在同一强配方（+0.7 EV、对比 40、5 点 S 形主曲线）下渲染差 **max 4 级 / mean 0.33 级**，输出不同级数 **112 vs 112** 未减少 | 强曲线把约 1 级输入误差放大到 ≤4 级，但**不产生色带**；因此**不升级为 16-bit 代理**。边界由 `test_proxy_quantisation_stays_below_visible_banding`（max ≤6、mean ≤1.0，且只写出一份代理 PNG）与 `test_strong_curve_bounds_input_quantisation_to_six_levels`（放大倍率 ≤2× + 1）锁定 |

没有"不必要的位深降低"被留下不管：`app/imaging` 内出现 `astype(np.uint8)` 的站点只有 4 处，逐一注明理由——`output.py`（管线末端唯一量化）、`detail.py`（OpenCV 去噪只收 8-bit）、`loader.py`（8-bit 代理，上述刻意取舍）、`analyzer.py`（仅分析用边缘检测，不在渲染路径）。渲染阶段模块（`pipeline/tone/color_ops/curves/hsl/color_grading/local/local_masks/geometry`）禁止中间量化，由 `test_render_stages_keep_float32` 与 `test_only_the_documented_sites_quantise_to_uint8` 检查；新增站点必须显式改白名单并说明理由。

## 4. 工作色彩空间与管线中的色彩步骤

工作空间：**float32、`[0,1]`、sRGB 编码值**，贯穿整个渲染管线，只在最末端一次量化到 `uint8`。

管线里的色彩相关步骤（完整顺序见 `docs/architecture.md` 的"渲染管线"）：

```text
原图字节
  → EXIF 方向烘焙（exif_transpose）
  → 模式归一 + 嵌入 ICC 转 sRGB + alpha 合成白底   ← §1
  → float32 [0,1] sRGB 编码工作空间                 ← §4
  → 代理缩放（draft 960 / final 1600 / export 全分辨率）
  → 旋转内接 → 裁切
  → sRGB → 线性光
  → 曝光 / 白平衡 / 高光 / 阴影 / 白色色阶 / 黑色色阶   （线性光）
  → 线性 → sRGB
  → 对比度 / 曲线 / HSL / 饱和度·自然饱和度 / 颜色分级  （sRGB 编码）
  → 局部调整（蒙版加权混合）→ 清晰度 / 暗角
  → 降噪（uint8 强制）/ 锐化 → 颗粒
  → uint8 量化 → 编码（嵌入 sRGB ICC）
```

- 线性光区段只覆盖全局调色的前四步；曲线、HSL、分级与局部混合都定义在 sRGB 编码值上，这是阶段四各任务的数学定义，不属于色彩管理改动范围。
- 预览与导出**共用同一条 `render()` 管线**，差异只在 `max_edge`、`quality` 与是否使用代理。因此本文件的每一条输入策略都同时作用于预览与导出，不存在"只修一侧"的可能。

## 5. 输出色彩空间与嵌入

| 项 | 承诺 | 实现 | 测试 |
| --- | --- | --- | --- |
| 目标色彩空间 | 恒为 **sRGB**。两处声明都只是显式确认，不是可选项：配方里的 `output.colorSpace` 与导出请求体里的 `colorSpace` 都是 `Literal["sRGB"]`，其他值（含小写 `"srgb"`）返回 422；`recipe.output` 整体不参与导出渲染 | `app/models/recipe.py:42, 297`、`app/models/export.py:26`、`app/imaging/output.py` | `tests/test_output.py`、`tests/test_compare_export_api.py::test_export_output_declares_and_embeds_srgb`、`::test_export_rejects_any_output_colour_space_other_than_srgb`、契约测试 |
| 位深 | 8-bit / 通道，RGB 三通道 | `output.py::to_uint8` | `tests/test_output.py:22` |
| ICC 嵌入 | JPEG 与 PNG 都嵌入标准 sRGB 配置；配置头部创建时间被 pin 死（`profile[24:36]`），保证同一像素与参数跨进程编码逐字节一致 | `app/imaging/output.py:30-36, 55` | `tests/test_output.py:32-79`、`tests/test_previews_api.py::test_preview_jpeg_embeds_srgb_profile_and_carries_no_metadata` |
| 元数据 | 导出/预览剥离全部 EXIF/XMP/IPTC（含 GPS），不写 `eXIf`/`tEXt`/`iTXt`；预览 JPEG 同样无 EXIF | `output.py::encode_image`（只带 `icc_profile`） | 同上 |
| 原图 | **不改写原图字节**：`GET /api/v1/images/{id}/original` 用 `FileResponse` 返回上传时保存的原始文件，因此保留原 ICC 配置与原 EXIF/GPS | `app/api/routes/images.py:80-95`、`app/services/image_service.py:160-212`（`sha256` 按原始字节计算并入库） | `tests/test_images.py` |

即："**原图不动、输出重编码**"。原图下载可能带出 GPS，只有导出会剥离——分享场景必须用导出。

## 6. Pillow / OpenCV 能力边界

| 能力 | Pillow 12.3.0 | OpenCV 4.14.0（headless） | 结论 |
| --- | --- | --- | --- |
| 高位深 RGB | 无 16-bit RGB 模式，解码即降 8-bit；`I;16` 仅灰度 | 有 `CV_16U`/`CV_32F`，但**不做色彩管理** | 真高位深需要自写解码或新依赖，超出范围 |
| ICC 管理 | ✅ `ImageCms`（lcms2） | ❌ 实测 `cv2.iccread` 不存在；`cv2.imread` 读 P3 标记 PNG 返回原始像素，不转换 | ICC 必须留在 Pillow/lcms 侧；当前管线只在 resize/细节处用 cv2，分工正确 |
| RAW 解码 | ❌（`rawpy` 未安装，实测 import 失败） | ❌ | 范围外，任务书已豁免 |
| 大图 | 有 `DecompressionBomb` 防护，loader 转成 413 | 无自身限制，受内存约束 | 由 `max_image_pixels=40_000_000` + 代理缓存覆盖 |
| 高精度转换 | 8-bit 输入下 lcms 输出仍 8-bit，无浮点中转 API | 纯浮点但不管理色彩 | 需要 `colorio` 一类依赖，本次不引入 |
| 其他容器 | TIFF 实测可解码；HEIF 需 `pillow-heif`（未安装） | — | 入口闸门只放 JPEG/PNG/WebP |

**依赖评估结论：不新增任何依赖。** 理由与逐项验证过程见 [ADR-0004](decisions/ADR-0004-color-management.md) D6。

## 7. 明确不支持

不宣称、不伪装、界面也不提供入口的能力：

- **RAW 显影**（`.cr2/.nef/.arw/.dng` 等）。入口闸门直接拒绝，`rawpy` 未安装。
- **高位深管线**：16-bit/HDR/32-bit RGB 全程 float32 的处理。16-bit RGB 输入在解码阶段降为 8-bit（§3），16-bit 灰度可进 float32 但没有 RGB 通道语义。
- **CMYK 正确显影**：带 RGB 设备空间配置的 CMYK 输入，lcms 组合不合法 → 回退按 Pillow 的 CMYK→RGB 近似转换，实测与参考转换差 **19–23 级**。这是错误输入的兜底，不是 CMYK 支持。
- **非 RGB 设备空间配置的转换**：灰度 / Lab 配置被显式跳过（`xcolor_space != "RGB"`），按 sRGB 解释。
- **导出 PNG 的 alpha 通道**：所有带 alpha 的输入在 loader 中统一合成到白底并转 RGB，PNG 导出语义等同白底合成（见 `docs/known-issues.md`）。
- **色域标记 / ICC 观测性**：API 不返回"是否检测到配置""输入色域"等字段。
- **广色域输出与软打样**：输出恒为 sRGB；宽色域输入被收敛到 sRGB，超出部分截断。
- **镜头校正、色彩查找表、设备链接配置、感知/饱和度渲染意图**。

## 8. 版本与缓存

任何改变输出像素的改动（含 §1 的配置管理范围）都必须提升 `ENGINE_VERSION` 并重新生成黄金图，规则见 `docs/decisions/ADR-0002-phase-2-decisions.md`。

本次：`ENGINE_VERSION` `frame-engine/7` → **`frame-engine/8`**（`app/imaging/params_map.py:3`），`PROXY_VERSION` `loader/2` → **`loader/3`**（`app/imaging/loader.py:21`）。

复审整改（2026-11-05）把 `ENGINE_VERSION` 提升到 **`frame-engine/9`**（白平衡守恒对象改为全图均值、HSL 色相加单调上限、颜色分级越界改为等比缩放），随后 **`frame-engine/10`** 落地 G5 摄影语义决策（Blacks 方向与掩膜端点、HSL 分档门控、曲线端点线性外推、对比度色度回收 ±5%，并删除遗留 `/images/{id}/analyze`）；`PROXY_VERSION` 保持 `loader/3`。两次提升都不改变色彩管理本身；27 张黄金图按 `frame-engine/10` 重生成，G1 那轮 9 张变化（color/hsl/local），G5 这轮 7 张变化（tone/curve/hsl，含 11 个像素的曲线用例），其余 20 张逐字节不变，逐图实测见 `docs/plans/stage-3-4-review-remediation.md` §12。

后果：历史会话的预览磁盘缓存与代理缓存全部自动失效，首次打开需要重新渲染；已保存的配方、revision 历史与原图字节不受影响。黄金图重生成后 30 个 PNG **逐字节不变**，证明无配置输入与 `RGB`/`RGBA` 输入的输出完全未受影响，§1 的"影响面仅限携带有效 RGB 配置的非 RGB 模式输入"成立。
