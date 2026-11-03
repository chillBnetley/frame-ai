# FRAME AI

响应式、非破坏性照片后期工具。本仓库已完成 **开发阶段 2：图像管线与非破坏编辑**：从上传、自动建会话、手动参数调整、前后对比、撤销/重做/重置，到从原图全分辨率导出 JPEG/PNG 的闭环。

原图字节从上传到导出全程不变；编辑只记录配方（recipe）与 revision，渲染始终从原图重算。阶段 3（AI 分析 provider 与自动配方）尚未开始。

## 开发状态

| 开发阶段 | 状态 | commit | 日期 |
| --- | --- | --- | --- |
| 开发阶段 1：可运行骨架与上传预览 | 已完成 | `11dd6d3` | 2026-11-02 |
| 开发阶段 1.1：阶段 1 审查收尾 | 已完成 | `a494e45` | 2026-11-02 |
| 开发阶段 2：图像管线与非破坏编辑 | 已完成，等待确认后进入阶段 3 | `a7e8fca`（T2.13 代码验证；T2.14 文档随后提交） | 2026-11-02 |
| 开发阶段 3：AI 分析与非破坏自动编辑 | 未开始 | — | — |

阶段 1.1 的完整命令、退出码与测试清单见 [docs/handoff/phase-1.1.md](docs/handoff/phase-1.1.md)；阶段 2 的完整交接见 [docs/handoff/phase-2.md](docs/handoff/phase-2.md)。

## 当前范围（阶段 2）

已实现：

- 安全上传：MIME 与内容双重校验、20 MiB / 40 MP 硬限制、随机 UUID 文件名、原图只读保存。
- SQLite 持久化：`image_asset / edit_session / edit_revision` 三表、自写版本迁移、阶段 1 JSON 登记表幂等导入。
- 配方 schema：15 个 `adjustments` 字段、硬范围校验、两位小数限制、规范化哈希。
- 确定性渲染管线：方向归一 → 缩放 → 几何（旋转内接 + 裁切）→ sRGB→线性 → 曝光 → 白平衡 → 高光/阴影 → 线性→sRGB → 对比度 → 饱和度/自然饱和度 → 局部（清晰度/暗角）→ 细节（降噪/锐化）→ 颗粒 → uint8。
- 会话与 revision：自动创建初始 revision、提交、撤销、重做、激活任意历史、重置、`Idempotency-Key` 幂等、409 冲突处理。
- 预览：`draft` 960 px / `final` 1600 px、内容寻址缓存、TTL 清理与 `cacheHit`。
- 前后对比：同尺寸原图代理与渲染代理，含按住空格查看原图。
- 导出：从原始分辨率重渲染、JPEG/PNG、剥离全部 EXIF/XMP/IPTC/GPS、嵌入 sRGB ICC、导出串行化。
- 前端编辑工作区：参数面板、裁切/旋转、历史栏、对比视图、导出对话框、可访问性检查。
- 预览可见性：桌面端左列预览与历史栏固定在视口内、参数面板独立滚动；窄屏在主预览离屏时显示固定迷你预览（对比/裁切/导出时隐藏）。
- Playwright 端到端（桌面 1280×800 / 1280×640 与窄屏 390×844 / 320×568）与 §7.8 性能基准。

明确未实现（后续阶段）：

- AI provider、自动配方、分析结果持久化（阶段 2 的 `/analyze` 只是启发式特征，不调用外部模型）。
- 导出 PNG 的 alpha 通道（当前 loader 统一合成到白底；见 [known-issues.md](docs/known-issues.md)）。
- 删除会话/图片、过期数据清理、配额与多用户。
- 鉴权、限流、公网部署加固；API 仅限本机（D-13）。
- 真实 iOS Safari / Android Chrome 真机回归。

## 架构与请求流

```text
Browser (Next.js 16 / React 19)
  │  POST /api/v1/images (multipart)
  │  POST /api/v1/sessions/{id}/render | revisions | undo | redo | export ...
  ▼
Next.js rewrite: /api/v1/* → API_INTERNAL_URL (default 127.0.0.1:8000)
  │
  ▼
FastAPI
  ├─ RequestContextMiddleware      请求 ID、耗时、状态码日志
  ├─ UploadSizeLimitMiddleware     Content-Length 预检与流式字节限制
  ├─ ImageService                 解码校验 → originals/<uuid> → image_asset
  ├─ SessionService               revision 事务、undo/redo/activate/reset、幂等
  ├─ RenderService                loader → pipeline → 预览缓存 → previews/<hash>
  ├─ ExportService                串行槽位 → 全分辨率重渲染 → 元数据剥离 → 文件流
  ├─ AnalysisService              启发式特征（进程内 LRU，不调用外部模型）
  └─ PreviewStore                 TTL 清理、原子写入
```

浏览器默认通过同源 `/api/v1` 代理访问后端，本地开发不依赖 CORS。FastAPI 也允许在 `.env` 中配置跨域来源，便于直接访问 API。

渲染管线固定顺序（D-08）：

```text
原图字节 → 方向归一 → 代理缩放 → 旋转内接/裁切 → sRGB→线性
        → 曝光 → 白平衡 → 高光/阴影 → 线性→sRGB
        → 对比度 → 饱和度/自然饱和度 → 清晰度/暗角
        → 降噪/锐化 → 颗粒 → uint8
```

`adjustments` 是唯一渲染权威；`styleId/styleStrength` 只作为来源元数据（D-10）。任何像素算法或常数变化都必须提升 `ENGINE_VERSION` 并重新生成黄金图。

引擎版本从 `frame-engine/2` 起，旋转只缩小画布到最大内接矩形，内容保持原比例（矩阵缩放固定为 1.0），因此画布不再包含源图之外的镜像像素；旧预览缓存键含引擎版本，会自动失效，已保存的 revision 是配方 JSON，不受影响。

## 目录

```text
.
├── apps/web/                     Next.js 页面、组件、编辑器、API 客户端、前端测试
│   ├── app/                      App Router 页面与全局样式
│   ├── components/               通用 UI 与图标
│   ├── features/editor/          上传、编辑工作区、调整面板、对比、裁切、历史、导出
│   ├── lib/                      API 客户端、配方规范化、错误映射、上传校验
│   └── tests/                    Vitest + Testing Library + axe
├── services/api/                 FastAPI 服务
│   ├── app/api/routes/           health、config、images、sessions、previews
│   ├── app/core/                 配置、错误、日志、中间件、上传限额
│   ├── app/imaging/              loader、geometry、tone、color_ops、local、detail、output、pipeline
│   ├── app/models/               Pydantic 请求/响应/配方模型
│   ├── app/repositories/         SQLite、迁移、原图存储、会话仓库
│   ├── app/services/             上传、会话、渲染、预览、导出、分析
│   ├── app/tools/                阶段 1 JSON 登记表导入器
│   ├── scripts/                  OpenAPI 导出与黄金图生成
│   └── tests/                    pytest 单元/接口/黄金图测试
├── shared/contracts/             OpenAPI 契约与生成说明
├── scripts/                      统一验证脚本与性能基准
├── tests/e2e/                    Playwright 端到端测试与夹具
├── docs/                         架构、API 契约、ADR、性能、已知问题与阶段交接
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

首次启动会自动创建 `data/`、SQLite 表与预览目录；若存在阶段 1 的 `data/image_registry.json`，会幂等导入并备份该文件。

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

无需 DeepSeek 密钥。阶段 2 不会调用任何 AI 服务：

1. 选择或拖入 JPEG/PNG/WebP 图片（超限或类型不符会在前后端双重拦截）。
2. 上传成功后自动创建编辑会话，左侧参数面板实时调整曝光、对比度、高光、阴影、色温、色调、饱和度、自然饱和度、清晰度、锐化、降噪、暗角、颗粒、旋转与裁切。
3. 可按住空格查看原图进行前后对比。
4. 每次保存生成 revision；支持撤销、重做、激活历史版本与重置。
5. 导出 JPEG/PNG：从原图全分辨率重渲染，自动剥离元数据并嵌入 sRGB。

## 环境变量

后端读取 `FRAME_` 前缀变量，优先级：进程环境 > `services/api/.env` > 根目录 `.env` > 默认值。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FRAME_ENVIRONMENT` | `development` | 环境标签 |
| `FRAME_LOG_LEVEL` | `INFO` | `DEBUG/INFO/WARNING/ERROR/CRITICAL` |
| `FRAME_DATA_DIR` | `<repo>/data` | 本地数据目录；相对路径按仓库根目录解析，与启动目录无关 |
| `FRAME_DATABASE_FILENAME` | `frame.db` | SQLite 文件名，位于数据目录下 |
| `FRAME_PREVIEW_TTL_SECONDS` | `3600` | 预览缓存有效秒数；过期后 `GET /previews/{id}` 返回 404 |
| `FRAME_PREVIEW_CLEANUP_INTERVAL_SECONDS` | `600` | 运行期预览清理间隔秒数；启动时另清一次 |
| `FRAME_RENDER_MAX_EDGE_DEFAULT` | `1600` | `final` 预览默认最长边 |
| `FRAME_RENDER_MAX_EDGE_LIMIT` | `2560` | 预览最长边配置上限；请求字段本身仍限制在 1…2560 |
| `FRAME_EXPORT_MAX_RSS_MB` | `3072` | 性能脚本的 40 MP 导出峰值内存上限（脚本读取；API 不限制） |
| `FRAME_MAX_UPLOAD_BYTES` | `20971520` | 单文件最大字节数（20 MiB） |
| `FRAME_MAX_IMAGE_PIXELS` | `40000000` | 最大像素数（40 MP） |
| `FRAME_CONTENT_LENGTH_ALLOWANCE` | `1048576` | Content-Length 预检给 multipart 的余量 |
| `FRAME_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | 允许直接跨域写入 API 的来源 |
| `FRAME_ALLOWED_HOSTS` | `127.0.0.1,localhost,::1` | 接受的 Host 头（防 DNS 重绑定）；留空则跳过校验 |

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

DeepSeek 变量仅在开发阶段 3 接入，当前不会读取：

| 变量 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 仅服务端使用，禁止进入前端构建或版本库 |
| `DEEPSEEK_BASE_URL` | 例如 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 例如 `deepseek-chat` |

## 存储与数据模型（阶段 2）

```text
data/
├── frame.db
├── originals/
│   └── 36973fbf-a830-4415-aee4-1314ccdbf739.png
└── tmp/
    └── previews/
        └── <sha256>.jpg
```

- 原图按服务端生成的 UUID + 实际解码格式扩展名保存；用户文件名不参与路径，原图字节不变。
- `frame.db` 使用标准库 `sqlite3`，启动时按 `app/repositories/migrations/` 执行带 checksum 的版本迁移。
- 表结构：
  - `image_asset`：图片元数据与 `sha256`，`width/height` 为 EXIF 方向归一后的显示尺寸。
  - `edit_session`：`active_revision_id` / `head_revision_id`、状态与时间戳。
  - `edit_revision`：`revision_no`、`parent_id`、配方 JSON 与哈希、`source`、`idempotency_key`；`UNIQUE(session_id, revision_no)` 与 `UNIQUE(session_id, idempotency_key)`。
- revision 不复制像素，只保存配方；渲染与导出始终读取不可变原图。
- 预览是内容寻址的 JPEG 缓存，可随时删除；SQLite 与原图是权威数据。
- 阶段 1 的 `image_registry.json` 在首次启动时导入后备份为 `image_registry.json.imported.bak`（重复导入时带时间戳），之后不再写入。
- 删除整个 `data/` 会清空所有图片、会话、revision 与缓存；当前没有删除接口或保护性清理脚本。

## 编辑语义

- **非破坏**：原图只读；revision 只记录配方；导出从原图重渲染。
- **会话**：上传后自动创建会话与 `source=initial` 的默认配方 revision。
- **提交**：`POST /revisions` 的 `parentRevisionId` 必须等于当前 `activeRevisionId`，否则 409 `revision_conflict`。
- **幂等**：同会话内 `Idempotency-Key` 唯一；网络重试复用同一 key 返回 200 与原 revision。
- **undo/redo/activate**：undo 沿 `parent_id` 回退；redo 沿通往 `head` 的路径前进；activate 可切到任意历史 revision 且不改 `head`；在历史中间提交会形成分支并移动 `head`。
- **reset**：生成 `source=reset` 的默认配方 revision；若活动配方已是默认值则不新增历史。
- **两位小数**：前端 `roundTo2` 并归一 `-0`；服务端拒绝超过两位小数，不四舍五入（D-11）。
- **旋转**：取最大同比例内接矩形，无填充；crop 坐标定义在旋转内接后的画布（D-04）。

## 支持的图片与限制

| 项目 | 阶段 2 约定 |
| --- | --- |
| 允许格式 | JPEG、PNG、WebP |
| 单次上传 | 仅一个 `file` 字段；多个文件返回 `400 invalid_upload` |
| 单文件上限 | 20 MiB（可配置） |
| 像素上限 | 40,000,000（可配置） |
| 声明 MIME | 必须是上述三种之一（`image/jpg` 归一为 JPEG） |
| 内容核验 | Pillow 解码格式必须与声明 MIME 一致 |
| 损坏/伪造 | 无效内容返回 `415 invalid_image`；类型不符返回 `415 mime_mismatch` |
| 动画 | 动画 WebP/APNG 返回 `415 animated_not_supported` |
| 超限 | 文件过大/像素超限返回 `413`，不会静默夹紧 |
| Alpha | 当前统一合成到白底；导出 PNG 不含 alpha 通道 |
| 色彩 | L/P/RGBA/CMYK/I;16 等统一转 sRGB RGB；不保留原 ICC 配置 |
| 方向 | 读取 EXIF 方向并在渲染前烘焙进像素；原图字节保留原始 EXIF |

服务端使用随机文件名与路径隔离；同时限制上传字节数和像素数。前端限制只用于即时提示，不能替代服务端校验。

## API（阶段 2）

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
| `POST /images/{id}/analyze` | 启发式图像特征（不调用外部模型） |
| `POST /sessions`, `GET /sessions/{id}` | 创建/读取会话 |
| `POST /sessions/{id}/revisions` | 提交 revision（幂等、409 冲突） |
| `GET /sessions/{id}/revisions` | 分页读取历史 |
| `POST /sessions/{id}/render` | 渲染预览，返回 `previewUrl/width/height/quality/cacheHit` |
| `POST /sessions/{id}/undo|redo|activate|reset` | 历史操作 |
| `GET /sessions/{id}/compare` | 原图与当前 revision 的同尺寸对比 |
| `POST /sessions/{id}/export` | 全分辨率导出 JPEG/PNG |
| `GET /previews/{previewId}` | 内容寻址预览缓存 |

所有响应包含 `X-Request-ID`。除任务书状态码外，阶段 2 新增 `409`（revision 冲突、无可撤销/重做步骤）与 `503 server_busy`（导出串行槽位占用）。

## 隐私与安全边界

- **仅本机**：API 无鉴权、无限流，必须绑定 `127.0.0.1`（D-13）；不得暴露公网或反向代理到公网。
- 原图、SQLite 与预览只保存在本机数据目录，不上传第三方存储。
- 阶段 2 不调用 DeepSeek 或任何外部模型；`/analyze` 是本地启发式算法。
- 密钥只从服务端环境变量读取；`.env`、`data/` 与测试产物已被忽略。
- 日志包含请求 ID、方法、路径、状态码、耗时和客户端地址；不记录图片字节、原始文件名、配方内容或密钥。导出日志只记录 sessionId、revisionId、格式、字节数与耗时。
- 导出剥离全部 EXIF/XMP/IPTC/GPS 并嵌入 sRGB ICC；PNG 不写 `eXIf`/`tEXt`/`iTXt`（D-09）。
- 原图下载仍返回上传时的原始字节，包含可能存在的 EXIF/GPS；界面会提示这一点。
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

性能基准（自启隔离 uvicorn，输出 p50/p95 与 40 MP 峰值 RSS）：

```bash
services/api/.venv/Scripts/python.exe scripts/bench_render.py
```

本阶段最后一次真实运行结果（2026-11-02，commit `a7e8fca`，干净工作区）：统一验证脚本 **10/10 门槛退出码为 0**；后端 **298 passed, 1 skipped**，`mypy app` 检查 53 个源文件无错误，`ruff` 85 个文件格式通过；前端 **15 个测试文件 / 113 tests passed**，lint/typecheck/契约/生产构建通过；Playwright **2 passed**（12.0 s）；性能基准 **全部 §7.8 项目 PASS**。逐条命令、工作目录、退出码与测试映射见 [docs/handoff/phase-2.md](docs/handoff/phase-2.md)。

2026-11-03 的预览可见性修复、上传错误诊断与滑杆预览闪烁修复在未提交工作区复跑：`scripts/verify.py` **10/10 gates**；前端 **17 个测试文件 / 132 tests passed**；后端 **298 passed, 1 skipped**。Playwright 最近一次完整运行 **7 passed / 5 skipped**（桌面 1280×800、1280×640，手机 390×844、320×568）；错误诊断改动后因 3000 端口开发服务器占用未重跑，已用浏览器实际上传正常图片与无效图片验证。滑杆闪烁修复另用 Playwright（Edge）对运行中的应用做真实鼠标拖拽：桌面 1280×900 与手机 390×844 分别连续采样 750 / 740 帧，均无空白帧与加载占位帧；约 1.8 s 的持续拖动触发 3 次 draft，松手后只发送 1 次 final。

## 性能（§7.8）

完整数据与测量方法见 [docs/performance.md](docs/performance.md)。本机结果摘要：

| 项目 | p50 | p95 | 目标 |
| --- | --- | --- | --- |
| final 预览 1600 px（12 MP） | 288 ms | 298 ms | ≤ 500 ms |
| draft 预览 960 px 含降噪（6 MP） | 186 ms | 226 ms | ≤ 400 ms |
| final 预览 1600 px 含降噪（12 MP） | 792 ms | 865 ms | ≤ 2500 ms |
| 24 MP 导出 | 1700 ms | 1725 ms | ≤ 20 s |
| 19.2 MiB 上传解码 | 239 ms | 254 ms | ≤ 3000 ms |
| 40 MP 导出峰值 RSS | — | 1577 MB | ≤ 3072 MB |

峰值 RSS 统计 API 进程树，包含进程基线；40 MP 内存结果是单次采样、单机数据。

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

**编辑时提示“编辑状态已更新”**

通常是另一个标签页/窗口或网络重试改变了活动 revision。前端会重新加载会话；重试提交时必须使用新的 `parentRevisionId` 与新的 `Idempotency-Key`。

**导出返回 503 `server_busy`**

同一进程只允许一个导出。等待 `Retry-After` 后重试；不要并发触发多个导出。

**预览返回 404 `preview_expired`**

预览缓存已按 TTL 清理。前端会自动重新 render；手动调用时重新请求 `POST /sessions/{id}/render` 即可。

**Playwright 提示缺少浏览器**

运行 `npx playwright install chromium`，或设置 `E2E_BROWSER_CHANNEL=msedge` 使用系统 Edge。若本机已有 Next 开发服务器，使用 `E2E_BASE_URL`/`E2E_API_PORT` 复用其 API 端口。

**原图文件丢失**

SQLite 记录仍存在但文件被移动/删除时，预览接口返回 `404 image_file_missing`。删除整个 `data/` 后旧 imageId 也会失效。

## 已知限制与风险

完整清单见 [docs/known-issues.md](docs/known-issues.md)。阶段 2 重点：

1. **PNG alpha 未保留**：loader 统一合成到白底，导出 PNG 没有 alpha 通道；与任务书“PNG 保留 alpha”存在差距。
2. **无真机回归**：只做了桌面 Chromium/Edge 与窄视口；未在真实 iOS Safari / Android Chrome 上验证触控与性能。
3. **API 无鉴权**：仅支持本机单进程；多 worker 与跨进程并发未验证，`--host` 必须为 `127.0.0.1`。
4. **40 MP 内存为单机单次采样**：1577 MB 峰值依赖 Pillow/NumPy 版本与机器；`FRAME_EXPORT_MAX_RSS_MB` 只由基准脚本断言。
5. **预览缓存写入的 Windows 兼容处理**：`os.replace` 遇到目标文件被占用时使用锁/重试与回退；不是跨进程缓存一致性方案。
6. **EXIF 原图下载**：原图字节保留原始 EXIF（含 GPS）；只有导出会剥离元数据。
7. **AI 未实现**：没有 DeepSeek provider、自动配方或分析持久化；阶段 3 才接入。

## 阶段 2 交接

**阶段：** 开发阶段 2 — 图像管线与非破坏编辑（已完成，等待确认进入阶段 3）。

完整交接（关键文件、验证命令与退出码、测试计数、E2E/性能结果、已知偏差、风险、启动方式、下一阶段建议）见 [docs/handoff/phase-2.md](docs/handoff/phase-2.md)。API 契约见 [docs/api-contract.md](docs/api-contract.md)，决策记录见 [ADR-0002](docs/decisions/ADR-0002-phase-2-decisions.md)，性能数据见 [docs/performance.md](docs/performance.md)。

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

**下一阶段建议：** 先确认阶段 2 交接与已知偏差，再进入开发阶段 3：DeepSeek provider 与 stub、分析结果持久化、自动配方生成与可解释性、失败回退与限流；继续保持原图不可变、导出元数据剥离与本机边界。**T2.14 之后停止，未获确认不进入开发阶段 3。**
