# FRAME AI

响应式、非破坏性照片后期工具。本仓库当前完成 **阶段 1：可运行骨架与上传预览**。

第一版最终目标是从上传到导出的闭环：读取原图、提取可计算特征、生成受约束的编辑配方，并由 Pillow/OpenCV 从原图重渲染。当前阶段只建立前端、API、原图存储与预览链路，不包含编辑、会话、AI 或导出。

## 当前范围（阶段 1）

已实现：

- Next.js + React + TypeScript + Tailwind 的响应式上传/预览界面。
- FastAPI 健康检查、统一错误结构、请求 ID 与访问日志。
- 图片上传的 MIME 与内容双重校验。
- 上传大小（默认 20 MiB）与像素（默认 40 MP）硬限制。
- 随机 UUID 文件名、路径隔离、原子写入的原图存储。
- 原图预览、下载（`Content-Disposition`）与本地元数据登记。
- 服务端配置样例、启动文档、后端与前端测试。

明确未实现（后续阶段）：

- 图像特征分析、编辑配方、参数面板、前后对比。
- 编辑会话、revision、撤销/重做/重置。
- Pillow/OpenCV 处理管线、非破坏性渲染与导出。
- SQLite 迁移、DeepSeek provider 与 stub。
- EXIF 方向归一化与导出元数据剥离。
- 删除会话/临时文件清理、鉴权、限流、公网部署加固。

## 架构与请求流

```text
Browser (Next.js 16 / React 19)
  │  POST /api/v1/images (multipart)
  ▼
Next.js rewrite: /api/v1/* → API_INTERNAL_URL (default 127.0.0.1:8000)
  │
  ▼
FastAPI
  ├─ RequestContextMiddleware   请求 ID、耗时、状态码日志
  ├─ UploadSizeLimitMiddleware Content-Length 预检
  ├─ ImageService
  │    ├─ 读取并限制字节数
  │    ├─ Pillow 检查真实格式 / 尺寸 / 像素 / 声明 MIME
  │    ├─ OriginalImageStore 写入 data/originals/<uuid>.<ext>
  │    └─ ImageRegistry 原子写入 data/image_registry.json
  └─ GET /images/{id}/original → FileResponse（原始字节）
```

浏览器默认通过同源 `/api/v1` 代理访问后端，因此本地开发不依赖 CORS。FastAPI 也允许在 `.env` 中配置跨域来源，便于直接访问 API。

## 目录

```text
.
├── apps/web/                 Next.js 页面、组件、API 客户端、前端测试
│   ├── app/                  App Router 页面与全局样式
│   ├── components/           通用 UI 与图标
│   ├── features/editor/      上传、预览、健康状态
│   ├── lib/                  API 客户端、错误映射、校验与格式化
│   └── tests/                Vitest + Testing Library
├── services/api/             FastAPI 服务
│   ├── app/api/routes/       health、images 路由
│   ├── app/core/             配置、错误、日志、中间件
│   ├── app/imaging/          安全解码与图片检查
│   ├── app/models/           Pydantic 响应/错误模型
│   ├── app/repositories/     原图存储与 JSON 元数据登记
│   ├── app/services/         上传编排
│   └── tests/                pytest 接口测试
├── data/                     运行期生成（已忽略）：原图与登记表
├── .env.example              后端配置样例（复制到根目录 .env）
├── .gitignore
└── README.md
```

## 先决条件

- Node.js 20+（本项目在 Node 24.19.0 验证）。
- npm 10+（本项目在 npm 11.17.0 验证）。
- Python 3.11+（本项目在 Python 3.14.7 验证）。
- Windows、macOS 或 Linux。命令示例以 Windows PowerShell / Git Bash 为主。

## 本地启动

### 1. 后端

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

可选配置：复制根目录配置样例。后端会自动读取仓库根目录的 `.env`，同时支持 `services/api/.env` 覆盖。

```powershell
cd ../..
copy .env.example .env
```

启动：

```powershell
cd services/api
python -m uvicorn app.main:app --reload --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>
- 数据目录默认：`<repository>/data`

Git Bash 等价命令：

```bash
cd services/api
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

### 2. 前端

```bash
cd apps/web
npm install
cp .env.example .env.local   # 可选；默认值即可启动
npm run dev
```

打开 <http://127.0.0.1:3000>。Next.js 会把 `/api/v1/*` 代理到 `API_INTERNAL_URL`，默认 `http://127.0.0.1:8000`。

### 3. 首次使用

无需 DeepSeek 密钥。阶段 1 不会调用任何 AI 服务：

1. 选择或拖入 JPEG/PNG/WebP 图片。
2. 前端先做大小/类型提示，服务端再做权威校验。
3. 上传成功后显示原图预览、尺寸、格式、文件大小。
4. 可下载原图或在新窗口打开。

## 环境变量

后端读取 `FRAME_` 前缀变量，优先级：进程环境 > `services/api/.env` > 根目录 `.env` > 默认值。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FRAME_ENVIRONMENT` | `development` | 环境标签 |
| `FRAME_LOG_LEVEL` | `INFO` | `DEBUG/INFO/WARNING/ERROR/CRITICAL` |
| `FRAME_DATA_DIR` | `<repo>/data` | 本地数据目录；相对路径按进程工作目录解析 |
| `FRAME_MAX_UPLOAD_BYTES` | `20971520` | 单文件最大字节数（20 MiB） |
| `FRAME_MAX_IMAGE_PIXELS` | `40000000` | 最大像素数（40 MP） |
| `FRAME_CONTENT_LENGTH_ALLOWANCE` | `1048576` | Content-Length 预检给 multipart 的余量 |
| `FRAME_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | 允许直接跨域访问 API 的来源 |

前端读取（放在 `apps/web/.env.local` 或 shell 环境）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `API_INTERNAL_URL` | `http://127.0.0.1:8000` | Next.js 服务端 rewrite 目标 |
| `NEXT_PUBLIC_API_BASE_URL` | 空 | 空表示走同源代理；填绝对地址则直接访问 API |
| `NEXT_PUBLIC_MAX_UPLOAD_BYTES` | `20971520` | 前端提示用上限，应与后端一致 |

DeepSeek 变量仅在第三阶段接入，当前不会读取：

| 变量 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 仅服务端使用，禁止进入前端构建或版本库 |
| `DEEPSEEK_BASE_URL` | 例如 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 例如 `deepseek-chat` |

## 存储与数据模型（阶段 1）

```text
data/
├── image_registry.json
└── originals/
    └── 36973fbf-a830-4415-aee4-1314ccdbf739.png
```

- 原图按服务端生成的 UUID + 实际解码格式扩展名保存；用户文件名不参与路径。
- `image_registry.json` 只记录相对 `storage_key`，写入使用临时文件 + `fsync` + `os.replace`。
- 原图只读使用：上传后没有覆盖或改写接口；预览和下载返回原始字节。
- 记录包含 `id`、`original_name`、`storage_key`、`mime_type`、`width`、`height`、`bytes`、`sha256`、`created_at`。
- 当前没有删除接口。开发清理时请先停止服务，再删除 `data/`。
- JSON 登记表不是最终持久化方案；阶段 3 迁移到带版本迁移的 SQLite，并扩展 ImageAsset / EditSession / EditRevision / AnalysisResult / ExportRecord。

## 支持的图片与限制

| 项目 | 阶段 1 约定 |
| --- | --- |
| 允许格式 | JPEG、PNG、WebP |
| 单文件上限 | 20 MiB（可配置） |
| 像素上限 | 40,000,000（可配置） |
| 声明 MIME | 必须是上述三种之一（`image/jpg` 归一为 JPEG） |
| 内容核验 | Pillow 解码格式必须与声明 MIME 一致 |
| 损坏/伪造 | 无效内容返回 `415 invalid_image`；类型不符返回 `415 mime_mismatch` |
| 超限 | 文件过大/像素超限返回 `413`，不会静默夹紧 |
| 未知资源 | `404 image_not_found` 或 `404 image_file_missing` |

服务端使用随机文件名与路径隔离；同时限制上传字节数和像素数。前端限制只用于即时提示，不能替代服务端校验。

## API（阶段 1）

统一前缀 `/api/v1`，JSON 字段使用 camelCase。错误统一为：

```json
{
  "error": {
    "code": "unsupported_media_type",
    "message": "Only JPEG, PNG, and WebP images are supported.",
    "details": {}
  }
}
```

| 方法与路径 | 请求 | 响应 |
| --- | --- | --- |
| `GET /api/v1/health` | 无 | `{status, service, version, storage}` |
| `POST /api/v1/images` | multipart，字段名 `file` | `201 {imageId, originalName, width, height, mimeType, bytes}` |
| `GET /api/v1/images/{imageId}/original` | 无 | 原图字节；`Content-Disposition: inline` |
| `GET /api/v1/images/{imageId}/original?download=true` | 无 | 原图字节；`Content-Disposition: attachment` |

示例：

```bash
curl -F "file=@photo.jpg;type=image/jpeg" http://127.0.0.1:8000/api/v1/images
curl -o original.jpg \
  "http://127.0.0.1:8000/api/v1/images/<imageId>/original?download=true"
```

所有响应包含 `X-Request-ID`。状态码按任务书约定：`400` 空文件/格式错误、`404` 资源不存在、`413` 超限、`415` 类型不支持、`422` 请求校验失败、`500` 未预期错误。

## 隐私与安全边界

- 原图与登记表只保存在本机数据目录，不上传第三方存储。
- 阶段 1 不调用 DeepSeek 或任何外部模型；没有密钥也不会阻断上传/预览。
- 密钥只从服务端环境变量读取；`.env` 与 `data/` 已被忽略。
- 日志包含请求 ID、方法、路径、状态码、耗时和客户端地址；不记录图片字节、密钥或完整文件内容。上传成功日志只记录随机 ID、字节数、尺寸与 MIME。
- 原图响应带 `X-Content-Type-Options: nosniff`，并使用服务端判定的 MIME。
- **EXIF 尚未处理**：原图按字节保存，当前下载会保留原始 EXIF（包括可能存在的 GPS）。EXIF 方向归一化和导出元数据剥离属于阶段 2/阶段 5，当前不应宣称已剥离。
- 当前没有登录、权限或限流；API 只适合本机开发，不应直接暴露到公网。

## 测试与检查

后端：

```powershell
cd services/api
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

前端：

```bash
cd apps/web
npm run lint
npm run typecheck
npm test
npm run build
```

本阶段最后一次真实运行结果：

- 后端 `pytest`：**21 passed**（1 条 Starlette TestClient 的 `httpx` 弃用警告，非失败）。
- 后端 `ruff check .`：**All checks passed**；`ruff format --check .`：**26 files already formatted**。
- 前端 `npm run lint`、`npm run typecheck`：通过。
- 前端 `npm test`：**2 个测试文件、8 个测试通过**。
- 前端 `npm run build`：Next.js 16.4.4 生产构建通过。
- 真实浏览器验证：上传 1600×1067 PNG 成功，界面显示预览与元数据；原图文件 SHA-256 与上传源文件一致；下载响应为 `attachment` 且尺寸/字节正确。
- `npm audit --omit=dev`：生产依赖 **0 vulnerabilities**；完整审计有 16 个 dev-only（ESLint/minimatch 工具链）moderate 提示，未影响运行时。

尚未执行或未覆盖：

- 真实移动设备/窄屏触控回归（仅使用桌面浏览器窄视口与响应式布局检查）。
- 导出、编辑会话、AI provider 相关测试（功能尚未实现）。
- 真实 DeepSeek 联调（阶段 1 不调用）。
- 并发上传、崩溃恢复、跨进程写登记表的压力测试。

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

**Turbopack 开发期 panic（本次验证中曾出现一次）**

停止所有 `next dev`/node 开发进程，删除 `apps/web/.next`，再运行 `npm run dev`。本项目的生产构建不受影响。

**界面显示 “API 未连接”**

确认 FastAPI 已在 8000 端口启动，且 `API_INTERNAL_URL` 指向正确地址。健康检查请求为 `GET /api/v1/health`。

**上传后立即 413**

检查后端 `FRAME_MAX_UPLOAD_BYTES` / `FRAME_MAX_IMAGE_PIXELS` 与前端 `NEXT_PUBLIC_MAX_UPLOAD_BYTES` 是否同步。像素超限与字节超限都会返回 413，错误 `details` 中会给出上限。

**原图文件丢失**

登记表仍存在但文件被移动/删除时，预览接口返回 `404 image_file_missing`。删除整个 `data/` 后旧 imageId 也会失效。

## 已知限制与风险

1. JSON 登记表按单进程假设设计；多 uvicorn worker 同时写入没有跨进程锁。阶段 3 用 SQLite 版本迁移替换。
2. 上传限制包含 Content-Length 预检与读取计数；FastAPI 会先完成 multipart 解析，因此缺少 Content-Length 的流式请求仍需由后续代理层/SQLite 阶段补强。
3. 原图写盘成功但登记表写入失败时会回滚删除；若进程恰好在两者之间崩溃，可能留下孤儿文件，需阶段 5 清理策略。
4. 未做鉴权、限流、病毒扫描；原图下载依赖不可猜测 UUID，但这不构成访问控制。
5. EXIF 方向、GPS 剥离、临时预览清理尚未实现。
6. 前端与后端的上传上限是两个配置项，修改时必须同步。
7. 完整 `npm audit` 的 16 个 moderate 均来自 ESLint 工具链，生产依赖审计为 0。

## 阶段 1 交接

**阶段：** 1 — 可运行骨架与上传预览

**本次完成：** 从浏览器上传到 FastAPI 校验、本地原图存储、预览与下载的可运行闭环；响应式界面；配置样例；后端 21 项、前端 8 项测试；真实浏览器与磁盘校验。

**关键文件：**

- `apps/web/app/page.tsx`、`apps/web/features/editor/editor-workspace.tsx`
- `apps/web/features/editor/upload-dropzone.tsx`、`upload-result.tsx`
- `apps/web/lib/api/client.ts`、`apps/web/lib/upload-validation.ts`
- `apps/web/next.config.ts`（`/api/v1` 代理与开发源白名单）
- `services/api/app/main.py`、`app/api/routes/images.py`
- `services/api/app/imaging/decoder.py`（MIME/内容/像素校验）
- `services/api/app/repositories/original_store.py`、`image_registry.py`
- `services/api/app/services/image_service.py`
- `services/api/tests/`、`apps/web/tests/`

**验证命令及真实结果：** 见上文“测试与检查”。

**未完成项与风险：** 见上文“已知限制与风险”；编辑、会话、SQLite、AI、导出均留给后续阶段。

**本地启动方式：**

```powershell
cd services/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/web
npm run dev
```

打开 <http://127.0.0.1:3000>。

**下一阶段建议：** 阶段 2 先实现配方 schema 与硬范围校验、分析特征、Pillow/OpenCV 确定性渲染、手动参数面板、前后对比、撤销/重做/重置与从原图导出；保持原图字节不变与 EXIF 方向处理。
