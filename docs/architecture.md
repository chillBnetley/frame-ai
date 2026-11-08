# 架构与请求流

## 当前范围

仓库处于阶段 5 完成状态：在阶段 2 的安全上传、SQLite 持久化、非破坏编辑会话、确定性渲染、内容寻址预览、前后对比与全分辨率导出，以及阶段 3 的异步 AI 分析、可替换 Provider、摄影诊断之上，新增 AI 摄影师——方案生成、风格库、对话调整、确定性点评与用户反馈。AI 只输出意图，配方一律由服务端校验、夹紧与取整；预览不写历史，接受仍走普通 revision；反馈只记录行为与评分，不代表质量结论。

## 总体结构

```text
Browser (Next.js 16 / React 19)
  │  同源 /api/v1/*
  ▼
Next.js rewrite → API_INTERNAL_URL（默认 http://127.0.0.1:8000）
  │
  ▼
FastAPI (127.0.0.1 only, D-13)
  ├─ RequestContextMiddleware       请求 ID、耗时、状态码日志
  ├─ LocalOriginGuardMiddleware    Host 白名单、Origin 与跨站写入防护
  ├─ CorsPreflightGuardMiddleware   CORS 预检边界
  ├─ UploadSizeLimitMiddleware      Content-Length 预检与流式字节限制
  ├─ ImageService                   解码校验 → originals/ → image_asset
  ├─ SessionService                 revision 事务、undo/redo/activate/reset、幂等
  ├─ RenderService                  渲染序号 → 代理内存/磁盘缓存 → pipeline（含蒙版权重缓存）→ previews/<hash>
  ├─ ExportService                  并发+内存准入 → 全分辨率解码 → 按计划尺寸缩放 → 重渲染 → 元数据剥离
  ├─ AnalysisService                阶段 2 启发式特征（进程内 LRU，保留兼容）
  ├─ AnalysisTaskService            任务队列、去重、启动恢复、重试、结果入库
  ├─ AnalysisOrchestrator           预处理 → 视觉 → CV 特征 → 诊断 → 报告
  ├─ ProviderBundle                 vision/decision Provider（mock 或 OpenAI 兼容）
  ├─ PhotographerService            方案/对话/点评/反馈编排与响应组装
  ├─ StyleCatalog                   参数化风格定义（与渲染引擎 styleId 解耦）
  ├─ PhotographerPlanner            方案与补丁生成（mock 或 OpenAI 兼容），只收结构化摘要
  ├─ CritiqueGenerator              确定性规则点评，证据引用闭合校验
  └─ PreviewStore                   TTL 清理、原子写入、Windows 占用兜底
```

浏览器默认通过同源代理访问后端，因此本地开发不依赖 CORS。FastAPI 仍允许 `.env` 配置跨域来源，便于直接访问 API。

## 主要请求流

### 上传

```text
POST /api/v1/images
  → 中间件按实际字节限制请求体
  → ImageService 读取并限制文件字节
  → Pillow 检查真实格式 / 声明 MIME / 像素 / 动画 / 截断 / EXIF 方向
  → OriginalImageStore 写入 data/originals/<uuid>.<ext>
  → SQLite image_asset 插入（失败则回滚删除文件）
  → 201 {imageId, width, height, exifOrientation, ...}
```

### 编辑与提交

```text
POST /api/v1/sessions                  → 初始 revision（source=initial）
POST /api/v1/sessions/{id}/render      → X-Render-Seq + 代理缓存 + 无状态渲染 + 预览缓存
POST /api/v1/sessions/{id}/revisions   → 事务内校验 parentRevisionId、取号、插入、移动 active/head
POST /api/v1/sessions/{id}/undo|redo|activate|reset
```

- 预览是按配方内容寻址的缓存，不写数据库；方向归一/缩放代理图另存于 `previews/proxies/`，与预览共用同一 TTL 清理轮。
- 阶段四加了两层进程内 LRU：解码后的代理图（`FRAME_PROXY_CACHE_MB`，默认 64）与蒙版权重（`FRAME_MASK_CACHE_MB`，默认 64，单条 24 MB 上限）。两者只在能给出与直接计算完全一致的字节时才命中——代理只存可无损转为 8-bit 的数组，权重数组取出即只读。
- 同进程最多并发 2 次渲染，槽位等待上限 10 秒；等待期间被更高 `X-Render-Seq` 取代的请求返回 409，防止旧结果覆盖新操作。前端序号由 `nextRenderSeq()` 统一发放（`max(Date.now(), 上一次 + 1)`），滑杆预览与裁切底图共用，跨重挂载与多标签页仍单调递增。
- revision 提交使用 `BEGIN IMMEDIATE`；`Idempotency-Key` 同 key 同内容命中时返回原 revision（200），内容或父 revision 不同则返回 409。
- 历史是 `parent_id` 图：`active` 是当前编辑点，`head` 是路径末端；在历史中间提交会形成分支。

### 渲染管线

```text
原图字节
  → 方向归一（EXIF 1–8）
  → 模式归一 + 嵌入 ICC 转 sRGB（携带有效 RGB 设备空间配置的输入：RGB/RGBA/P/PA/1/L/LA）
  → 代理缩放（draft 960 / final 默认 1600 / export 全分辨率或请求的 maxEdge）
  → 旋转内接（无填充，最大同比例矩形）
  → 裁切（坐标位于旋转后画布）
  → sRGB → 线性
  → 曝光 / 白平衡 / 高光 / 阴影 / 白色色阶 / 黑色色阶
  → 线性 → sRGB
  → 对比度
  → 曲线（Master → R → G → B）
  → HSL 色带（红 / 橙 / 黄 / 绿 / 青 / 蓝 / 紫 / 洋红）
  → 饱和度 / 自然饱和度
  → 颜色分级（阴影 / 中间调 / 高光）
  → 局部调整（全图 / 矩形 / 椭圆蒙版）
  → 清晰度 / 暗角
  → 降噪 / 锐化
  → 颗粒
  → uint8 编码
```

`adjustments`、`curve`、`hsl`、`colorGrading`、`masks` 与 `localAdjustments` 是渲染权威；`styleId/styleStrength` 只作为来源元数据（D-10）。任何算法、常数或顺序变化必须提升 `ENGINE_VERSION` 并重新生成黄金图。

### 色彩管理

完整策略与实测数据见 [color-management.md](color-management.md)，决策见 [ADR-0004](decisions/ADR-0004-color-management.md)。摘要：

- **输入**：EXIF 方向先烘焙，再在模式归一之后做配置管理。携带有效 RGB 设备空间配置的输入（`RGB`/`RGBA`/`P`/`PA`/`1`/`L`/`LA`）经 lcms2 转 sRGB（相对色度 + 黑点补偿）；配置设备空间非 RGB、配置损坏或为空时**回退按 sRGB 解释**；无配置时**按 sRGB 解释**——这是显式默认策略，不是隐含行为。不存在"把所有输入无条件当作同一色彩空间"的分支。
- **入口分层**：上传闸门接受 JPEG/PNG/WebP/TIFF；TIFF 只支持单页、未压缩或 Deflate，LZW/JPEG 返回 415。色彩管理与容器无关。
- **工作空间**：float32 `[0,1]` sRGB 编码值贯穿管线，只在末端量化一次（8-bit 或 16-bit）。`app/imaging` 内 `astype(np.uint8)` 站点固定于末端量化、OpenCV 去噪的 8-bit 限制、8-bit 代理与分析用边缘检测；渲染阶段模块由测试禁止引入中间量化。
- **位深**：16-bit PNG 用 OpenCV `IMREAD_UNCHANGED`、16-bit TIFF 用 tifffile 解码，Pillow 只提供容器/ICC/方向元数据，因此 16-bit RGB 不再被截断。8-bit 代理仍是实测取舍：强曲线下 max 4 级 / mean 0.33 级且不产生色带，因此预览/代理不升级 16-bit；16-bit 源的代理缓存键追加 `|b16`。
- **ICC（16-bit）**：纯 NumPy 矩阵/TRC（`curv`/`para 0–4`）经 D50 PCS 转 sRGB，float32、256 行分块；sRGB/untagged 走恒等快路径。LUT/mAB/mft 或非 RGB/XYZ 配置返回 422 `unsupported_icc_profile`，不静默降级；8-bit 路径继续 lcms2。
- **输出**：目标空间恒为 sRGB，位深 8 或 16（JPEG 固定 8）；JPEG/PNG/TIFF 均嵌入固定 sRGB ICC（头部时间戳 pin 死以保证跨进程字节一致），预览与导出都剥离全部元数据。PNG/TIFF 可保留同深度 alpha，JPEG 与预览白底合成。原图字节不改写，`GET /images/{id}/original` 仍带原配置与原 EXIF/GPS。
- **依赖**：OpenCV 不参与色彩管理，tifffile **2026.3.3（BSD-3-Clause）** 仅用于 16-bit TIFF；未引入 `imagecodecs`/`rawpy`/`pillow-heif`/`colorio`。仍不支持 RAW 显影、32-bit/HDR、16-bit JPEG、CMYK 正确显影、LUT ICC、TIFF LZW/JPEG 与多页。

### 全局调色数学定义

全局调色固定按以下顺序执行；所有参数为 0 时每一步都是恒等变换。

| 步骤 | 参数 | 定义 |
|---|---|---|
| 1 | 曝光 | 线性光 `RGB' = RGB × 2^E`，`E ∈ [-5, 5]` EV。 |
| 2 | 色温 / 色调 | 通道增益 `gR = 1 + 0.25·T`、`gG = 1 − 0.12·M`、`gB = 1 − 0.25·T`，其中 `T = temperature/100`、`M = tint/100`；随后按全图平均亮度比 `Ȳ_before / Ȳ_after` 对三通道施加**同一个**标量，保持全图平均亮度。逐像素守恒会在纯色像素上自我抵消（红/蓝通道增益被自己除回 1），故不采用。 |
| 3 | 高光 / 阴影 | 令感知亮度 `L = sRGB(Y)`（可选高斯模糊，`σ = 0.004·max(W,H)`）；`m_h = smoothstep(L; 0.5, 1)`、`m_s = 1 − smoothstep(L; 0, 0.5)`；`gain = 2^{(highlights/100)·1.0·m_h + (shadows/100)·1.5·m_s}`，三通道同乘。 |
| 4 | 白色色阶 / 黑色色阶 | 同一 `L`；`m_w = smoothstep(L; 0.7, 1)`、`m_b = 1 − smoothstep(L; 0, 0.20)`；`gain = 2^{(whites/100)·0.7·m_w − (blacks/100)·1.0·m_b}`，三通道同乘。正向 Blacks 压暗阴影末端、负向提亮，遵循 Lightroom/ACR 约定；掩膜端点从 0.30 收到 0.20 以降低与 Shadows（0–0.5）的功能重叠。 |
| 5 | 对比度 | 转回 sRGB 后，令 `L = Y`，`L' = L + (contrast/100)·(smoothstep(L; 0, 1) − L)`；`r = L'/L`（`L ≤ 1e-6` 时取 1），`c = clip(r, 0.95, 1.05)`，输出 `RGB' = L' + (RGB − L)·c` 并截断到 `[0,1]`。Rec.709 权重和为 1，因此缩放色度不改变曲线给定的亮度；旧实现按 `r` 缩放三通道会把色度一并放大，实测非灰像素 ±14.3%。 |
| 6 | 曲线 | 在 sRGB 编码空间依次应用 Master → Red → Green → Blue；每条曲线先按 Fritsch–Carlson 单调三次 Hermite 预计算 8192 格点 LUT，再逐像素线性插值；空通道为恒等。 |
| 7 | HSL 色带 | 转 sRGB→HSL，按色相在八个色带中心之间平滑加权，调整色相 / 饱和度 / 明度后再转回 sRGB；详见下节。 |
| 8 | 饱和度 | `RGB' = Y + (RGB − Y)·(1 + saturation/100)`，其中 `Y` 为 Rec.709 亮度。 |
| 9 | 自然饱和度 | 色度 `C = max(RGB) − min(RGB)`，权重 `w = (1 − C)^1.5`，`RGB' = Y + (RGB − Y)·(1 + vibrance/100·w)`。 |
| 10 | 颜色分级 | 按 Rec.709 亮度把像素平滑分配到阴影 / 中间调 / 高光，叠加各自色相与强度对应的零亮度色偏；详见下节。 |

- 第 1–4 步在线性光空间执行；第 5–10 步在 sRGB 编码空间执行；所有通道缩放均为等比缩放，避免改变色相。
- 高光/阴影与白色/黑色采用不同的亮度掩码区间（`0.5–1.0` / `0–0.5` 对 `0.7–1.0` / `0–0.20`），减少功能重叠。
- 白色/黑色增益上限经过约束，使亮度映射在参数区间内保持单调，避免可见色阶反转。
- 参数为有限值，掩码有界，因此输出不会出现 NaN 或 Infinity；亮度映射只使用有限指数与截断。

### 曲线插值

曲线控制点按 `x` 严格递增，每个通道 0 或 ≥2 个点、最多 32 个，`x,y ∈ [0,1]` 且最多六位小数。空数组表示恒等，单点被拒绝。

对区间 `h_i = x_{i+1} − x_i`、斜率 `δ_i = (y_{i+1} − y_i)/h_i`：

1. 初始切线 `m_0 = δ_0`、`m_{n−1} = δ_{n−2}`，内部 `m_i = (δ_{i−1} + δ_i)/2`。
2. 逐区间做 Fritsch–Carlson 限制：`δ_i = 0` 时令两端切线为 0；否则 `α = m_i/δ_i`、`β = m_{i+1}/δ_i`，负值置 0；若 `α² + β² > 9`，取 `τ = 3/√(α²+β²)` 并按 `τ` 缩放两端切线。
3. 区间内使用三次 Hermite：`t = (x − x_i)/h_i`，`y = h00·y_i + h10·h_i·m_i + h01·y_{i+1} + h11·h_i·m_{i+1}`，其中 `h00 = 2t³ − 3t² + 1`、`h10 = t³ − 2t² + t`、`h01 = −2t³ + 3t²`、`h11 = t³ − t²`。
4. 首末节点之外按端点切线线性外推（`y = y_0 + m_0·(x − x_0)` / `y = y_{n−1} + m_{n−1}·(x − x_{n−1})`），再截断到 `[0,1]`；悬空曲线因此不会把暗部/高光压平，clip 处可能出现斜率折点但在测试中保持连续与单调。
5. 渲染时不在整图上逐点求 Hermite，而是在 `x∈[0,1]` 的 8192 个均匀格点上用同一套系数求值得到 LUT（每条曲线约 32 KB），像素值按 `u = clamp(v,0,1)·8191` 取相邻两格点做线性插值。与逐点 Hermite 相比，整图临时量从 9 个降到 4 个、无 int64 索引，24 MP 曲线阶段从 4.3 GB 降到 1.15 GB 瞬态分配；插值误差实测最大 0.000918（1 万条随机曲线 × 1 万采样点），低于半个 8-bit 级（1/510）。

该算法在控制点单调的区间内保持单调，在局部极值处不产生额外振荡，避免可见过冲。

### HSL 色带

HSL 阶段在曲线之后、全局饱和度/自然饱和度之前执行，输入为 sRGB 编码值 `[0,1]`：

1. `RGB → HSL`：`L = (max+min)/2`，`S = Δ/(1 − |2L − 1|)`（`Δ≈0` 时 `S=0`），`H` 为标准 0…360 色相；无彩色像素 `H=0`。
2. 色带中心依次为红 0°、橙 30°、黄 60°、绿 120°、青 180°、蓝 240°、紫 285°、洋红 330°，并以 0°/360° 首尾相接。对色相 `H` 找到相邻中心 `c_i ≤ H ≤ c_{i+1}`，令 `t = (H − c_i)/(c_{i+1} − c_i)`、`w = smoothstep(t; 0, 1)`；参数按 `(1 − w)·p_i + w·p_{i+1}` 插值。相邻色带权重和为 1，在中心处只受该色带影响，边界连续无跳变。
3. 色相先查一张**周期单调**映射表：把八个带参数 `ΔH_i` 按相邻带心间距做斜率预算——平滑阶跃在宽度 `g` 的间隙上导数上界为 `1.5/g`，因此约束 `|ΔH_i − ΔH_j| ≤ g·(1 − 0.05)/1.5`（超出部分对半分给这一对，不扩散到远端色带），再在 0.25° 网格（1440 点）上采样 `shift(h)`，逐像素线性插值后 `H' = mod(H + shift(H), 360)`。这样 `h ↦ H'` 斜率恒 ≥ 0.05，**不会局部反序，也不会产生等色轮廓带**；代价是单个色带的色相滑杆在邻带很近时（30° 间距）约 ±20° 后不再增长。`S' = clip(S × clip(1 + ΔS/100, 0, 2), 0, 1)`；`L' = clip(L × 2^(ΔL/100), 0, 1)`，即明度 ±100 对应 ±1 EV。
4. 色度门控按参数分档：`g_h = smoothstep(C; 0.02, 0.10)` 用于色相偏移（色相在色度趋零时无定义），`g_t = smoothstep(C; 0.005, 0.03)` 用于饱和度/明度；最终 `RGB' = RGB + (HSL→RGB(H',S',L') − RGB)·g`，其中色相分量的权重为 `g_h`、饱和度/明度分量为 `g_t`。灰色与接近无彩色的像素不受色相影响，但明度/饱和度仍能在低色度皮肤、天空与浅色背景上生效。
5. 只有插值后的参数非零的像素才执行混合，未受影响的像素保持原始值。

每个色带包含 `hue ∈ [-180,180]`、`saturation/luminance ∈ [-100,100]`；全部为 0 时该阶段为恒等变换。色相表按本次渲染的八个 `ΔH_i` 生成一次，供所有分块共用，不参与缓存键。大图按 1,000,000 像素分块处理，控制导出时的峰值内存。

### 颜色分级

颜色分级在全局饱和度/自然饱和度之后、清晰度/暗角之前执行，输入为 sRGB 编码值 `[0,1]`，每个区域包含 `hue ∈ [0,360]` 与 `saturation（强度）∈ [0,100]`：

1. 令 `L = 0.2126·R + 0.7152·G + 0.0722·B`，并按 `balance ∈ [-100,100]` 平移亮度锚点：`L_s = clip(L + balance/100·0.25, 0, 1)`。
2. 分界点固定在 `0.35` / `0.65`；半宽 `h = (0.08 + 0.52·blending/100)/2`（`blending ∈ [0,100]` 映射到过渡宽度 0.08–0.60）。
3. 两个平滑阶跃 `a = smoothstep(L_s; 0.35−h, 0.35+h)`、`c = smoothstep(L_s; 0.65−h, 0.65+h)`，得到权重 `w_shadow = 1−a`、`w_mid = a(1−c)`、`w_high = a·c`。三者恒和为 1，区域间连续过渡，不会出现固定全图色偏。
4. 每个区域的色偏方向取 `HSV(hue,1,1)` 并减去自身 Rec.709 亮度，得到零亮度向量；幅度为 `strength/100·0.30`。令 `Δ = Σ w_z·amp_z·dir_z`，对每个通道求"刚好不越界"的比例 `t_c = (1 − RGB_c)/Δ_c`（`Δ_c > 0`）或 `RGB_c/(−Δ_c)`（`Δ_c < 0`），`Δ_c = 0` 时为 `∞`；`scale = clip(min_c t_c, 0, 1)`，最终 `RGB' = RGB + Δ·scale`。
5. 三个区域强度均为 0 时直接返回输入，不产生任何像素变化。`scale` 是标量而 `Δ` 零亮度，因此**输出亮度与输入严格相等**，越界像素只是分级力度减弱，不再出现"裁剪抬高黑位"。

大图按 1,000,000 像素分块。触及 `[0,1]` 边界的极端高光或纯色像素不再被裁剪，而是把色偏按比例缩到刚好不越界，因此黑位不会被抬亮；代价是这些像素的分级强度弱于滑杆标称值。

### 局部蒙版与区域调整

局部调整阶段在颜色分级之后、全局清晰度/暗角之前执行，输入为 sRGB 编码值 `[0,1]`。蒙版与局部参数都来自不可变 revision 的 recipe，前端预览、对比与导出共用同一套映射和混合代码。

#### 坐标空间

- `UserMask.x/y/width/height` 是 **EXIF 方向归一化后的原图坐标**，范围 `[0,1]`；原点为原图左上角。
- 蒙版不保存像素尺寸或栅格文件，也不依赖代理尺寸；预览（draft 960 / final 1600）与全分辨率导出使用同一个归一化定义，因此不会出现蒙版与原图尺寸不一致的问题。
- 旋转与裁切只改变显示位置，不改变蒙版绑定的原图内容；旋转后蒙版随内容一起旋转。

#### 蒙版类型

| 类型 | 表示 | 说明 |
| --- | --- | --- |
| 全图 | `maskId: "full"` | 内置 ID，不需要 `UserMask` 对象，权重恒为 1 |
| 矩形 | `shape: "rectangle"` | 原图坐标轴对齐；旋转后随内容旋转 |
| 椭圆 | `shape: "ellipse"` | 外接矩形内切椭圆 |

**不提供人物 / 天空蒙版。** 阶段三的视觉结果只有边界框，没有像素级分割；把 bbox 当蒙版会污染框内背景，因此后端没有 `person`/`sky` 类型，界面上对应按钮禁用并说明需要真实分割模型。未来接入真实分割后再新增类型，不在本版伪造。

#### 权重计算

对输出像素 `(i, j)`，先通过旋转矩阵的逆与裁切偏移找到对应的源像素，再按像素中心归一化 `px = (src_x + 0.5) / src_w`、`py = (src_y + 0.5) / src_h`。几何函数（`rotation_target_size`、`rotation_matrix`、`crop_bounds`）与真正的 `rotate_inscribed` / `crop_pixels` 同源，避免复制公式产生漂移。

设 `cx=x+w/2`、`cy=y+h/2`、`hw=w/2`、`hh=h/2`、`f=feather/100`：

- 矩形：`wx = 1 − smoothstep(|px−cx|; hw(1−f), hw)`、`wy = 1 − smoothstep(|py−cy|; hh(1−f), hh)`，`weight = wx·wy`；`f=0` 时退化为二值包含判断。
- 椭圆：`d = sqrt(((px−cx)/hw)² + ((py−cy)/hh)²)`，`weight = 1 − smoothstep(d; 1−f, 1)`；`f=0` 时 `d≤1` 为 1。
- 羽化带完全位于形状内部，形状外权重严格为 0，因此不会向蒙版外泄漏；这也意味着 `feather=100` 时只有中心（矩形为中心线）完全生效。
- 之后应用 `inverted`（`weight = 1 − weight`）与 `opacity/100`；结果裁剪到 `[0,1]`。
- 权重图按行分块计算（`LOCAL_MASK_CHUNK_PIXELS = 1,000,000`），整图权重以 `float32` 保留到该局部调整处理完毕。

#### 局部参数与混合

v1 支持 11 个局部字段：`exposureEv`、`contrast`、`highlights`、`shadows`、`whites`、`blacks`、`temperature`、`tint`、`saturation`、`vibrance`、`clarity`。内部顺序与全局语义一致：

```text
曝光/色温/色调/高光/阴影/白色/黑色（线性光）
→ 对比度（sRGB）
→ 饱和度/自然饱和度（sRGB）
→ 清晰度（sRGB）
```

- `sharpen/denoise/vignette/grain` 的 schema 字段保留，但局部非零值保存时返回 422；前端不暴露这些控件。局部降噪/锐化在代理与导出分辨率之间的语义未验证，局部暗角本质是全局径向效果。
- 多个局部调整按 `id` 字典序依次处理，后一项看到前一项的结果；这与 canonical JSON 的排序一致，结果确定可复现。没有图层合成或蒙版布尔运算。
- `full` 蒙版直接以权重 1 混合；形状蒙版按 `rgb·(1−w) + adjusted·w` 混合。全部参数为 0、`enabled=false`、`opacity=0` 或权重全 0（例如蒙版完全在裁切范围外）时不执行像素运算。
- `maskId` 引用不存在的蒙版时，跳过该局部调整并返回 `local_mask_missing:<maskId>` warning；不崩溃，也不回退到全图或错误区域。

#### 预览 / 导出一致性与限制

- 预览与导出调用同一个 `render()` 和 `mask_weights()`；差异仅来自代理与全分辨率的目标尺寸取整，边界位置在归一化空间一致（误差不超过一个预览像素对应的归一化量）。
- 前端缩略图上的蒙版轮廓是近似显示，用于定位与拖动创建；像素级结果以服务端渲染为准。
- 每个 mask 的坐标最多 4 位小数，`feather/opacity` 2 位；`x+width≤1`、`y+height≤1`、`width/height>0`。最多 20 个蒙版与 20 个局部调整。
- 早期阶段四版本（`frame-engine/6` 及以前）没有真实局部渲染；`frame-engine/7` 起局部调整参与像素计算；`frame-engine/8` 把嵌入 ICC 管理的适用范围从 `RGB`/`RGBA` 扩展到全部可归一为 RGB 的模式（调色板、1-bit、灰度）；`frame-engine/9` 修正白平衡守恒对象（全图均值）、HSL 色相单调性与颜色分级的越界处理方式；`frame-engine/10` 落地复审摄影语义决策——Blacks 方向与掩膜端点、HSL 分档门控、曲线端点线性外推、对比度色度回收（±5%），并删除遗留 `POST /images/{id}/analyze`。`schemaVersion` 参与 canonical 哈希，因此 v1→v2 重标会改变同一旧配方在新代码下计算出的摘要；自复审整改起 revision 身份口径为 **v2.1**，`output`/`styleId`/`styleStrength` 移出 canonical 哈希但保留在持久化的完整配方中（见 [ADR-0005](decisions/ADR-0005-recipe-identity.md)）。`recipe_hash` 列只作缓存，重置与幂等比较都用当前代码从已存 `recipe_json` 重新推导，不承诺跨版本哈希恒定。空 `masks` 是唯一被省略的惰性字段，不出现在 canonical/pixel JSON 中。

### 对比与导出

```text
GET  /api/v1/sessions/{id}/compare
  → 原图代理（方向归一、同 maxEdge，仅应用该 revision 的旋转/裁切）
  → 当前 revision 渲染代理
  → 两张同尺寸 JPEG URL

POST /api/v1/sessions/{id}/export
  → 按本次计划像素与配方估算内存（超限 413 export_too_large）
  → 并发槽位 + 在跑导出估算之和双重准入（不满足立即 503 server_busy，带 Retry-After: 2）
  → 全分辨率解码原图 → 需要时先把源缩放到 maxEdge 对应尺寸（不放大）
  → 与预览同一个 render(quality="export")（计划像素超阈值且启用降噪时带 X-Export-Warning）
  → 剥离 EXIF/XMP/IPTC/GPS，嵌入 sRGB ICC，按 bitDepth 量化到 8/16-bit
  → JPEG/PNG/TIFF 文件流 + X-Export-Width/Height/Bit-Depth（缩放后的实际画布）
```

- 缩放发生在解码之后、管线之前：`maxEdge` 导出仍读原图字节，但参与渲染的像素数按计划尺寸计算，因此耗时与内存都显著低于全尺寸导出，构图与全尺寸一致。
- 估算按计划像素计算，但解码始终读整张原图，因此再小的 `maxEdge` 也不会让估算低于"原图像素 × 45 B/px + 150 MB"这条解码地板。系数在 Task 8 用 11 个实测峰值标定，复审整改 G4 又用 8 个新峰值把满配方从 240 下调到 **160 B/px**（本轮最高 131 B/px，仍留约 22% 余量）；中性 45 与每个启用局部调整 8 B/px 不变。静态估算通过后还有第二道 psutil 实时可用内存门（`FRAME_EXPORT_RESERVE_MB`，默认 256），不满足返回 503。数据见 [performance.md](performance.md) 的 Task 8 与 G4 小节，默认预算下的行为变化见 [known-issues.md](known-issues.md)。

### AI 分析

```text
POST /api/v1/analysis
  → 读取 image_asset 与只读原图 → 计算 config_key / dedupe_key
  → 未失败的去重任务：200 返回当前状态；已失败任务：重置 pending 重新入队
  → force=true 或首次：插入 analysis_task，202，提交到进程内线程池
      → preprocessing：sha256 复核 → 解码 → 最长边缩放 → 白底合成 → 内存 JPEG
      → vision：发送 JPEG 副本 + 选项 + 测量摘要；输出经 Pydantic Schema 校验
      → features：亮度分位/直方图/截断/色偏/饱和度分布/RGB/HSV 直方图/
                  主色集中度/清晰度/噪声/梯度各向异性/边缘/主色
      → diagnosis：候选问题（测量证据）→ 决策 Provider → 证据/范围校验
      → report `stage3/1` → analysis_result 入库 → completed
      → 任一步失败：记录安全 error_code/message，status=failed，任务保留供重试
GET  /api/v1/analysis/{id}         → 状态、真实阶段、isMock；完成时内嵌报告
GET  /api/v1/analysis/{id}/result  → 仅 completed 返回报告
DELETE /api/v1/analysis/{id}       → 运行中返回 409，否则删除任务与结果
```

- 视觉 Provider 只收到内存 JPEG 副本；决策 Provider 只收到结构化测量、语义与候选问题，**不收到图片**。
- Mock Provider 完全离线；真实 Provider 通过 OpenAI 兼容适配与 `PinnedHttpTransport` 传输，带超时、有限重试与安全错误映射；出站默认只允许公网 HTTPS，DNS 结果逐个校验并固定连接 IP，不读取环境代理；每次调用记录 provider/model/阶段/尝试/token/延迟，不记录 prompt、图片或 Base64。
- `unknown` 是合法枚举值，不确定信息进入 `limitations`；后端校验决策不得新增候选之外的问题。关闭任一 `AnalysisOptions` 时对应结果退化为 `unknown`/空数组并记录限制，`qualityDiagnosis=false` 时不输出问题与建议。
- 报告包含色彩协调、构图遮挡、主体面积占比、问题级建议；测量包含 RGB/HSV 直方图与饱和度分布。
- 主体与区域只有归一化边界框和区域引用，`regions[].mask` 恒为 `null`；不伪造像素蒙版。
- 任务状态、阶段、尝试次数、错误码与报告都持久化；进程重启时 `pending/processing` 任务按尝试次数恢复或标记失败。

### 模型设置与热替换

```text
GET  /api/v1/settings/providers       → 脱敏视图（无密钥）
POST /api/v1/settings/providers       → 合并补丁 → 解析生效配置 → 校验 →
                                        构建候选 Bundle → 原子写覆盖文件 →
                                        交换内存 Bundle → 通知 AnalysisTaskService
POST /api/v1/settings/providers/test  → 当前配置 + 临时补丁 → 构建候选 Bundle →
                                        每个 Provider 一条纯文本请求 → 返回 ok/延迟/安全错误
POST /api/v1/settings/providers/reset → 删除覆盖文件 → 按环境变量重建
```

- `ProviderSettingsService` 在启动时读取 `<FRAME_DATA_DIR>/provider-settings.json`，按“本地保存字段 > 环境变量”解析生效配置并构建 `ProviderBundle`；文件损坏或 `openai` 配置缺字段时启动失败，不回退 Mock。
- 保存流程先校验并构建候选 Bundle，再以临时文件 + `os.replace` 原子写入；写入失败时内存与运行时 Provider 都不变。交换操作由 `RLock` 保护。
- `AnalysisTaskService.update_providers` 在同一把锁内替换 Provider 与 Orchestrator；已提交的任务持有旧 Orchestrator 并继续执行，新任务读取新快照。去重键仍由生效 Provider 类型、模型与提示词版本生成。
- 覆盖文件默认是 v2 加密格式（详见下节「密钥加密层」）；GET、错误、日志与测试结果均不含密钥或上游响应正文。测试连接只发送文本提示，不发送图片。
- 本机覆盖文件与 `.env` 都是服务端配置，前端只持有脱敏视图；修改后无需重启 API。
- Provider 出站边界由 `ai/net_policy.py` 与 `ai/transport.py::PinnedHttpTransport` 执行：保存/启动只做 URL 语法与字面 IP 分类（不联网），请求前解析 DNS 并校验**每个**结果，任一地址被拒即 fail-closed；连接固定到已校验 IP，HTTPS 仍以原始主机名做 SNI/证书校验，Host 头保留原始主机（非默认端口带端口、IPv6 加方括号）。默认 `public-only` + 禁明文 `http`，本机 Provider 需 `FRAME_PROVIDER_URL_POLICY=allow-local`（明文再加 `FRAME_PROVIDER_ALLOW_INSECURE_HTTP=true`）；元数据/链路本地/组播/保留/未指定地址始终拒绝。传输不经 urllib opener，因此环境代理不能改变请求路径。重定向手写循环最多 5 跳、每跳重新校验，只允许同源；301/302/303 转 GET，307/308 保留 body，`Authorization` 不跨源。
- 策略拒绝映射为不可重试的 `provider_endpoint_error`，DNS 失败映射为可重试的 `provider_unavailable`；错误文案为固定文本，不含 URL/host/IP/key。`UrllibJsonTransport` 仅为旧测试/显式注入保留，默认工厂不再使用。

### 密钥加密层（L5 / B6b）

`services/secret_store.py` 是唯一接触主密钥与密文的模块，`ProviderSettingsService` 只调用它的窄接口：

```
MasterKeyStore(Protocol).load_or_create() -> bytearray   # 32 字节
SecretBox.encrypt(plaintext, aad) -> SecretBlob(nonce, ciphertext, alg)
SecretBox.decrypt(blob, aad) -> str
default_master_key_store(data_dir, *, allow_create=True) -> Dpapi / Keychain / File 之一
write_private_document(path, payload)                    # 原子 + 私有权限
```

「是否允许创建主密钥」是后端构造参数（`create_if_missing` / `allow_create`），不进入
`load_or_create()` 的 Protocol 签名，调用方语义保持窄接口。

- **算法与封装**：`cryptography==50.0.2` 的 `AESGCM`（AES-256-GCM）。`AESGCM` 本身接受 16/24/32B key 与 8–128B nonce，所以封装层显式校验 `len(key)==32`、`len(nonce)==12`、tag 16B、`alg=="AES-256-GCM"`，不符即 `SecretStoreError`。主密钥用 `AESGCM.generate_key(bit_length=256)`，每次保存取新的 `os.urandom(12)`。
- **AAD 绑定**：`b"frame-ai/provider-settings/v2/<kind>"`，同时绑定格式版本与 provider 角色，跨 provider 挪动密文解密失败。
- **v2 文件形状**：`{"version":2,"vision":{"provider","model","base_url"},"decision":null,"planner":null,"secrets":{"vision":{"alg","nonce","ciphertext"}}}`。v2 存储模型 `extra="forbid"` 且**没有 `api_key` 字段**，夹带明文会被拒绝；`secrets` 只为显式保存了非空 key 的 provider 生成。v1 模型保留，只用于读旧文件与迁移，同时继续充当内存域模型；`required` 模式下内存域模型**绝不直接序列化到磁盘**。
- **主密钥后端**：Windows 走 ctypes DPAPI（`CRYPTPROTECT_UI_FORBIDDEN` + 固定 entropy，`LocalFree` 显式声明 `argtypes` 防 64 位指针截断），`provider-master-key` 里只有 blob，安全性不依赖 `chmod`（Windows 上无效）；macOS 走 Security.framework 的 Keychain 通用密码项，密钥不进 argv；其余 POSIX 用 `os.open(O_CREAT|O_EXCL|O_WRONLY, 0o600)` 创建，读取时校验 `stat.S_IMODE==0o600`，不符则 chmod 后复检，仍不符 fail-closed。所有后端失败统一 `SecretStoreError`，文案固定、不含密文/密钥。
- **平台回落决策**：支持矩阵是 Windows / Linux / macOS（P13）。`default_master_key_store` 对矩阵之外的平台（如 BSD）有意沿用 POSIX `FileMasterKeyStore`：它仍强制 `0600` 并在读取时复检权限，建立不了私有权限就 fail-closed，不存在明文回落。**不加平台白名单**，这是显式记录的回落决策而不是缺陷。
- **主密钥创建许可（不静默替换）**：`ProviderSettingsService` 在 `_load()` 之前用 `_may_create_master_key()` 判定——只有「没有覆盖文件」「v1 明文文件」「v2 但 `secrets` 为空」这三种没有密文可解的情况才允许创建第一把主密钥；只要 v2 里还有 `secrets`，就以 `allow_create=False` 构造后端，缺失/删掉的主密钥只会抛静态 `SecretStoreError`，**绝不铸造一把解不开旧数据的新密钥**（DPAPI / Keychain / POSIX 三个后端一致）。`SecretBox` 经惰性属性解析，未用到加密的启动路径不会触碰系统密钥库。
- **写入路径**：先在内存里完成全部加密与序列化（不产生半成品）→ `os.open(..., 0o600)` 建临时文件 → 写入 → `fsync` → `os.replace`；任一步失败删除临时文件并抛错。
- **v1→v2 迁移顺序**：读 v1 → 校验生效配置（含 B6a 网络策略）→ 构建 Bundle → **再**写 v2。非法 v1 不迁移、原文件保留；失败时 v1 字节完全不变、临时文件清理、启动抛 `ProviderConfigurationError`（fail-closed，不以明文继续运行）；成功记 `provider_settings_migrated from=1 to=2`，不带字段值。
- **读取分支**：先读 JSON `version`：2 → 校验 v2 并逐 provider 解密；1/缺失 → 按 v1 读并标记待迁移；其他 → `ProviderConfigurationError`。解密的 `InvalidTag`/base64/长度错误统一转 `SecretStoreError`，只记录 kind 与异常类型名。**解密后的明文重建 `StoredProviderEntry` 也放在同一 try 边界内**并额外捕获 `ValidationError`：超长/非法明文只抛固定文案的 `ProviderConfigurationError`，日志只有 `error_type`，不会让 pydantic 通过 `input_value` 回显 key 前缀。所有解析异常用 `raise ... from None`，避免 pydantic 异常链回显输入里的明文 key。
- **开关与错误**：`FRAME_PROVIDER_SETTINGS_ENCRYPTION=required|off`，默认 `required`；`off` 写明文 v1 并在启动与每次保存打 WARNING（仅回退/救援），读 v2 仍需主密钥。启动/迁移/解密失败 → `ProviderConfigurationError`；保存期加密失败 → HTTP 500 `secret_store_error`，写盘失败 → 500 `provider_settings_write_failed`，运行时配置与磁盘文件都不变。API 视图仍只有 `hasApiKey`/`apiKeySource`，前端无需改动（`describeSettingsError` 对未知 code 回落到安全 message）。
- **测试分层**：单元层用 `InMemoryMasterKeyStore` 与 fake DPAPI 函数 / fake Keychain bridge，不触碰真实系统密钥库；API 集成层用平台默认后端（Windows 上是真实 DPAPI）。POSIX 权限断言在 Windows 上 skip，Windows DPAPI blob 断言在其他平台 skip，不互相伪通过。「v2 有密文 + 主密钥缺失 → 拒绝创建」与「无密文 → 正常创建首把密钥」两条回归覆盖三后端：Windows 上真实 DPAPI 分支实跑，POSIX / Keychain 用 fake 后端加参数化平台断言。macOS Keychain **未实机验证**。

### AI 摄影师（阶段 5）

```text
POST /api/v1/ai/photographer/plan
  → 读取会话活动 revision 与已完成的分析报告 → 校验 analysisId 归属该会话/图片
  → 组装结构化诊断摘要 + 风格定义（参数化，无 LUT）→ Planner Provider
  → 意图（AdjustmentIntent + 方向 + changes）→ 服务端校验范围/蒙版/冲突 → 完整配方
  → photographer_plan 入库（provider/model/prompt_version/is_mock/degraded/confidence）
  → 返回预览；不写 revision、不改原图
POST /api/v1/ai/photographer/chat
  → 当前配方 + 指令原文（只在该次请求内使用）→ 最小补丁：只写 adjustments.<field>
    与已有蒙版的 localAdjustments.<maskId>.<field>，曲线/HSL/分级/蒙版/裁剪/旋转/输出保持不变
  → 越界能力返回 200 + supported:false（配方逐字段不变）；无法映射返回 supported:true + 空 changes + warnings
POST /api/v1/ai/photographer/critique
  → 只读分析报告 → 确定性规则（不调用语言模型）→ strengths / technical / creative / suggestions
  → 每条结论带 evidenceRefs；离开服务端前校验引用闭合，越界即 500 critique_invalid
POST /api/v1/ai/photographer/feedback
  → 用户行为（accepted/rejected/reset）+ 可选 10 维 1–5 评分 → 服务端派生 modified 与 changedPaths
  → 同一 (planId, action) 幂等；不保存指令原文、照片或文件名
GET  /api/v1/ai/photographer/feedback  → items + summary（计数、来源、mock/真实、均分、固定 disclaimer）
```

- Provider 分工：分析阶段的视觉 Provider 收到内存 JPEG 副本；摄影师的 Planner 只收到结构化诊断摘要与风格参数，**不接收图片**。`isMock` 与 `degraded` 随方案、点评与反馈如实返回。
- 方案与补丁都只是预览：接受由前端显式提交 `POST /sessions/{id}/revisions`（`source:"ai"`），历史、撤销/重做与幂等仍由阶段 2 的 revision 事务保证。
- 风格全部以配方参数表达，不依赖 LUT 或滤镜文件；风格 id 是开放命名空间，与渲染引擎的 7 个 `styleId` 解耦。
- 点评是确定性的：同一份报告必然得到同一份点评（e2e 断言两次响应逐字节相同）；技术问题按置信度分档，创作建议全部 `subjective:true`。
- 反馈不参与渲染与方案生成：只写入 `photographer_feedback`，可单条删除或随图片/会话级联；汇总不输出“质量提升”类结论。

## 数据模型

```text
data/
├── frame.db                 SQLite（权威）
├── originals/<uuid>.<ext>   原图（只读，权威）
└── tmp/previews/
    ├── <hash>.jpg           预览缓存（可丢弃）
    └── proxies/<hash>.jpg   方向归一/缩放代理缓存（可丢弃）
```

- `image_asset`：图片元数据、显示尺寸、`sha256`、原始方向。
- `edit_session`：`image_id`、`active_revision_id`、`head_revision_id`、状态与时间。
- `edit_revision`：`session_id`、`parent_id`、`revision_no`、配方 JSON/哈希、`source`、`idempotency_key`、时间。
- `UNIQUE(session_id, revision_no)` 与 `UNIQUE(session_id, idempotency_key)`。
- `analysis_task`：`image_id`、`image_sha256`、选项、`config_key`、唯一 `dedupe_key`、状态/阶段/尝试次数、错误码与时间。
- `analysis_result`：`task_id`、报告 Schema 版本、`is_mock`、报告 JSON 与时间。
- `photographer_plan`：`image_id`/`session_id`/`analysis_id`（均级联删除）、`mode`（`auto`/`style`/`chat`）、风格 id/版本/强度、`provider`/`model`/`prompt_version`、`is_mock`/`degraded`、`confidence`、方案 JSON、结果配方 JSON/哈希与时间。
- `photographer_feedback`：`image_id`/`session_id` 级联删除，`plan_id`/`revision_id` 可空并随父行级联；`action`、`source`、`changed_paths_json`、`rubric_json`、`is_mock`/`degraded` 与时间；`UNIQUE(plan_id, action)` 保证决策幂等（`plan_id` 为 NULL 的 `reset` 行不受约束，各自独立）。
- 迁移：`app/repositories/migrations/`，`schema_migrations` 记录版本与 checksum；已应用迁移不可修改；`0002_analysis.sql` 新增分析两表，`0003_photographer_plan.sql`、`0004_photographer_feedback.sql` 新增阶段五两表。
- 阶段 1 的 `image_registry.json` 在启动时幂等导入，之后备份为 `*.imported.bak`。

`FRAME_DATA_DIR` 若为相对路径，一律相对**仓库根目录**解析，与启动时的工作目录无关。

## 一致性与并发

- 单进程假设：SQLite 写事务、预览写锁、导出准入（并发槽位 + 内存预算）、两层渲染 LRU 与分析线程池都是进程内机制。
- 会话提交在 `BEGIN IMMEDIATE` 中完成校验、取号、插入与 active/head 更新，避免重复 `revision_no`。
- 分析任务用唯一 `dedupe_key`（含 `image.id`、内容 sha256 与配置）与 `BEGIN IMMEDIATE` 防重复创建；同一资产同配置才复用，失败重试复用原记录；`analysis_max_concurrency` 默认 2。
- 原图写入与 SQLite 插入之间失败会回滚删除文件；进程在两步之间崩溃可能留下孤儿文件，启动扫描只告警。
- 导出准入是进程内的“并发上限 + 估算总和”两道门（`FRAME_EXPORT_MAX_CONCURRENCY` 默认 1）：任一不满足立即 503，不排队；释放按估算值扣减，因此并发导出共享同一内存预算。
- 预览写入使用临时文件 + `os.replace`；Windows 目标被占用时短重试并回退到已存在文件。
- 多 uvicorn worker、跨进程缓存一致性与水平扩展不在当前范围。

## 安全边界

- Host 白名单防止 DNS 重绑定；写入请求校验 Origin 与 `Sec-Fetch-Site`，CORS 预检使用统一错误信封。
- 服务端判定 MIME 与真实解码格式，声明类型不匹配返回 415。
- 上传限额同时由纯 ASGI 中间件（实际字节）与业务层（文件字节）执行。
- 用户文件名只用于展示与下载头；磁盘文件名始终是 UUID。
- 原图只读：没有覆盖或改写接口；导出从原图重算。
- 导出剥离全部元数据并嵌入 sRGB ICC；原图下载保留原始 EXIF/GPS，界面提示。
- 日志不记录图片字节、Base64、原始文件名、配方内容、分析报告正文或密钥；阶段五另加：不记录对话指令原文（只记录长度）、不记录反馈评分明细。
- 默认 Mock Provider 完全离线；只有显式选择 `openai` 时才会把 1024 px JPEG 副本发给视觉服务，决策服务只收结构化数据；摄影师的 Planner 任何模式下都不接收图片。
- Provider 错误统一包装为安全错误码与文案；响应/任务错误不包含密钥、原始模型响应、图片字节或绝对路径。
- Provider 出站默认只允许公网 HTTPS；私网/回环需显式 `allow-local`，链路本地/云元数据/组播/保留/未指定地址始终拒绝。DNS 每个结果在连接前校验并固定 IP，环境代理不能改变请求路径；重定向同源且最多 5 跳；错误/日志不含 URL/host/IP/key。
- 反馈表结构上没有自由文本字段，照片、指令与文件名无法写入；用户可单条删除，图片/会话删除时级联清除。
- API 无鉴权，只绑定 `127.0.0.1`（D-13）。

## 测试布局（对任务书 §3 的有记录偏离）

任务书建议把前后端与端到端测试都放在根目录 `tests/`。当前安排：

- 后端单元/接口/黄金图测试位于 `services/api/tests/`，与 Python 包和虚拟环境同目录，便于直接运行。
- 前端组件/单元测试位于 `apps/web/tests/`，与 Vitest 配置同目录。
- 根目录 `tests/e2e/` 放 Playwright 端到端测试与夹具。

这是有记录的偏离，不改变任务书要求的测试覆盖内容。
