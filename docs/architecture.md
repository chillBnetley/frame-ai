# 架构与请求流

## 当前范围

仓库处于阶段 2：安全上传、SQLite 持久化、非破坏编辑会话、确定性渲染、内容寻址预览、前后对比与全分辨率导出。AI provider、自动配方与分析持久化属于阶段 3。

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
  ├─ CorsPreflightGuardMiddleware   CORS 预检边界
  ├─ UploadSizeLimitMiddleware      Content-Length 预检与流式字节限制
  ├─ ImageService                   解码校验 → originals/ → image_asset
  ├─ SessionService                 revision 事务、undo/redo/activate/reset、幂等
  ├─ RenderService                  loader → pipeline → 预览缓存 → previews/<hash>
  ├─ ExportService                  串行槽位 → 全分辨率重渲染 → 元数据剥离
  ├─ AnalysisService                启发式特征（进程内 LRU）
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
POST /api/v1/sessions/{id}/render      → 无状态渲染 + 预览缓存
POST /api/v1/sessions/{id}/revisions   → 事务内校验 parentRevisionId、取号、插入、移动 active/head
POST /api/v1/sessions/{id}/undo|redo|activate|reset
```

- 预览是按配方内容寻址的缓存，不写数据库。
- revision 提交使用 `BEGIN IMMEDIATE`；`Idempotency-Key` 命中时返回原 revision（200）。
- 历史是 `parent_id` 图：`active` 是当前编辑点，`head` 是路径末端；在历史中间提交会形成分支。

### 渲染管线

```text
原图字节
  → 方向归一（EXIF 1–8）
  → 代理缩放（draft 960 / final 默认 1600 / export 全分辨率）
  → 旋转内接（无填充，最大同比例矩形）
  → 裁切（坐标位于旋转后画布）
  → sRGB → 线性
  → 曝光 / 白平衡 / 高光 / 阴影
  → 线性 → sRGB
  → 对比度
  → 饱和度 / 自然饱和度
  → 清晰度 / 暗角
  → 降噪 / 锐化
  → 颗粒
  → uint8 编码
```

`adjustments` 是唯一渲染权威；`styleId/styleStrength` 只作为来源元数据（D-10）。任何算法、常数或顺序变化必须提升 `ENGINE_VERSION` 并重新生成黄金图。

### 对比与导出

```text
GET  /api/v1/sessions/{id}/compare
  → 原图代理（方向归一、同 maxEdge、无编辑）
  → 当前 revision 渲染代理
  → 两张同尺寸 JPEG URL

POST /api/v1/sessions/{id}/export
  → 获取单进程导出槽位（失败 503 server_busy）
  → 从原图全分辨率重渲染
  → 剥离 EXIF/XMP/IPTC/GPS，嵌入 sRGB ICC
  → JPEG/PNG 文件流 + X-Export-Width/Height
```

## 数据模型

```text
data/
├── frame.db                 SQLite（权威）
├── originals/<uuid>.<ext>   原图（只读，权威）
└── tmp/previews/<hash>.jpg  预览缓存（可丢弃）
```

- `image_asset`：图片元数据、显示尺寸、`sha256`、原始方向。
- `edit_session`：`image_id`、`active_revision_id`、`head_revision_id`、状态与时间。
- `edit_revision`：`session_id`、`parent_id`、`revision_no`、配方 JSON/哈希、`source`、`idempotency_key`、时间。
- `UNIQUE(session_id, revision_no)` 与 `UNIQUE(session_id, idempotency_key)`。
- 迁移：`app/repositories/migrations/`，`schema_migrations` 记录版本与 checksum；已应用迁移不可修改。
- 阶段 1 的 `image_registry.json` 在启动时幂等导入，之后备份为 `*.imported.bak`。

`FRAME_DATA_DIR` 若为相对路径，一律相对**仓库根目录**解析，与启动时的工作目录无关。

## 一致性与并发

- 单进程假设：SQLite 写事务、预览写锁与导出槽位都是进程内机制。
- 会话提交在 `BEGIN IMMEDIATE` 中完成校验、取号、插入与 active/head 更新，避免重复 `revision_no`。
- 原图写入与 SQLite 插入之间失败会回滚删除文件；进程在两步之间崩溃可能留下孤儿文件，启动扫描只告警。
- 预览写入使用临时文件 + `os.replace`；Windows 目标被占用时短重试并回退到已存在文件。
- 多 uvicorn worker、跨进程缓存一致性与水平扩展不在当前范围。

## 安全边界

- 服务端判定 MIME 与真实解码格式，声明类型不匹配返回 415。
- 上传限额同时由纯 ASGI 中间件（实际字节）与业务层（文件字节）执行。
- 用户文件名只用于展示与下载头；磁盘文件名始终是 UUID。
- 原图只读：没有覆盖或改写接口；导出从原图重算。
- 导出剥离全部元数据并嵌入 sRGB ICC；原图下载保留原始 EXIF/GPS，界面提示。
- 日志不记录图片字节、原始文件名、配方内容或密钥。
- API 无鉴权，只绑定 `127.0.0.1`（D-13）。

## 测试布局（对任务书 §3 的有记录偏离）

任务书建议把前后端与端到端测试都放在根目录 `tests/`。当前安排：

- 后端单元/接口/黄金图测试位于 `services/api/tests/`，与 Python 包和虚拟环境同目录，便于直接运行。
- 前端组件/单元测试位于 `apps/web/tests/`，与 Vitest 配置同目录。
- 根目录 `tests/e2e/` 放 Playwright 端到端测试与夹具。

这是有记录的偏离，不改变任务书要求的测试覆盖内容。
