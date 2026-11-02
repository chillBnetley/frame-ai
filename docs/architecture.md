# 架构与请求流

## 当前范围

仓库处于阶段 1.1：可运行骨架、安全上传、本地原图存储、预览与下载。未实现图像管线、编辑会话、AI provider、导出。

## 请求流

```text
Browser (Next.js 16 / React 19)
  │  POST /api/v1/images (multipart)
  ▼
Next.js rewrite: /api/v1/* → API_INTERNAL_URL (默认 127.0.0.1:8000)
  │
  ▼
FastAPI
  ├─ CORS
  ├─ RequestContextMiddleware      请求 ID、访问日志、统一 413 的 X-Request-ID
  ├─ UploadSizeLimitMiddleware     纯 ASGI，按实际接收字节中止超限请求
  ├─ ImageService
  │    ├─ 读取并限制文件字节数
  │    ├─ Pillow 检查格式 / 声明 MIME / 像素 / 动画 / 截断 / EXIF 方向
  │    ├─ OriginalImageStore       写入 data/originals/<uuid>.<ext>
  │    └─ ImageRepository          原子写入 data/image_registry.json
  ├─ GET /api/v1/health            不返回绝对路径
  ├─ GET /api/v1/config            返回非敏感上传限制
  └─ GET /api/v1/images/{id}/original → FileResponse（原始字节）
```

浏览器默认通过同源 `/api/v1` 代理访问后端，因此本地开发不依赖 CORS。FastAPI 仍允许 `.env` 配置跨域来源，便于直接访问 API。

## 数据目录

- 默认 `<repository>/data`。
- `FRAME_DATA_DIR` 若为相对路径，一律相对**仓库根目录**解析，与启动时的工作目录无关。
- 原图保存在 `data/originals/`，登记表为 `data/image_registry.json`。
- `data/` 仅忽略仓库根目录下的运行数据，不会误伤测试夹具目录。

## 安全边界

- 服务端判定 MIME 与真实解码格式，声明类型不匹配返回 `415 mime_mismatch`。
- 上传限额同时由纯 ASGI 中间件（实际字节）与业务层（文件字节）执行。
- 用户文件名只用于展示与下载头；磁盘文件名始终是 UUID。
- 原图只读：没有覆盖或改写接口，预览/下载返回原始字节。
- 日志不记录图片字节、原始文件名或密钥。

## 测试布局（对任务书 §3 的有记录偏离）

任务书建议把前后端与端到端测试都放在根目录 `tests/`。当前安排：

- 后端单元/接口测试位于 `services/api/tests/`，与 Python 包和虚拟环境同目录，便于直接运行。
- 前端组件/单元测试位于 `apps/web/tests/`，与 Vitest 配置同目录。
- 根目录 `tests/e2e/` 预留给阶段 2 的 Playwright 端到端测试。

这是有记录的偏离，不改变任务书要求的测试覆盖内容。
