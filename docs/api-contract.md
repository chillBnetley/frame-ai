# FRAME AI API 契约（阶段 2 / 阶段 3 / 阶段 4）

- 状态：已实现并同步至阶段 4 Task 7，2026-11-04
- 适用：开发阶段 2（图像管线、非破坏编辑、会话与导出）、阶段 3（AI 分析任务、诊断报告）与阶段 4（曲线、HSL、颜色分级、局部蒙版）
- 机器可读契约：[`shared/contracts/openapi.json`](../shared/contracts/openapi.json)
- 前端类型：[`apps/web/types/api.d.ts`](../apps/web/types/api.d.ts)
- 决策依据：[ADR-0002](decisions/ADR-0002-phase-2-decisions.md)、[ADR-0003](decisions/ADR-0003-compare-geometry-alignment.md)、[ADR-0004](decisions/ADR-0004-color-management.md)（色彩管理策略与依赖边界）
- 色彩策略：[docs/color-management.md](color-management.md)——输入 ICC 处理、默认解释策略、位深取舍与输出嵌入的权威描述

本文细化任务书 §7，并登记所有**相对任务书的契约扩展**（以 ⊕ 标记）。实现以 OpenAPI 与代码为准；两者不一致时先修代码或重新导出契约，不得只改文档。

## 1. 通用约定

- 基础前缀：`/api/v1`。
- JSON 字段一律 camelCase（D-12）。数据库、内部规范 JSON 与日志使用 snake_case。
- 请求与响应编码：UTF-8；时间戳为 RFC 3339 UTC，例如 `2026-11-02T08:00:00.000Z`。
- ID 为 UUID 字符串；无法解析的 ID 按资源不存在处理，返回 404，不泄漏内部错误。
- 所有响应带 `X-Request-ID`。
- 错误统一信封：

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "The edit state has changed; reload the session before committing.",
    "details": {}
  }
}
```

`details` 可能为空对象、字段列表或具体上限。它只用于诊断与前端文案，不是稳定业务字段；稳定字段是 HTTP 状态码与 `code`。

### 1.1 状态码

| 状态码 | 用途 |
| --- | --- |
| 200 | 读取成功、更新成功、幂等重放 |
| 201 | 新建图片、会话或 revision |
| 202 | 分析任务已创建并进入后台队列 |
| 204 | 删除分析任务成功，无响应体 |
| 400 | 请求体本身错误（空文件、多个 `file` 字段、缺少字段），或 Host 头不在允许列表 |
| 403 | 写入请求的来源不在允许列表，或浏览器标记为跨站写入 |
| 404 | 图片、会话、revision 或预览不存在 |
| 409 ⊕ | 状态冲突：父 revision 不是活动版本、无可撤销/重做步骤、渲染已被更新请求取代 |
| 413 | 文件字节、像素数或导出预估内存超限 |
| 415 | 无法解码、MIME 与内容不符、格式不支持、动画图 |
| 422 | 字段校验失败（范围、两位小数、crop 越界等） |
| 500 | 未预期错误或本地存储失败 |
| 503 | 导出/渲染串行槽位被占用，或服务未就绪 |

任务书的状态码清单没有 403、409。并发/历史冲突使用 409、本机来源防护使用 403 是阶段 2 的契约扩展；具体 `code` 见 §4 与 §6。

### 1.2 本机边界

API 只绑定 `127.0.0.1`，无鉴权、无限流（D-13）。启动命令必须显式使用 `--host 127.0.0.1`；不得把端口暴露到公网或反向代理到公网。任何部署加固都属于后续阶段。

### 1.3 Host 与来源防护（阶段 2.1）

API 在本机边界之上再加两道轻量防护，避免 DNS 重绑定与浏览器跨站写入：

- **Host 校验**：所有 HTTP 请求的 `Host` 主机名必须位于 `FRAME_ALLOWED_HOSTS`（默认 `127.0.0.1,localhost,::1`），否则返回 400 `invalid_host`。列表留空时跳过校验。
- **来源校验**：仅对非安全方法（`POST` 等，`GET/HEAD/OPTIONS` 不受限）检查：
  - 带 `Origin` 且不在 `FRAME_ALLOWED_ORIGINS` → 403 `origin_not_allowed`；
  - 浏览器标记 `Sec-Fetch-Site: cross-site` → 403 `origin_not_allowed`。
- **CORS 预检**：`OPTIONS` 预检的来源不在允许列表时返回 403 `cors_origin_denied`；请求的方法不在允许列表（`GET/POST/DELETE/OPTIONS`）时返回 405 `cors_method_denied`。两者都用统一错误信封，不再由 CORS 中间件返回 `text/plain`。
- **请求体上限**：中间件按真实接收字节计数，分两档——`/api/v1/images` 走 `FRAME_MAX_UPLOAD_BYTES`（`Content-Length` 预检再放宽 `FRAME_CONTENT_LENGTH_ALLOWANCE` 的 multipart 封装开销），其余 `POST/PUT/PATCH` 写口走 `FRAME_MAX_JSON_BODY_BYTES`（默认 2 MiB）。超限返回 413 `payload_too_large`，`details.maxBytes` 是该路由对外的上限、`details.maxBodyBytes` 是实际执行的上限（只有上传档因 multipart 余量而比 `maxBytes` 大）。
- **未知字段**：所有请求体模型都设 `extra="forbid"`（OpenAPI 中对应 `additionalProperties: false`）。拼错的字段（如把 `maxEdge` 写成 `maxEge`）返回 422 `validation_error`，`details.fields[].rule` 为 `extra_forbidden`，不会静默按默认值执行。

默认允许来源为 `http://localhost:3000,http://127.0.0.1:3000`；通过 Next.js 同源代理访问时无需修改。若前端换端口、换主机名，或使用 `NEXT_PUBLIC_API_BASE_URL` 直连 API，必须同步更新 `FRAME_ALLOWED_ORIGINS`。这些检查不是鉴权，只降低浏览器与被诱导请求的风险。

## 2. 会话状态对象

创建、读取、提交、撤销、重做、激活、重置均返回同一结构：

```json
{
  "sessionId": "6f8f0b0e-6a8e-4f1b-9b1e-5b8f0b9c1a2d",
  "imageId": "1d3f9f8a-2f5a-4a7c-9a2e-0b6a1c2d3e4f",
  "activeRevisionId": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
  "headRevisionId": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
  "canUndo": true,
  "canRedo": false,
  "revision": {
    "id": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
    "revisionNo": 3,
    "parentId": "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "source": "user",
    "recipe": { "...": "见 §3" },
    "createdAt": "2026-11-02T08:00:00.000Z"
  }
}
```

语义：

- `activeRevisionId`：当前正在编辑/渲染的 revision。
- `headRevisionId`：历史路径末端。新建 revision 时 `active` 与 `head` 同时移到新节点；undo/redo/activate 只移动 `active`，不改 `head`。
- `canUndo`：活动 revision 存在 `parentId`。
- `canRedo`：从 `head` 沿 `parentId` 回溯的路径上存在活动 revision 的下一节点。
- `source ∈ {initial, user, ai, reset}`；客户端只能提交 `user` 或 `ai`。

## 3. 配方（EditRecipe）

当前版本为 `2.0`。阶段 2 保存的 `1.0` 配方在读取或提交时会自动升级为 `2.0`，不修改数据库中的历史值。

```json
{
  "schemaVersion": "2.0",
  "styleId": "natural",
  "styleStrength": 0,
  "adjustments": {
    "exposureEv": 0,
    "contrast": 0,
    "highlights": 0,
    "shadows": 0,
    "whites": 0,
    "blacks": 0,
    "temperature": 0,
    "tint": 0,
    "saturation": 0,
    "vibrance": 0,
    "clarity": 0,
    "sharpen": 0,
    "denoise": 0,
    "vignette": 0,
    "grain": 0,
    "rotationDeg": 0,
    "crop": null
  },
  "curve": {
    "master": [],
    "red": [],
    "green": [],
    "blue": []
  },
  "hsl": {
    "red": { "hue": 0, "saturation": 0, "luminance": 0 },
    "orange": { "hue": 0, "saturation": 0, "luminance": 0 },
    "yellow": { "hue": 0, "saturation": 0, "luminance": 0 },
    "green": { "hue": 0, "saturation": 0, "luminance": 0 },
    "aqua": { "hue": 0, "saturation": 0, "luminance": 0 },
    "blue": { "hue": 0, "saturation": 0, "luminance": 0 },
    "purple": { "hue": 0, "saturation": 0, "luminance": 0 },
    "magenta": { "hue": 0, "saturation": 0, "luminance": 0 }
  },
  "colorGrading": {
    "shadows": { "hue": 0, "saturation": 0 },
    "midtones": { "hue": 0, "saturation": 0 },
    "highlights": { "hue": 0, "saturation": 0 },
    "balance": 0,
    "blending": 50
  },
  "masks": [
    {
      "id": "mask_001",
      "shape": "rectangle",
      "source": "user",
      "coordinateSpace": "source-normalized",
      "x": 0.2,
      "y": 0.15,
      "width": 0.45,
      "height": 0.55,
      "feather": 15,
      "opacity": 100,
      "inverted": false
    }
  ],
  "localAdjustments": [
    {
      "id": "local_001",
      "maskId": "mask_001",
      "enabled": true,
      "adjustments": { "exposureEv": 0.35, "contrast": 5, "saturation": -8 }
    }
  ],
  "output": {
    "format": "jpeg",
    "quality": 92,
    "colorSpace": "sRGB"
  },
  "rationale": [],
  "warnings": []
}
```

| 字段 | 范围 / 规则 |
| --- | --- |
| `exposureEv` | −5…5 |
| 其余全局/局部色彩与细节参数 | −100…100；全局 `sharpen/denoise/grain` 为 0…100 |
| `rotationDeg` | −15…15（仅全局） |
| `crop` | `null` 或 `{x,y,w,h}`；`x,y∈[0,1]`，`w,h∈(0,1]`，`x+w≤1`、`y+h≤1` |
| `curve.*` | 每个通道 0 或 ≥2 个点，最多 32 个；`x,y∈[0,1]`；按 `x` 严格递增；最多六位小数 |
| `hsl.<band>.hue` | −180…180 |
| `hsl.<band>.saturation/luminance` | −100…100 |
| `colorGrading.<zone>.hue` | 0…360 |
| `colorGrading.<zone>.saturation` | 0…100 |
| `colorGrading.balance` | −100…100 |
| `colorGrading.blending` | 0…100，默认 50 |
| `masks` | 最多 20 项；`id` 匹配 `^mask_[A-Za-z0-9_-]{1,58}$` 且唯一；`shape` 为 `rectangle` 或 `ellipse`；`source` 固定 `user`；`coordinateSpace` 固定 `source-normalized`；最多 4 位小数 |
| `masks[].x/y` | 0…1；`masks[].width/height` 为 (0,1]；`x+width≤1`、`y+height≤1` |
| `masks[].feather/opacity` | 0…100，默认分别为 15 / 100；`inverted` 必须是布尔值 |
| `localAdjustments` | 最多 20 项；`id` 匹配 `^local_[A-Za-z0-9_-]{1,58}$` 且唯一；`maskId` 为 `full` 或 `mask_*`；`enabled` 必须是布尔值 |
| `localAdjustments[].adjustments` | v1 支持 `exposureEv/contrast/highlights/shadows/whites/blacks/temperature/tint/saturation/vibrance/clarity`；`sharpen/denoise/vignette/grain` 必须为 0，否则 422 |
| `output.format` | `jpeg` 或 `png` |
| `output.quality` | 整数 1…100，默认 92 |
| `output.colorSpace` | 固定 `sRGB`（`Literal["sRGB"]`，其他值 422）；输出目标色彩空间恒为 sRGB 并嵌入 sRGB ICC，见 [色彩管理](color-management.md) |
| `rationale/warnings` | 每条 ≤200 字符，各最多 8 条 |
| 数值 | 必须是 JSON number；全局与局部参数最多两位小数，曲线最多六位；拒绝 `NaN/Infinity`；超出范围返回 422，不静默夹紧（D-11） |

补充：

- 所有层级都拒绝未知字段（`extra="forbid"`），防止拼写错误被静默忽略。
- 缺省字段取默认值；`crop` 缺省为 `null`，曲线通道缺省为空数组，`masks` 与 `localAdjustments` 缺省为空数组。
- 旧版 `schemaVersion:"1.0"` 只补齐新字段并升级版本号；版本号不是 `1.0` 或 `2.0` 的配方直接拒绝。
- `styleId/styleStrength`、`rationale/warnings`、`output` 是元数据或输出偏好；预览缓存只按真正影响像素的字段（`adjustments/curve/hsl/colorGrading/masks/localAdjustments`）计算哈希。自阶段四复审（v2.1 口径）起，`output`、`styleId`、`styleStrength` 也不进入 revision 身份（canonical 哈希）：改导出格式或风格只改变请求行为，不会再生成“像素完全相同”的新 revision。空 `masks` 不出现在 canonical/pixel JSON 中，是唯一被省略的惰性字段。`schemaVersion` 仍参与 canonical 哈希，所以 v1→v2 重标会改变同一旧配方在新代码下计算出的摘要；`recipe_hash` 列仅作缓存，`reset` 与幂等命中都用当前代码从已存 `recipe_json` 重新推导后比较，不承诺跨版本哈希恒定。
- 客户端发送前必须做舍入：全局与局部参数 `roundTo2`，曲线 `roundTo6`，并把 `-0` 归零。
- 色温 / 色调语义：对线性光施加固定三通道增益（红 `1+0.25·T`、绿 `1−0.12·M`、蓝 `1−0.25·T`），再用**一个全图标量**把平均 Rec.709 亮度拉回原值。守恒对象是全图均值而非逐像素，因此高饱和的红/蓝区域会真正随色温移动（逐像素守恒会在这些像素上自我抵消）；接近纯白的高光仍可能因通道增益而削顶。
- 曲线语义：空数组表示恒等；单点被拒绝；通道按 Master → Red → Green → Blue 依次应用；使用 Fritsch–Carlson 单调三次 Hermite 预计算 8192 格点 LUT 并在格点间线性插值（与逐点 Hermite 最大偏差实测 0.000918，低于半个 8-bit 级），首末节点之外按**端点斜率线性外推**后截断到 `[0,1]`（不再保持端点值），因此悬空曲线不会把暗部/高光压平。曲线在对比度之后、饱和度/自然饱和度之前执行，作用在 sRGB 编码值上。
- HSL 语义：八个色带中心为 0°/30°/60°/120°/180°/240°/285°/330°（红/橙/黄/绿/青/蓝/紫/洋红），相邻中心之间用 smoothstep 权重平滑过渡并在 0°/360° 首尾相接。由于中心不等距，每条带的有效范围（到相邻中心为止）不同：红 330°–30°（60°）、橙 0°–60°（60°）、黄 30°–120°（90°）、绿 60°–180°（120°）、青 120°–240°（120°）、蓝 180°–285°（105°）、紫 240°–330°（90°）、洋红 285°–30°（105°）；同值滑块在窄带上的覆盖范围小、在宽带上的覆盖范围大，这是保持既有配方观感的代价。`hue` 为相对色相偏移，`saturation` 为色度缩放（−100 变为灰色、+100 最多加倍），`luminance` 为明度增益（±100 对应 ±1 EV），结果截断到合法范围。色相偏移受**单调性上限**约束：相邻带心间距越小，允许的两带偏移差越小（约束为 `|ΔH_i − ΔH_j| ≤ gap·0.95/1.5`，超出的部分对半分给这一对），因此 30° 间距上的单个色带 `hue` 约在 ±20° 后不再增加，60° 间距约 ±40°；这保证了输出不会出现局部色相反序或等色轮廓带。低色度门控分两档：`hue` 在 `max−min` 0.02→0.10 上渐入（色相在色度趋零时无定义），`saturation/luminance` 在 0.005→0.03 上渐入，因此皮肤、天空与浅色背景上的明度/饱和度滑块仍然有效；完全无彩色像素不受影响，全部为 0 时恒等。HSL 在曲线之后、饱和度/自然饱和度之前执行。
- 颜色分级语义：按 Rec.709 亮度把像素平滑分配到阴影 / 中间调 / 高光，三个权重恒和为 1；`hue` 为色偏方向，`saturation` 为该区域强度（0…100），`balance` 平移亮度锚点（±100 对应 ±0.25），`blending` 控制区域过渡宽度（0…100 映射到 0.08–0.60）。色偏使用零亮度方向向量，并把向量**等比缩放到刚好不越出 `[0,1]`**（不再逐通道裁剪），因此输出亮度严格等于输入亮度，越界像素只是分级力度减弱；三个区域强度均为 0 时恒等。颜色分级在饱和度/自然饱和度之后、清晰度/暗角之前执行。
- 蒙版语义：`x/y/width/height` 锚定 EXIF 方向归一化后的原图坐标，不随预览/导出尺寸变化；矩形按轴对齐、椭圆为内接椭圆，羽化带完全位于形状内部，形状外权重严格为 0；`inverted` 在形状权重之后取反，`opacity` 最后缩放。`maskId:"full"` 使用内置全图蒙版，不需要对应的 `masks` 项。前端人物/天空按钮仅为禁用占位，后端没有 `person`/`sky` 类型，也不把阶段三 bbox 当作蒙版。
- 局部调整语义：v1 只实现 11 个字段，顺序为线性光曝光/白平衡/高光/阴影/白场/黑场 → sRGB 对比度 → 饱和度/自然饱和度 → 清晰度；每个局部调整按 `id` 字典序依次混合，后一项看到前一项的结果。`sharpen/denoise/vignette/grain` 非零返回 422（避免静默忽略）。局部阶段在颜色分级之后、全局清晰度/暗角之前执行；`enabled=false`、全零参数、`opacity=0` 或蒙版完全在裁切外时等价于恒等。
- 蒙版引用：`maskId` 不在 `masks` 中时，服务端跳过该局部调整并在渲染/导出 warnings 中返回 `local_mask_missing:<maskId>`；不回退到全图或错误区域，也不返回 5xx。前端恢复会话时若发现悬空引用，显示“蒙版缺失，已停用此局部调整”并提供删除入口。
- 引擎版本 `frame-engine/10` 改变五处像素/契约语义：Blacks 正向改为一律压暗（Lightroom 约定，掩膜端点 0.30→0.20）、HSL 低色度门控按参数分档（色相 0.02→0.10，饱和度/明度 0.005→0.03）、曲线首末节点外改为端点斜率线性外推、对比度后把色度回收至原值 ±5% 容差内，并删除遗留 `POST /images/{id}/analyze`；`frame-engine/9` 改变三处像素语义：白平衡的亮度守恒从逐像素改为全图均值标量、HSL 色相改为受单调上限约束的查表映射、颜色分级越界由逐通道裁剪改为等比缩放到边界；`frame-engine/8` 把嵌入 ICC 管理的范围从 `RGB`/`RGBA` 扩展到全部可归一为 RGB 的模式（`P`/`PA`/`1`/`L`/`LA`）；`frame-engine/7` 起局部调整参与渲染；`frame-engine/6` 引入颜色分级，`frame-engine/5` 引入 HSL，`frame-engine/4` 引入曲线。预览缓存键包含 `curve`、`hsl`、`colorGrading`、`masks` 与 `localAdjustments`，任一变化都会产生新的 `previewId`。
- 规范化会把局部调整按 `id` 排序，保证相同语义的配方得到相同哈希。

## 4. 端点

### 4.1 系统与图片（阶段 1 延续）

| 方法与路径 | 请求 | 响应 | 主要错误 |
| --- | --- | --- | --- |
| `GET /api/v1/health` | — | `{status, service, version, storage:{ok,writable}}` | — |
| `GET /api/v1/config` | — | `{maxUploadBytes, maxJsonBodyBytes, maxImagePixels, allowedMimeTypes}` | — |
| `POST /api/v1/images` | multipart，唯一 `file` 字段 | 201 `{imageId, originalName, width, height, exifOrientation, mimeType, bytes}` | 400 `invalid_upload`/`empty_file`；413 `payload_too_large`/`file_too_large`；415 `invalid_image`/`mime_mismatch`/`unsupported_media_type`/`animated_not_supported`；500 `storage_error` |
| `GET /api/v1/images/{imageId}/original` | 可选 `?download=true` | 原始字节；`inline` 或 `attachment` | 404 `image_not_found`/`image_file_missing` |

`width/height` 是 EXIF 方向归一后的显示尺寸；`exifOrientation` 保留原始 1–8（D-07）。原图字节从上传到导出全程不变。阶段三遗留的 `POST /api/v1/images/{imageId}/analyze` 已在阶段四复审中删除（前端无引用，且与任务化 `POST /api/v1/analysis` 重复）；图像分析统一走 `/analysis` 任务接口。

**原图与输出的色彩差异**（详见 [色彩管理](color-management.md)）：`/original` 返回上传时保存的原始字节，因此**保留原嵌入 ICC 配置与原 EXIF/GPS**；预览与导出则按 §1 的策略把输入转换到 sRGB、重编码为 8-bit sRGB、剥离全部元数据并**嵌入固定 sRGB ICC**。契约是"原图不动、输出重编码"，分享场景应使用导出而非原图下载。上传入口只接受 JPEG/PNG/WebP；`loader` 能解码更多容器（实测 TIFF），但不受入口暴露。`X-Export-Warning` 只承载降噪与蒙版缺失提示，与色彩无关。

该端点是阶段 2 的启发式特征（`features.isHeuristic=true`），不调用外部模型，结果只在进程内 LRU 缓存。阶段 3 的 AI 分析与持久化使用 §4.6 的 `/analysis` 任务端点，两者并存但互不替代。

### 4.2 会话

| 方法与路径 | 请求 | 响应 | 主要错误 |
| --- | --- | --- | --- |
| `POST /api/v1/sessions` | `{imageId}` | 201 会话状态；创建 `source=initial` 的默认配方 revision | 404 `image_not_found`；422 |
| `GET /api/v1/sessions/{sessionId}` | — | 会话状态 | 404 `session_not_found` |
| `GET /api/v1/sessions/{sessionId}/revisions` ⊕ | `?limit=20&cursor=3` | `{items:[{id, revisionNo, parentId, source, recipeHash, createdAt}], nextCursor}`；按 `revisionNo` 降序 | 404 `session_not_found`；422 |
| `POST /api/v1/sessions/{sessionId}/render` | `{recipe, maxEdge?, quality?}` + 可选头 `X-Render-Seq` | 200 `{previewUrl, width, height, quality, cacheHit, warnings}`；无状态，不写数据库 | 404 `session_not_found`/`image_not_found`；409 `render_superseded`；422 `validation_error`；503 `server_busy` |
| `POST /api/v1/sessions/{sessionId}/revisions` | `{recipe, parentRevisionId, source?}` + 头 `Idempotency-Key` | 201 新 revision 并设为活动；同 key 同内容重放 200 原 revision | 409 `revision_conflict` / `idempotency_key_reuse`；404；422 |
| `POST /api/v1/sessions/{sessionId}/undo` | 可选 `{revisionId}` | 会话状态；仅移动 `active` | 409 `nothing_to_undo`；409 `revision_conflict`（客户端期望版本不符） |
| `POST /api/v1/sessions/{sessionId}/redo` ⊕ | — | 会话状态；沿通往 `head` 的路径前进一步 | 409 `nothing_to_redo` |
| `POST /api/v1/sessions/{sessionId}/activate` ⊕ | `{revisionId}` | 会话状态；切到会话内任意 revision，不改 `head` | 404 `revision_not_found` |
| `POST /api/v1/sessions/{sessionId}/reset` | — | 会话状态；若活动配方已是默认配方，直接返回当前状态且不新增 revision | 404 |
| `GET /api/v1/sessions/{sessionId}/compare` | `?revisionId=&maxEdge=1600` | `{original:{previewUrl,width,height}, revision:{previewUrl,width,height}, warnings}` | 404 |
| `POST /api/v1/sessions/{sessionId}/export` | ⊕ `{revisionId, format:"jpeg"\|"png", quality?, maxEdge?, colorSpace?}` | 文件流 + `Content-Disposition` + `X-Export-Width/Height`；必要时带 `X-Export-Warning`（逗号分隔，如 `denoise_simplified`、`local_mask_missing:<maskId>`） | 404；413 `export_too_large`；422；503 `server_busy` |
| `GET /api/v1/previews/{previewId}` ⊕ | — | `image/jpeg` | 404 `preview_expired` |

#### 提交 revision 与幂等

```http
POST /api/v1/sessions/{sessionId}/revisions
Idempotency-Key: 8f3a1c6e-6e1c-4b0b-9b3a-2f0d5c7e9a11
Content-Type: application/json

{
  "recipe": { "schemaVersion": "2.0", "adjustments": { "exposureEv": 0.2 } },
  "parentRevisionId": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
  "source": "user"
}
```

- `parentRevisionId` 必须等于当前 `activeRevisionId`，否则 409 `revision_conflict`，`details.activeRevisionId` 给出服务端当前值。
- 同一会话内 `Idempotency-Key` 唯一；网络重试必须复用同一个 key。重放返回原 revision 与会话状态，HTTP 200。key 最多 200 字符，空串按未提供处理。
- 同 key 但 `recipe` 哈希或 `parentRevisionId` 与首次请求不一致时返回 409 `idempotency_key_reuse`，`details.revisionId` 给出已占用该 key 的 revision；不会静默返回旧 revision。
- 不要在同一 key 下提交不同意图的配方；服务端会拒绝内容或父 revision 不一致的重用。
- 新建 revision 在 `BEGIN IMMEDIATE` 事务中完成校验、取号、插入与活动/head 更新；单进程串行，不产生重复 `revisionNo`。
- 在历史中间提交会从该 revision 分支，并把 `head` 移到新节点；旧分支仍可 activate。

#### undo / redo / activate / reset

- undo 传 `revisionId` 表示“客户端认为的当前活动版本”；不一致返回 409 `revision_conflict`，避免误撤销别人的状态。
- undo 到初始 revision 后再撤销 → 409 `nothing_to_undo`。
- redo 只沿 `active → head` 的路径前进；不存在目标 → 409 `nothing_to_redo`。
- activate 可以跳到任意历史 revision（阶段 4 历史切换的基础）；不修改 `head`，之后 redo 仍沿原 head 路径。
- reset 生成 `source=reset` 的默认配方 revision 并移动 `active/head`；若当前活动配方哈希已等于默认配方，则不加历史记录。

### 4.3 render 与预览

```http
POST /api/v1/sessions/{sessionId}/render
X-Render-Seq: 42
Content-Type: application/json

{
  "recipe": { "...": "..." },
  "maxEdge": 1600,
  "quality": "final"
}
```

```json
200
{
  "previewUrl": "/api/v1/previews/9a7c...e1",
  "width": 1600,
  "height": 1067,
  "quality": "final",
  "cacheHit": false,
  "warnings": []
}
```

- `quality ∈ {draft, final}`，默认 `final`。
- `maxEdge` 默认 1600，范围 1…2560；实际边长不会超过原图最长边。
- 响应中的 `width/height` 是**旋转内接并裁切后的画布尺寸**，前端据此绘制裁切框与对比容器（D-04）。引擎版本 `frame-engine/2` 起，旋转只缩小画布，内容不再二次缩放，画布不包含源图之外的像素。
- render 无状态：不改会话、不新增 revision，只可能写入预览缓存文件。
- `cacheHit=true` 表示命中内容寻址缓存，未重新渲染。
- `warnings` 是本次渲染中**被跳过或简化**的非致命步骤，可能含 `local_mask_missing:<maskId>`（局部调整引用的蒙版不存在，已跳过）。预览档的 warnings 只由配方决定，因此缓存命中时按同一规则重算，不会丢失；前端把该值存进 `preview.warnings` 并在局部调整面板标注被跳过的条目。
- `X-Render-Seq` 是可选的非负整数，客户端在同一会话内单调递增。服务端按会话记录最大序号；等待渲染槽位期间若出现更新的序号，当前请求返回 409 `render_superseded`，不写入预览。前端静默忽略该错误，因为更新请求会提供结果。命中缓存时直接返回，不做 superseded 检查。
- ⊕ 阶段四：前端用 `nextRenderSeq()`（`apps/web/lib/render-seq.ts`）统一发号，取 `max(Date.now(), 上一次 + 1)`，滑杆预览与裁切底图共用同一个计数器。用时钟是为了让同一会话在页面重挂载、多标签页之间仍然可比，`+1` 下限保证同一毫秒内的两次请求也严格递增；共用计数器避免裁切底图被滑杆请求判定为过期。`renderPreview` 的序号参数默认值仍是 `Date.now()`；完全不带该头时服务端不记录序号、也不做 superseded 判断。
- 同进程最多并发执行 2 次渲染；等待槽位超过 10 秒返回 503 `server_busy`，带 `Retry-After: 1`。
- 预览渲染的方向归一/缩放代理图另缓存于 `data/tmp/previews/proxies/`，键含原图 SHA-256、代理版本与按 64 px 向上取整的最长边。命中时刷新 mtime，再缩放到请求边长；写入失败只记录日志并继续使用内存中的代理图。
- ⊕ 阶段四：解码后的代理图还有一层进程内 LRU（`FRAME_PROXY_CACHE_MB`，默认 64，0 关闭），让连续拖动滑杆在同一路径长度下只解码原图一次。只有能无损表示为 8 bit 的数组才入缓存，缓存条目取出时复制，因此开关缓存的字节输出完全一致。
- ⊕ 阶段四：局部调整的蒙版权重同样有进程内 LRU（`FRAME_MASK_CACHE_MB`，默认 64，0 关闭），键含蒙版几何、画布尺寸、旋转与裁切（不含蒙版 id，形状相同的蒙版共享权重）。缓存数组只读；单条超过 24 MB 不入库——24 MP 画布的权重约 91.55 MB，因此大导出不会占用长期内存。开关缓存的字节输出一致。

`previewId` 由原图 SHA-256、引擎版本、规范化像素配方（`adjustments/curve/hsl/colorGrading/localAdjustments`）、实际边长与质量共同哈希得到（64 位小写十六进制）；`styleId/styleStrength`、`rationale/warnings` 与 `output` 不影响预览缓存。`GET /previews/{previewId}`：

- 返回 JPEG，`Cache-Control: private, max-age=<FRAME_PREVIEW_TTL_SECONDS>`。
- 带 `X-Content-Type-Options: nosniff` 与 CSP `default-src 'none'; sandbox`。
- 文件不存在或已清理 → 404 `preview_expired`；前端应静默重新 render，不弹错误。
- 预览文件位于 `data/tmp/previews/`，按 mtime 超过 TTL（默认 3600 秒）清理；启动时清一次，运行中每 10 分钟清一次。清理只处理该目录内的普通文件，跳过符号链接与子目录；`proxies/` 内的代理图不会被预览清理误删。

### 4.4 compare

```json
GET /api/v1/sessions/{sessionId}/compare?revisionId=<uuid>&maxEdge=1600
```

```json
200
{
  "original": {
    "previewUrl": "/api/v1/previews/1c2d...aa",
    "width": 1600,
    "height": 1067
  },
  "revision": {
    "previewUrl": "/api/v1/previews/9a7c...e1",
    "width": 1600,
    "height": 1067
  },
  "warnings": []
}
```

- `warnings` 汇总两侧渲染的非致命告警（目前为 `local_mask_missing:<maskId>`，去重后保留顺序）；原图侧只应用几何，通常为空。

- `revisionId` 省略时使用当前活动 revision；必须属于该会话。
- `maxEdge` 默认 1600，范围 1…2560。
- “原图”会应用该 revision 的旋转与裁切，但不做任何色调、色彩、细节调整；两张图尺寸一致，便于像素对齐对比。这是对任务书 §7.5“原图不含任何编辑”的有意偏离，原因见 [ADR-0003](decisions/ADR-0003-compare-geometry-alignment.md)。

### 4.5 export

```json
POST /api/v1/sessions/{sessionId}/export
{
  "revisionId": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
  "format": "jpeg",
  "quality": 92,
  "maxEdge": 2400,
  "colorSpace": "sRGB"
}
```

`maxEdge` 与 `colorSpace` 都可省略；省略 `maxEdge` 表示按原图长边导出。

响应：

- `Content-Type: image/jpeg` 或 `image/png`。
- `Content-Disposition: attachment; filename="frame-<8位id>.jpg"`（或 `.png`）。
- `X-Export-Width`、`X-Export-Height`：实际导出像素尺寸；等于请求 `maxEdge` 限制后的画布尺寸（未请求时是旋转/裁切后的完整画布尺寸）。
- 本次**实际参与渲染的像素**（应用 `maxEdge` 下采样之后）超过 `FRAME_EXPORT_DENOISE_SIMPLIFY_PIXELS`（默认 12 MP）且启用了降噪时，导出使用与 draft 相同的较小降噪搜索窗口，并带 `X-Export-Warning: denoise_simplified`；无简化时省略此头。因此同一张大图的全尺寸导出会带该头、长边 2400 的导出不会。前端应向用户显示“大图导出使用简化降噪”。
- `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。

规则：

- 从**原始分辨率**重渲染，不使用预览代理图。
- `revisionId` 必须属于该会话，否则 404 `revision_not_found`。
- JPEG `quality` 1…100，默认 92；quality ≥ 90 时 `subsampling=0`。PNG 忽略 quality。
- ⊕ `maxEdge`（64…100000 整数）指定输出的最长边；长边在该边长内保持不变，超过原图长边的请求**不放大**。边长在旋转/裁切之后的画布上测量，比例与构图与全尺寸导出一致（实测与全尺寸导出缩放到同画布后平均差 0.205、最大 1 灰阶）。前端导出对话框的自定义输入更严格：64…8192，留空表示原图尺寸。
- ⊕ `colorSpace` 只接受字面量 `"sRGB"`；其他值（含小写 `"srgb"`）返回 422 `validation_error`。输出目标恒为 sRGB，因此该字段是显式声明而不是可选项。
- 导出准入（⊕ 阶段四）：并发上限 `FRAME_EXPORT_MAX_CONCURRENCY`（默认 1，即串行）。超出并发数，或**已在跑的导出估算之和 + 本次估算**超过 `FRAME_EXPORT_MAX_RSS_MB` 时，立即返回 503 `server_busy` 并带 `Retry-After: 2`，不排队等待。通过静态估算后还有第二道实时门（复审整改 G4/P3-9）：用 `psutil.virtual_memory().available` 检查真实可用内存，若 `可用 − 本次估算 < FRAME_EXPORT_RESERVE_MB`（默认 256）同样返回 503 `server_busy`；该检查在静态估算之后执行，不替代它。
- ⊕ 阶段四：导出**不支持服务端中止**。客户端断开或超时只停止前端等待，服务端会继续完成本次渲染后丢弃结果（导出不写缓存），因此期间新的导出仍可能拿到 503。
- 解码前按**本次计划触及的像素数**与配方估算峰值内存（系数在阶段四 Task 8 按实测标定，复审整改 G4 把满配方从 240 下调到 160 B/px）：中性配方 45 B/px，其余 160 B/px；每个启用且参数非零的局部调整再加 8 B/px（一张全画布 float32 权重图约 4 B/px；实测增加局部调整对峰值的影响在 −48…+29 MB 之间，所以这 8 B/px 是余量而不是预测）；另加 150 MB 基线。
- ⊕ **解码地板**：原图始终按整尺寸解码，所以估算不低于"原图像素 × 45 B/px + 150 MB"。带 `maxEdge` 时计划项按缩放后的源像素计算，因此下采样导出可以落入全尺寸导出被拒绝的预算；但一旦计划项掉到地板以下，再小的 `maxEdge` 也不会让估算继续下降（40 MP 原图的地板是 1863 MB）。
- 估算超过 `FRAME_EXPORT_MAX_RSS_MB`（默认 3072）时返回 413 `export_too_large`，`details.estimatedPeakMb/limitMb/pixels/maxEdge` 给出估算、上限与本次尺寸，避免大图导出拖垮进程。默认预算下的实测边界（G4，估算／实测峰值）：40 MP 中性 1867／1635 MB 与 12 MP 满配方 1981／1478 MB **可导出**；24 MP 满配方 3812／2907 MB 与 40 MP 满配方 6254／4793 MB **返回 413**（满配方系数为 160 B/px，高于本轮实测最高的 131 B/px，仍保留约 22% 余量）。同一批图片改为 `maxEdge=2400` 后可导出，估算 1180／实测 794 MB（24 MP）与 1867／实测 1209 MB（40 MP），耗时 p95 4.3 s 与 5.0 s。
- 元数据：剥离全部 EXIF/XMP/IPTC（含 GPS）；嵌入标准 sRGB ICC；PNG 不写 `eXIf`/`tEXt`/`iTXt`（D-09）。ICC 头部创建时间固定，保证同一像素与参数跨进程编码逐字节一致。
- 输出目标色彩空间**恒为 sRGB**、8-bit/通道、RGB 三通道（不带 alpha）；预览 JPEG 同样嵌入 sRGB ICC 且不含 EXIF。原图的 ICC 配置不保留到输出，输入按 [色彩管理](color-management.md) §1 的策略转换或回退。
- 原图字节不被改写；日志只记录 sessionId、revisionId、格式、字节数与耗时。

#### 阶段 2 的 PNG alpha 限制

任务书要求“导出 PNG 保留 alpha；导出 JPEG 合成到白底”。阶段 2 的 loader 会把所有带 alpha 的输入统一合成到白底并转为 RGB，因此**导出的 PNG 目前没有 alpha 通道**，语义等同于白底合成。这是已记录的实现缺口，不是契约承诺；修复计划见 [known-issues.md](known-issues.md)。

### 4.6 分析任务与报告（阶段 3）

| 方法与路径 | 请求 | 响应 | 主要错误 |
| --- | --- | --- | --- |
| `POST /api/v1/analysis` ⊕ | `{imageId, options?, force?}` | 202 `{analysisId, status, stage, deduplicated}`；去重命中返回 200 | 400 `invalid_analysis_options`；404 `image_not_found`；413 `analysis_input_too_large`；503 `server_busy`（队列已满）；500 `storage_error`（任务行写入失败） |
| `GET /api/v1/analysis/{analysisId}` ⊕ | — | 状态对象；`completed` 时 `result` 内嵌完整报告 | 404 `analysis_not_found` |
| `GET /api/v1/analysis/{analysisId}/result` ⊕ | — | `stage3/1` 报告 | 404 `analysis_not_found`；409 `analysis_not_ready`；500 `analysis_failed` |
| `DELETE /api/v1/analysis/{analysisId}` ⊕ | — | 204，无响应体 | 404 `analysis_not_found`；409 `analysis_in_progress` |

请求示例：

```json
{
  "imageId": "1d3f9f8a-2f5a-4a7c-9a2e-0b6a1c2d3e4f",
  "options": {
    "sceneRecognition": true,
    "subjectDetection": true,
    "lightingAnalysis": true,
    "colorAnalysis": true,
    "compositionAnalysis": true,
    "qualityDiagnosis": true
  },
  "force": false
}
```

`options` 可省略，默认全部启用；全部为 `false` 返回 400 `invalid_analysis_options`。关闭某项时对应结果退化为 `unknown`/空数组，并在 `limitations` 中说明；`qualityDiagnosis=false` 时不输出问题与建议。

#### 去重与重试

- `dedupe_key = sha256(image.id + "\n" + image.sha256 + "\n" + config_key)`：同一资材、同一内容与选项才去重。
- `force=false`：存在未失败的任务时返回 200 与当前状态（`deduplicated=true`），不新建任务；存在已失败任务时重置为 `pending` 并重新入队（等价“重试”），同样返回 200。重置是条件更新（`WHERE status='failed'`）：并发点“重试”只有一个请求能翻转成功并入队，败方直接返回当前行，不会重复排队。
- `force=true`：追加随机 UUID 生成新 key，始终创建新任务并返回 202；前端“重新分析”使用此模式。
- 同一图片重新上传会生成新的 `image.id`，因此不会复用旧任务；报告中的 `result.image.id` 始终对应当前图片。前端仍会校验 `result.image.id === 当前 imageId`，不匹配时显示“分析结果与当前图片不匹配”。
- 待处理（`pending`）任务数达到 `FRAME_ANALYSIS_QUEUE_MAX`（默认 16）时，新建分析返回 503 `server_busy` + `Retry-After: 5`，`details` 为 `{queued, queueMax}`；去重命中不占用配额。
- 状态迁移使用 compare-and-set：`mark_started` 只翻转 `pending` 行，`mark_failed` / `complete_with_result` 只作用于自己仍持有的 `processing` 行。抢不到认领的 worker 零写入，也不会把已完成的任务改回失败或留下孤立结果行。

#### 状态对象

```json
{
  "analysisId": "d3a5c374-f095-4db0-9fc5-883d07e7ac9c",
  "status": "completed",
  "stage": "completed",
  "isMock": true,
  "resultAvailable": true,
  "error": null,
  "createdAt": "2026-11-03T11:17:15.000Z",
  "updatedAt": "2026-11-03T11:17:16.000Z",
  "startedAt": "2026-11-03T11:17:15.000Z",
  "completedAt": "2026-11-03T11:17:16.000Z",
  "result": { "...": "stage3/1 报告" }
}
```

- `status ∈ {pending, processing, completed, failed}`。
- `stage ∈ {queued, preprocessing, vision, features, diagnosis, completed, failed}`；只反映真实阶段，没有百分比。
- `error` 仅在 `failed` 时给出 `{code, message}`；`message` 为安全文案，不含密钥、原始响应、图片字节或路径。
- `isMock` 表示**产出这份报告的那次运行**是否为 Mock（取自入库的 `analysis_result.is_mock`），不是当前 Provider 的实时状态；保存新的模型设置不会改写历史报告的标记。任务尚未完成时回落到当前 Provider 配置。前端据此显示“模拟分析（未调用真实视觉模型）”。

#### 报告 `stage3/1`

关键字段（camelCase）：

```json
{
  "analysisId": "…",
  "schemaVersion": "stage3/1",
  "generatedAt": "…",
  "image": {"id": "…", "width": 4000, "height": 3000, "aspectRatio": 1.333, "sha256": "…"},
  "engine": {
    "visionProvider": "mock",
    "visionModel": "mock-backlit",
    "decisionProvider": "mock",
    "decisionModel": "mock-rules",
    "promptVersion": "stage3/2",
    "analyzerVersion": "…",
    "isMock": true
  },
  "scene": {"primary": "portrait", "secondary": ["nature"], "confidence": 0.5},
  "subjects": [{"id": "s1", "type": "person", "role": "primary", "confidence": 0.5, "bbox": {"x": 0.3, "y": 0.15, "width": 0.4, "height": 0.75}, "regionId": "r1"}],
  "regions": [{"id": "r1", "type": "person", "source": "vision", "confidence": 0.5, "bbox": {"…": "…"}, "mask": null}],
  "lighting": {"direction": "back", "type": "natural", "contrast": "high", "confidence": 0.4},
  "color": {"temperature": "warm", "saturation": "moderate", "harmony": "moderate", "dominantColors": ["#E8C08A", "#3A3F4A"], "confidence": 0.4},
  "composition": {"balance": "moderate", "subjectPosition": "center", "negativeSpace": "moderate", "occlusion": "none", "subjectAreaRatio": 0.28, "horizonTiltDeg": 1.2, "confidence": 0.4},
  "measurements": {"…": "亮度分位/直方图/截断/色偏/饱和度分布/RGB/HSV 直方图/主色集中度/清晰度/噪声/梯度各向异性/边缘网格"},
  "issues": [{"id": "…", "type": "subject_underexposure", "severity": "high", "confidence": 0.6, "evidence": "…", "suggestion": "…", "regionIds": ["r1"]}],
  "recommendations": [{"priority": "high", "category": "exposure", "description": "…", "targetRegions": ["r1"]}],
  "limitations": ["模拟数据：未调用真实视觉模型。"]
}
```

- `bbox` 使用归一化坐标（0–1，相对方向归一后的显示尺寸）；`regions[].mask` 当前恒为 `null`，**没有像素级蒙版**。
- `color.harmony`、`composition.occlusion` 可取 `unknown`；`composition.subjectAreaRatio` 与 `horizonTiltDeg` 可为 `null`（无法可靠估计时）。
- `measurements.color.rgbHistogram` 为 R/G/B 三组 32 桶，`hsvHistogram` 为 H16/S8/V8 三组，均已归一化；`saturationP10/P50/P90`、`colorConcentration`、`detail.gradientAnisotropy` 为新增测量。
- `issues[].suggestion` 为单条问题的简短建议（可选），与 `recommendations` 互补。
- `unknown` 是合法枚举值，不会被渲染成问题；不确定信息放入 `limitations`。
- 报告只保存结构化结果与测量值，不保存图片副本。`schemaVersion` 仍为 `stage3/1`（向后兼容新增字段）；提示词/特征/诊断版本分别提升为 `stage3/2`、`frame-features/2`、`diagnosis/2`。

#### 任务失败码

任务失败时查询仍返回 200，`status=failed`，`error.code` 为：

| code | 说明 |
| --- | --- |
| `analysis_failed` | 未预期错误或结果入库失败 |
| `analysis_invalid_output` | Provider 输出或决策结果未通过 Schema/证据校验 |
| `analysis_input_too_large` | 内存 JPEG 副本超过 `FRAME_ANALYSIS_MAX_INPUT_BYTES` |
| `analysis_timeout` | 整任务超过 `FRAME_ANALYSIS_TIMEOUT_SECONDS`，在阶段边界检查并中止 |
| `original_changed` | 原图在分析开始/完成前发生变化 |
| `provider_auth_error` / `provider_endpoint_error` / `provider_error` | Provider 配置/请求错误 |
| `provider_rate_limited` | Provider 返回 429 |
| `provider_timeout` | Provider 超时 |
| `provider_unavailable` | Provider 网络不可用或 5xx |
| `provider_response_too_large` | Provider 响应体超限 |

### 4.7 模型设置（阶段 3 补充）

| 方法与路径 | 请求 | 响应 | 主要错误 |
| --- | --- | --- | --- |
| `GET /api/v1/settings/providers` | — | 脱敏配置视图，不含 API Key | 503 `provider_settings_unavailable` |
| `POST /api/v1/settings/providers` | `{vision?, decision?}` | 保存并热替换后的脱敏配置视图 | 422 `invalid_provider_settings`；500 `provider_settings_write_failed`；503 |
| `POST /api/v1/settings/providers/test` | `{vision?, decision?}`，用“当前配置 + 临时修改”测试 | `{vision, decision}` 两项独立结果；不持久化 | 422；503 |
| `POST /api/v1/settings/providers/reset` | — | 删除本机覆盖文件后按环境变量重建的视图 | 500；503 |

脱敏视图：

```json
{
  "vision": {"provider": "mock", "model": "mock-vision", "baseUrl": "", "hasApiKey": false, "apiKeySource": "none"},
  "decision": {"provider": "mock", "model": "mock-decision", "baseUrl": "", "hasApiKey": false, "apiKeySource": "none"},
  "isMock": true,
  "hasSavedOverrides": false
}
```

- `apiKeySource ∈ {saved, environment, none}`；任何响应都不会包含 API Key 本身。
- 保存请求可只带一个 Provider。字段缺省或 `null` 表示保持当前值；`apiKey` 为空字符串表示保持已保存密钥；`clearApiKey=true` 删除本地保存的密钥。`apiKey` 非空与 `clearApiKey=true` 同时出现返回 422 `validation_error`。
- 选择 `openai` 时，模型名、Base URL 与 API Key 必须有值（本地保存或环境变量）；Base URL 必须是 `http(s)` 绝对地址；缺失/非法字段返回 422 `invalid_provider_settings`，`details.fields` 与请求体校验同构（对象数组 `{field, rule, limit, message}`，`rule ∈ {missing, invalid_url, invalid_characters}`），不改变已生效配置。
- 保存成功后原子写入 `<FRAME_DATA_DIR>/provider-settings.json`（明文，尽力 `chmod 0600`），并热替换 Provider：新创建的分析任务使用新配置，已开始的任务继续使用旧 Provider。保存失败不会替换运行时配置。
- `test` 使用“当前生效配置 + 请求内临时修改”，不写入文件。真实 Provider 只发送一条纯文本 Chat Completions 提示，不发送用户图片；每项返回 `{ok, provider, model, latencyMs, code, message}`，失败码为安全的 `provider_*`/`provider_test_failed`，不返回上游响应正文。
- `reset` 删除覆盖文件并恢复环境变量配置；没有覆盖文件时同样返回 200。

## 5. 相对任务书 §7 的契约扩展

| 扩展 | 说明 |
| --- | --- |
| ⊕ 403 / 409 状态码 | `origin_not_allowed`/`cors_origin_denied`、`revision_conflict`/`nothing_to_undo`/`nothing_to_redo`/`render_superseded`；任务书状态码表无 403、409 |
| ⊕ `GET /sessions/{id}/revisions` | 历史条分页；按 `revisionNo` 降序，`cursor` 为上一页最后一条的 `revisionNo` |
| ⊕ `GET /previews/{previewId}` | 内容寻址预览路由（D-06） |
| ⊕ `POST /sessions/{id}/redo` | 沿 head 路径前进（D-02） |
| ⊕ `POST /sessions/{id}/activate` | 历史切换；不改 head（D-02） |
| ⊕ `render.quality` / `cacheHit` | `draft`/`final` 两档与缓存命中标记 |
| ⊕ `X-Render-Seq` / `render_superseded` | 同会话单调渲染序号；过期渲染返回 409，避免旧结果覆盖新操作 |
| ⊕ `X-Export-Warning` / `export_too_large` | 大图简化降噪提示与导出内存预算拒绝 |
| ⊕ `export.maxEdge` | 导出目标长边 64…100000；超过原图长边不放大，边长在旋转/裁切后的画布上测量 |
| ⊕ `export.colorSpace` | 只接受字面量 `"sRGB"`，其他值 422；输出恒为 8-bit sRGB 并嵌入 ICC |
| ⊕ 导出准入 | `FRAME_EXPORT_MAX_CONCURRENCY`（默认 1）与“在跑导出估算之和 + 本次估算”双重门；拒绝即 503 `server_busy` |
| ⊕ 渲染缓存分层 | 代理磁盘缓存 + 进程内解码缓存（`FRAME_PROXY_CACHE_MB`）+ 进程内蒙版权重缓存（`FRAME_MASK_CACHE_MB`，单条上限 24 MB）；键均含 `ENGINE_VERSION`，命中与未命中输出字节一致 |
| ⊕ Host/Origin 防护 | 本机 Host 白名单、写入请求 Origin 与 `Sec-Fetch-Site` 检查 |
| ⊕ 请求体分档上限 | 上传走 `FRAME_MAX_UPLOAD_BYTES`（+ multipart 封装余量），其余写口走 `FRAME_MAX_JSON_BODY_BYTES`；按真实字节计数，块式请求无法绕过 |
| ⊕ 分析超时与队列 | `FRAME_ANALYSIS_TIMEOUT_SECONDS` 在阶段边界中止（`analysis_timeout`）；`FRAME_ANALYSIS_QUEUE_MAX` 满时 503 `server_busy` + `Retry-After: 5` |
| ⊕ 已删除 `POST /images/{id}/analyze` | 阶段三遗留的同步调试口；前端无引用、结果不可查询，阶段四复审删除 |
| ⊕ `POST /analysis` | 阶段 3 异步分析任务；`202` 新建、`200` 去重复用、`force=true` 强制重跑 |
| ⊕ `GET /analysis/{id}` / `GET /analysis/{id}/result` / `DELETE /analysis/{id}` | 任务状态、完整报告与删除；状态包含真实阶段与 Mock 标记 |
| ⊕ `status/stage/error` 任务模型 | 失败任务保留供重试；只返回安全错误码与文案 |
| ⊕ `stage3/1` 报告 | 场景/主体/区域/光线/色彩/构图/测量/问题/建议/局限；`bbox` 归一化，`mask` 为 `null` |
| ⊕ `GET|POST /settings/providers`、`/test`、`/reset` | 应用内 Provider 配置；脱敏读取、热替换、纯文本连接测试与环境变量恢复 |

## 6. 错误码

| code | HTTP | 说明 |
| --- | --- | --- |
| `invalid_upload` | 400 | 上传字段不是恰好一个文件 |
| `empty_file` | 400 | 文件为空 |
| `invalid_host` | 400 | Host 主机名不在 `FRAME_ALLOWED_HOSTS` |
| `origin_not_allowed` | 403 | 写入请求的 Origin 不在允许列表，或 `Sec-Fetch-Site` 为 `cross-site` |
| `cors_origin_denied` | 403 | CORS 预检的 Origin 不在允许列表 |
| `cors_method_denied` | 405 | CORS 预检请求的方法不在 `GET/POST/DELETE/OPTIONS` |
| `not_found` | 404 | 通用路由不存在 |
| `image_not_found` | 404 | 图片 ID 不存在 |
| `image_file_missing` | 404 | 登记存在但原图文件缺失 |
| `session_not_found` | 404 | 会话 ID 不存在或格式非法 |
| `revision_not_found` | 404 | revision 不属于该会话或不存在 |
| `preview_expired` | 404 | 预览不存在或已被 TTL 清理 |
| `revision_conflict` | 409 | 父 revision/期望 revision 与服务端活动版本不符 |
| `idempotency_key_reuse` | 409 | 同一 Idempotency-Key 被用于不同配方或不同父 revision |
| `nothing_to_undo` | 409 | 已到历史根节点 |
| `nothing_to_redo` | 409 | 当前路径上没有下一步 |
| `render_superseded` | 409 | 等待渲染期间已有更高 `X-Render-Seq` 的请求；前端静默忽略 |
| `payload_too_large` | 413 | 请求体超过中间件上限：`/api/v1/images` 按 `FRAME_MAX_UPLOAD_BYTES`，其余写口按 `FRAME_MAX_JSON_BODY_BYTES` |
| `file_too_large` | 413 | 单文件超过 `FRAME_MAX_UPLOAD_BYTES` |
| `image_too_many_pixels` | 413 | 像素数超过 `FRAME_MAX_IMAGE_PIXELS` |
| `export_too_large` | 413 | 导出预估峰值内存超过 `FRAME_EXPORT_MAX_RSS_MB` |
| `analysis_input_too_large` | 413 | 分析内存 JPEG 副本超过 `FRAME_ANALYSIS_MAX_INPUT_BYTES` |
| `invalid_analysis_options` | 400 | 分析选项全部为 `false` |
| `analysis_not_found` | 404 | 分析任务不存在或 ID 非法 |
| `analysis_not_ready` | 409 | 任务未完成时请求完整报告 |
| `analysis_in_progress` | 409 | 运行中的任务不能删除 |
| `analysis_failed` / `analysis_invalid_output` | 任务错误码 | 保存在 `status.error.code`，不是查询接口的 HTTP 502 |
| `provider_*` | 任务错误码 | Provider 失败的安全包装；体现在 `status.error.code` |
| `invalid_provider_settings` | 422 | Provider 配置缺字段或字段非法；`details.fields` 为 `{field, rule, limit, message}` 对象数组 |
| `provider_settings_write_failed` | 500 | 本机覆盖文件写入/删除失败；运行时配置保持不变 |
| `provider_settings_unavailable` | 503 | 设置服务尚未就绪 |
| `unsupported_media_type` | 415 | 声明 MIME 不在允许列表 |
| `invalid_image` | 415 | 内容无法解码或尺寸非法 |
| `mime_mismatch` | 415 | 声明 MIME 与真实格式不符 |
| `animated_not_supported` | 415 | 多帧图片 |
| `validation_error` | 422 | 字段校验失败（含未知字段 `extra_forbidden`），`details.fields` 给出字段、规则与限制 |
| `storage_error` | 500 | 原图或登记写入失败 |
| `storage_conflict` | 500 | 存储键冲突 |
| `internal_error` | 500 | 未预期错误 |
| `server_busy` | 503 | 导出并发数或内存预算已满，渲染槽位等待超过 10 秒，或分析待处理队列达到 `FRAME_ANALYSIS_QUEUE_MAX` |
| `service_unavailable` | 503 | 服务未就绪 |
| `provider_rate_limited` / `provider_unavailable` | 任务错误码 | 阶段 3 的 Provider 限流/不可用，记录在分析任务的 `status.error.code` |

阶段 1 已约定的错误码与文案映射（前端 `apps/web/lib/error-messages.ts`）保持不变；`revision_conflict` 映射为“编辑状态已更新，已为你刷新”，`idempotency_key_reuse` 提示保存请求与已有版本冲突；`render_superseded` 与 `preview_expired` 静默处理。`export_too_large` 会展示预估内存与上限。

## 7. 契约同步流程

1. 修改后端 Pydantic 模型或路由。
2. 在 `services/api` 运行 `python scripts/export_openapi.py` 重新生成 `shared/contracts/openapi.json`。
3. 在 `apps/web` 运行 `npm run gen:api` 重新生成 `types/api.d.ts`。
4. 提交前运行 `python scripts/export_openapi.py --check` 与 `npm run check:api`；两者必须退出 0。
5. 同步更新本文与当前阶段交接（`STAGE_3_COMPLETION_REPORT.md` 或 `docs/handoff/phase-*.md`）中受影响的行为说明。

## 8. 复跑示例

以下命令假设 API 在 `127.0.0.1:8000`：

```bash
# 上传
curl -sS -F "file=@tests/e2e/.artifacts/fixture.jpg;type=image/jpeg" \
  http://127.0.0.1:8000/api/v1/images

# 创建会话（把 IMAGE_ID 换成上传返回的 imageId）
curl -sS -X POST http://127.0.0.1:8000/api/v1/sessions \
  -H "Content-Type: application/json" -d '{"imageId":"IMAGE_ID"}'

# 渲染（把 SESSION_ID 换成会话 ID）
curl -sS -X POST http://127.0.0.1:8000/api/v1/sessions/SESSION_ID/render \
  -H "Content-Type: application/json" \
  -d '{"recipe":{"schemaVersion":"2.0","adjustments":{"exposureEv":1,"saturation":-100}},"quality":"final","maxEdge":1600}'

# 导出（把 REVISION_ID 换成会话返回的 activeRevisionId）
curl -sS -D export.headers -o export.jpg \
  -X POST http://127.0.0.1:8000/api/v1/sessions/SESSION_ID/export \
  -H "Content-Type: application/json" \
  -d '{"revisionId":"REVISION_ID","format":"jpeg","quality":92}'

# 创建分析任务（把 IMAGE_ID 换成上传返回的 imageId）
curl -sS -X POST http://127.0.0.1:8000/api/v1/analysis \
  -H "Content-Type: application/json" \
  -d '{"imageId":"IMAGE_ID","force":false}'

# 查询状态（把 ANALYSIS_ID 换成创建返回的 analysisId）
curl -sS http://127.0.0.1:8000/api/v1/analysis/ANALYSIS_ID

# 获取完整报告（仅 completed）
curl -sS http://127.0.0.1:8000/api/v1/analysis/ANALYSIS_ID/result
```

端到端自动化见 [tests/e2e/editor.spec.ts](../tests/e2e/editor.spec.ts)、[tests/e2e/analysis.spec.ts](../tests/e2e/analysis.spec.ts) 与 [tests/e2e/README.md](../tests/e2e/README.md)。
