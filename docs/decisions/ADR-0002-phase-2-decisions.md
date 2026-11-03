# ADR-0002：开发阶段 2 决策（D-01…D-13）

- 状态：已接受并已实现（2026-11-02，用户确认全部采用审查报告推荐方案；2026-11-03 随阶段 2.1 修订 D-03、D-04、D-06、D-09、D-13 的实现说明）
- 适用：开发阶段 2 —— 图像管线与非破坏编辑
- 相关文档：[API 契约](../api-contract.md)、[ADR-0003](ADR-0003-compare-geometry-alignment.md)、[阶段 2 交接](../handoff/phase-2.md)、[阶段 2.1 交接](../handoff/phase-2.1.md)、[性能测量](../performance.md)

## 背景

阶段 1 只有上传、原图存储与预览，没有编辑、会话或导出。阶段 2 要引入配方、revision、确定性渲染和全分辨率导出，必须先固定一批影响数据模型、API 契约和像素结果的选择。审查报告给出 D-01…D-13 的建议方案，用户确认**全部按推荐方案执行**。

本 ADR 逐条记录当时的决策、理由、后果与实现证据。实现以代码与 OpenAPI 为准；若未来改变其中任何一条，应新增 ADR 而不是静默修改本文。

## 决策总表

| 编号 | 采用方案 |
| --- | --- |
| D-01 | 阶段 2 起点引入 SQLite |
| D-02 | 新增 `redo` 与 `activate` |
| D-03 | `Idempotency-Key` 幂等与 409 冲突 |
| D-04 | 旋转取最大同比例内接矩形 |
| D-05 | 保持阶段 1 状态码约定 |
| D-06 | 新增内容寻址的 `GET /previews/{previewId}` |
| D-07 | EXIF 显示方向在渲染前烘焙进像素 |
| D-08 | 颗粒位于锐化/降噪之后、编码之前 |
| D-09 | 导出剥离全部元数据并嵌入 sRGB ICC |
| D-10 | `adjustments` 是唯一渲染权威 |
| D-11 | 前端两位小数，服务端严格拒绝超精度 |
| D-12 | 对外 camelCase，内部 snake_case |
| D-13 | 仅本机、无鉴权 |

---

## D-01：阶段 2 起点引入 SQLite

**背景。** 阶段 1 用 `data/image_registry.json` 记录图片，只有进程内锁，不支持多 worker，也无法承载会话与 revision 的关系数据。

**决策。** 阶段 2 一开始就切换到 SQLite，而不是继续扩展 JSON：

- 使用标准库 `sqlite3`，不引入 ORM。
- 自写 SQL 迁移运行器：`schema_migrations(version, name, checksum, applied_at)`，启动时校验已应用迁移的 SHA-256，防止历史迁移被改写。
- 本阶段只建三张表：`image_asset`、`edit_session`、`edit_revision`。
- 提供幂等的 JSON→SQLite 导入器；导入成功后把旧登记表改名为 `*.imported.bak`，不再写入 JSON。
- 分析结果、导出记录等表留到阶段 3。

**后果。**

- 会话与 revision 可以在事务中完成取号、插入与活动/head 更新。
- 迁移文件一旦应用不可修改，只能追加新版本。
- 仍假设单进程；SQLite 的连接与写锁策略不解决多进程部署。

**实现与证据。**

- `services/api/app/repositories/db.py`：连接、事务与迁移运行器。
- `services/api/app/repositories/migrations/0001_init.sql`：三表、外键、`UNIQUE(session_id, revision_no)`、`UNIQUE(session_id, idempotency_key)`。
- `services/api/app/tools/import_json_registry.py`：校验 sha256、读取方向、幂等插入与备份。
- 测试：`tests/test_db.py`、`tests/test_importer.py`、`tests/test_session_repo.py`。

## D-02：新增 `redo` 与 `activate`

**背景。** 任务书要求撤销/重做/重置，但如果只保存线性快照，无法处理“从历史中间继续编辑”的分支场景。

**决策。**

- `edit_session` 同时保存 `active_revision_id` 与 `head_revision_id`。
- `parent_id` 构成历史图；`revision_no` 每个会话单调递增。
- `undo` 沿 `parent_id` 回退；`redo` 沿 `active → head` 的路径前进一步。
- `activate` 可切到会话内任意 revision，不修改 `head`。
- 在非 head 位置提交新 revision 会形成分支，并把 `head` 移到新节点；旧分支仍可通过 `activate` 访问。

**后果。**

- redo 的语义是“回到当前 head 路径”，不是全局重做栈。
- 历史查询与前端跳转需要同时理解 `active` 与 `head`。
- 分支不会被删除，历史只增不减。

**实现与证据。**

- `services/api/app/services/session_service.py`：`undo/redo/activate/reset` 与事务内 head 移动。
- `services/api/app/api/routes/sessions.py`：对应路由。
- 测试：`tests/test_sessions_api.py`，覆盖分支提交、undo 到根、redo 路径与 activate。

## D-03：`Idempotency-Key` 幂等与 409 冲突

**背景。** 编辑提交可能因网络重试重复发送；同时多个标签页可能基于不同 revision 提交，造成静默覆盖。

**决策。**

- 客户端提交 revision 时携带 `Idempotency-Key`（≤200 字符，空串视为未提供）。
- `UNIQUE(session_id, idempotency_key)`；同 key、同规范化配方哈希与同父 revision 的重放返回 200 与原 revision，不新增历史。
- 同 key 但配方哈希或父 revision 不同，返回 409 `idempotency_key_reuse`，不静默复用旧结果（阶段 2.1 修正）。
- `parentRevisionId` 必须等于当前 `activeRevisionId`，否则 409 `revision_conflict`，`details.activeRevisionId` 返回服务端当前值。
- 新建 revision 在 `BEGIN IMMEDIATE` 事务中完成校验、取号、插入与活动/head 更新。
- `source ∈ {initial,user,ai,reset}`；客户端只能提交 `user` 或 `ai`。

**后果。**

- 任务书状态码表没有 409，本决策引入契约扩展，必须写入 API 契约。
- 调用方必须每次新意图使用新 key；服务端会拒绝同 key 下不同配方或不同父 revision 的请求。
- 服务端不尝试自动合并冲突，只要求客户端刷新后重试。

**实现与证据。**

- `services/api/app/services/session_service.py`：幂等查找、事务提交与冲突检测。
- `services/api/app/models/sessions.py`、`services/api/app/api/routes/sessions.py`。
- 测试：`tests/test_sessions_api.py` 中的重放、冲突与并发提交用例。

## D-04：旋转取最大同比例内接矩形

**背景。** 旋转后的画布可以选择“扩大画布并填充边缘”或“保持原比例并裁掉四角”。填充会引入黑色/镜像边缘，破坏导出构图。

**决策。**

- 旋转后取最大同比例内接矩形，不引入填充边框。
- 内接画布尺寸按 `1 / (cos θ + max(w/h, h/w) sin θ)` 计算；仿射矩阵的缩放固定为 1.0，只做旋转与平移，内容保持源图比例。
- **实现修正（阶段 2.1 / F2-01）**：初版把内接缩放同时用于内容，导致旋转后再次缩小并可能采样到源图之外的镜像边缘。现改为只缩小输出画布，不二次缩放内容；`ENGINE_VERSION` 提升为 `frame-engine/2`，旧预览缓存自动失效，已保存的配方不受影响。
- `crop` 坐标定义在旋转内接后的画布；render 返回该画布的 `width/height`。
- 插值：draft 用双线性，final/export 用双三次；`BORDER_REFLECT_101` 仅是仿射插值的边缘行为，正确内接几何不会依赖源图之外的像素形成可见内容。

**后果。**

- 旋转会缩小可见画布并损失四角内容，但输出始终是完整矩形，内容不会被二次缩小。
- 前端必须使用 render 返回的画布尺寸绘制裁切框。
- 旋转角度范围限制在 −15°…15°，避免过度裁切。

**实现与证据。**

- `services/api/app/imaging/geometry.py`：`inscribed_scale`、`rotate_inscribed`、`crop_pixels`。
- 测试：`tests/test_geometry.py`；黄金图 `tests/golden/` 覆盖旋转与裁切组合。

## D-05：保持阶段 1 状态码约定

**背景。** 阶段 1 已把“无法解码/类型不符”定为 415，把“请求体本身错误”定为 400。阶段 2 新增大量请求模型，需要避免同类错误在不同端点返回不同状态码。

**决策。**

- 无法解码、MIME 与内容不符、格式不支持、动画图 → 415。
- 空文件、多个 `file` 字段、缺少字段 → 400。
- 字段范围、精度、crop 越界等 schema 校验 → 422。
- 资源不存在 → 404；状态冲突 → 409；导出忙 → 503。

**后果。**

- 前端错误映射可以按 `code` 稳定工作。
- 400 与 422 的边界必须写清楚：请求体结构问题用 400，字段值问题用 422。

**实现与证据。**

- `services/api/app/api/errors.py`、`services/api/app/core/errors.py`。
- `docs/api-contract.md` §1.1 与 §6。
- 测试：`tests/test_errors.py`、`tests/test_images.py`、`tests/test_sessions_api.py`。

## D-06：新增内容寻址的 `GET /previews/{previewId}`

**背景。** 任务书只要求 render 返回预览，但浏览器需要可缓存的图片 URL；直接把 base64 放进 JSON 会放大响应并失去 HTTP 缓存。

**决策。**

- 新增 `GET /api/v1/previews/{previewId}`，返回 JPEG。
- `previewId` 由原图 SHA-256、`ENGINE_VERSION`、规范化 adjustments、实际最长边与质量共同哈希（64 位小写十六进制）。
- 文件存放在 `data/tmp/previews/`；启动时清理一次，运行中每 `FRAME_PREVIEW_CLEANUP_INTERVAL_SECONDS`（默认 600 秒）清理超过 TTL（默认 3600 秒）的文件。
- 阶段 2.1 增加 `previews/proxies/` 方向归一/缩放代理缓存，按 64 px 边长分桶复用；命中刷新 mtime，写失败降级为内存渲染，预览 TTL 清理不进入该子目录。
- 响应带 `Cache-Control: private, max-age=<TTL>`、`nosniff` 与 CSP sandbox。
- 文件不存在或已过期 → 404 `preview_expired`，前端静默重新 render。

**后果。**

- 预览是纯缓存，可随时删除；SQLite 与原图才是权威数据。
- 哈希包含引擎版本，算法变化不会命中旧缓存。
- 单进程内需要处理 Windows 上 `os.replace` 目标被占用的情况。

**实现与证据。**

- `services/api/app/services/preview_store.py`：内容寻址、原子写入、TTL 清理、锁/重试。
- `services/api/app/services/render_service.py`：`render_key`、缓存命中与 compare 代理图。
- `services/api/app/api/routes/previews.py`。
- 测试：`tests/test_preview_store.py`、`tests/test_previews_api.py`。

## D-07：EXIF 显示方向在渲染前烘焙进像素

**背景。** 阶段 1 只记录 `exif_orientation` 与显示尺寸，不旋转像素；浏览器预览可能自动纠正方向，但服务端渲染不会。

**决策。**

- 上传时登记原始 1–8 方向；`width/height` 为方向归一后的显示尺寸。
- 渲染前按方向标签旋转/翻转到显示方向，之后所有几何与像素操作都基于该方向。
- 原图字节保持不变；导出不携带原始 EXIF。

**后果。**

- 同一张图在浏览器与服务端渲染中的方向一致。
- 方向烘焙发生在缩放之前，避免先缩放再旋转造成额外插值。
- PNG/无 EXIF 图片方向按 1 处理。

**实现与证据。**

- `services/api/app/imaging/loader.py`：`load_image` 与方向归一。
- `services/api/app/imaging/decoder.py`、`tests/test_loader.py`、`tests/test_decoder.py`。
- 黄金图覆盖方向 1–8。

## D-08：颗粒位于锐化/降噪之后、编码之前

**背景。** 颗粒、锐化与降噪都作用于高频细节；顺序不同会显著改变噪点形态与可复现性。

**决策。**

固定管线顺序：

```text
方向归一 → 缩放 → 旋转内接/裁切 → sRGB→线性
→ 曝光 → 白平衡 → 高光/阴影 → 线性→sRGB
→ 对比度 → 饱和度/自然饱和度 → 清晰度/暗角
→ 降噪/锐化 → 颗粒 → uint8
```

颗粒在 `apply_detail` 内、锐化与降噪之后生成，随后才做最终 uint8 量化。

**后果。**

- 改变顺序或常数必须提升 `ENGINE_VERSION` 并重新生成黄金图。
- draft 与 final 使用相同顺序，只改变插值与尺寸。

**实现与证据。**

- `services/api/app/imaging/pipeline.py`：唯一编排入口。
- `services/api/app/imaging/detail.py`、`services/api/app/imaging/params_map.py`。
- 测试：`tests/test_pipeline.py`、`tests/test_detail.py`、`tests/test_golden.py`。

## D-09：导出剥离全部元数据并嵌入 sRGB ICC

**背景。** 原图可能包含 GPS、相机信息与厂商注释；导出若直接复制原图元数据会泄漏位置，并产生不一致的颜色解释。

**决策。**

- JPEG：清除 EXIF/XMP/IPTC；质量 ≥90 时 `subsampling=0`；嵌入标准 sRGB ICC。
- PNG：不写 `eXIf`、`tEXt`、`iTXt`、`zTXt`、`tIME` 等元数据块；嵌入 sRGB ICC。
- 编码结果必须字节级确定：同一像素与参数重复编码得到相同字节。阶段 2.1 将 sRGB ICC 头部的 lcms 创建时间固定为 2020-01-01 00:00:00，避免不同进程生成不同 ICC 字节；像素算法与引擎版本不变。
- 导出文件名使用服务端生成的 `frame-<8位id>.jpg|png`，不使用原始文件名。

**后果。**

- 导出图不再保留拍摄信息；这是有意的隐私选择。
- 原图下载仍保留原始 EXIF/GPS，界面需要提示。
- 编码器版本变化可能改变字节结果；黄金图测试覆盖像素，不覆盖导出字节的跨版本稳定性。

**实现与证据。**

- `services/api/app/imaging/output.py`：`encode_image`、ICC 嵌入、确定性编码。
- `services/api/app/services/export_service.py`：导出编排与日志脱敏。
- 测试：`tests/test_output.py`、`tests/test_compare_export_api.py`，E2E `tests/e2e/verify_export.py`。

## D-10：`adjustments` 是唯一渲染权威

**背景。** 配方中同时存在 `styleId/styleStrength` 与显式参数；如果渲染器再解释风格强度，会产生两套互相叠加的调整。

**决策。**

- 渲染器只读取 `adjustments`；`styleId/styleStrength` 仅作为来源与 UI 元数据。
- 预览哈希与 revision 配方哈希都基于规范化 `adjustments`；`rationale/warnings` 不参与渲染哈希。
- 前端调节风格时，必须把结果写入 `adjustments`，而不是依赖渲染器理解风格。

**后果。**

- 同一 `adjustments` 在任何来源下都产生相同像素。
- 风格预设只是前端生成 `adjustments` 的工具。
- 阶段 3 的 AI 输出也必须落到 `adjustments`。

**实现与证据。**

- `services/api/app/models/recipe.py`：`canonical_adjustments_json`、`recipe_hash`、`render_key`。
- `services/api/app/imaging/pipeline.py` 只接收 `Adjustments`。
- 测试：`tests/test_recipe.py`、`tests/test_pipeline.py`。

## D-11：前端两位小数，服务端严格拒绝超精度

**背景。** 浮点滑块与序列化会产生 `0.30000000000000004` 之类的值，导致预览哈希不稳定、revision 无意义地新增。

**决策。**

- 前端提交前统一 `roundTo2`：`Math.round(v * 100) / 100`，并把 `-0` 归一为 `0`。
- 服务端拒绝超过两位小数的值，返回 422；不替客户端四舍五入。
- 拒绝 `NaN/Infinity` 与非 JSON number。
- 超出硬范围同样 422，不静默夹紧。

**后果。**

- 同一 UI 操作在不同浏览器上生成相同配方哈希。
- 第三方客户端必须自行规范化，否则会收到 422。
- 预览缓存不会因浮点噪声产生重复条目。

**实现与证据。**

- `services/api/app/models/recipe.py`：`_TwoDecimals`、`_JsonNumber` 与硬范围。
- `apps/web/lib/recipe.ts`：`roundTo2` 与默认配方。
- 测试：`tests/test_recipe.py`、`apps/web/tests/recipe.test.ts`。

## D-12：对外 camelCase，内部 snake_case

**背景。** 前端 TypeScript 习惯 camelCase，Python 与 SQL 习惯 snake_case；混用会导致契约漂移和手写转换错误。

**决策。**

- HTTP JSON 一律 camelCase；通过 Pydantic `alias_generator=to_camel` + `populate_by_name=True` 实现。
- SQLite 列名、内部规范 JSON、日志字段使用 snake_case。
- OpenAPI 导出与前端类型生成是唯一契约来源；`--check` 防止漂移。

**后果。**

- 后端代码内部仍可写 Python 风格字段。
- 新增字段必须同时更新 OpenAPI 与前端生成类型。
- 错误 `details` 不是稳定业务字段，但仍遵循 camelCase。

**实现与证据。**

- `services/api/app/models/schemas.py`：`CamelModel`。
- `shared/contracts/openapi.json`、`apps/web/types/api.d.ts`。
- `services/api/scripts/export_openapi.py --check`、`apps/web` 的 `npm run check:api`。

## D-13：仅本机、无鉴权

**背景。** 阶段 2 的目标是本地单用户编辑闭环；鉴权、配额、限流与公网加固不属于本阶段，但 API 会接触原图与导出。

**决策。**

- API 只绑定 `127.0.0.1`；启动文档固定使用 `--host 127.0.0.1`。
- 不实现登录、权限或限流。阶段 2.1 增加本机 Host 白名单、写入 Origin 与 `Sec-Fetch-Site` 检查，降低 DNS 重绑定和浏览器跨站写入风险；这些检查不是鉴权，也不声称是完整 CSRF 防护。
- 不提供公网部署说明；任何反向代理暴露都不在支持范围内。
- 日志与错误信息不返回绝对路径、原始文件名、图片字节或密钥。

**后果。**

- 本机其他进程可以访问 API；这是可接受的本机信任边界。
- 阶段 3 若引入外部模型调用，必须继续保证密钥只在服务端，并补充出站请求的超时/重试/限流。
- 公网部署需要新的 ADR 与安全审查。

**实现与证据。**

- `README.md` 启动命令与安全边界章节。
- `docs/api-contract.md` §1.2。
- `services/api/app/core/logging.py`、`tests/test_images.py` 的日志脱敏用例。

---

## 全局后果

- API 新增 409 与 503，已写入 [API 契约](../api-contract.md)。
- SQLite 与原图是权威数据；预览是可丢弃缓存。
- 任何像素算法、常数或管线顺序变化都必须提升 `ENGINE_VERSION` 并重新生成黄金图。
- 单进程假设仍然成立；多 worker、水平扩展与公网部署不在阶段 2 范围。
- 阶段 3 的 AI 输出必须落到 `adjustments`，不得绕过 D-10；新增 provider 失败路径需要补齐超时、限流与错误映射。

## 复审

下次复审：进入阶段 3 前。若阶段 3 需要改变 D-01（多进程/外部数据库）、D-03（冲突合并）、D-09（保留部分元数据）或 D-13（鉴权/远程访问），必须先新增 ADR 并获得确认。
