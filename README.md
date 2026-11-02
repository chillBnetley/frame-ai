# FRAME AI

响应式、非破坏性照片后期工具。本仓库当前完成 **开发阶段 1：可运行骨架与上传预览**，并已完成阶段 1.1 审查收尾。

第一版最终目标是从上传到导出的闭环：读取原图、提取可计算特征、生成受约束的编辑配方，并由 Pillow/OpenCV 从原图重渲染。当前阶段只建立前端、API、原图存储与预览链路，不包含编辑、会话、AI 或导出。

## 开发状态

| 开发阶段 | 状态 | commit | 日期 |
| --- | --- | --- | --- |
| 开发阶段 1：可运行骨架与上传预览（含阶段 1.1 收尾） | 已完成 | `11dd6d3`（R-19 代码提交；交接文档随后提交） | 2026-11-02 |
| 开发阶段 2：图像管线与非破坏编辑 | 未开始，等待确认决策 D-01…D-04、D-07 | — | — |

阶段 1.1 的完整命令、退出码与测试清单见 [docs/handoff/phase-1.1.md](docs/handoff/phase-1.1.md)。

## 当前范围（阶段 1）

已实现：

- Next.js + React + TypeScript + Tailwind 的响应式上传/预览界面。
- FastAPI 健康检查、运行时配置、统一错误结构、请求 ID 与访问日志。
- 图片上传的 MIME 与内容双重校验。
- 上传大小（默认 20 MiB）与像素（默认 40 MP）硬限制，覆盖有/无 `Content-Length` 的流式请求。
- 随机 UUID 文件名、路径隔离、原子写入的原图存储。
- EXIF 方向读取与显示尺寸换算；原图字节保持不变。
- 原图预览、下载（`Content-Disposition`）与本地元数据登记。
- 服务端配置样例、启动文档、后端与前端测试、统一验证脚本。

明确未实现（后续开发阶段）：

- 图像特征分析、编辑配方、参数面板、前后对比。
- 编辑会话、revision、撤销/重做/重置。
- Pillow/OpenCV 处理管线、非破坏性渲染与导出。
- SQLite 迁移、DeepSeek provider 与 stub。
- 将 EXIF 方向烘焙进像素、导出元数据（含 GPS）剥离。
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
│   ├── app/api/routes/       health、config、images 路由
│   ├── app/core/             配置、错误、日志、中间件
│   ├── app/imaging/          安全解码与图片检查
│   ├── app/models/           Pydantic 响应/错误模型
│   ├── app/repositories/     原图存储与 JSON 元数据登记
│   ├── app/services/         上传编排
│   ├── scripts/              OpenAPI 导出
│   └── tests/                pytest 接口测试
├── shared/contracts/         OpenAPI 契约与生成说明
├── scripts/verify.py         根目录统一验证脚本
├── tests/e2e/                端到端测试位置（阶段 2 预留）
├── docs/                     架构、ADR、审查记录与阶段交接
├── data/                     运行期生成（已忽略）：原图与登记表
├── .env.example              后端配置样例（复制到根目录 .env）
├── .gitignore
└── README.md
```

## 先决条件

- Node.js 24.19.0（见 `.nvmrc`；`package.json` 要求 `>=24.19.0 <25`）。
- npm 11.17.0（见 `package.json` 的 `engines`）。
- Python 3.14.7（见 `.python-version`；代码保持 3.11+ 兼容，mypy 以 3.11 为目标）。
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
npm ci
cp .env.example .env.local   # 可选；默认值即可启动
npm run dev                  # Turbopack
# 若开发环境出现 Turbopack 问题：npm run dev:webpack
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
| `FRAME_DATA_DIR` | `<repo>/data` | 本地数据目录；相对路径按仓库根目录解析，与启动目录无关 |
| `FRAME_MAX_UPLOAD_BYTES` | `20971520` | 单文件最大字节数（20 MiB） |
| `FRAME_MAX_IMAGE_PIXELS` | `40000000` | 最大像素数（40 MP） |
| `FRAME_CONTENT_LENGTH_ALLOWANCE` | `1048576` | Content-Length 预检给 multipart 的余量 |
| `FRAME_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | 允许直接跨域访问 API 的来源 |

前端读取（放在 `apps/web/.env.local` 或 shell 环境）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `API_INTERNAL_URL` | `http://127.0.0.1:8000` | Next.js 服务端 rewrite 目标；在 `next build` 时写入产物，变更后需重新构建 |
| `NEXT_PUBLIC_API_BASE_URL` | 空 | 空表示走同源代理；填绝对地址则直接访问 API |
| `NEXT_PUBLIC_MAX_UPLOAD_BYTES` | `20971520` | `/api/v1/config` 不可用时的前端回退上限 |

DeepSeek 变量仅在开发阶段 3 接入，当前不会读取：

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
- `image_registry.json` 只记录相对 `storage_key`，写入使用临时文件 + `fsync` + `os.replace`，并受进程内锁保护。
- 原图只读使用：上传后没有覆盖或改写接口；预览和下载返回原始字节。
- 记录包含 `id`、`original_name`、`storage_key`、`mime_type`、`width`、`height`、`exif_orientation`、`bytes`、`sha256`、`created_at`。`width/height` 为 EXIF 方向应用后的显示尺寸。
- JSON 登记表不是最终持久化方案；开发阶段 2 计划按 [ADR-0001](docs/decisions/ADR-0001-json-registry.md) 引入 SQLite（决策 D-01 待确认），开发阶段 3 再补分析结果与导出记录。

### 删除本地图片

当前没有删除接口，也没有 `scripts/purge_data.py`（该保护性清理脚本登记为开发阶段 5 需求）。手工删除单张图片时，先停止 API 服务并备份登记表，再同时处理两处：

1. 在 `data/image_registry.json` 的 `images` 对象中删除对应 `imageId` 条目。
2. 删除 `data/originals/<storage_key>`；`storage_key` 字段的值就是 `originals/` 下的文件名。

只删文件或只删登记项都会造成不一致：前者留下悬空记录（下载返回 `404 image_file_missing`），后者留下孤儿文件。重启服务后启动扫描会把这类不一致写入日志，但不会自动删除。清空全部数据：停止服务后删除整个 `data/`。

## 支持的图片与限制

| 项目 | 阶段 1 约定 |
| --- | --- |
| 允许格式 | JPEG、PNG、WebP |
| 单次上传 | 仅一个 `file` 字段；多个文件返回 `400 invalid_upload` |
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
| `GET /api/v1/health` | 无 | `{status, service, version, storage: {ok, writable}}`；不返回绝对路径 |
| `GET /api/v1/config` | 无 | `{maxUploadBytes, maxImagePixels, allowedMimeTypes}`；前端据此更新上传限制 |
| `POST /api/v1/images` | multipart，字段名 `file`，且只能有一个文件 | `201 {imageId, originalName, width, height, exifOrientation, mimeType, bytes}`；多个 `file` 返回 `400 invalid_upload` |
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
- 日志包含请求 ID、方法、路径、状态码、耗时和客户端地址；不记录图片字节、密钥或完整文件内容。上传成功日志只记录随机 ID、字节数、尺寸与 MIME，不记录原始文件名。测试 `test_logs_redact_original_filename_and_image_bytes` 会验证这一点。
- 原图响应带 `X-Content-Type-Options: nosniff`、CSP sandbox 与服务端判定的 MIME。
- **EXIF 只读取方向，不修改像素**：服务端读取方向标签并返回显示尺寸（1–8），原图按字节保存；因此当前下载会保留原始 EXIF（包括可能存在的 GPS）。界面在上传成功后提示“原图保存在本机，下载原图会包含拍摄位置信息”。方向烘焙、元数据剥离属于开发阶段 2/5。
- 当前没有登录、权限或限流；API 只适合本机开发，不应直接暴露到公网。

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

本阶段最后一次真实运行结果（2026-11-02，commit `11dd6d3`）：统一验证脚本 **10/10 门槛退出码为 0**；后端 **79 passed**，`mypy app` 检查 25 个源文件无错误，OpenAPI 契约同步；前端 **20 passed**，lint/typecheck/build/契约检查通过。逐条命令、工作目录、退出码与测试映射见 [docs/handoff/phase-1.1.md](docs/handoff/phase-1.1.md)。

尚未执行或未覆盖：

- 真实移动设备/窄屏触控回归（仅使用桌面浏览器窄视口与响应式布局检查）。
- 真实 iOS Safari / Android Chrome 真机回归。
- 导出、编辑会话、AI provider 相关测试（功能尚未实现）。
- 真实 DeepSeek 联调（阶段 1 不调用）。

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

1. JSON 登记表按单进程假设设计；多 uvicorn worker 同时写入没有跨进程锁。开发阶段 2 计划按 ADR-0001 用 SQLite 版本迁移替换（D-01 待确认）。
2. 上传限额由纯 ASGI 中间件按实际接收字节执行，并有 `Content-Length` 预检；无 `Content-Length` 的 chunked 请求同样会中止在限额处。Next.js 开发代理的请求体上限已调到 22 MiB，真实限制仍由后端执行。
3. 原图写盘成功但登记表写入失败时会回滚删除；若进程恰好在两者之间崩溃，可能留下孤儿文件，需后续清理策略。
4. 未做鉴权、限流、病毒扫描；原图下载依赖不可猜测 UUID，但这不构成访问控制。
5. EXIF 方向只用于计算显示尺寸，像素与原始 EXIF（含 GPS）未被改写或剥离；导出相关处理尚未实现。
6. 前端上传上限优先读取 `/api/v1/config`，接口不可用时回落到 `NEXT_PUBLIC_MAX_UPLOAD_BYTES`；修改后端 `.env` 后刷新页面即可同步，无需重新构建前端。
7. 完整 `npm audit` 的 dev-only 工具链提示仍存在，生产依赖审计为 0；下次复查日期见 `docs/known-issues.md`。

## 阶段 1 交接

**阶段：** 开发阶段 1.1 收尾 — 可运行骨架与上传预览（已完成，等待确认进入开发阶段 2）。

完整交接（任务书 §12 模板：关键文件、验证命令与退出码、未执行项、风险、启动方式、下一阶段建议）见 [docs/handoff/phase-1.1.md](docs/handoff/phase-1.1.md)。阶段 0 盘点见 [docs/handoff/phase-0-inventory.md](docs/handoff/phase-0-inventory.md)，审查核验记录见 [docs/review/phase-1-verification.md](docs/review/phase-1-verification.md)。

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

**下一阶段建议：** 开发阶段 2 先确认 D-01…D-04、D-07，再实现配方 schema 与硬范围校验、分析特征、Pillow/OpenCV 确定性渲染、手动参数面板、前后对比、撤销/重做/重置与从原图导出；保持原图字节不变并正确处理 EXIF 方向。R-19 之后停止，未获确认不进入开发阶段 2。
