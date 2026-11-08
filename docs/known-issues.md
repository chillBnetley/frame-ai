# 已知问题与限制

更新日期：2026-11-07。每阶段结束时复查一次。

阶段 2 已解决阶段 1 的以下问题：JSON 登记表迁移到 SQLite；EXIF 方向在渲染前烘焙进像素；导出剥离元数据并嵌入 sRGB ICC；Playwright 端到端补齐。阶段 2.1 进一步修复旋转内容缩放、嵌入 ICC 转换、导出内存预算、Host/Origin 防护、渲染竞态、历史草稿保护、对比几何对齐、幂等键重用与代理缓存。阶段 3 新增 AI 分析任务、Provider 抽象、CV 测量、区域引用、诊断与五区界面，默认 Mock。阶段 4 Task 1–6 新增配方 v2、全局调色扩展、曲线、HSL、颜色分级、局部参数与用户矩形/椭圆蒙版；Task 7 关闭调色板/1-bit 输入的 ICC 缺口，并把色彩管理策略、位深取舍与依赖边界写成 [color-management.md](color-management.md) 与 [ADR-0004](decisions/ADR-0004-color-management.md)。阶段 5 新增 AI 摄影师：方案提案、12 个参数化风格、对话补丁、确定性点评与反馈闭环，全部只提案、不自动应用；真实照片人工评估仍未完成。设计限制整改 B5a（2026-11-07）关闭“导出 PNG 没有 alpha 通道”缺口（8-bit 默认路径；预览/代理/分析仍白底）。B5b（同日）关闭 L10（16-bit RGB 输入降位与 16-bit 输出未启用）：16-bit PNG/TIFF 输入保真进入 float32，PNG/TIFF 可导出 8/16-bit，ICC 使用矩阵/TRC 转换。以下为现有阶段的限制；阶段 1/2 的既有条目继续有效。

## 数据与并发

- SQLite、原图存储与预览缓存都按**单进程**设计。没有跨进程锁；不要用多个 uvicorn worker 同时写同一数据目录。
- 会话提交使用 `BEGIN IMMEDIATE` 保证进程内串行；多进程下仍可能冲突，未测试。
- 预览是本地内容寻址缓存，不是共享缓存；多实例部署需要共享存储与清理协调。
- 原图写入使用临时文件、`fsync` 与 `os.replace`，写入失败会清理临时文件；原图写入成功、SQLite 写入失败时会回滚删除文件。进程若恰好在两步之间崩溃，仍可能留下孤儿文件，启动扫描只告警，不自动删除。
- **删除是硬删除，没有回收站**：`DELETE /api/v1/images/{imageId}` 与 `DELETE /api/v1/sessions/{sessionId}` 返回 204；未知或非法 id 返回 404；重复删除仍是 204，由 `deleted_resource(kind, id, deleted_at)` 墓碑表区分“已删除”与“从未存在”。删除图片在同一事务内先删会话（满足 `image_id … ON DELETE RESTRICT`），再删图片，由既有外键级联清除 revision、分析任务/结果、方案与反馈；提交后删除原图，代理仅在无其他 `image_asset` 共享同一 `sha256` 时删除，并清空本机预览 JPEG 与进程内解码代理缓存；该图片/会话已成功的导出作业与 `tmp/exports` 结果文件也一并清除（`GET /exports/{jobId}` 与 `/result` 此后均 404）。删除与提交之间的竞态由导出作业的 retired 围栏处理（见下方导出条目）；重复删除仍为 204，并会重试上次失败的 unlink 与目录孤儿清理。删除会话保留原图。分析任务处于 pending/processing 或该会话正在导出时返回 409 `resource_busy`（`details.reasons` 为 `analysis`/`export`）。编辑器提供二次确认；删除后回上传态，刷新不能恢复会话。
  - 文件删除发生在数据库提交之后；Windows 文件占用等失败不会回滚已经返回的 204，日志记录 `image_files_deleted … skipped`，由 `services/api/scripts/purge_orphans.py` 重试。该脚本默认 dry-run，`--apply` 才删除孤儿原图/代理，并把“登记存在但原图缺失”的图片按删除路径清理。
  - 预览没有“图片 → 预览文件”反向索引，删除任意图片会把本机预览目录清空（预览可再生）；代理目录按内容寻址，只删不再被引用的 sha。
  - 删除整个 `data/` 仍会清空所有数据；鉴于删除不可恢复，重要图片应先下载原图或导出。部分失败留下的孤儿文件（含无法 unlink 的导出结果）不会阻塞接口，但会占用磁盘，直到手工运行 purge 或下次启动清空导出目录。
- 阶段 1 的 `image_registry.json` 首次导入后改名为 `*.imported.bak`；导入器幂等，但备份文件不会自动清理。

## 预览与导出

- **PNG/TIFF 导出保留 alpha（8-bit 与 16-bit），JPEG 合成白底。** loader 在 `preserve_alpha=True`（默认）时把 `RGBA`/`LA`/带 `transparency` 的 `P` 拆成 RGB + alpha 两条 float32 通道，几何变换、分辨率缩放与画布缩放都按预乘 alpha 同步处理，渲染阶段只改 RGB、alpha 原样透传，PNG/TIFF 编码写出 RGBA 并嵌入 sRGB ICC；JPEG 编码在最后用 `round(rgb*a + 255*(1-a))` 合成白底。**预览与代理仍恒为 8-bit JPEG / RGB PNG 白底合成**：预览没有 alpha 消费方，代理版本保持 `loader/3`，不为 alpha 升级缓存格式或失效历史缓存；16-bit 源使用带 `|b16` 的代理键。16-bit alpha 只在导出结果中可见。
- 预览缓存按**空闲时间 + 容量上限**清理：`tmp/previews/` 与 `previews/proxies/` 中 mtime 超过 `FRAME_PREVIEW_TTL_SECONDS` 的文件在启动时和每个清理间隔删除；`GET /previews/{id}` 成功返回时用 `os.utime` 续期，代理命中时也刷新 mtime，因此持续查看的会话不会被 TTL 删除。清理只删普通文件、跳过符号链接与子目录；若文件已被外部删除或容量淘汰，仍返回 `404 preview_expired`，前端 `PreviewImage.onError → retry()` 自动重渲染恢复。`GET /previews/{id}` 在路由内读取文件而不是交给 `FileResponse` 延迟打开，因此 resolve 之后才被清理的竞态也映射为 404，不会变成 500。
  - **容量上限**：预览目录与代理目录合计超过 `FRAME_PREVIEW_MAX_BYTES`（默认 2 GB）时，按 mtime 最旧优先淘汰到上限内（LRU）。因此“按访问续期”不会让磁盘无限增长；长期积累的旧缓存仍受总容量约束。只读文件系统导致 `os.utime` 失败时忽略续期，不影响预览返回；Windows 文件占用等删除失败会跳过并计入 `skipped`，在下一轮清理重试。
  - 蒙版画布的参考图（`局部蒙版预览`）不是 `PreviewImage`，没有重渲染入口：Task 8 起在加载失败时改为显示“参考图已过期”说明并保持画布可框选，任何新的渲染（URL 变化）都会自动恢复它。
- 两层进程内缓存（解码代理 `FRAME_PROXY_CACHE_MB`、蒙版权重 `FRAME_MASK_CACHE_MB`）只在服务运行期间存在，服务重启即全部失效；单进程预算默认各 64 MB，按条目大小计数而**不统计进程真实 RSS**，缓存占用也不从导出准入的预算里扣除。导出准入使用"静态估算 + psutil 实时可用内存"两道门（见下），是另外两套机制。蒙版权重单条超过 24 MB 不入库：24 MP 画布的权重约 91.55 MB，因此大导出每次都重新计算权重，缓存对它没有收益（实测见 `docs/performance.md`）。
- Windows 上 `os.replace` 目标被浏览器/杀毒软件占用时会失败。`PreviewStore` 使用进程内锁、短重试与“回退到已存在目标”兜底；这不是跨进程一致性方案。
- 导出串行化只限制单进程（`BoundedSemaphore(1)`）；第二个请求返回 `503 server_busy` 与 `Retry-After: 2`。多进程下可能同时执行多个大图导出。
- **导出作业是内存态、单进程的**：`/api/v1/exports` 的作业表保存在服务进程内，重启后旧 `jobId` 全部返回 404，启动时也会清空上次遗留的结果文件；已结束作业与结果文件超过 `FRAME_EXPORT_JOB_TTL_SECONDS`（默认 3600）后，在 `GET`/`DELETE` 查询状态或提交新作业时惰性清理，删除图片/会话时同步清除。取消是协作式的：运行中的渲染在解码前后、缩放、旋转/裁切、全局调色、局部调整、细节与编码前后检查取消令牌，接近完成的作业可能仍以 `succeeded` 结束，以 `GET` 状态为准。旧同步端点 `POST /sessions/{id}/export` 仍保留，但直接渲染、不排队也不可取消，仅为兼容；前端已改用异步作业。作业跨重启、多实例共享与持久化历史不在本阶段范围。
- **删除与导出的窄竞态由 retired 围栏兜底**：删除前的忙碌检查与数据库提交不在同一事务，作业可能在检查之后才完成自身校验。`purge_sessions` 会把被删除会话登记为 retired（TTL 内有效并有硬上限），取消并从作业表移除匹配的 queued/running 作业；工作线程在写结果后、置 `succeeded` 前在锁内复核作业仍在表中且会话未 retired，否则删除文件并丢弃。结果文件下载在锁内打开句柄后流式返回，作业被清理或文件缺失时是 404 而不是 500。unlink 失败（Windows 占用）进入待删集合并由后续请求或墓碑重复删除重试，墓碑分支还会扫描导出目录清理不属于任何在表作业的普通结果文件（跳过隐藏临时文件、目录与符号链接）。残余风险：retired 记录在 TTL 后清除，超过 TTL 仍在渲染的作业理论上可能晚到，但正常渲染远短于默认 3600 秒；目录扫描按文件名 stem 与作业 id 匹配，若未来结果命名规则改变需同步调整。
- API 在导出解码前按像素数、配方与位深估算峰值内存，超过 `FRAME_EXPORT_MAX_RSS_MB` 返回 413 `export_too_large`；基准脚本也用同一上限断言实测 RSS。该机制是保守估算，不是运行期 RSS 硬限制，实际峰值仍可能受依赖版本、系统分配器与其他进程影响。复审整改 P3-9 增加了第二道门：静态估算通过后，再用 `psutil.virtual_memory().available` 检查"真实可用 − 本次估算 ≥ `FRAME_EXPORT_RESERVE_MB`（默认 256）"，不满足则返回 503 `server_busy`。这仍是采样时刻的快照，不跟踪导出期间其他进程的内存增长；它只把"整机已经紧张"的情况挡在解码之前。复审整改 G4 按 8 个实测峰值把满配方系数从 Task 8 的 240 降到 **160 B/px**（本轮最高 131 B/px：24 MP + 3 蒙版 2999 MB；24 MP 满配方 2907 MB、40 MP 满配方 4793 MB、12 MP 满配方 1478 MB），中性 45 B/px 不变（24 MP 1043 MB、40 MP 1635 MB），局部 +8 B/px 不变（3 个局部 +92 MB）。系数仍保留约 22% 余量。B5b 为 16-bit 源与输出各加 **18 B/px**（合计 36 B/px）：24/40 MP 实测中性 16-bit 仅比 8-bit 高 60/109 MB，满配方峰值由渲染主导、16-bit 与 8-bit 基本相同（2801/2801、4616/4617 MB），因此该附加项是保守预留而非拟合值。**默认 3072 MB 预算下 24 MP 满配方仍被拒绝**（8-bit 估算 3812 MB、实测 2907 MB）；16-bit 中性 24 MP 可导出，40 MP 中性会被保守估算拒绝（估算 3240 MB、实测 1671 MB）。长边 2400 可导出（估算 1180 MB、实测 794 MB、p95 4.3 s）。在本机 15.4 GiB 内存上，了解余量后可以把上限调到 6144 MB 放行全尺寸。
- 导出峰值内存是单机、每种配方 1 次采样的结果，且**同一档在不同轮次之间会漂移**：40 MP 满配方在 Task 6 那轮是 8258 MB、Task 8 是 7366 MB（−11%）。G4 的 4793 MB 比 Task 8 低 35%，其中曲线 LUT 是可直接归因的部分（曲线阶段瞬态从 4.3 GB 降到 1.15 GB），不能当作纯轮间漂移；标定仍按本轮最高系数加余量，不承诺是所有环境的硬上限。`FRAME_MAX_IMAGE_PIXELS=40000000` 因此解码地板最高 1867 MB，默认预算不会因为下采样而误拒大图。
- **阶段四满配方导出超出阶段 2 的 20 s 目标**：Task 8 完整基准（20 次）24 MP 满配方 p50 29.6 s、p95 32.2 s；12 MP 为 13.9／14.8 s，40 MP 为 49.8／52.2 s。该目标没有随阶段四管线扩展（曲线、HSL、颜色分级）而更新，当前如实标记 FAIL，不代表局部蒙版单独造成回退。同一批图片选长边 2400 后 24 MP 满配方 p50 4.6 s、40 MP 5.3 s，是当前的实用规避路径。详见 `docs/performance.md` 的"阶段 4 Task 8"。
- 原图超过 12 MP（`EXPORT_DENOISE_SIMPLIFY_PIXELS`）且启用降噪时，8-bit 导出改用更小的非局部均值模板/搜索窗，并通过 `X-Export-Warning: denoise_simplified` 告知前端；导出成功对话框会显示“降噪已简化（导出尺寸超过 12 MP）”并建议改用更小的长边。**16-bit 导出直接跳过降噪**（OpenCV 去噪只收 uint8），返回 `denoise_skipped_for_16bit`；不生成 8-bit 中间结果，其余调整保持 float32。预览恒走代理尺寸（≤ 1600 px）的全量降噪，因此大图导出的降噪细节与小图预览不完全等价。**这个分叉不是用画质掩盖性能**：`cv2.fastNlMeansDenoisingColored` 的耗时随搜索窗面积与像素数增长，大图上保持全量窗口会让单次导出从数十秒膨胀到分钟级；简化的是算法搜索窗，而不是跳过降噪或改用户参数。需全量降噪时请减小导出像素数或改用 8-bit 导出。
- **颜色分级按亮度分区，不是空间蒙版**：阴影/中间调/高光权重只取决于 Rec.709 亮度，同亮度的不同颜色会得到相同权重；极端高光或纯色像素在叠加色偏后可能触及 `[0,1]` 边界而被截断，无法在保持亮度时完全避免。阶段四 Task 6 的局部调整使用独立的几何蒙版，不复用颜色分级的亮度权重；仍不包含吸管取色或 AI 自动分级。

## 上传与图像

- 单次上传只接受一个 `file` 字段；多个文件返回 `400 invalid_upload`。
- 动画 WebP/APNG 返回 `415 animated_not_supported`；不处理多帧。
- 16 位/高位深输入：**16-bit RGB PNG/TIFF 不再降位**。PNG 用 OpenCV `IMREAD_UNCHANGED`、TIFF 用 `tifffile` 取 uint16 像素，Pillow 只读 ICC/EXIF/方向；uint16 归一为 float32 后进入同一管线，`LoadedImage.bit_depth=16`。16-bit 灰度（`I;16*`/`I`/`F`）仍按 `/65535` 归一直接进入 float32。16-bit PNG/TIFF 可导出 8/16-bit；HDR 色调映射与 32-bit 容器仍未支持。策略与实测见 [color-management.md](color-management.md)。
- **TIFF 输入只支持单页、未压缩或 Deflate**（压缩值 1/8/32946）；LZW/JPEG 压缩返回 415 `unsupported_tiff_compression`，多页返回 415 `tiff_multipage_not_supported`，associated（预乘）alpha（tag 338 含 1）返回 415 `associated_alpha_not_supported`（只接受 unassociated alpha，与输出端 `unassalpha` 一致）。`PlanarConfiguration=2` 的 16-bit TIFF 按 tag 284 解码为 `(S,H,W)`，并与 tag 256/257 校验形状；不再根据 shape 猜测布局。20 MiB 上传上限不变，因此大 TIFF 需要无损压缩后才可上传；未引入 `imagecodecs`。
- 嵌入 ICC 管理：8-bit 路径在模式归一之后用 lcms 转换，覆盖携带有效 RGB 设备空间配置的 `RGB`/`RGBA`/`P`/`PA`/`1`/`L`/`LA`（阶段 2.1 的 F2-02 只覆盖 `RGB`/`RGBA`，调色板与 1-bit 的 37 级缺口已在阶段四 Task 7 关闭）。8-bit 下设备空间非 RGB 的配置（灰度/Lab）、`CMYK` 图片上的 RGB 配置（lcms 组合不合法，静默回退，实测与参考差 19–23 级）、损坏或截断的配置仍按 sRGB 解释。**16-bit 路径改用纯 NumPy 矩阵/TRC**：只支持 `rXYZ/gXYZ/bXYZ` + `rTRC/gTRC/bTRC`（curv/para 0–4）；LUT 类（`mft/mAB/mBA`）、非 RGB/XYZ 设备空间、越界或损坏配置返回 422 `unsupported_icc_profile`，不静默降级。sRGB 快速路径也先做结构校验（无 LUT、矩阵/TRC 与标准 sRGB 等价），profile description 不参与判断；该 422 在上传后的首次解码（preview/render/export）产生，上传入口不校验 ICC。`I;16*`/`F` 灰度没有 RGB 通道可管理。
- 带 alpha 的输入：导出路径保留 alpha（PNG/TIFF 输出 RGBA，8/16-bit；JPEG 在白底合成），预览、代理与 AI 分析仍按白底合成（分析侧显式 `preserve_alpha=False`，对应既有的 `ALPHA_LIMITATION`）；预览界面没有“透明棋盘格”显示。半透明像素在 PNG/TIFF 中保留原 alpha，JPEG 与预览看到的是白底结果。
- 原图下载返回上传时的原始字节，可能包含 EXIF/GPS；只有导出会剥离元数据。界面已提示。
- 渲染不保留原图的 EXIF 方向标签以外的元数据；方向在渲染前烘焙。
- **不做 RAW 显影、镜头校正、软打样、设备链接配置与感知/饱和度渲染意图**，也没有色域标记或"是否检测到 ICC"的观测字段。输入广色域被收敛到 sRGB，超出部分截断；输出为 **8-bit 或 16-bit sRGB**（PNG/TIFF；JPEG 固定 8-bit）。依赖评估：8-bit 路径不新增依赖；B5b 只新增 `tifffile==2026.3.3`（BSD-3-Clause，用于 TIFF 读写），`rawpy`/`pillow-heif`/`colorio`/`imagecodecs` 均未引入，理由与验证见 [ADR-0004](decisions/ADR-0004-color-management.md) D6/D9。
- 8-bit 预览代理是实测取舍：强曲线（+0.7 EV、对比 40、5 点 S 形）下 float 源与 8-bit 代理源渲染差 max 4 级 / mean 0.33 级，输出级数不变、不产生色带；边界由 `tests/test_color_management.py` 钉住。若后续调整代理精度，这两条测试会失败提醒。16-bit 源仍写 8-bit RGB 代理，但代理键追加 `|b16`，不会复用旧截断代理；预览与代理本身仍不保留 16-bit。
- `frame-engine/8` 与 `loader/3` 提升使**全部历史预览磁盘缓存与代理缓存自动失效**：历史会话首次打开需要重新渲染，已保存配方、revision 与原图字节不受影响。
- `frame-engine/9`（白平衡守恒对象、HSL 色相单调上限、颜色分级越界缩放）与 `frame-engine/10`（Blacks 方向/掩膜、HSL 分档门控、曲线端点外推、对比度色度回收）只提升引擎版本：预览磁盘缓存与局部蒙版权重缓存按 `ENGINE_VERSION` 键控，自动失效；代理缓存键只含原图 SHA、`loader/3` 与边长，**不**因这两次提升而失效，历史缩略图仍可命中。B5b 不提升 `ENGINE_VERSION` 或 `PROXY_VERSION`：8-bit 输出字节不变，16-bit 源仅在代理键后追加 `|b16`，8-bit 历史代理继续命中。

## 编辑器与前端

- 没有真实 iOS Safari / Android Chrome 真机回归；E2E 覆盖桌面 Chromium 引擎（本机使用系统 Edge）的 1280×800、1280×640 与 390×844、320×568 视口，浏览器缩放与软键盘仍以手工检查为主。
- 桌面端左列使用固定视口高度（`100dvh`）承载预览与历史栏，参数面板内部滚动；高度 ≤680 px 时历史列表隐藏，只保留撤销/重做/重置按钮以给预览让位。
- 窄屏迷你预览由 `IntersectionObserver` 触发，固定挂载到 `document.body` 以避开 `backdrop-filter` 的定位影响；极旧且不支持该 API 的浏览器不会显示迷你预览，但主预览与编辑流程不受影响。
- 迷你预览在前后对比、裁切与导出对话框打开时强制隐藏；退出后由观察器重新判断。不支持手动收起，避免与主预览的显示状态产生额外状态机。
- 对比视图的原图一侧会应用旋转/裁切（几何归一），因此两侧尺寸一致；若第三方响应出现宽高比差异超过 1%，前端回退到 `object-contain` 并提示，不再拉伸。
- 参数面板的两位小数规范化在前端完成；第三方客户端必须自行 `roundTo2`，否则服务端返回 422。
- 没有离线草稿或本地持久化；刷新页面依赖 URL 中的会话信息恢复。
- **模态必须挂到 `document.body`**：原图工作区卡片带 `backdrop-filter`，它会让卡片内部的 `fixed` 元素以卡片为包含块——实测遮罩 659×6079、对话框被推出视口，而 Playwright 的 `toBeVisible` 仍会通过。评分与导出对话框已用 `createPortal(..., document.body)` 修复，e2e 断言包围盒落在视口内；新增模态必须沿用同一写法。

## 局部调整与蒙版

- **没有人物 / 天空自动蒙版**：局部调整只支持全图、用户矩形和用户椭圆。阶段三视觉结果只有归一化 bbox，`regions[].mask` 仍为 `null`；bbox 不是像素蒙版，把它当蒙版会污染框内背景，因此界面中的“人物蒙版”“天空蒙版”按钮是禁用占位，后端也没有对应类型。接入真实分割模型前不会提供该能力。
- **蒙版是参数化几何，不是栅格蒙版**：矩形/椭圆、羽化、反选、不透明度随 recipe 以 JSON 保存，没有 `storageRef` 或蒙版图片；因此不支持画笔、渐变、多蒙版布尔运算或语义蒙版。最多 20 个蒙版 / 20 个局部调整。
- **局部 v1 只支持 11 个字段**：曝光、对比、高光、阴影、白场、黑场、色温、色调、饱和度、自然饱和度、清晰度。`sharpen/denoise/vignette/grain` 的字段仍保留在 schema 中，但非零值保存返回 422；前端不提供这些控件。局部降噪/锐化在代理与导出分辨率之间的语义未验证，局部暗角本质是全局径向效果。
- **多个局部调整按 `id` 顺序叠加，不是图层合成**：后一项看到前一项的结果；重叠区域没有混合模式、蒙版相减或独立图层。结果确定可复现，但不等价于 Photoshop 式图层。
- **蒙版轮廓是近似显示**：前端 SVG 轮廓用于定位和拖动创建，受预览尺寸、旋转/裁切取整影响；像素级结果以服务端渲染为准。预览与导出使用同一归一化坐标和同一权重函数，边界位置一致，但目标尺寸取整会带来亚像素级差异。
- **恢复会话的源码尺寸可能未知**：刷新后若上传响应不在内存中，前端用预览宽高比与裁切合成 4096 px 高的源尺寸来推导显示几何；这只影响轮廓显示，不影响服务端渲染与保存的蒙版坐标。
- **悬空蒙版引用静默降级**：历史或外部数据中的 `maskId` 指向不存在的蒙版时，服务端跳过该局部调整并返回 `local_mask_missing:<maskId>` warning，不会崩溃或套用到全图；前端显示“蒙版缺失，已停用此局部调整”。当前没有自动修复或合并蒙版的工具。
- **局部性能取决于蒙版数量与画布尺寸**：全 0 参数、`enabled=false`、`opacity=0` 与完全在裁切外的蒙版会跳过像素运算；其余蒙版需要整图权重与一次局部渲染。实测数据见 `docs/performance.md` 中 Task 6 局部场景，未测量的组合不应假定为相同耗时。

## AI 与分析

- **默认是 Mock Provider**：Mock 场景固定、置信度是演示值，界面明确显示“模拟分析（未调用真实视觉模型）”。Mock 结果只用于开发与流程验证，不代表真实模型能力，不得用于准确率宣传。
- **没有真实 Provider 的准确率/成本评估**：本机没有用户授权的标注图片集，也没有配置真实 API Key；真实模型调用的耗时、token 与费用均**未测量**。`scripts/bench_analysis.py` 只测量预处理、CV 特征与 Mock 任务。`scripts/eval_analysis.py` 已提供标注集评估框架（缺 manifest/图片时非零退出且不输出指标），`scripts/smoke_live_provider.py` 用于真实 Provider 连通性检查，未配置时安全跳过；两者都不能替代正式质量数据。规范见 [evaluation.md](evaluation.md)。
- **分析结果没有像素级蒙版**：主体与区域只提供归一化边界框与 `regionId`，`regions[].mask` 恒为 `null`；不生成 RLE 或伪造分割。编辑器的局部调整另使用用户手动画的矩形/椭圆参数蒙版，但它不是语义分割，不能自动选中人物或天空。
- **检测器选型结论**：第一版使用视觉 Provider 返回的 bbox，未引入 YOLO/ONNX/分割大模型；原因是依赖体积、模型下载、部署复杂度与当前环境不匹配，且阶段三只要求基础区域识别。`RegionInfo.source` 已预留 `detector`，后续可在 `VisionProvider` 内部替换而不影响业务层。
- **AI 只提案，不自动应用**：阶段 3 只输出诊断与建议；阶段 5 会基于诊断生成配方提案并在前端预览，但不会自动写 revision 或修改原图。只有用户点击“应用”后才以 `source:"ai"` 提交普通 revision，历史中可撤销/重做；没有后台自动调色、批处理或跳过确认的路径。
- **去重按图片资产与内容**：`dedupe_key` 使用 `sha256(image.id + image.sha256 + config_key)`。同一资产、同一配置仍会去重；重新上传同一内容会得到新的 `image.id`，因此会创建新任务，报告内的 `image.id` 始终与当前图片一致。`force=true` 仍可强制重新分析。
- **单进程任务队列**：线程池、启动恢复与状态更新都在进程内协调；多 uvicorn worker 可能重复执行或状态不一致，不在当前范围。
- **透明图**：带 alpha 的输入在分析副本中按白底合成，原图不变；报告 `limitations` 会说明这一点，不做透明背景语义分析。
- **Provider 侧无配额，应用侧有本地每日上限**：上游 Provider 本身没有按用户/日期的费用配额；应用只在本机按 UTC 日期统计真实 HTTP 请求与 token，由 `FRAME_PROVIDER_DAILY_REQUEST_LIMIT` / `FRAME_PROVIDER_DAILY_TOKEN_LIMIT` 控制（默认 0 = 不强制但仍记录，细节见下一条 L14）。选择 `openai` 前仍需自行评估费用与数据合规；应用内“测试连接”会发起一次真实的最小纯文本请求（不发送图片），既计入 Provider 侧 token 用量与费用，也计入本地额度。
- **API Key 加密存储不是多用户密钥保险箱（L5 已整改）**：页面内保存的配置写入 `<FRAME_DATA_DIR>/provider-settings.json`，默认是 **v2 加密格式**：非密钥字段可读，API Key 以 AES-256-GCM 密文存放在 `secrets` 分组（每次保存新 12 字节 nonce、16 字节 tag、base64 存储），文件里没有 `api_key` 明文字段。32 字节主密钥单独存在 `<FRAME_DATA_DIR>/provider-master-key`，由系统机制保护。旧 v1 明文文件在首次以 v2 启动时自动迁移（读 v1 → 校验生效配置 → 构建 Provider → 再原子写 v2，成功记 `provider_settings_migrated from=1 to=2`）；迁移失败时 v1 字节完全不变、临时文件清理、启动明确失败，不会以明文继续运行。密文通过 AAD `frame-ai/provider-settings/v2/<kind>` 绑定 provider 角色，改任一字节或跨 provider 挪动密文都会 fail-closed；主密钥丢失/损坏时启动失败并提示重新输入 API Key，不静默回退明文，**也不会自动生成替代主密钥**——只要 v2 文件里还有 `secrets`，缺失的主密钥只会报错，磁盘/钥匙串里不会被写入一把解不开旧数据的新密钥（首次使用、v2 尚无 `secrets`、以及 v1 迁移仍正常创建第一把密钥）。剩余风险：**以同一 OS 用户身份运行的本机进程仍可调用 DPAPI/Keychain 解密**，因此这不是多用户隔离的保险箱；进程内存中仍短暂持有明文 key；`FRAME_PROVIDER_SETTINGS_ENCRYPTION=off` 会退回明文 v1（仅回退/救援用，启动与每次保存打 WARNING）。
- **每日成本上限的计数口径与限制（L14 已实现）**：`provider_usage` 每个 UTC 日期、每个 Provider 一行，只存请求数与 token 计数，不存 prompt/响应/图片/密钥。计数发生在出站策略与 DNS 解析成功之后、真实发送之前，所以被策略/DNS 拦截的调用不消耗额度；重试每次、重定向每跳各计 1。token 优先用响应 `usage`，缺失时用请求体+响应体字节数估算（`ceil(bytes/4)`），两者不重复计。限额默认 0（只记录不强制）；用量账本读写失败会 fail-closed（分析入队与 usage 端点 503 `provider_usage_unavailable`；设置页测试连接仍 200，以 `ProviderTestResult.code` 报告），而不是放行无界流量。队列内任务没有结构化 details 通道，只落 `provider_budget_exceeded` + 静态 message，由前端按 code 映射中文；同步 429 才带 `limit/used/remaining/resetAt`。Mock Provider 不计量。旧数据按日期保留，没有自动清理。

  | 平台 | 主密钥保护方式 | 支持状态 |
  | --- | --- | --- |
  | Windows x64（amd64） | DPAPI `CryptProtectData`/`CryptUnprotectData`（当前用户、禁 UI、固定 entropy）；文件内只有 blob | 支持，Windows 实机验证通过 |
  | Linux x86_64 / aarch64 | 主密钥文件 `O_CREAT\|O_EXCL` + `0600`，读取校验模式位，不符则 chmod 后复检，仍不符 fail-closed | 支持（依赖官方 wheel；**本次未实机验证**，POSIX 断言在 Windows 上 skip） |
  | macOS Apple Silicon（arm64） | 登录 Keychain 通用密码项（Security.framework ctypes，密钥不进 argv） | 支持（**未实机验证**，仅 fake bridge 单测） |
  | Intel Mac（x86_64 macOS） | — | **不支持**：`cryptography==50.0.2` 无该 wheel |
  | 32-bit Windows / Windows on ARM | — | **不支持**：`cryptography==50.0.2` 无这些 wheel |

  运维须知：备份时 `provider-settings.json` 与 `provider-master-key` 必须**成对**；DPAPI/Keychain 保护的主密钥通常无法在另一台机器/另一个用户下解开，**换机后请重新输入 API Key**。恢复路径：删除 `provider-settings.json`（必要时连 `provider-master-key`）后重填；需要回退到不读 v2 的旧代码时，先用 `FRAME_PROVIDER_SETTINGS_ENCRYPTION=off` 保存一次写成明文 v1 再回退。Windows 上 `os.chmod` 不改变 DACL，安全性来自 DPAPI + 用户目录 ACL，不是文件模式位。依赖 `cryptography==50.0.2`（`cp311-abi3` 是 CPython **稳定 ABI** wheel，适用 3.11+，本机在 3.14.7 验证；实测传递依赖 `cffi==2.1.1` + `pycparser==3.12`）。
- **Provider Base URL 默认只允许公网 HTTPS（L6 已整改）**：默认策略 `FRAME_PROVIDER_URL_POLICY=public-only` 且 `FRAME_PROVIDER_ALLOW_INSECURE_HTTP=false`，保存与启动都会拒绝明文 `http`、私网（`10/8`、`172.16/12`、`192.168/16`、`fc00::/7`）、回环、IPv4-mapped 私网、链路本地/云元数据（`169.254.0.0/16`，含 `169.254.169.254`）、`fe80::/10`、`0.0.0.0/8`、组播、保留与未指定地址，字段规则为 `invalid_url`。字面 IP 在保存时分类；DNS 名保存时只做语法校验、不联网；请求前对 `getaddrinfo` 的**每个**结果分类，任一地址被拒即 fail-closed，连接只使用已校验 IP（防 DNS 重绑定，重定向每跳重新校验）。传输改用 `http.client` 直连，不读取 `HTTP_PROXY`/`HTTPS_PROXY`；HTTPS 仍用原始主机名做 SNI/证书校验。重定向只允许同源且最多 5 跳：跨源与 `https → http` 降级在发请求前拒绝并返回 `provider_endpoint_error`，`Authorization` 不会跨源；301/302/303 转 GET，307/308 保留 body。DNS 解析失败返回可重试的 `provider_unavailable`；所有错误与日志不含 URL/host/IP/key。本机 Ollama/LM Studio 等需要显式设置 `FRAME_PROVIDER_URL_POLICY=allow-local`，明文 `http://127.0.0.1:...` 还需 `FRAME_PROVIDER_ALLOW_INSECURE_HTTP=true`；即使放行本机，元数据/链路本地/组播/保留地址仍被拒绝，且没有 `legacy` 全开策略。剩余风险：DNS 解析器本身与系统 CA 仍被信任；本地单用户部署下不要把 API 暴露到公网，也不要让不可信输入决定 Base URL。
- **本地覆盖优先于环境变量**：保存过 Provider 字段后，修改 `.env` 不会改变这些字段，直到在设置中点击“恢复环境变量配置”删除覆盖文件。覆盖文件损坏、密文被改动、主密钥丢失/损坏或配置不完整都会导致 API 启动失败（fail-closed）；需要手工修复或删除 `provider-settings.json`（必要时连 `provider-master-key`）后重启并重新输入 API Key。
- **配置热替换只影响新任务**：保存新 Provider 后，已开始的分析任务继续使用旧 Provider 完成；切换配置不会自动取消或重跑现有任务。
- 阶段三遗留的 `/images/{id}/analyze` 已在阶段四复审中删除：它同步执行、不受任务闸门约束，返回的 `analysisId` 也无法通过 `/analysis/{id}` 查询或清理，且前端从未调用。图像分析统一走 `POST /analysis` 任务接口。

## AI 摄影师（阶段 5）

- **默认是 Mock Planner**：`mock-planner` 固定输出、置信度是演示值，界面显示 Mock 徽标。自动化回归只证明流程、结构、范围与边界，**不代表真实模型的摄影判断质量**，不得用于准确率或“更专业”的宣传。
- **真实 Provider 与真实照片均未评估**：[stage-5-evaluation.md](evaluation/stage-5-evaluation.md) §4–§7 的 14 类真实照片评分、A/B/C/D 对照、真实 Provider 三次重复稳定性与失败案例计数全部为“未评估（待补）”。仓库不附带授权照片集，不得填写推断分数。
- **没有像素级语义蒙版**：方案只能引用用户已创建的矩形/椭圆蒙版；AI 编造 `maskId` 会被校验拒绝。逆光人像等需要局部提亮但无蒙版时，降级为全局调整并在 `limitations` 中说明，不伪造分割。
- **`styleId/styleStrength` 是惰性元数据**：12 个风格的效果全部落实为配方参数（包络 + 约束），渲染引擎不读取风格字段。风格跨版本时 `styleVersion` 只用于追溯；不要指望只改 `styleId` 就会改变画面。
- **对话只能改白名单路径**：全局 `adjustments.*` 与已存在的 `localAdjustments.<maskId>.*`；不修改曲线、HSL、颜色分级、裁切、旋转、输出设置或蒙版集合。未提及参数保持不变，越界值被裁剪而非落库，无法解析为参数时返回 `supported:false` 而不猜测。
- **点评是确定性证据驱动**：`build_critique` 不调用自由文本模型，优点是稳定、可复现、不编造；局限是表达模板化，只覆盖分析报告中有证据的项。`critique/apply` 只生成全局参数补丁，不改曲线/HSL/分级/蒙版/几何。
- **Planner 已可独立配置，但没有专用清除入口（L15 已整改）**：可在“模型设置”中独立配置 Planner 的 Provider、模型名、Base URL、API Key 及超时/重试/修复次数；未保存的字段逐项跟随当前生效的 decision（含已保存的 decision 覆盖），旧版 `provider-settings.json` 没有 `planner` 分组时按“未配置”读取，行为与此前一致。清除 planner 覆盖只能清空对应字段，或使用“恢复环境变量配置”（会同时删除 vision/decision 覆盖），没有“只清除 planner”的按钮。选择 `openai` 时 Planner 只接收结构化分析摘要与当前配方，不接收图片。Provider 输出不可解析时走确定性规则回退并标 `degraded`；非法输出、超时、不可用分别映射 502/504/503。
- **并发槽位不排队**：`FRAME_PHOTOGRAPHER_MAX_CONCURRENCY` 只限制方案与对话的 Planner 调用；满时立即 503 `photographer_busy`。点评、点评应用与反馈是本地操作，不占槽位。槽位、去重与持久化都在进程内，多 uvicorn worker 不在当前范围。
- **方案与反馈的保存边界**：`photographer_plan` 保存方案/配方 JSON 与 provider/model/promptVersion/styleVersion 等元数据；`photographer_feedback` 只保存动作、来源、参数差异、可选评分与时间，不保存图片、指令原文或点评正文。`UNIQUE(plan_id, action)` 使重复评分更新原行；删除图片/会话时级联清除。
- **接受不等于质量提升**：反馈汇总固定返回三条 disclaimer，前端也固定展示；接受率、拒绝率与评分是行为/主观数据，不能推出“方案更优”。真实质量结论只能来自授权照片的人工评分与对照实验。

## 安全与部署

- **API 无鉴权、无限流、无病毒扫描**；只应绑定 `127.0.0.1`（D-13），不得暴露公网或反向代理到公网。Host 白名单、Origin 与 `Sec-Fetch-Site` 检查只降低 DNS 重绑定和浏览器跨站写入风险，不是鉴权或完整 CSRF 防护。
- 本机其他进程可以访问 API；这是当前接受的本机信任边界。
- 日志不记录图片字节、原始文件名、配方内容或密钥；阶段 5 也不记录对话指令原文（只记录 `instruction_chars`）、点评正文或反馈评分明细。错误响应不返回绝对路径。新增日志点必须继续遵守。
- 导出会剥离元数据，但原图下载不会；不要在分享场景使用原图下载。

## 工具链

- 根目录 `scripts/verify.py` 汇总全部门槛并打印退出码表；必须用 `services/api/.venv/Scripts/python.exe` 运行，以保证与交接记录使用同一解释器和依赖。
- Next.js 16 开发代理默认只转发 10 MB 请求体，会先于 FastAPI 截断大图并返回 500。已在 `apps/web/next.config.ts` 设置 `experimental.proxyClientMaxBodySize: "22mb"`；该值必须高于后端 `FRAME_MAX_UPLOAD_BYTES + FRAME_CONTENT_LENGTH_ALLOWANCE`，真实限制仍由后端执行。修改后需重启开发服务器。
- `next.config.ts` 的 rewrites 在构建时求值；部署到新地址必须重新构建，运行期改 `API_INTERNAL_URL` 无效。
- `npm audit` 的完整审计包含 dev-only 的 ESLint/minimatch 工具链 moderate 提示；`npm audit --omit=dev` 为 0。下次复查：2026-12-02。
- Turbopack 在 Windows 上曾出现子进程退出导致样式加载失败；已改用标准 `@tailwindcss/postcss` + `postcss.config.mjs`，`npm run dev:webpack` 保留为备用入口。
- 在非交互后台 shell 中启动 `next dev` 时，偶尔会留下孤儿 next-server 进程并占用端口；重新启动前需结束该 PID。
- Playwright 默认使用 Chromium；本机未下载 Chromium，E2E 使用 `E2E_BROWSER_CHANNEL=msedge`。安装 Chromium 后可直接 `npm run test:e2e`。
- pytest 在 Windows 上跳过符号链接测试（创建符号链接需要开发者模式或管理员权限）；不是失败。
