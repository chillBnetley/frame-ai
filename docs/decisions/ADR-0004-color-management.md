# ADR-0004：色彩管理策略与依赖边界

- 状态：已接受并实现（2026-11-04，阶段四 Task 7）
- 适用：`services/api/app/imaging/loader.py`、`output.py`、`params_map.py` 及所有渲染/导出/预览路径
- 相关文档：[色彩管理](../color-management.md)、[架构](../architecture.md)、[API 契约](../api-contract.md)、[已知问题](../known-issues.md)、[ADR-0002](ADR-0002-phase-2-decisions.md)、[实施计划](../plans/phase-4-task-7-color-management.md)
- 本文所有数值均为 2026-11-04 本机项目 venv 实测（Pillow 12.3.0 / OpenCV 4.14.0 headless / NumPy 2.5.4 / Python 3.14.7），不含估计值

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

### D3 位深：如实记录，不伪装高位深支持

- 16-bit **RGB** 输入在 Pillow 解码阶段即降为 8-bit（实测最大偏差 **0.72 级**，64 个不同色仍为 64 个），loader 拿不到高位深；测试断言 `PIL.Image.open(...).mode == "RGB"` 并把 ≤1 级偏差钉成**期望行为**，Pillow 未来改变时测试会提醒。
- 16-bit **灰度**（`I;16*`/`I`）按 `/65535` 归一直接进 float32，不经过 8-bit 中间步骤（实测误差 ≤1e-6）。
- 8-bit 预览代理是**刻意取舍**：源可 8-bit 表示时代理逐值相同；在强配方（+0.7 EV、对比 40、5 点 S 形主曲线）下 float 源与 8-bit 源渲染差 **max 4 级 / mean 0.33 级**，且输出不同级数 **112 vs 112** 未减少——强曲线会放大约 1 级输入误差到 ≤4 级，但不产生色带。**因此不升级为 16-bit 代理。**
- 文档与界面不出现任何"支持 16-bit / HDR 管线"的表述。

### D4 工作空间与"过早低精度转换"用可维护性测试守卫

- 工作空间是 float32 `[0,1]` sRGB 编码值，`to_uint8` 只在管线末端一次；`srgb_to_linear` ↔ `linear_to_srgb` 全 256 级往返最大偏差 **1.5e-5 级**，无可测损失。
- 唯一的强制降位站点是 OpenCV NL-means 去噪（库限制）：`denoise(float)` 与 `denoise(已量化)` 差 **max 0.00 / mean 0.000 级**，量化幂等，不引入额外损失。
- 处理方式：把"渲染阶段模块不出现中间量化"写成测试（`test_render_stages_keep_float32`，扫描 `pipeline/tone/color_ops/curves/hsl/color_grading/local/local_masks/geometry` 九个模块）；`app/imaging` 内允许 `astype(np.uint8)` 的站点固定为 4 处并各自注明理由——`output.py`（末端量化）、`detail.py`（OpenCV 去噪只收 8-bit）、`loader.py`（8-bit 代理，D3 取舍）、`analyzer.py`（仅分析用边缘检测，不在渲染路径）。新增站点必须显式改白名单。

### D5 输出策略保持，请求侧契约留给 Task 8

- 所有输出（预览 JPEG、对比图、导出 JPEG/PNG）目标空间恒为 sRGB、8-bit、嵌入固定 sRGB ICC、剥离全部元数据。ICC 头部创建时间 pin 死，保证跨进程逐字节一致。
- 本任务只补**预览侧**的直接断言（此前只有单元侧与导出侧覆盖）：`tests/test_previews_api.py::test_preview_jpeg_embeds_srgb_profile_and_carries_no_metadata`。
- `output.colorSpace` 目前是 `Literal["sRGB"]`，不参与导出决策；把它写成显式契约、以及导出尺寸/并发，属于 Task 8（`docs/plans/phase-4-task-8-preview-export-performance.md`）。**避免两个任务改同一处。**
- 同步核对（只读）：`GET /api/v1/images/{id}/original` 用 `FileResponse` 返回上传时保存的原始字节，保留原 ICC 与原 EXIF/GPS；导出与预览才是"重编码 + 剥离元数据 + 嵌入 sRGB"。`POST /export` 的 `X-Export-Warning` 只用于简化降噪，与色彩无关，本次不动。

### D6 依赖评估结论：不新增任何依赖

任务书要求"评估 Pillow/OpenCV 在高位深、ICC 管理、RAW 解码、大图、高精度转换上的边界，先独立验证再决定引入"。验证过程与结果：

| 能力 | 独立验证方式 | 结果 |
| --- | --- | --- |
| 高位深 RGB | 用 OpenCV 写 16-bit RGB PNG，再用 Pillow 打开 | `mode == "RGB"`（Pillow 无 16-bit RGB 模式），偏差 ≤0.72 级 → 需自写解码或新依赖 |
| ICC 管理 | `hasattr(cv2, "iccread")`；用 `cv2.imread` 读 P3 标记 PNG | `False`；返回原始像素 `(200,30,30)` 不转换 → ICC 必须留在 Pillow/lcms 侧，现有分工正确 |
| RAW 解码 | `import rawpy` | 失败（未安装）；任务书已豁免 RAW → 不引入 |
| 大图 | 触发 `Image.DecompressionBombWarning` | loader 已转成 413；`max_image_pixels=40_000_000` + 代理缓存覆盖 → 无需新依赖 |
| 高精度转换 | 8-bit 输入下 `ImageCms` 输出模式 | 仍为 8-bit，无浮点中转 API → 需 `colorio` 一类依赖，超范围 |
| 其他容器 | `import pillow_heif`；TIFF 经 `load_image` | HEIF 失败（未安装）；TIFF 可解码但入口闸门不暴露 |

结论：现有栈（Pillow + lcms2 + OpenCV + NumPy float32）满足全部已承诺行为；需要新依赖的项要么被任务书豁免（RAW），要么是明确不支持（高位深管线）。**不引入 `rawpy`、`pillow-heif`、`colorio` 或任何 lcms 绑定类依赖**，符合"不得一次性引入大量依赖"。

### D7 预览与导出共用同一管线，作为不变量守卫

现状已成立：两者都走 `render_image` → `render()`，差异只在 `quality` / `max_edge` / 是否使用代理。本任务把它写成不变量并记录在 `docs/color-management.md` §4，确保 D2 这类输入侧改动不会只覆盖一侧。

## 后果

- `ENGINE_VERSION` 升 `frame-engine/7 → frame-engine/8`，`PROXY_VERSION` 升 `loader/2 → loader/3`。按 ADR-0002 的规则，像素行为变化必须提升引擎版本并重新生成黄金图。
- **全部历史预览磁盘缓存与代理缓存自动失效**：用户再次打开历史会话时首次渲染需要重建。已保存的配方、revision 历史与原图字节不受影响，不需要迁移。
- `docs/known-issues.md` 的"P/1-bit 输入的配置暂不转换"一条关闭；保留灰度设备空间配置、CMYK 配置、16-bit RGB 解码降位、PNG 无 alpha 四条真实限制。
- 新增 `docs/color-management.md` 作为色彩策略权威文档，新增 17 个测试函数（`tests/test_color_management.py`，参数化后 28 个用例）与 1 条预览嵌入断言。
- 后端测试从 781 + 1 skipped 增至 **810 passed, 1 skipped**；黄金图 27 例逐字节不变。

## 未采纳的方案

- **给 API 增加 `inputColorSpace` / `hasIccProfile` 响应字段**：属于观测性扩展，会改契约与前端类型，且本任务无需求驱动 → 不做。
- **改用 16-bit 代理**：实测收益低于 4 级，代价是代理缓存体积翻倍与全部代理缓存重建 → 不做（D3）。
- **`convert("RGB")` 之前先做 lcms（保持原顺序，只对 P 模式特判）**：会形成第二条色彩路径和更多分支，且无法覆盖 `1`/`L`/`LA`；顺序调整方案更短且已由黄金图证明安全 → 不做。
- **CMYK 走 lcms 组合配置**：`CMYK` + RGB 设备空间配置的 lcms 组合实测不合法（抛 `PyCMSError`），且这本身就是错误输入；保留静默回退并在文档中记为限制 → 不修。
