# FRAME AI

响应式、非破坏性照片后期工具。本仓库已完成 **开发阶段 5：AI 摄影师与智能后期决策**（Task 0–9），在阶段 3 的视觉理解之上增加了可解释的调色方案、参数化风格、对话修改、摄影点评与反馈闭环；执行层沿用阶段 4 的专业调色引擎（配方 v2、全局调色、RGB 曲线、八色带 HSL、三区域颜色分级、全图/矩形/椭圆蒙版局部调整，以及导出尺寸、两层进程内缓存、导出并发准入与渲染序号统一）。阶段 2 的完整编辑闭环继续保留：上传、自动建会话、手动参数调整、前后对比、撤销/重做/重置，到从原图全分辨率导出 JPEG/PNG/TIFF（PNG/TIFF 可选 8/16-bit，带 alpha 时保留透明度）。

原图字节从上传到导出全程不变；编辑只记录配方（recipe）与 revision，渲染始终从原图重算。阶段 3 的异步分析任务（预处理与 OpenCV 测量、可替换的视觉/决策 Provider、主体与区域引用、摄影问题诊断、五区界面）继续作为阶段 5 的输入。阶段 5 的 AI 摄影师把“照片是什么样”转换为“建议调什么、调多少、为什么”，但**只生成提案并在预览中展示，不自动写入配方或修改原图**；只有用户显式接受后才生成普通 revision。默认使用离线 Mock Provider，风格由参数实现，**不伪造人物/天空语义分割**。

## 开发状态

| 开发阶段 | 状态 | commit | 日期 |
| --- | --- | --- | --- |
| 开发阶段 1：可运行骨架与上传预览 | 已完成 | `11dd6d3` | 2026-11-02 |
| 开发阶段 1.1：阶段 1 审查收尾 | 已完成 | `a494e45` | 2026-11-02 |
| 开发阶段 2：图像管线与非破坏编辑 | 已完成 | `a7e8fca`（T2.13 代码验证；T2.14 文档随后提交） | 2026-11-02 |
| 开发阶段 2.1：阶段 2 审查修复 | 已完成 | `22ed468`（F2-00…F2-14；F2-15 回归与交接随最终提交） | 2026-11-03 |
| 开发阶段 3：AI 摄影理解与智能诊断 | 已完成（commit `1f8909b`） | 见 [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md) | 2026-11-03 |
| 开发阶段 4：专业摄影调色引擎 | 已完成（Task 1–8，含色彩管理收尾与性能/内存治理；commit `1f8909b`） | 见 [STAGE_4_COMPLETION_REPORT.md](STAGE_4_COMPLETION_REPORT.md) | 2026-11-04 |
| 开发阶段 5：AI 摄影师与智能后期决策 | 已完成（Task 0–9；改动尚未提交） | 见 [STAGE_5_COMPLETION_REPORT.md](STAGE_5_COMPLETION_REPORT.md) | 2026-11-06 |

阶段 1.1 的完整命令、退出码与测试清单见 [docs/handoff/phase-1.1.md](docs/handoff/phase-1.1.md)；阶段 2 的完整交接见 [docs/handoff/phase-2.md](docs/handoff/phase-2.md)；阶段 2.1 审查修复见 [docs/handoff/phase-2.1.md](docs/handoff/phase-2.1.md)；阶段 3 的测试、性能与遗留问题见 [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md)；阶段 4 的逐 Task 交付、验收对照与回滚方式见 [STAGE_4_COMPLETION_REPORT.md](STAGE_4_COMPLETION_REPORT.md)；阶段 5 的逐 Task 交付、测试计数与未评估项见 [STAGE_5_COMPLETION_REPORT.md](STAGE_5_COMPLETION_REPORT.md)。

### 根目录文档索引

根目录保留多份阶段性文档，职责与重叠关系如下（未移动或删除任何文件）：

- [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md) / [STAGE_4_COMPLETION_REPORT.md](STAGE_4_COMPLETION_REPORT.md) / [STAGE_5_COMPLETION_REPORT.md](STAGE_5_COMPLETION_REPORT.md)：对应阶段的正式交接，含逐 Task 交付、门禁与测试计数、性能实测、验收对照与回滚。
- [STAGE_3_INITIAL_AUDIT.md](STAGE_3_INITIAL_AUDIT.md) / [STAGE_4_AUDIT_REPORT.md](STAGE_4_AUDIT_REPORT.md) / [STAGE_5_AUDIT_REPORT.md](STAGE_5_AUDIT_REPORT.md)：阶段开工前的现状审查与风险清单，属于历史快照，结论以完成报告为准。
- [STAGE_3_4_CODE_REVIEW_2026-11-04.md](STAGE_3_4_CODE_REVIEW_2026-11-04.md)：阶段 3/4 联合代码复审；逐条整改方案见 [docs/plans/stage-3-4-review-remediation.md](docs/plans/stage-3-4-review-remediation.md)，两份文档的问题编号一一对应。
- [阶段三.md](阶段三.md) / [阶段四任务书.md](阶段四任务书.md) / [阶段四操作建议.md](阶段四操作建议.md) / [第五阶段任务书.md](第五阶段任务书.md) / [第五阶段实施方法.md](第五阶段实施方法.md)：各阶段的任务书与操作建议，是验收口径的来源；完成报告只引用、不改写任务书。
- [phase 2 review.md](phase%202%20review.md) / [建议与标准.md](建议与标准.md)：阶段 2 复审与通用标准素材，保留为参考，不属于当前交付链。
- [FRAME_AI_UI_改造记录.md](FRAME_AI_UI_改造记录.md) / [FRAME_AI_滑杆预览闪烁_解决方案.md](FRAME_AI_滑杆预览闪烁_解决方案.md) / [FRAME_AI_上传后未知错误_排查与解决方案.md](FRAME_AI_上传后未知错误_排查与解决方案.md)：用户侧 UI 改造记录与两次问题排查方案；其中滑杆闪烁与上传错误诊断已落地，UI 改造记录描述目标而非现状。

系统化规范与决策见 [docs/](docs/) 下的 `architecture.md`、`api-contract.md`、`color-management.md`、`performance.md`、`known-issues.md` 与 `decisions/`；阶段 5 的人工评估规范、14 类测试图与 A/B/C/D 模板见 [docs/evaluation/stage-5-evaluation.md](docs/evaluation/stage-5-evaluation.md)。

## 当前范围（阶段 3 + 阶段 4 + 阶段 5）

已实现：

- 安全上传：MIME 与内容双重校验、20 MiB / 40 MP 硬限制、随机 UUID 文件名、原图只读保存。
- SQLite 持久化：`image_asset / edit_session / edit_revision` 三表、自写版本迁移、阶段 1 JSON 登记表幂等导入。
- 配方 schema：15 个 `adjustments` 字段、硬范围校验、两位小数限制、规范化哈希。
- 确定性渲染管线：EXIF 方向归一 → 模式归一 + 嵌入 ICC 转 sRGB → 缩放 → 几何（旋转内接 + 裁切）→ sRGB→线性 → 曝光 → 白平衡 → 高光/阴影 → 白色/黑色色阶 → 线性→sRGB → 对比度 → 曲线 → HSL → 饱和度/自然饱和度 → 颜色分级 → 局部调整（蒙版）→ 清晰度/暗角 → 细节（降噪/锐化）→ 颗粒 → uint8。
- 会话与 revision：自动创建初始 revision、提交、撤销、重做、激活任意历史、重置、`Idempotency-Key` 幂等与内容一致性校验、409 冲突处理；历史操作前自动保存未提交草稿。
- 预览：`draft` 960 px / `final` 1600 px、内容寻址缓存、方向归一代理缓存、TTL 清理与 `cacheHit`；`X-Render-Seq` 保证过期渲染不覆盖新操作。
- 前后对比：原图侧仅应用相同旋转/裁切，与渲染代理保持同尺寸和像素对齐，含按住空格查看原图。
- 导出：从原始分辨率重渲染、JPEG/PNG/TIFF、剥离全部 EXIF/XMP/IPTC/GPS、嵌入 sRGB ICC、导出串行化、运行期内存预算与降噪提示；PNG/TIFF 可选 8/16-bit，透明输入导出 RGBA（8/16-bit alpha），JPEG 在白底合成且只支持 8-bit。16-bit 输入不被截断，工作空间保持 float32；16-bit + 降噪会跳过降噪并返回 `denoise_skipped_for_16bit`。预览与代理仍为 8-bit 白底 RGB，不因 alpha 失效缓存。
- 前端编辑工作区：参数面板、裁切/旋转、历史栏、对比视图、导出对话框、可访问性检查。
- 预览可见性：桌面端左列预览与历史栏固定在视口内、参数面板独立滚动；窄屏在主预览离屏时显示固定迷你预览（对比/裁切/导出时隐藏）。
- AI 分析任务：`POST /analysis` 异步创建，`pending/processing/completed/failed` 状态与真实阶段（预处理/视觉/特征/诊断）；失败任务保留供重试，`force=true` 重新分析，按图片内容与配置去重。
- 预处理与 CV 测量：从只读原图生成内存 JPEG 副本（最长边 `FRAME_ANALYSIS_MAX_EDGE`，默认 1024），透明通道按白底合成并记录限制；亮度分位、直方图、截断、色偏、饱和度分布、RGB/HSV 直方图、主色集中度、清晰度、噪声、梯度各向异性、地平线倾斜与主色。
- 可替换 Provider：视觉、决策与规划三个独立接口（规划未单独配置时逐字段跟随决策）；`mock`（默认，离线）与 OpenAI 兼容实现；API Key 只保存在服务端，可来自环境变量或页面内“模型设置”写入的本机覆盖文件，GET 只返回是否已配置；决策模型只接收结构化测量与语义，不接收图片；模型调用日志记录 provider/model/阶段/重试/token/延迟，不记录图片或 Base64。
- 应用内模型设置：顶栏入口可分别配置视觉/决策/规划（可选）Provider、模型名、Base URL 与 API Key；规划留空的字段逐项跟随决策；保存后原子写入 `<FRAME_DATA_DIR>/provider-settings.json` 并热替换 Provider，新任务立即生效；“测试连接”只发送文本提示，不发送用户图片。
- 主体与区域：视觉输出主体类型、归一化边界框、置信度与区域 ID；只提供边界框与区域引用，**没有像素级蒙版**；为后续局部调色预留统一区域接口。
- 摄影诊断：曝光、色彩、构图、清晰度（含动态模糊/细节不足）、光线候选问题均带测量证据、严重度、置信度、关联区域与逐条建议；色彩协调/构图遮挡/主体占比进入结果；决策结果经后端校验，`unknown` 不会被包装成事实；场景/主体/光线/色彩/构图/质量诊断可按 `AnalysisOptions` 关闭并在局限中说明。
- 前端分析界面：工具栏入口、五区结果、Mock 徽标、局限说明、真实阶段状态、主体框叠加、构图与遮挡摘要、可展开证据、逐条建议、重新分析、失败重试、切换图片清空状态。
- 评估与真实 Provider 验证工具：[`docs/evaluation.md`](docs/evaluation.md)、`scripts/eval_analysis.py`（标注集指标）、`scripts/smoke_live_provider.py`（未配置时安全跳过）。
- Playwright 端到端（桌面 1280×800 与窄屏 390×844，含分析重试/查看/重新分析/换图与上传编辑导出回归）与阶段 2/3 性能基准。
- 配方 v2：在阶段 2 的 15 个全局字段之上新增曲线、八色带 HSL、三区域颜色分级、用户蒙版与局部调整；`schemaVersion:"1.0"` 读取时自动升级，未知字段与越界值返回 422。
- 专业全局调色：曝光、白平衡、高光/阴影、白色/黑色色阶在线性光空间执行，对比度、饱和度/自然饱和度在 sRGB 空间执行；所有参数为 0 时恒等。正向 Blacks 压暗阴影末端（Lightroom 约定），对比度把色度回收至原值 ±5% 内。
- RGB 曲线：Master → Red → Green → Blue 依次应用，Fritsch–Carlson 单调三次 Hermite 插值，空通道恒等；不产生额外过冲；首末节点之外按端点斜率线性外推后截断。
- 八色带 HSL：红/橙/黄/绿/青/蓝/紫/洋红，相邻色带 smoothstep 平滑过渡；色相在低色度上渐隐，饱和度/明度用更低门控，皮肤与天空上的滑块仍然有效。
- 颜色分级：按 Rec.709 亮度平滑分配阴影/中间调/高光，支持色相、强度、balance 与 blending；零亮度色偏在未截断时保持亮度。
- 局部调整：全图或用户矩形/椭圆蒙版，支持曝光、对比、高光、阴影、白/黑场、色温、色调、饱和、自然饱和度、清晰度 11 个字段；羽化带位于形状内部，支持反选与不透明度；蒙版锚定 EXIF 归一化原图坐标，预览与导出共用同一映射；悬空蒙版跳过并返回 `local_mask_missing` warning。
- 编码 `frame-engine/10`。`schemaVersion` 参与 canonical 哈希，因此 v1→v2 重标会改变旧 revision 在新代码下计算出的摘要；`recipe_hash` 列只作缓存，重置与幂等比较都用当前代码从已存 `recipe_json` 重新推导，不承诺跨版本哈希恒定。空 `masks` 是唯一被省略的惰性字段。新增曲线、HSL、颜色分级与局部调整黄金图。`frame-engine/8` 把嵌入 ICC 管理的适用范围从 `RGB`/`RGBA` 扩展到全部可归一为 RGB 的输入（含调色板、1-bit、灰度）；`frame-engine/9` 修正三处调色语义——白平衡改为守恒全图平均亮度（纯色不再自我抵消）、HSL 色相改为受单调上限约束的查表映射（消除局部色相反序与等色轮廓带）、颜色分级越界由逐通道裁剪改为等比缩放（黑位不被抬亮）；`frame-engine/10` 落地复审摄影语义决策——Blacks 方向与掩膜端点、HSL 分档门控、曲线端点线性外推、对比度色度回收，并删除遗留 `POST /images/{id}/analyze`。
- 色彩管理（Task 7 + B5b）：8-bit 路径的 ICC 管理移到模式归一之后，调色板/1-bit/灰度输入按嵌入配置转换；16-bit 路径用 OpenCV/tifffile 解码并以纯 NumPy 矩阵/TRC 转换到 sRGB，支持 `curv`/`para 0–4`，LUT/mAB/mft 或非 RGB/XYZ 配置返回 422 `unsupported_icc_profile`，不静默降级。CMYK 上的 RGB 配置仍回退；依赖边界见 [docs/color-management.md](docs/color-management.md) 与 [ADR-0004](docs/decisions/ADR-0004-color-management.md)。
- 导出尺寸与色彩空间（Task 8）：`maxEdge`（64…100000，前端另给原图/2400/1600/1080 预设与 64…8192 自定义）在解码之后、渲染之前缩放源图，构图与全尺寸导出一致且**不放大**；`colorSpace` 只接受 `"sRGB"`，其他值 422。24 MP 满配方导出因此从 p50 29.6 s 降到 4.6 s。
- 渲染缓存分层（Task 8）：解码代理与蒙版权重的进程内 LRU（各 `FRAME_PROXY_CACHE_MB`/`FRAME_MASK_CACHE_MB`，默认 64 MB，0 关闭）＋代理磁盘缓存；`previews/proxies/` 纳入同一轮 TTL 清理。预览冷解码 200–471 ms → 内存命中 12–13 ms，蒙版权重 57–67 ms → 0.02 ms。
- 导出并发准入（Task 8 + G4）：`FRAME_EXPORT_MAX_CONCURRENCY`（默认 1，上限 4）与"在跑导出估算之和 ≤ `FRAME_EXPORT_MAX_RSS_MB`"两道门，任一不满足立即 503 `server_busy` 带 `Retry-After: 2`，不排队；通过静态估算后还会用 psutil 的实时可用内存做第二道门（`FRAME_EXPORT_RESERVE_MB`，默认 256）。估算系数按 Task 8 的 11 个与 G4 的 8 个实测峰值标定，满配方为 160 B/px，并保留原图解码地板。
- 渲染取消加强（Task 8）：前端统一用 `nextRenderSeq()`（`apps/web/lib/render-seq.ts`）发号，滑杆预览与裁切底图共用同一序列，服务端解码代理后再查一次序号，过期请求 409 `render_superseded` 不再白算。
- AI 摄影师方案（阶段 5）：`POST /ai/photographer/plan` 复用已有分析报告，输出方向、诊断、具体参数改动、逐条理由与证据；`mode` 为 `auto`/`style`（对话修改走独立 `/chat`），Mock 下同输入可复现，`isMock`/`degraded` 如实标注。方案只入库为提案，**不写 revision、不改原图**。
- 参数化风格库：12 个风格（自然摄影、自然人像、清透人像、风光、街头、纪实、复古胶片、电影叙事、黑白纪实、鲜艳纪实、暖调生活、冷调城市），每个风格有独立版本、适用场景、参数包络与约束；强度 0–1 缩放；风格效果全部落实为配方参数，`styleId/styleStrength` 只是元数据。
- 对话修改：`POST /ai/photographer/chat` 把自然语言指令映射为允许路径上的参数补丁，只改被要求的参数，未提及参数保持不变，返回 `changes` 与提案；指令原文不落库，日志只记录长度。
- 摄影点评：`POST /ai/photographer/critique` 基于分析证据生成优点、问题、创作方向与可执行建议（确定性规则，不调用自由文本模型）；`POST /ai/photographer/critique/apply` 把建议转成可预览的配方提案。
- 反馈闭环：接受、拒绝、修改、重置四种决策自动记录，接受后可补 10 维 1–5 评分；`UNIQUE(plan_id, action)` 幂等，同一方案反复评分只更新原行；汇总带固定 disclaimer，明确“接受 ≠ 质量提升”；反馈不保存图片或指令原文，可单条删除并随图片/会话级联清除。
- 前端 AI 摄影师面板：方向与诊断、参数改动与理由、风格选择与强度滑杆、对话输入、点评、反馈历史；接受前先渲染预览，接受后走普通 revision 历史，可撤销/重做。评分对话框与导出对话框均通过 portal 挂到 `document.body`，避免工作区卡片的 `backdrop-filter` 改变 `fixed` 包含块。
- 阶段 5 评估：14 类场景回归集（33 项）、功能检查与负面用例见 [docs/evaluation/stage-5-evaluation.md](docs/evaluation/stage-5-evaluation.md)；真实照片人工评分、A/B/C/D 对照与真实 Provider 稳定性仍为未评估项。

明确未实现（后续阶段）：

- 自动应用配方：阶段 5 会生成方案并在预览中展示，但只有用户点击“应用”才写入普通 revision；没有后台自动调色、批处理或跳过确认的路径。
- 人物/天空语义分割与自动蒙版；局部调整只支持全图与用户手动画的矩形/椭圆，阶段三 bbox 不会被当作蒙版，AI 也不能引用不存在的蒙版。
- 栅格蒙版、画笔/渐变蒙版、蒙版布尔运算与图层混合；当前蒙版是随 recipe 保存的参数化几何。
- 几何编辑（裁剪/旋转/扩图/删除物体/换背景）不由 AI 发起；方案不生成裁切或旋转。
- 真实视觉/规划模型的准确率、成本与稳定性评估；本机没有授权标注集与真实密钥，默认 Mock Provider 未调用第三方。评估框架与冒烟脚本已提供，但正式指标仍为未测量。
- 预览、代理与 AI 分析仍为 8-bit 白底 RGB；16-bit 只用于上传解码与导出，没有 HDR/32-bit 管线，16-bit JPEG 不支持；TIFF 只接受单页、未压缩或 Deflate（见 [known-issues.md](docs/known-issues.md)）。
- 删除后的回收站/撤销、跨进程一致性与配额、多用户。
- 鉴权、限流、公网部署加固；API 仅限本机（D-13）。
- 真实 iOS Safari / Android Chrome 真机回归。

## 架构与请求流

```text
Browser (Next.js 16 / React 19)
  │  POST /api/v1/images (multipart)
  │  POST /api/v1/sessions/{id}/render | revisions | undo | redo ...
  │  POST /api/v1/exports → GET/DELETE /api/v1/exports/{jobId} → GET .../result
  ▼
Next.js rewrite: /api/v1/* → API_INTERNAL_URL (default 127.0.0.1:8000)
  │
  ▼
FastAPI
  ├─ RequestContextMiddleware      请求 ID、耗时、状态码日志
  ├─ LocalOriginGuardMiddleware   Host 白名单、Origin 与跨站写入防护
  ├─ CorsPreflightGuardMiddleware CORS 预检统一错误信封
  ├─ UploadSizeLimitMiddleware    Content-Length 预检与流式字节限制
  ├─ ImageService                 解码校验 → originals/<uuid> → image_asset
  ├─ SessionService               revision 事务、undo/redo/activate/reset、幂等
  ├─ RenderService                渲染序号 → 代理缓存 → pipeline → previews/<hash>
  ├─ ExportService                串行槽位 → 内存预算 → 全分辨率重渲染 → 文件流
  ├─ ExportJobManager             异步导出作业、队列上限、取消、结果文件与 TTL
  ├─ AnalysisService              阶段 2 启发式特征（进程内 LRU，保留兼容）
  ├─ AnalysisTaskService          分析任务队列、去重、恢复、重试、结果入库
  ├─ AnalysisOrchestrator         预处理 → 视觉 → CV 特征 → 诊断 → 报告
  ├─ PhotographerService          方案/对话/点评/反馈、并发槽位、校验与落库
  ├─ PhotographerPlanner          结构化分析 + 偏好/风格 → 方案（mock 或 OpenAI 兼容）
  ├─ ProviderBundle               vision/decision Provider（mock 或 OpenAI 兼容）
  └─ PreviewStore                 TTL 清理、原子写入
```

浏览器默认通过同源 `/api/v1` 代理访问后端，本地开发不依赖 CORS。FastAPI 也允许在 `.env` 中配置跨域来源，便于直接访问 API。

分析任务流：

```text
POST /api/v1/analysis
  → 校验图片与选项 → config_key / dedupe_key
  → 命中未完成/已完成任务：直接复用（200），不重复入队
  → 命中 failed 任务：原子翻转 failed→pending 后才重新入队（抢占失败则只返回当前行）
  → 待分析队列已满（≥ FRAME_ANALYSIS_QUEUE_MAX）：503 server_busy + Retry-After
  → 新建任务 → 202，后台线程执行
      → 抢占：compare-and-set pending→processing，失败方立即退出（不写状态、不写结果）
      → 预处理：sha256 校验 → 解码 → 缩放 → 白底合成 → 内存 JPEG
      → 视觉 Provider：场景/主体/光线/色彩/构图 JSON（经 Schema 校验）
      → CV 特征：亮度分位/直方图/截断/色偏/饱和度/清晰度/噪声/主色
      → 诊断：候选问题（测量证据）→ 决策 Provider 校验 → 报告
      → 每个阶段切换点检查 FRAME_ANALYSIS_TIMEOUT_SECONDS 时间预算，超时写 analysis_timeout
      → 结果入库与状态更新在同一事务，且只在 processing 状态下生效；抢占已失则丢弃结果并记日志
GET  /api/v1/analysis/{id}          → 状态、阶段、mock 标记（来自产出该报告的那次运行）、完成时内嵌报告
GET  /api/v1/analysis/{id}/result   → 仅 completed 时返回完整报告
```

视觉 Provider 收到的是最长边 1024 px 的内存 JPEG 副本；决策 Provider 只收到测量、语义与候选问题，不收到图片。原图始终只读。

阶段 5 方案流：

```text
POST /api/v1/ai/photographer/{plan|chat}
  → 校验 session / image / analysisId 一致性（不匹配 409）
  → 读取已完成的分析报告与图片尺寸；Planner 只收结构化摘要，不收图片字节
  → 取进程内并发槽位（FRAME_PHOTOGRAPHER_MAX_CONCURRENCY，满则 503 photographer_busy）
  → 规则/风格/偏好 → 配方提案 → 范围、路径、证据与蒙版校验
  → Provider 输出不可解析时确定性规则回退并标 degraded；非法输出 502、超时 504
  → photographer_plan 落库（mode/style/version/provider/isMock/degraded/置信度）
  → 前端仅预览；用户接受才提交普通 revision（source:"ai"），拒绝/修改/重置写反馈

POST /api/v1/ai/photographer/critique       → 确定性规则 + 证据校验，不调用模型
POST /api/v1/ai/photographer/critique/apply → 建议转补丁，走同一路径/范围校验
```

方案与反馈的语义、错误码与 curl 示例见 [docs/api-contract.md](docs/api-contract.md)；14 类场景的期望行为与人工评分口径见 [docs/evaluation/stage-5-evaluation.md](docs/evaluation/stage-5-evaluation.md)。

渲染管线固定顺序（D-08）：

```text
原图字节 → EXIF 方向归一 → 模式归一 + 嵌入 ICC 转 sRGB → 代理缩放 → 旋转内接/裁切 → sRGB→线性
        → 曝光 → 白平衡 → 高光/阴影 → 白色/黑色色阶 → 线性→sRGB
        → 对比度 → 曲线（Master → R → G → B）→ HSL 色带（8 色）
        → 饱和度/自然饱和度 → 颜色分级（阴影/中间调/高光）
        → 局部调整（全图/矩形/椭圆蒙版）→ 清晰度/暗角
        → 降噪/锐化 → 颗粒 → uint8
```

`adjustments`、`curve`、`hsl`、`colorGrading`、`masks` 与 `localAdjustments` 是渲染权威；`styleId/styleStrength` 只作为来源元数据（D-10）。任何像素算法或常数变化都必须提升 `ENGINE_VERSION` 并重新生成黄金图。

当前引擎版本为 `frame-engine/10`，阶段四在全局调色之后新增 Master/Red/Green/Blue 曲线（Fritsch–Carlson 单调三次插值）、八色带 HSL（平滑相邻过渡，灰色不受影响）、三区域颜色分级（按亮度平滑分配阴影/中间调/高光，零亮度色偏）与局部蒙版调整（EXIF 归一化原图坐标、矩形/椭圆、羽化/反选/不透明度，缺失蒙版跳过并 warning）。`frame-engine/8` 同时把嵌入 ICC 管理的适用范围从 `RGB`/`RGBA` 扩展到全部可归一为 RGB 的输入（调色板、1-bit、灰度），策略与实测见 `docs/color-management.md`。`frame-engine/10` 落地复审的摄影语义决策：Blacks 正向压暗、HSL 分档门控、曲线端点线性外推、对比度色度回收，并删除遗留 `POST /images/{id}/analyze`。自 `frame-engine/2` 起，旋转只缩小画布到最大内接矩形，内容保持原比例（矩阵缩放固定为 1.0），因此画布不再包含源图之外的镜像像素；旧预览缓存键含引擎版本，会自动失效，已保存的 revision 是配方 JSON，不受影响。全局调色、曲线、HSL、颜色分级与局部蒙版数学定义见 `docs/architecture.md`。

## 目录

```text
.
├── apps/web/                     Next.js 页面、组件、编辑器、API 客户端、前端测试
│   ├── app/                      App Router 页面与全局样式
│   ├── components/               通用 UI 与图标
│   ├── features/editor/          上传、编辑工作区、调整面板、对比、裁切、历史、导出
│   ├── features/analysis/        AI 分析面板、五区报告、主体叠加、状态 Hook
│   ├── features/photographer/    AI 摄影师面板、风格、对话、点评、反馈与评分
│   ├── lib/                      API 客户端、配方规范化、错误映射、上传校验
│   └── tests/                    Vitest + Testing Library + axe
├── services/api/                 FastAPI 服务
│   ├── app/api/routes/           health、config、images、sessions、previews、analysis、settings、photographer
│   ├── app/ai/                   Provider 接口、Mock、OpenAI 兼容适配、传输与错误
│   ├── app/analysis/             预处理、CV 特征、区域、诊断、编排
│   ├── app/photographer/         规则、风格、方向、生成、校验、补丁、点评、服务
│   ├── app/core/                 配置、错误、日志、中间件、上传限额
│   ├── app/imaging/              loader、geometry、tone、color_ops、local、local_masks、detail、output、pipeline
│   ├── app/models/               Pydantic 请求/响应/配方/分析报告/方案与反馈模型
│   ├── app/repositories/         SQLite、迁移、原图存储、会话/分析/方案/反馈仓库
│   ├── app/services/             上传、会话、渲染、预览、导出、分析、分析任务
│   ├── app/tools/                阶段 1 JSON 登记表导入器
│   ├── scripts/                  OpenAPI 导出与黄金图生成
│   └── tests/                    pytest 单元/接口/黄金图测试
├── shared/contracts/             OpenAPI 契约与生成说明
├── scripts/                      统一验证、性能基准、分析评估与真实 Provider 冒烟脚本
├── tests/e2e/                    Playwright 端到端测试与夹具
├── docs/                         架构、API 契约、评估、ADR、性能、已知问题与阶段交接
├── data/                         运行期生成（已忽略）：原图、SQLite、预览缓存
├── .env.example                  后端配置样例（复制到根目录 .env）
├── playwright.config.ts          根目录 Playwright 配置
├── package.json                  E2E 依赖与脚本
├── .gitignore
└── README.md
```

## 先决条件

- Node.js 24.19.0（见 `.nvmrc`；`package.json` 要求 `>=24.19.0 <25`）。
- npm 11.17.0（见 `package.json` 的 `engines`）。
- Python 3.14.7（见 `.python-version`；代码保持 3.11+ 兼容，mypy 以 3.11 为目标）。
- Windows、macOS 或 Linux。命令示例以 Windows PowerShell / Git Bash 为主。
- 可选：Playwright Chromium，或使用系统 Edge（`E2E_BROWSER_CHANNEL=msedge`）。

## 本地启动

### 1. 后端

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

`requirements.txt` 固定 `tifffile==2026.3.3`（BSD-3-Clause），仅用于 16-bit TIFF 输入/输出；LZW 压缩需要其可选的 `imagecodecs`，本项目不引入，因此 LZW TIFF 返回 415。

可选配置：复制根目录配置样例。后端会自动读取仓库根目录的 `.env`，同时支持 `services/api/.env` 覆盖。

```powershell
cd ../..
copy .env.example .env
```

启动（D-13：必须显式绑定回环地址）：

```powershell
cd services/api
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>
- 数据目录默认：`<repository>/data`

Git Bash 等价命令：

```bash
cd services/api
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

首次启动会自动创建 `data/`、SQLite 表、预览目录与导出结果目录 `data/tmp/exports/`；若存在阶段 1 的 `data/image_registry.json`，会幂等导入并备份该文件。导出结果文件只在作业存活期间保留，启动时会清空上次进程的遗留文件。

### 2. 前端

```bash
cd apps/web
npm ci
cp .env.example .env.local   # 可选；默认值即可启动
npm run dev                  # Turbopack
# 若开发环境出现 Turbopack 问题：npm run dev:webpack
```

打开 <http://127.0.0.1:3000>。Next.js 会把 `/api/v1/*` 代理到 `API_INTERNAL_URL`，默认 `http://127.0.0.1:8000`。

### 3. 首次使用

无需任何 API Key。默认使用离线 Mock Provider，界面会显示“模拟分析（未调用真实视觉模型）”；Mock 结果只用于开发与流程验证，不代表真实模型能力：

1. 选择或拖入 JPEG/PNG/WebP/TIFF 图片（超限或类型不符会在前后端双重拦截；TIFF 仅支持单页、未压缩或 Deflate）。
2. 上传成功后自动创建编辑会话，左侧参数面板实时调整曝光、对比度、高光、阴影、色温、色调、饱和度、自然饱和度、清晰度、锐化、降噪、暗角、颗粒、旋转与裁切。
3. 可按住空格查看原图进行前后对比。
4. 每次保存生成 revision；支持撤销、重做、激活历史版本与重置。
5. 点击工具栏“AI 摄影分析”：开始分析、查看场景/主体/光线与色彩/问题/建议、显示主体框、重新分析；失败可重试，切换图片会清空旧结果。
6. 打开“AI 摄影师”面板：选择风格与强度或直接生成方案，查看参数改动、理由与证据；可在预览中确认，接受后写入普通历史，也可拒绝、重置或提交评分。对话输入用于自然语言修改，点评区显示确定性优点/问题/建议。
7. 导出 JPEG/PNG/TIFF：从原图全分辨率重渲染，自动剥离元数据并嵌入 sRGB；PNG/TIFF 可选 8/16-bit 并保留透明通道，JPEG 在白底合成且固定 8-bit。

使用真实 OpenAI 兼容视觉/决策/规划服务时，可直接在页面顶栏打开“模型设置”，填写 Provider、模型名、Base URL 与 API Key 后“保存并应用”；规划模型留空的字段逐项跟随决策模型。也可以继续用 `.env` 设置 `FRAME_VISION_PROVIDER=openai`、`FRAME_DECISION_PROVIDER=openai`（可选 `FRAME_PLANNER_PROVIDER=openai`）及对应 `*_API_KEY`、`*_MODEL`、`*_API_BASE_URL`。本地保存的字段优先于环境变量，点击“恢复环境变量配置”会删除覆盖文件（包括规划覆盖）。缺少必需配置时启动或保存失败，不会静默回退到 Mock。密钥只留在服务端的本机覆盖文件或环境变量中，不会回显到页面、日志或前端构建产物，禁止提交到版本库。

## 环境变量

后端读取 `FRAME_` 前缀变量，优先级：进程环境 > `services/api/.env` > 根目录 `.env` > 默认值。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FRAME_ENVIRONMENT` | `development` | 环境标签 |
| `FRAME_LOG_LEVEL` | `INFO` | `DEBUG/INFO/WARNING/ERROR/CRITICAL` |
| `FRAME_DATA_DIR` | `<repo>/data` | 本地数据目录；相对路径按仓库根目录解析，与启动目录无关 |
| `FRAME_DATABASE_FILENAME` | `frame.db` | SQLite 文件名，位于数据目录下 |
| `FRAME_PREVIEW_TTL_SECONDS` | `3600` | 预览缓存与 `previews/proxies/` 代理磁盘缓存的空闲秒数（按 mtime；`GET /previews/{id}` 与代理命中会刷新）；空闲超时或容量淘汰后 `GET /previews/{id}` 返回 404 |
| `FRAME_PREVIEW_CLEANUP_INTERVAL_SECONDS` | `600` | 运行期预览清理间隔秒数；启动时另清一次 |
| `FRAME_PREVIEW_MAX_BYTES` | `2147483648` | 预览目录 + `previews/proxies/` 合计容量上限（字节）；超出后按 mtime 最旧优先淘汰到上限内 |
| `FRAME_PROXY_CACHE_MB` | `64` | 解码后渲染代理的进程内 LRU 预算（MB），0 关闭；只缓存可无损转为 8-bit 的数组，开关不影响输出字节 |
| `FRAME_MASK_CACHE_MB` | `64` | 蒙版权重的进程内 LRU 预算（MB），0 关闭；单条超过 24 MB 不入库（24 MP 画布权重约 91.55 MB） |
| `FRAME_RENDER_MAX_EDGE_DEFAULT` | `1600` | `final` 预览默认最长边 |
| `FRAME_RENDER_MAX_EDGE_LIMIT` | `2560` | 预览最长边配置上限；请求字段本身仍限制在 1…2560 |
| `FRAME_EXPORT_MAX_CONCURRENCY` | `1` | 同时准入的导出数量（1…4）；准入还要求"在跑导出估算之和"不超过下面的预算 |
| `FRAME_EXPORT_MAX_RSS_MB` | `3072` | 导出预估峰值内存上限；超限返回 413 `export_too_large`，性能脚本也据此断言实测 RSS。系数在阶段四 Task 8 按 11 个实测峰值标定（45/240/8 B/px + 150 MB 基线 + 原图解码地板），复审整改 G4 把满配方降到 160 B/px；PNG/WebP/TIFF 输入另加 4 B/px 覆盖 alpha，16-bit 源与输出各加 18 B/px。默认值会拒绝 24 MP 满配方的全尺寸导出 |
| `FRAME_EXPORT_DENOISE_SIMPLIFY_PIXELS` | `12000000` | 本次实际参与渲染的像素（应用 `maxEdge` 之后）超过该值且启用降噪时，导出使用简化降噪并返回 `X-Export-Warning` |
| `FRAME_EXPORT_QUEUE_MAX` | `8` | 异步导出作业的等待队列上限（只计 `queued`，运行中的作业不计入）；达到上限后新作业返回 503 `server_busy` 并带 `Retry-After: 2` |
| `FRAME_EXPORT_JOB_TTL_SECONDS` | `3600` | 已结束导出作业的状态与结果文件保留秒数；过期后查询返回 404 `export_not_found`，结果文件在启动时也会清空 |
| `FRAME_MAX_UPLOAD_BYTES` | `20971520` | 单文件最大字节数（20 MiB） |
| `FRAME_MAX_JSON_BODY_BYTES` | `2097152` | 除 `/api/v1/images` 上传前缀外，所有 `POST/PUT/PATCH` 的请求体上限（2 MiB），超限返回 413 `payload_too_large` |
| `FRAME_MAX_IMAGE_PIXELS` | `40000000` | 最大像素数（40 MP） |
| `FRAME_CONTENT_LENGTH_ALLOWANCE` | `1048576` | Content-Length 预检给 multipart 的余量 |
| `FRAME_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | 允许直接跨域写入 API 的来源 |
| `FRAME_ALLOWED_HOSTS` | `127.0.0.1,localhost,::1` | 接受的 Host 头（防 DNS 重绑定）；留空则跳过校验 |
| `FRAME_VISION_PROVIDER` | `mock` | 视觉 Provider：`mock` 或 `openai` |
| `FRAME_VISION_API_KEY` | 空 | 视觉 Provider 密钥；仅服务端读取，禁止提交 |
| `FRAME_VISION_MODEL` | 空 | 视觉模型名 |
| `FRAME_VISION_API_BASE_URL` | 空 | OpenAI 兼容 API 根地址 |
| `FRAME_VISION_TIMEOUT` | `60` | 单次视觉请求超时秒数 |
| `FRAME_VISION_MAX_RETRIES` | `2` | 网络错误/408/429/5xx 最大重试次数 |
| `FRAME_VISION_REPAIR_ATTEMPTS` | `1` | 视觉 JSON 校验失败后的修复尝试次数 |
| `FRAME_DECISION_PROVIDER` | `mock` | 决策 Provider：`mock` 或 `openai` |
| `FRAME_DECISION_API_KEY` | 空 | 决策 Provider 密钥；仅服务端读取，禁止提交 |
| `FRAME_DECISION_MODEL` | 空 | 决策模型名 |
| `FRAME_DECISION_API_BASE_URL` | 空 | OpenAI 兼容 API 根地址 |
| `FRAME_DECISION_TIMEOUT` | `60` | 单次决策请求超时秒数 |
| `FRAME_DECISION_MAX_RETRIES` | `2` | 网络错误/408/429/5xx 最大重试次数 |
| `FRAME_DECISION_REPAIR_ATTEMPTS` | `1` | 决策 JSON 校验失败后的修复尝试次数 |
| `FRAME_PLANNER_PROVIDER` | 空 | 规划 Provider：`mock` 或 `openai`；空 = 跟随 `FRAME_DECISION_PROVIDER` |
| `FRAME_PLANNER_API_KEY` | 空 | 规划 Provider 密钥；空 = 跟随 `FRAME_DECISION_API_KEY`；仅服务端读取，禁止提交 |
| `FRAME_PLANNER_MODEL` | 空 | 规划模型名；空 = 跟随 `FRAME_DECISION_MODEL` |
| `FRAME_PLANNER_API_BASE_URL` | 空 | OpenAI 兼容 API 根地址；空 = 跟随 `FRAME_DECISION_API_BASE_URL` |
| `FRAME_PLANNER_TIMEOUT` | 空 | 单次规划请求超时秒数；空 = 跟随 `FRAME_DECISION_TIMEOUT` |
| `FRAME_PLANNER_MAX_RETRIES` | 空 | 规划请求最大重试次数；空 = 跟随 `FRAME_DECISION_MAX_RETRIES` |
| `FRAME_PLANNER_REPAIR_ATTEMPTS` | 空 | 规划 JSON 校验失败后的修复尝试次数；空 = 跟随 `FRAME_DECISION_REPAIR_ATTEMPTS` |
| `FRAME_MOCK_SCENARIO` | `generic` | Mock 场景：`generic/portrait/landscape/low_light/backlit` |
| `FRAME_ANALYSIS_MAX_EDGE` | `1024` | 发送给视觉 Provider 的内存副本最长边；范围 512–2048 |
| `FRAME_ANALYSIS_MAX_CONCURRENCY` | `2` | 后台分析线程池大小 |
| `FRAME_ANALYSIS_MAX_ATTEMPTS` | `2` | 启动恢复时中断任务的最大尝试次数 |
| `FRAME_ANALYSIS_MAX_INPUT_BYTES` | `8388608` | 内存 JPEG 副本字节上限（8 MiB） |
| `FRAME_ANALYSIS_TIMEOUT_SECONDS` | `600` | 单个分析任务的整体时间预算；超时标记失败为 `analysis_timeout`。默认值按 Provider「超时 ×(1+重试) ×(1+修复) × 2 个 Provider」的最坏合法耗时留出余量 |
| `FRAME_ANALYSIS_QUEUE_MAX` | `16` | `pending` 任务数上限；超限的新分析请求返回 503 `server_busy` + `Retry-After`，而不是无界排队 |
| `FRAME_PHOTOGRAPHER_MAX_CONCURRENCY` | `2` | 同时执行的 Planner 调用（方案与对话）上限（1…8）；满时立即 503 `photographer_busy`，不排队 |

页面内“模型设置”保存的字段写入 `<FRAME_DATA_DIR>/provider-settings.json`（已被 `.gitignore`），优先级高于上表中的同名字段；未保存的字段继续使用环境变量。规划分组中未保存的字段逐项跟随当前生效的决策配置（含已保存的 decision 覆盖），而不是先回退到默认值；旧版覆盖文件没有规划分组时按“未配置”读取。该文件以明文保存 API Key（Unix 上尽力 `chmod 0600`），不是密钥保险箱，本机其他进程/用户仍可能读取。文件损坏或选择了 `openai` 但缺少必需字段时，API 启动失败而不是静默回退。

前端读取（放在 `apps/web/.env.local` 或 shell 环境）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `API_INTERNAL_URL` | `http://127.0.0.1:8000` | Next.js 服务端 rewrite 目标；在 `next build` 时写入产物，变更后需重新构建 |
| `NEXT_PUBLIC_API_BASE_URL` | 空 | 空表示走同源代理；填绝对地址则直接访问 API |
| `NEXT_PUBLIC_MAX_UPLOAD_BYTES` | `20971520` | `/api/v1/config` 不可用时的前端回退上限 |

Playwright（`tests/e2e/README.md` 有完整说明）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `E2E_BASE_URL` | — | 复用已有 Next.js 服务器时指定 |
| `E2E_API_PORT` / `E2E_API_URL` | `8010` / `http://127.0.0.1:8010` | Playwright 启动的 API 端口与地址 |
| `E2E_WEB_PORT` | `3010` | Playwright 启动的 Next.js 端口 |
| `E2E_BROWSER_CHANNEL` | 空（Chromium） | 设为 `msedge` 使用系统 Edge |
| `E2E_PYTHON` | `services/api/.venv` | 指定 Python 解释器 |
| `E2E_MOCK_SCENARIO` | `backlit` | E2E API 使用的 `FRAME_MOCK_SCENARIO` |

## 存储与数据模型（阶段 2）

```text
data/
├── frame.db
├── originals/
│   └── 36973fbf-a830-4415-aee4-1314ccdbf739.png
└── tmp/
    └── previews/
        ├── <sha256>.jpg             内容寻址预览
        └── proxies/<hash>.jpg       方向归一与缩放代理缓存
```

- 原图按服务端生成的 UUID + 实际解码格式扩展名保存；用户文件名不参与路径，原图字节不变。
- `frame.db` 使用标准库 `sqlite3`，启动时按 `app/repositories/migrations/` 执行带 checksum 的版本迁移。
- 表结构：
  - `image_asset`：图片元数据与 `sha256`，`width/height` 为 EXIF 方向归一后的显示尺寸。
  - `edit_session`：`active_revision_id` / `head_revision_id`、状态与时间戳。
  - `edit_revision`：`revision_no`、`parent_id`、配方 JSON 与哈希、`source`、`idempotency_key`；`UNIQUE(session_id, revision_no)` 与 `UNIQUE(session_id, idempotency_key)`。
  - `analysis_task`：图片、选项、`config_key`、唯一 `dedupe_key`、状态/阶段/尝试次数、错误码与时间戳。
  - `analysis_result`：任务 ID、报告 Schema 版本、`is_mock` 与完整报告 JSON；报告内嵌本次分析的图片 ID。
  - `photographer_plan`：会话/图片/分析、`mode`、风格与版本/强度、Provider/模型/提示词版本、`is_mock`/`degraded`、置信度、方案 JSON、配方 JSON 与哈希。
  - `photographer_feedback`：图片、会话、方案、revision、来源（`plan/chat/critique`）、动作（`accepted/rejected/modified/reset`）、参数差异、可选评分 JSON、`is_mock`/`degraded` 与时间；`UNIQUE(plan_id, action)` 保证同一方案同一决策只有一行。
- 阶段 3 迁移 `0002_analysis.sql`、阶段 5 迁移 `0003_photographer_plan.sql` 与 `0004_photographer_feedback.sql`、删除墓碑迁移 `0005_deleted_resource.sql` 可在新库与既有库上应用；已应用的迁移不可修改。
- revision 不复制像素，只保存配方；渲染与导出始终读取不可变原图。分析结果只保存结构化报告，不复制原图；方案只保存方案/配方 JSON，不保存图片或指令原文。
- 预览与 `previews/proxies/` 代理图都是可丢弃的 JPEG 缓存；SQLite 与原图是权威数据。代理图按 64 px 边长分桶复用，缓存写失败不影响渲染。
- 阶段 1 的 `image_registry.json` 在首次启动时导入后备份为 `image_registry.json.imported.bak`（重复导入时带时间戳），之后不再写入。
- **删除能力**：`DELETE /api/v1/images/{id}` 与 `DELETE /api/v1/sessions/{id}` 硬删除并返回 204；重复删除仍是 204（`deleted_resource` 墓碑），未知/非法 id 返回 404，分析或导出进行中返回 409 `resource_busy`。删除图片会级联清除其会话、revision、分析、方案与反馈，并在提交后删除原图、无共享引用的代理与预览缓存；已成功的导出作业与结果文件随删除清除，之后 `GET /exports/{jobId}` 与 `/result` 均返回 404。删除会话保留原图。没有回收站，编辑器提供二次确认。
- **异步导出**：前端通过 `POST /api/v1/exports` 提交作业，轮询 `GET /exports/{jobId}`，成功后下载 `GET /exports/{jobId}/result`；对话框可在导出中取消（`DELETE /exports/{jobId}`）。排队中的作业立即取消，运行中的作业在下一个渲染阶段边界停止并释放并发槽位与内存准入。作业状态保存在进程内，服务重启即丢失；结果文件位于 `data/tmp/exports/`，启动时清空上次进程遗留，访问/提交时惰性清理超过 `FRAME_EXPORT_JOB_TTL_SECONDS` 的文件，删除会话/图片时同步清除。删除与导出并发时，已通过删除前忙碌检查的作业会被取消并从作业表移除，晚到的结果不落盘或立即丢弃。旧同步端点 `POST /sessions/{id}/export` 仍保留但已标记 deprecated。
- 进程崩溃或 Windows 文件占用可能留下孤儿文件或“登记存在、原图缺失”的记录；`services/api/scripts/purge_orphans.py` 默认 dry-run，`--apply` 才删除孤儿原图/代理并清理缺失原图的登记行。删除整个 `data/` 仍会清空全部数据。

## 编辑语义

- **非破坏**：原图只读；revision 只记录配方；导出从原图重渲染。
- **会话**：上传后自动创建会话与 `source=initial` 的默认配方 revision。
- **提交**：`POST /revisions` 的 `parentRevisionId` 必须等于当前 `activeRevisionId`，否则 409 `revision_conflict`。
- **幂等**：同会话内 `Idempotency-Key` 唯一；同 key、同配方哈希与同父 revision 的网络重试返回 200 与原 revision；同 key 但内容或父 revision 不同返回 409 `idempotency_key_reuse`。
- **undo/redo/activate**：undo 沿 `parent_id` 回退；redo 沿通往 `head` 的路径前进；activate 可切到任意历史 revision 且不改 `head`；在历史中间提交会形成分支并移动 `head`。
- **reset**：生成 `source=reset` 的默认配方 revision；若活动配方已是默认值则不新增历史。
- **两位小数**：前端 `roundTo2` 并归一 `-0`；服务端拒绝超过两位小数，不四舍五入（D-11）。
- **旋转**：取最大同比例内接矩形，无填充；crop 坐标定义在旋转内接后的画布（D-04）。

## 支持的图片与限制

| 项目 | 阶段 2 约定 |
| --- | --- |
| 允许格式 | JPEG、PNG、WebP、TIFF |
| 单次上传 | 仅一个 `file` 字段；多个文件返回 `400 invalid_upload` |
| 单文件上限 | 20 MiB（可配置；大 TIFF 需先用 Deflate 压缩） |
| 像素上限 | 40,000,000（可配置） |
| 声明 MIME | 必须是上述四种之一（`image/jpg` 归一为 JPEG） |
| 内容核验 | Pillow 解码格式必须与声明 MIME 一致 |
| 损坏/伪造 | 无效内容返回 `415 invalid_image`；类型不符返回 `415 mime_mismatch` |
| 动画 | 动画 WebP/APNG 与多页 TIFF 返回 415（前者 `animated_not_supported`，后者 `tiff_multipage_not_supported`） |
| TIFF 压缩 | 仅未压缩与 Deflate；LZW/JPEG 等返回 `415 unsupported_tiff_compression` |
| 超限 | 文件过大/像素超限返回 `413`，不会静默夹紧 |
| Alpha | 导出路径保留 8/16-bit alpha：PNG/TIFF 输出 RGBA，JPEG 在白底合成；预览、代理与 AI 分析仍按白底合成且为 8-bit |
| 色彩 | 8-bit 输入（L/P/PA/1/RGBA/CMYK 等）转 8-bit sRGB；16-bit PNG/TIFF 保持 16-bit，用 NumPy 矩阵/TRC 转到 sRGB；非 RGB 设备空间或损坏配置按 sRGB 解释；16-bit 的 LUT/非 RGB/XYZ 配置返回 422 `unsupported_icc_profile`；导出不保留原 ICC 配置，恒嵌入 sRGB ICC。详见 `docs/color-management.md` |
| 色彩管理边界 | 不做 RAW 显影、32-bit/HDR 管线、16-bit JPEG、CMYK 正确显影、非 RGB 配置转换、广色域输出与软打样；TIFF 不支持 LZW/JPEG 压缩与多页。依赖为 Pillow/OpenCV/NumPy 与新增的 `tifffile==2026.3.3`（BSD-3-Clause），未引入 imagecodecs/rawpy/pillow-heif/colorio（`docs/decisions/ADR-0004-color-management.md`） |
| 方向 | 读取 EXIF 方向并在渲染前烘焙进像素；原图字节保留原始 EXIF |

服务端使用随机文件名与路径隔离；同时限制上传字节数和像素数。前端限制只用于即时提示，不能替代服务端校验。

## API（阶段 3–5）

统一前缀 `/api/v1`，JSON 字段使用 camelCase（D-12）。错误统一为：

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "The edit state has changed; reload the session before committing.",
    "details": {}
  }
}
```

完整契约（状态码、会话语义、配方范围、render/preview/compare/export 细节、409 扩展、错误码表、OpenAPI 同步流程与 curl 示例）见 **[docs/api-contract.md](docs/api-contract.md)**。

| 方法与路径 | 作用 |
| --- | --- |
| `GET /health`, `GET /config` | 健康检查与运行时上传限制 |
| `POST /images`, `GET /images/{id}/original` | 上传与原始字节下载 |
| `POST /sessions`, `GET /sessions/{id}` | 创建/读取会话 |
| `POST /sessions/{id}/revisions` | 提交 revision（幂等、409 冲突） |
| `GET /sessions/{id}/revisions` | 分页读取历史 |
| `POST /sessions/{id}/render` | 渲染预览，支持 `X-Render-Seq`，返回 `previewUrl/width/height/quality/cacheHit` |
| `POST /sessions/{id}/undo|redo|activate|reset` | 历史操作 |
| `GET /sessions/{id}/compare` | 原图侧仅应用旋转/裁切，与当前 revision 同尺寸对比 |
| `POST /sessions/{id}/export` | 全分辨率导出 JPEG/PNG/TIFF（可选 8/16-bit），带内存预算与降噪提示 |
| `POST /exports`、`GET/DELETE /exports/{id}`、`GET /exports/{id}/result` | 异步导出作业：202 + 轮询、协作式取消、结果 TTL |
| `DELETE /images/{id}`, `DELETE /sessions/{id}` | 硬删除图片/会话（204）；重复删除幂等，忙碌 409 |
| `GET /previews/{previewId}` | 内容寻址预览缓存 |
| `POST /analysis` | 创建异步分析任务；`force=true` 强制重新分析，去重命中返回 200 |
| `GET /analysis/{id}` | 查询状态/阶段/mock 标记；完成时内嵌报告 |
| `GET /analysis/{id}/result` | 获取完整分析报告（仅 completed） |
| `DELETE /analysis/{id}` | 删除分析任务与结果（204） |
| `GET /settings/providers` | 读取脱敏的 Provider 配置（不含 API Key） |
| `POST /settings/providers` | 保存并热替换 Provider；字段缺省表示保持当前值 |
| `POST /settings/providers/test` | 用表单临时值测试连接（纯文本，不持久化） |
| `POST /settings/providers/reset` | 删除本机覆盖文件，恢复环境变量配置 |
| `GET /ai/photographer/styles`, `GET /ai/photographer/styles/{id}` | 风格目录与单个风格定义（版本、场景、包络、约束） |
| `POST /ai/photographer/plan` | 基于已完成分析生成方案提案；`mode=auto/style/chat`，`previewOnly` 语义 |
| `POST /ai/photographer/chat` | 自然语言修改当前提案，只改允许路径，返回 `changes` 与补丁 |
| `POST /ai/photographer/critique` | 基于分析证据的确定性点评（优点/问题/创作方向/建议） |
| `POST /ai/photographer/critique/apply` | 把单条点评建议转成配方补丁并校验 |
| `POST /ai/photographer/feedback`, `GET /ai/photographer/feedback`, `DELETE /ai/photographer/feedback/{id}` | 记录/查询/删除用户决策与可选评分；汇总含固定 disclaimer |

所有响应包含 `X-Request-ID`。除任务书状态码外，还使用 `400 invalid_host`/`400 invalid_analysis_options`（本机 Host 防护、分析选项全关）、`403 origin_not_allowed`/`cors_origin_denied`（本机来源防护）、`405 cors_method_denied`（CORS 预检请求了未允许的方法）、`409`（revision/幂等冲突、无可撤销/重做步骤、过期渲染、分析未完成或分析仍在运行、删除目标正在分析/导出 `resource_busy`、导出作业未就绪/已取消/已失败）、`413 export_too_large`/`analysis_input_too_large`（内存预算）/`payload_too_large`（请求体分档上限）、`500 storage_error`（任务写入失败）、`503 server_busy`（导出/渲染槽位耗尽、异步导出队列已满，或待分析队列达到 `FRAME_ANALYSIS_QUEUE_MAX`）。导出作业另有 `404 export_not_found`/`export_result_missing`、`409 export_not_ready`/`export_cancelled`/`export_failed`、`500 export_storage_error`。请求体中的未知字段一律返回 422 `validation_error`（不做静默忽略）。分析任务不存在返回 `404 analysis_not_found`；任务执行失败时 HTTP 查询仍为 200，`status=failed`，`error.code` 为 `analysis_failed`、`analysis_timeout`、`analysis_invalid_output` 或 `provider_*`（如 `provider_timeout`、`provider_unavailable`）。阶段 5 另用 `style_not_found`/`plan_not_found`/`feedback_not_found`（404）、`style_required`/`photographer_recipe_invalid`（422）、`analysis_required`/`image_analysis_mismatch`/`plan_session_mismatch`（409）、`photographer_busy`/`photographer_unavailable`（503）、`photographer_timeout`（504）、`photographer_invalid_output`/`photographer_provider_error`（502）与 `critique_invalid`（500）；完整清单见 [docs/api-contract.md](docs/api-contract.md)。

## 隐私与安全边界

- **仅本机**：API 无鉴权、无限流，必须绑定 `127.0.0.1`（D-13）；不得暴露公网或反向代理到公网。
- **Host/Origin 防护**：校验 `FRAME_ALLOWED_HOSTS`，并拒绝不在 `FRAME_ALLOWED_ORIGINS` 的写入 Origin 与 `Sec-Fetch-Site: cross-site`，降低 DNS 重绑定和浏览器跨站写入风险；这不是鉴权。
- 原图、SQLite 与预览只保存在本机数据目录，不上传第三方存储。
- 默认 Mock Provider 完全离线，不调用任何外部服务；仅当显式选择 `openai` Provider 时，才会把最长边 1024 px 的 JPEG 副本发送到配置的服务端，并把结构化测量/语义/候选问题发送给决策 Provider（**不发送图片**）。
- **阶段 5 的 Planner 不接收图片**：方案、对话与点评只读取已完成的分析报告、图片尺寸、当前配方与用户偏好；Planner 默认逐字段跟随决策 Provider 配置（也可在“模型设置”中独立配置），收到的是结构化摘要，因此不会产生第二次图片外传。点评完全由本地确定性规则生成，不调用模型。
- **对话指令不落库**：`POST /chat` 的指令原文只在请求内使用，日志只记录 `instruction_chars` 长度；方案表保存方案/配方 JSON 与元数据，不保存指令、提示词或模型原始响应。
- **反馈不含自由文本或图片**：反馈表只有动作、来源、参数差异、可选 1–5 评分与时间；不保存原图、指令或点评正文。单条可删除，图片/会话删除时级联清除。
- **第三方数据留存**：发送到外部 Provider 的图片副本与结构化数据受该 Provider 自身的留存、日志与训练政策约束，本项目无法控制；接入前应确认服务条款与所在地区的合规要求。本项目不替用户开启训练授权，也不会把 Provider 返回的原始响应持久化。
- 密钥只存在于服务器进程内存、`.env` 或本机覆盖文件 `<FRAME_DATA_DIR>/provider-settings.json` 中，不会出现在 API 响应、日志或前端构建产物中；`.env`、`data/` 与测试产物已被忽略。覆盖文件以明文保存密钥并尽力限制权限，能读取数据目录的本机进程仍可读取它。
- 日志包含请求 ID、方法、路径、状态码、耗时、分析任务 ID 与阶段；不记录图片字节、Base64、原始文件名、配方内容、分析报告正文或密钥。
- 导出与预览剥离全部 EXIF/XMP/IPTC/GPS 并嵌入 sRGB ICC；PNG 不写 `eXIf`/`tEXt`/`iTXt`（D-09）。输出目标色彩空间恒为 sRGB，位深为 8 或 16（JPEG 固定 8）；PNG/TIFF 可带一条同深度的 alpha（RGBA），其余输出为 RGB 三通道。
- 原图下载仍返回上传时的原始字节，包含可能存在的 EXIF/GPS 与原嵌入 ICC 配置；界面会提示这一点。契约是"原图不动、输出重编码"。
- 当前没有登录、权限或限流；本机以外的访问不属于支持范围。

## 测试与检查

一条命令跑完全部门槛（后端格式/类型/lint/单测、OpenAPI 契约、前端 lint/类型/测试/契约/生产构建），并打印退出码表：

```bash
# 在仓库根目录
services/api/.venv/Scripts/python.exe scripts/verify.py
```

单独运行：

```powershell
cd services/api
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe scripts/export_openapi.py --check
```

```bash
cd apps/web
npm run lint
npm run typecheck
npm test
npm run check:api
npm run build
```

清理删除/崩溃遗留的孤儿文件（默认只报告，不删除）：

```bash
cd services/api
.\.venv\Scripts\python.exe scripts/purge_orphans.py            # dry-run，打印计数
.\.venv\Scripts\python.exe scripts/purge_orphans.py --apply    # 实际删除
```

端到端（根目录；默认自启隔离 API 与 Next，桌面 + 窄屏各一遍）：

```bash
npm ci
npx playwright install chromium          # 或使用 E2E_BROWSER_CHANNEL=msedge
npm run test:e2e
```

复用已有 frontend/API 时：

```bash
E2E_BASE_URL=http://127.0.0.1:3000 E2E_API_PORT=8001 E2E_API_URL=http://127.0.0.1:8001 \
E2E_BROWSER_CHANNEL=msedge npx playwright test
```

若现有 Next.js 开发服务器因单实例锁不能同时启动第二个实例，可把 `apps/web` 复制到临时子目录（不复制 `node_modules`/`.next`，子目录会向上复用 `apps/web/node_modules`），用独立端口启动后把 `E2E_BASE_URL` 指向它；Playwright 仍会自启隔离 API。本轮回归采用该方式，未终止用户正在运行的 `:3000`/`:8000`。命令与结果见 [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md)。

分析评估与真实 Provider 冒烟（需要人工标注集/密钥时手动运行，默认不参与门禁）：

```bash
# 人工标注集评估；缺少 manifest/图片/API 时非零退出，不输出指标
services/api/.venv/Scripts/python.exe scripts/eval_analysis.py \
  --manifest eval-data/manifest.json

# 真实 Provider 连通性冒烟；未配置时输出 SKIPPED（--require-live 则退出 2）
services/api/.venv/Scripts/python.exe scripts/smoke_live_provider.py
```

阶段 5 的 14 类场景回归集（不依赖真实照片，使用合成夹具）：

```bash
cd services/api
.venv/Scripts/python.exe -m pytest tests/test_photographer_regression.py -q
```

规范与指标口径见 [docs/evaluation.md](docs/evaluation.md)；阶段 5 的 14 类测试图、1–5 分评分表、A/B/C/D 对照与失败分类见 [docs/evaluation/stage-5-evaluation.md](docs/evaluation/stage-5-evaluation.md)。

性能基准（自启隔离 uvicorn，输出 p50/p95 与 40 MP 峰值 RSS）：

```bash
services/api/.venv/Scripts/python.exe scripts/bench_render.py
```

缓存基准（不走 HTTP，直接测量代理解码与蒙版权重的冷/命中耗时与峰值 RSS）：

```bash
services/api/.venv/Scripts/python.exe scripts/bench_cache.py --iterations 5 \
  --output C:/Temp/frame-bench-cache.md
```

分析性能基准（1/12/40 MP 预处理与 CV 特征、Mock 任务端到端）：

```bash
services/api/.venv/Scripts/python.exe scripts/bench_analysis.py --iterations 5 \
  --json C:/Temp/frame-bench-analysis.json
```

阶段 3 最终真实运行结果（2026-11-03）：`scripts/verify.py` **12/12 gates 退出码 0**；后端 **657 passed, 1 skipped**（跳过项为 Windows 符号链接权限测试），`mypy app` 检查 **78 个源文件**无错误，`ruff` **130 个文件**格式通过，OpenAPI 与前端类型同步；前端 **22 个测试文件 / 212 tests passed**，lint/typecheck/契约/生产构建通过；Playwright **11 passed / 5 skipped（35.2 s）**（跳过项是视口不匹配的既有用例），包含新增分析 E2E 与上传/编辑/导出回归。明细与性能数字见 [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md)。

阶段 4 最终真实运行结果（2026-11-04，Task 0–8 完成；后随 commit `1f8909b` 一并提交）：`scripts/verify.py` **12/12 gates 退出码 0**；`ruff format --check` **144 个文件**已格式化，`mypy app`（strict）**84 个源文件**无错误，后端 **899 passed, 1 skipped**（跳过项同上），OpenAPI 与前端类型同步，两条阶段 2.1 复审复现仍通过（旋转越界 0.000%、ICC 最大通道差 0）；前端 **29 个测试文件 / 317 tests passed**，lint/typecheck/契约/生产构建全部退出码 0；Playwright 当时 **11 passed / 5 skipped（21.8 s）**；黄金图 **27 张**（3 张合成源图 × 9 个配方，容差 1 灰阶；`test_golden.py` 收集 28 条含 manifest 元测试）逐例通过，当时编码 `frame-engine/8` / 代理 `loader/3`。阶段四全程**未新增任何第三方依赖**。已知未达标项：24 MP 满配方全尺寸导出 p50 29.6 s / p95 32.2 s 超过 20 s 目标（保留 FAIL），以及任务书 §八 的真实照片测试集与人工评估记录尚未建立。逐条数字与验收对照见 [STAGE_4_COMPLETION_REPORT.md](STAGE_4_COMPLETION_REPORT.md)。

阶段 3/4 复审整改（2026-11-05，commit `1f8909b`）：当前引擎 `frame-engine/10`；`scripts/verify.py` **12/12 gates passed**——后端 `mypy app`（strict）83 个源文件无错误、**1020 passed / 1 skipped**，前端 Vitest **29 文件 / 328 tests passed**，lint/typecheck/契约/生产构建全部退出码 0，两条复审复现仍为旋转越界 0.000% / ICC 最大通道差 0。新增 4 个阶段四面板的 Playwright 用例后 E2E 为 **13 passed / 7 skipped（33.3 s，隔离栈 :3010/:8012）**，无障碍 axe 覆盖“编辑器打开且四面板展开”状态且未放宽规则。逐条 finding 结论见 [复审整改计划](docs/plans/stage-3-4-review-remediation.md) §12。

历史记录：阶段 2（2026-11-02，commit `a7e8fca`）验证脚本 **10/10**、后端 **298 passed, 1 skipped**、前端 **113 tests passed**、Playwright **2 passed**；阶段 2.1（2026-11-03，commit `22ed468`）验证脚本 **12/12**、后端 **385 passed, 1 skipped**、Playwright **9 passed / 5 skipped**。逐条命令与退出码见对应交接文档。

历史：2026-11-03 的预览可见性修复、上传错误诊断与滑杆预览闪烁修复在未提交工作区复跑：`scripts/verify.py` **10/10 gates**；前端 **17 个测试文件 / 132 tests passed**；后端 **298 passed, 1 skipped**。Playwright 最近一次完整运行 **7 passed / 5 skipped**（桌面 1280×800、1280×640，手机 390×844、320×568）；错误诊断改动后因 3000 端口开发服务器占用未重跑，已用浏览器实际上传正常图片与无效图片验证。滑杆闪烁修复另用 Playwright（Edge）对运行中的应用做真实鼠标拖拽：桌面 1280×900 与手机 390×844 分别连续采样 750 / 740 帧，均无空白帧与加载占位帧；约 1.8 s 的持续拖动触发 3 次 draft，松手后只发送 1 次 final。

2026-11-03 阶段 2.1 最终回归（`22ed468`，仅文档随后提交）：`scripts/verify.py` **12/12 gates 退出码 0**，后端 **385 passed, 1 skipped**；两条审查复现脚本作为独立 gate 通过；Playwright 复用现有 3000 服务运行 **9 passed / 5 skipped（17.5 s）**；完整基准退出码 0、总耗时 517.7 s，§7.8 可测项目全部 PASS，40 MP 满配方按默认预算返回预期 `413 export_too_large`。明细见 [docs/handoff/phase-2.1.md](docs/handoff/phase-2.1.md)。

## 性能

完整数据与测量方法见 [docs/performance.md](docs/performance.md)。最新的阶段 4 Task 8 结果在下方“阶段 4 Task 8”小节；阶段 2 摘要保留为历史记录，其中的内存估算系数已在 Task 8 重标定。阶段 2 本机结果摘要：

| 项目 | p50 | p95 | 目标 |
| --- | --- | --- | --- |
| final 预览 1600 px（12 MP） | 290 ms | 295 ms | ≤ 500 ms |
| draft 预览 960 px 含降噪（6 MP） | 171 ms | 212 ms | ≤ 400 ms |
| final 预览 1600 px 含降噪（12 MP） | 780 ms | 849 ms | ≤ 2500 ms |
| 24 MP 导出（中性配方） | 1651 ms | 1764 ms | ≤ 20 s |
| 24 MP 导出（满配方） | 11353 ms | 11638 ms | ≤ 20 s |
| 19.2 MiB 上传解码 | 236 ms | 250 ms | ≤ 3000 ms |
| 40 MP 导出峰值 RSS（中性 / 满配方） | — | 1590 / 4700 MB | ≤ 3072 MB |

峰值 RSS 统计 API 进程树，包含进程基线；40 MP 内存结果是单配方单次采样、单机数据。满配方 40 MP 实测超过默认预算，运行期会在解码前按估算返回 413，而不是继续渲染；该预算是保守估算，不是实时 RSS 硬限制。

阶段 3 分析性能（2026-11-03，`scripts/bench_analysis.py --iterations 5`，先热身 1 次；分析副本最长边 1024）：

| 项目 | 源图 | 预处理 p50 / p95 | CV 特征 p50 / p95 | 合计 p50 / p95 |
| --- | --- | --- | --- | --- |
| 预处理 + 特征 | 1 MP（1000×1000） | 32.0 / 32.1 ms | 664.5 / 687.0 ms | 696.6 / 719.1 ms |
| 预处理 + 特征 | 12 MP（4000×3000） | 178.2 / 179.2 ms | 512.3 / 514.3 ms | 688.5 / 692.5 ms |
| 预处理 + 特征 | 40 MP（7296×5472） | 566.5 / 614.1 ms | 524.1 / 544.1 ms | 1095.8 / 1145.1 ms |
| Mock 任务端到端（backlit） | 1 MP | — | — | 1701.5 / 1762.4 ms |

1 MP 的 CV 特征比 12 MP 慢，是因为分析副本小于 `FRAME_ANALYSIS_MAX_EDGE=1024`、不会被缩小；12/40 MP 都会缩到约 0.79 MP 再测量。此为补全 R2 扩充特征集后的重测结果，数字为本机单次采样、单 Pillow/NumPy/OpenCV 版本结果。真实 Provider 调用的耗时与 token/费用**未测量**（本机未配置真实密钥）。

阶段 4 Task 6 局部蒙版（2026-11-04，`scripts/bench_render.py --iterations 20 --memory-runs 1`，6 MP 预览、20 个唯一缓存键）：

| 场景 | p50 | p95 | 峰值 RSS |
| --- | --- | --- | --- |
| 6 MP 预览，无局部 | 247 ms | 269 ms | 204 MB |
| 6 MP 预览，1 个椭圆蒙版 | 590 ms | 652 ms | 246 MB |
| 6 MP 预览，3 个蒙版（含反选/羽化） | 1495 ms | 1526 ms | 301 MB |
| 24 MP 满配方 + 3 个蒙版导出（单次采样） | — | — | 5081 MB |

局部调整会按启用蒙版数量增加渲染与内存开销；24 MP 满配方 + 3 个蒙版实测约 5081 MB，超过默认 3072 MB 预算，默认配置会在导出前返回 413。扩展后的阶段四满配方（含曲线/HSL/调色）24 MP 导出 p95 26.2 s，超过阶段 2 定下的 20 s 目标，已如实记录为 FAIL；40 MP 满配方那轮实测峰值 8258 MB。该轮的 120 B/px 满配方系数已在下面的 Task 8 一节重标定（同一档 Task 8 实测 7366 MB，两轮相差 11%，说明单次采样本身有漂移）。

阶段 4 Task 8 预览 / 导出 / 缓存（2026-11-04，`scripts/bench_render.py --iterations 20 --memory-runs 1`，全表 2763.3 s；为完成内存采样把导出预算临时设为 `FRAME_EXPORT_MAX_RSS_MB=16384`，产品默认仍是 3072）：

| 项目 | p50 | p95 | 峰值 RSS | 目标 | 结果 |
| --- | --- | --- | --- | --- | --- |
| final 预览 1600 px（12 MP，不含降噪） | 315 ms | 333 ms | — | ≤ 500 ms | PASS |
| draft 预览 960 px 含降噪（6 MP） | 205 ms | 222 ms | — | ≤ 400 ms | PASS |
| final 预览 1600 px 含降噪（12 MP） | 856 ms | 937 ms | — | ≤ 2500 ms | PASS |
| 19.2 MiB 上传解码 | 2242 ms | 2615 ms | — | ≤ 3000 ms | PASS |
| 24 MP 中性导出 | 2211 ms | 2289 ms | 994 MB | ≤ 20 s | PASS |
| 24 MP 满配方导出 | 29626 ms | 32213 ms | 5094 MB | ≤ 20 s | **FAIL** |
| 24 MP 满配方 + 长边 2400（本轮新增能力） | 4608 ms | 4640 ms | 959 MB | 参考 | — |
| 40 MP 满配方 + 长边 2400（本轮新增能力） | 5343 ms | 5408 ms | 1117 MB | 参考 | — |
| 40 MP 满配方（原图尺寸） | 49801 ms | 52174 ms | 7366 MB | 参考 | — |

24 MP 满配方的超标来自阶段四新增的曲线／HSL／颜色分级三个全图阶段（12 MP 也要 14.8 s），与局部蒙版无关；`maxEdge` 是本轮新增的导出尺寸能力，同配方下 24 MP 从 29.6 s 降到 4.6 s、40 MP 从 49.8 s 降到 5.3 s。§7.8 口径的预览与上传项目全部 PASS，局部场景峰值 RSS 为 220／265／320 MB（无局部／1 蒙版／3 蒙版）。

上表“19.2 MiB 上传解码 2242／2615 ms”一行已被复审整改 G1 的复测否证：同一脚本同一项为 248／259 ms，且 `upload_scenario` 在两轮之间未改动。原表保留为该轮的直接输出，但这一行不应作为可复现结论引用；详见 [docs/performance.md](docs/performance.md) 的 Task 8 批注与 G1 小节。

缓存（`scripts/bench_cache.py --iterations 5`，直接调用函数本体、不经 HTTP）：代理内存命中把 6 MP 冷解码 200.79 ms 降到 13.42 ms、24 MP 471.12 ms 降到 12.16 ms（磁盘命中 34–40 ms），冷解码／磁盘命中／内存命中三条路径逐像素一致；蒙版权重缓存在 1600 px 预览画布把 57–67 ms 降到 0.02 ms，但 24 MP 画布的权重单条 91.55 MB 超过 24 MB 上限，因此不入库、按未缓存速度执行。

估算系数重标定：Task 8 把满配方 120 → 240 B/px、每个启用局部调整 40 → 8 B/px，中性 45 B/px 与基线 150 MB 不变，并新增“解码地板”（原图整张解码，估算是原图像素 × 45 B/px + 150 MB）。用 11 个实测行校准后每一行估算都不低于实测（最紧 +3.1%，其余 +10.8%…+71%）。副作用是默认 3072 MB 预算拒绝 24 MP 满配方的全尺寸导出（当时估算 5643 MB，实测 5094 MB）；导出时选择长边 2400（估算 1180 MB，实测 959 MB）或调高 `FRAME_EXPORT_MAX_RSS_MB` 仍可导出。复审整改 G4 又按 8 个新峰值把满配方降到 160 B/px（本轮最高 131 B/px），并增加 psutil 实时可用内存门；24 MP 满配方仍被拒绝（估算 3812 MB、实测 2907 MB）。

## 常见故障

**`python`/`py` 不在 PATH（本机常见）**

使用完整解释器路径创建虚拟环境，例如：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m venv .venv
```

或安装 Python 时勾选 “Add python.exe to PATH”。

**端口被占用**

```powershell
netstat -ano | findstr :8000
netstat -ano | findstr :3000
```

结束旧的 uvicorn/Next 进程后再启动。若 Next.js 开发服务器残留，清理 `.next` 后重启。

**界面显示 “API 未连接”**

确认 FastAPI 已在 8000 端口启动，且 `API_INTERNAL_URL` 指向正确地址。健康检查请求为 `GET /api/v1/health`。

**上传后立即 413**

检查后端 `FRAME_MAX_UPLOAD_BYTES` / `FRAME_MAX_IMAGE_PIXELS` 与前端 `NEXT_PUBLIC_MAX_UPLOAD_BYTES` 是否同步。像素超限与字节超限都会返回 413，错误 `details` 中会给出上限。

**保存设置、创建会话或渲染返回 413 `payload_too_large`**

上传前缀 `/api/v1/images` 使用 `FRAME_MAX_UPLOAD_BYTES`，其余 `POST/PUT/PATCH` 使用另一档 `FRAME_MAX_JSON_BODY_BYTES`（默认 2 MiB）。`details` 里 `maxBytes` 是对用户声明的上限、`maxBodyBytes` 是实际执行的上限（上传档还要加上 multipart 余量，两者才不同）。正常配方/蒙版请求远小于该值；命中说明请求体里混入了图片字节或非法的大数组，提高上限不是解决办法。

**编辑时提示“编辑状态已更新”**

通常是另一个标签页/窗口或网络重试改变了活动 revision。前端会重新加载会话；重试提交时必须使用新的 `parentRevisionId` 与新的 `Idempotency-Key`。

**导出或渲染返回 503 `server_busy`**

导出并发槽位默认 1 个（`FRAME_EXPORT_MAX_CONCURRENCY`，可设 1–4），渲染最多并发 2 个且槽位最多等待 10 秒。即使还有空闲槽位，若正在运行的导出估算总和会超过 `FRAME_EXPORT_MAX_RSS_MB`，新导出同样返回 503；等待 `Retry-After` 后重试，不要并发触发多个大图导出。

`POST /analysis` 的 503 是另一种情况：待分析（`pending`）任务数已达 `FRAME_ANALYSIS_QUEUE_MAX`（默认 16）。分析用有界线程池，请求会先排队而不是无界占用内存；同样等 `Retry-After` 后重试。已完成或失败的任务重新分析（`force=true`）走原子抢占，重复点击不会重复入队。

**分析任务以 `analysis_timeout` 失败**

单个任务从进入执行起的时间预算是 `FRAME_ANALYSIS_TIMEOUT_SECONDS`（默认 600 秒），在每个阶段切换点检查。真实 Provider 下这个值和 Provider 超时/重试是耦合的：最坏合法耗时约为 `超时 ×(1+重试次数) ×(1+修复次数)` 再叠加两个 Provider，默认值据此留出余量。把它调小会在网络慢的时候砍掉本来会成功的分析；想更快放弃请同时调低 `FRAME_VISION_TIMEOUT` / `FRAME_*_MAX_RETRIES`。

**导出返回 413 `export_too_large`**

按导出计划像素与配方估算的峰值内存超过 `FRAME_EXPORT_MAX_RSS_MB`（系数与解码地板见 [docs/api-contract.md](docs/api-contract.md)）。可导出长边更小的尺寸、减少调整项，或在了解本机内存余量后调高上限；重标定后默认 3072 MB 会拒绝 24 MP 满配方的全尺寸导出，选长边 2400 或把上限调到 6144 是两条已实测的路径。错误详情包含估算值与限制，前端文案会给出这两个办法。

**预览返回 404 `preview_expired`**

预览缓存已按 TTL 清理。前端会自动重新 render；手动调用时重新请求 `POST /sessions/{id}/render` 即可。

**Playwright 提示缺少浏览器**

运行 `npx playwright install chromium`，或设置 `E2E_BROWSER_CHANNEL=msedge` 使用系统 Edge。若本机已有 Next 开发服务器，使用 `E2E_BASE_URL`/`E2E_API_PORT` 复用其 API 端口。

**原图文件丢失**

SQLite 记录仍存在但文件被移动/删除时，预览接口返回 `404 image_file_missing`。删除整个 `data/` 后旧 imageId 也会失效。

## 已知限制与风险

完整清单见 [docs/known-issues.md](docs/known-issues.md)。阶段 2/3/5 重点：

1. **alpha 只在导出 PNG/TIFF 中保留（8/16-bit）**：导出的 PNG/TIFF 带 alpha、JPEG 白底合成；预览、代理与 AI 分析仍为 8-bit 白底合成，预览没有透明棋盘格。16-bit 只覆盖上传解码与导出，16-bit JPEG 不支持；16-bit + 降噪会跳过降噪并给出 `denoise_skipped_for_16bit`。
2. **无真机回归**：只做了桌面 Chromium/Edge 与窄视口；未在真实 iOS Safari / Android Chrome 上验证触控与性能。
3. **API 无鉴权**：仅支持本机单进程；多 worker 与跨进程并发未验证，`--host` 必须为 `127.0.0.1`。
4. **大图导出内存是估算与单机采样**：Task 8 按 11 个实测行标定、G4 又按 8 个实测行重标定估算系数（中性 45／满配方 **160**／每个启用局部 8 B/px + 150 MB 基线 + 原图解码地板）；B5b 为 16-bit 源与输出各加 18 B/px。满配方 8-bit 本轮最高为 131 B/px，160 仍保留约 22% 余量；同档单次采样在不同轮次仍可能漂移约 11%。16-bit 实测峰值 24/40 MP 中性 1026/1671 MB、满配方 2801/4616 MB，同尺寸 8-bit 中性 966/1562 MB，说明 36 B/px 附加项保守；默认 3072 MB 预算仍会拒绝 24 MP 满配方、40 MP 满配方与 40 MP 中性 16-bit（后者实测 1671 MB）。改选导出长边 2400 或调高 `FRAME_EXPORT_MAX_RSS_MB` 可导出。静态估算之外还有 psutil 实时可用内存门（`FRAME_EXPORT_RESERVE_MB`），但它只是采样快照，不是实时 RSS 硬限制；结果依赖 Pillow/NumPy/OpenCV/tifffile 版本与机器。
5. **缓存写入的 Windows 兼容处理**：预览 `os.replace` 遇到目标文件被占用时使用锁/重试与回退，代理缓存写失败则继续使用内存结果；都不是跨进程缓存一致性方案。蒙版权重缓存有 24 MB 单条上限，24 MP 画布的权重（约 91.55 MB）因此不入库、每次导出都重算。
6. **EXIF 原图下载**：原图字节保留原始 EXIF（含 GPS）；只有导出会剥离元数据。
7. **AI 默认是 Mock**：默认模型结果用于开发与流程验证，不代表真实模型能力；没有真实 Provider 的准确率/成本评估，也没有像素级主体蒙版。
8. **分析任务按单进程设计**：线程池、启动恢复与任务状态都在进程内协调；多 uvicorn worker 不在当前范围。
9. **AI 摄影师只提案，不自动应用**：方案在预览中展示，必须由用户接受才写入 revision；没有批处理、后台自动调色或跳过确认的路径。
10. **没有像素级语义蒙版**：方案只能引用用户已创建的矩形/椭圆蒙版；无蒙版时局部提亮会降级为全局并给出提示，不会伪造人物/天空蒙版。
11. **风格是参数化配方，不是滤镜引擎**：12 个风格由参数包络与约束实现，`styleId/styleStrength` 只是元数据，渲染引擎不读取风格字段；风格跨版本时记录的 `styleVersion` 仅用于追溯。
12. **点评是确定性证据驱动**：v1 不调用自由文本模型，避免编造；优点是稳定可复现，局限是表达模板化、无法评价证据之外的美学细节。
13. **AI 不做几何编辑**：不支持裁剪、旋转、扩图、删除物体或换背景；构图问题只作为诊断与建议呈现。
14. **阶段 5 的质量评估未完成**：14 类真实照片 × 10 维评分、A/B/C/D 对照、真实 Provider 稳定性与失败案例计数均**未评估（待用户照片与授权）**；自动化回归只证明流程、结构与边界，不证明摄影质量提升。
15. **Planner 独立配置没有专用清除入口**：Planner 已支持在“模型设置”中独立配置，未填写的字段逐项回退决策 Provider；但清除 planner 覆盖只能清空对应字段，或使用“恢复环境变量配置”（会同时删除 vision/decision 覆盖），没有“只清除 planner”的按钮。并发槽位是进程内机制，多 worker 不在当前范围。

## 阶段 4 交接

**阶段：** 开发阶段 4 — 专业摄影调色引擎（Task 0–8 已完成；全部改动见 commit `1f8909b`）。

完整交接（逐 Task 交付、修改与新增清单、依赖结论、12 道门禁与测试计数、性能与内存实测、任务书 §十/§十一 与操作建议 §十七 的逐条验收对照、未完成项、启动/验证/回滚、下一阶段建议）见 [STAGE_4_COMPLETION_REPORT.md](STAGE_4_COMPLETION_REPORT.md)。逐 Task 的计划与实施结果见 [docs/plans/](docs/plans/) 下的 `phase-4-task-3…8`。阶段 3 交接见 [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md)，阶段 2 与 2.1 见 [docs/handoff/phase-2.md](docs/handoff/phase-2.md) 与 [docs/handoff/phase-2.1.md](docs/handoff/phase-2.1.md)。API 契约见 [docs/api-contract.md](docs/api-contract.md)，色彩管理策略与实测见 [docs/color-management.md](docs/color-management.md)，性能数据见 [docs/performance.md](docs/performance.md)，决策记录见 [ADR-0002](docs/decisions/ADR-0002-phase-2-decisions.md)、[ADR-0003](docs/decisions/ADR-0003-compare-geometry-alignment.md) 与 [ADR-0004](docs/decisions/ADR-0004-color-management.md)。

**本地启动方式：**

```powershell
cd services/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd apps/web
npm run dev
```

打开 <http://127.0.0.1:3000>。

**下一阶段建议：** 先处理阶段四唯一未达成的验收项——任务书 §八 的 14 类真实照片测试集与 §8.5 的人工评估记录（需要用户授权素材，`eval-data/` 目前不存在），并按 Task 拆分提交本阶段改动。性能主线应是管线级优化（减少全图 float32 中间量、分块渲染），内存估算系数已按实测峰值标定，不建议再调。语义蒙版、可中断导出、跨进程缓存与 32-bit/HDR 管线仍需要独立决策与 ADR，且必须保持"AI 不直接覆盖原图、原图字节不可变"的既有约束。**阶段 4 到此停止，未获确认不进入下一阶段。**

## 阶段 5 交接

**阶段：** 开发阶段 5 — AI 摄影师与智能后期决策（Task 0–9 已完成；改动尚未提交）。

完整交接（逐 Task 交付、测试计数、mock/真实 Provider 与真实照片状态、已知问题、验收对照与回滚）见 [STAGE_5_COMPLETION_REPORT.md](STAGE_5_COMPLETION_REPORT.md)。开工审计见 [STAGE_5_AUDIT_REPORT.md](STAGE_5_AUDIT_REPORT.md)，逐 Task 计划与交付记录见 [docs/plans/phase-5-execution-plan.md](docs/plans/phase-5-execution-plan.md)；评估规范见 [docs/evaluation/stage-5-evaluation.md](docs/evaluation/stage-5-evaluation.md)。阶段 4 交接见 [STAGE_4_COMPLETION_REPORT.md](STAGE_4_COMPLETION_REPORT.md)，阶段 3 见 [STAGE_3_COMPLETION_REPORT.md](STAGE_3_COMPLETION_REPORT.md)。

阶段 5 最终真实运行结果（2026-11-06）：`scripts/verify.py` **12/12 gates 退出码 0**；`ruff format --check` **174 个文件**通过，`mypy app`（strict）**97 个源文件**无错误，后端 **1324 passed, 1 skipped**（跳过项为 Windows 符号链接权限测试），OpenAPI 与前端类型同步，两条阶段 2.1 复审复现仍为旋转越界 0.000% / ICC 最大通道差 0；前端 **44 个测试文件 / 461 tests passed**，lint/typecheck/契约/生产构建全部退出码 0；Playwright 在隔离栈（`next start -p 3031` + API `:8014`）**21 passed / 15 skipped（1.2 min）**，覆盖上传→分析→方案→接受，以及撤销/重做/导出、风格、对话、点评、反馈与阶段 3/4 回归。所有自动化测试使用 **Mock Provider 与合成夹具**，真实照片评分、A/B/C/D 对照与真实 Provider 稳定性仍未评估。

**本地启动方式：**

```powershell
cd services/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd apps/web
npm run dev
```

打开 <http://127.0.0.1:3000>，上传图片并完成一次 AI 分析后，打开“AI 摄影师”面板：选择风格或直接生成方案，查看参数与理由，接受后在普通历史中撤销/重做；也可用对话修改、查看点评并提交评分。

**下一阶段建议：** 先用用户授权的真实照片补齐 [docs/evaluation/stage-5-evaluation.md](docs/evaluation/stage-5-evaluation.md) §4–§7（14 类评分、A/B/C/D、真实 Provider 稳定性与失败计数）；在那之前不应宣称任何摄影质量提升。若要扩展能力，语义蒙版、自由文本点评与几何编辑都需要单独决策与 ADR，并继续保持“AI 只提案、原图字节不可变、用户显式接受才写 revision”的约束。**阶段 5 到此停止，未获确认不进入下一阶段。**
