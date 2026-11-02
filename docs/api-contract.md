# FRAME AI API 契约（阶段 2）

- 状态：已实现，2026-11-02
- 适用：开发阶段 2（图像管线、非破坏编辑、会话与导出）
- 机器可读契约：[`shared/contracts/openapi.json`](../shared/contracts/openapi.json)
- 前端类型：[`apps/web/types/api.d.ts`](../apps/web/types/api.d.ts)
- 决策依据：[ADR-0002](decisions/ADR-0002-phase-2-decisions.md)

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
| 400 | 请求体本身错误：空文件、多个 `file` 字段、缺少字段 |
| 404 | 图片、会话、revision 或预览不存在 |
| 409 ⊕ | 状态冲突：父 revision 不是活动版本、无可撤销/重做步骤 |
| 413 | 文件字节或像素数超限 |
| 415 | 无法解码、MIME 与内容不符、格式不支持、动画图 |
| 422 | 字段校验失败（范围、两位小数、crop 越界等） |
| 500 | 未预期错误或本地存储失败 |
| 503 | 导出串行槽位被占用，或服务未就绪 |

任务书的状态码清单没有 409。并发/历史冲突使用 409 是阶段 2 的契约扩展；具体 `code` 见 §4。

### 1.2 本机边界

API 只绑定 `127.0.0.1`，无鉴权、无限流（D-13）。启动命令必须显式使用 `--host 127.0.0.1`；不得把端口暴露到公网或反向代理到公网。任何部署加固都属于后续阶段。

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

```json
{
  "schemaVersion": "1.0",
  "styleId": "natural",
  "styleStrength": 0,
  "adjustments": {
    "exposureEv": 0,
    "contrast": 0,
    "highlights": 0,
    "shadows": 0,
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
  "rationale": [],
  "warnings": []
}
```

| 字段 | 范围 / 规则 |
| --- | --- |
| `exposureEv` | −3…3 |
| 其余色彩、局部、细节参数 | −100…100；`sharpen/denoise/grain` 为 0…100 |
| `rotationDeg` | −15…15 |
| `crop` | `null` 或 `{x,y,w,h}`；`x,y∈[0,1]`，`w,h∈(0,1]`，`x+w≤1`、`y+h≤1` |
| `rationale/warnings` | 每条 ≤200 字符，各最多 8 条 |
| 数值 | 必须是 JSON number；最多两位小数；拒绝 `NaN/Infinity`；超出范围返回 422，不静默夹紧（D-11） |

补充：

- 缺省字段取默认值 0；`crop` 缺省为 `null`。
- `styleId/styleStrength` 只是来源与 UI 元数据；渲染器只读取 `adjustments`（D-10）。
- 客户端发送前必须做 `roundTo2`：`Math.round(v*100)/100`，并把 `-0` 归零。
- 服务端按规范化 `adjustments` 计算预览哈希；`rationale/warnings` 不参与渲染哈希。

## 4. 端点

### 4.1 系统与图片（阶段 1 延续）

| 方法与路径 | 请求 | 响应 | 主要错误 |
| --- | --- | --- | --- |
| `GET /api/v1/health` | — | `{status, service, version, storage:{ok,writable}}` | — |
| `GET /api/v1/config` | — | `{maxUploadBytes, maxImagePixels, allowedMimeTypes}` | — |
| `POST /api/v1/images` | multipart，唯一 `file` 字段 | 201 `{imageId, originalName, width, height, exifOrientation, mimeType, bytes}` | 400 `invalid_upload`/`empty_file`；413 `payload_too_large`/`file_too_large`；415 `invalid_image`/`mime_mismatch`/`unsupported_media_type`/`animated_not_supported`；500 `storage_error` |
| `GET /api/v1/images/{imageId}/original` | 可选 `?download=true` | 原始字节；`inline` 或 `attachment` | 404 `image_not_found`/`image_file_missing` |
| `POST /api/v1/images/{imageId}/analyze` ⊕ | `{sessionId?}`（可省略） | `{analysisId, features, analyzerVersion}`；阶段 2 仅进程内 LRU 缓存 | 404 `image_not_found` |

`width/height` 是 EXIF 方向归一后的显示尺寸；`exifOrientation` 保留原始 1–8（D-07）。原图字节从上传到导出全程不变。

分析结果为启发式特征（`features.isHeuristic=true`），不调用任何外部模型；持久化留到阶段 3。

### 4.2 会话

| 方法与路径 | 请求 | 响应 | 主要错误 |
| --- | --- | --- | --- |
| `POST /api/v1/sessions` | `{imageId}` | 201 会话状态；创建 `source=initial` 的默认配方 revision | 404 `image_not_found`；422 |
| `GET /api/v1/sessions/{sessionId}` | — | 会话状态 | 404 `session_not_found` |
| `GET /api/v1/sessions/{sessionId}/revisions` ⊕ | `?limit=20&cursor=3` | `{items:[{id, revisionNo, parentId, source, recipeHash, createdAt}], nextCursor}`；按 `revisionNo` 降序 | 404 `session_not_found`；422 |
| `POST /api/v1/sessions/{sessionId}/render` | `{recipe, maxEdge?, quality?}` | 200 `{previewUrl, width, height, quality, cacheHit}`；无状态，不写数据库 | 404 `session_not_found`/`image_not_found`；422 `validation_error` |
| `POST /api/v1/sessions/{sessionId}/revisions` | `{recipe, parentRevisionId, source?}` + 头 `Idempotency-Key` | 201 新 revision 并设为活动；同 key 重放 200 原 revision | 409 ⊕ `revision_conflict`；404；422 |
| `POST /api/v1/sessions/{sessionId}/undo` | 可选 `{revisionId}` | 会话状态；仅移动 `active` | 409 `nothing_to_undo`；409 `revision_conflict`（客户端期望版本不符） |
| `POST /api/v1/sessions/{sessionId}/redo` ⊕ | — | 会话状态；沿通往 `head` 的路径前进一步 | 409 `nothing_to_redo` |
| `POST /api/v1/sessions/{sessionId}/activate` ⊕ | `{revisionId}` | 会话状态；切到会话内任意 revision，不改 `head` | 404 `revision_not_found` |
| `POST /api/v1/sessions/{sessionId}/reset` | — | 会话状态；若活动配方已是默认配方，直接返回当前状态且不新增 revision | 404 |
| `GET /api/v1/sessions/{sessionId}/compare` | `?revisionId=&maxEdge=1600` | `{original:{previewUrl,width,height}, revision:{previewUrl,width,height}}` | 404 |
| `POST /api/v1/sessions/{sessionId}/export` | `{revisionId, format:"jpeg"\|"png", quality?}` | 文件流 + `Content-Disposition` + `X-Export-Width/Height` | 404；422；503 `server_busy` |
| `GET /api/v1/previews/{previewId}` ⊕ | — | `image/jpeg` | 404 `preview_expired` |

#### 提交 revision 与幂等

```http
POST /api/v1/sessions/{sessionId}/revisions
Idempotency-Key: 8f3a1c6e-6e1c-4b0b-9b3a-2f0d5c7e9a11
Content-Type: application/json

{
  "recipe": { "schemaVersion": "1.0", "adjustments": { "exposureEv": 0.2 } },
  "parentRevisionId": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
  "source": "user"
}
```

- `parentRevisionId` 必须等于当前 `activeRevisionId`，否则 409 `revision_conflict`，`details.activeRevisionId` 给出服务端当前值。
- 同一会话内 `Idempotency-Key` 唯一；网络重试必须复用同一个 key。重放返回原 revision 与会话状态，HTTP 200。key 最多 200 字符，空串按未提供处理。
- 不要在 key 下提交不同意图的配方；服务端把同 key 视为同一动作。
- 新建 revision 在 `BEGIN IMMEDIATE` 事务中完成校验、取号、插入与活动/head 更新；单进程串行，不产生重复 `revisionNo`。
- 在历史中间提交会从该 revision 分支，并把 `head` 移到新节点；旧分支仍可 activate。

#### undo / redo / activate / reset

- undo 传 `revisionId` 表示“客户端认为的当前活动版本”；不一致返回 409 `revision_conflict`，避免误撤销别人的状态。
- undo 到初始 revision 后再撤销 → 409 `nothing_to_undo`。
- redo 只沿 `active → head` 的路径前进；不存在目标 → 409 `nothing_to_redo`。
- activate 可以跳到任意历史 revision（阶段 4 历史切换的基础）；不修改 `head`，之后 redo 仍沿原 head 路径。
- reset 生成 `source=reset` 的默认配方 revision 并移动 `active/head`；若当前活动配方哈希已等于默认配方，则不加历史记录。

### 4.3 render 与预览

```json
POST /api/v1/sessions/{sessionId}/render
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
  "cacheHit": false
}
```

- `quality ∈ {draft, final}`，默认 `final`。
- `maxEdge` 默认 1600，范围 1…2560；实际边长不会超过原图最长边。
- 响应中的 `width/height` 是**旋转内接并裁切后的画布尺寸**，前端据此绘制裁切框与对比容器（D-04）。
- render 无状态：不改会话、不新增 revision，只可能写入预览缓存文件。
- `cacheHit=true` 表示命中内容寻址缓存，未重新渲染。

`previewId` 由原图 SHA-256、引擎版本、规范化 adjustments、实际边长与质量共同哈希得到（64 位小写十六进制）。`GET /previews/{previewId}`：

- 返回 JPEG，`Cache-Control: private, max-age=<FRAME_PREVIEW_TTL_SECONDS>`。
- 带 `X-Content-Type-Options: nosniff` 与 CSP `default-src 'none'; sandbox`。
- 文件不存在或已清理 → 404 `preview_expired`；前端应静默重新 render，不弹错误。
- 预览文件位于 `data/tmp/previews/`，按 mtime 超过 TTL（默认 3600 秒）清理；启动时清一次，运行中每 10 分钟清一次。清理只处理该目录内的普通文件，跳过符号链接。

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
  }
}
```

- `revisionId` 省略时使用当前活动 revision；必须属于该会话。
- `maxEdge` 默认 1600，范围 1…2560。
- “原图”是 EXIF 方向归一后、按同一 `maxEdge` 缩放的代理图，**不含任何编辑**；两张图尺寸一致，便于像素对齐对比。

### 4.5 export

```json
POST /api/v1/sessions/{sessionId}/export
{
  "revisionId": "b4c7d2e1-3a5f-4e6a-8b7c-9d0e1f2a3b4c",
  "format": "jpeg",
  "quality": 92
}
```

响应：

- `Content-Type: image/jpeg` 或 `image/png`。
- `Content-Disposition: attachment; filename="frame-<8位id>.jpg"`（或 `.png`）。
- `X-Export-Width`、`X-Export-Height`：实际导出像素尺寸，等于旋转/裁切后的完整画布尺寸。
- `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。

规则：

- 从**原始分辨率**重渲染，不使用预览代理图。
- `revisionId` 必须属于该会话，否则 404 `revision_not_found`。
- JPEG `quality` 1…100，默认 92；quality ≥ 90 时 `subsampling=0`。PNG 忽略 quality。
- 导出串行化：同一进程同时只允许一个导出；第二个请求返回 503 `server_busy`，带 `Retry-After: 2`。
- 元数据：剥离全部 EXIF/XMP/IPTC（含 GPS）；嵌入标准 sRGB ICC；PNG 不写 `eXIf`/`tEXt`/`iTXt`（D-09）。
- 原图字节不被改写；日志只记录 sessionId、revisionId、格式、字节数与耗时。

#### 阶段 2 的 PNG alpha 限制

任务书要求“导出 PNG 保留 alpha；导出 JPEG 合成到白底”。阶段 2 的 loader 会把所有带 alpha 的输入统一合成到白底并转为 RGB，因此**导出的 PNG 目前没有 alpha 通道**，语义等同于白底合成。这是已记录的实现缺口，不是契约承诺；修复计划见 [known-issues.md](known-issues.md)。

## 5. 相对任务书 §7 的契约扩展

| 扩展 | 说明 |
| --- | --- |
| ⊕ 409 状态码 | `revision_conflict`、`nothing_to_undo`、`nothing_to_redo`；任务书状态码表无 409 |
| ⊕ `GET /sessions/{id}/revisions` | 历史条分页；按 `revisionNo` 降序，`cursor` 为上一页最后一条的 `revisionNo` |
| ⊕ `GET /previews/{previewId}` | 内容寻址预览路由（D-06） |
| ⊕ `POST /sessions/{id}/redo` | 沿 head 路径前进（D-02） |
| ⊕ `POST /sessions/{id}/activate` | 历史切换；不改 head（D-02） |
| ⊕ `render.quality` / `cacheHit` | `draft`/`final` 两档与缓存命中标记 |
| ⊕ `POST /images/{id}/analyze` | 阶段 2 启发式特征端点；`sessionId` 仅保留兼容，不改变行为 |

## 6. 错误码

| code | HTTP | 说明 |
| --- | --- | --- |
| `invalid_upload` | 400 | 上传字段不是恰好一个文件 |
| `empty_file` | 400 | 文件为空 |
| `not_found` | 404 | 通用路由不存在 |
| `image_not_found` | 404 | 图片 ID 不存在 |
| `image_file_missing` | 404 | 登记存在但原图文件缺失 |
| `session_not_found` | 404 | 会话 ID 不存在或格式非法 |
| `revision_not_found` | 404 | revision 不属于该会话或不存在 |
| `preview_expired` | 404 | 预览不存在或已被 TTL 清理 |
| `revision_conflict` | 409 | 父 revision/期望 revision 与服务端活动版本不符 |
| `nothing_to_undo` | 409 | 已到历史根节点 |
| `nothing_to_redo` | 409 | 当前路径上没有下一步 |
| `payload_too_large` | 413 | 请求体超过中间件上限 |
| `file_too_large` | 413 | 单文件超过 `FRAME_MAX_UPLOAD_BYTES` |
| `image_too_many_pixels` | 413 | 像素数超过 `FRAME_MAX_IMAGE_PIXELS` |
| `unsupported_media_type` | 415 | 声明 MIME 不在允许列表 |
| `invalid_image` | 415 | 内容无法解码或尺寸非法 |
| `mime_mismatch` | 415 | 声明 MIME 与真实格式不符 |
| `animated_not_supported` | 415 | 多帧图片 |
| `validation_error` | 422 | 字段校验失败，`details.fields` 给出字段、规则与限制 |
| `storage_error` | 500 | 原图或登记写入失败 |
| `storage_conflict` | 500 | 存储键冲突 |
| `internal_error` | 500 | 未预期错误 |
| `server_busy` | 503 | 已有导出占用串行槽位 |
| `service_unavailable` | 503 | 服务未就绪 |
| `rate_limited` / `provider_unavailable` | 429 / 502 | 预留：阶段 2 不使用；阶段 3 接入 AI provider 时启用 |

阶段 1 已约定的错误码与文案映射（前端 `apps/web/lib/error-messages.ts`）保持不变；新增 409 的映射为“编辑状态已更新，已为你刷新”。

## 7. 契约同步流程

1. 修改后端 Pydantic 模型或路由。
2. 在 `services/api` 运行 `python scripts/export_openapi.py` 重新生成 `shared/contracts/openapi.json`。
3. 在 `apps/web` 运行 `npm run gen:api` 重新生成 `types/api.d.ts`。
4. 提交前运行 `python scripts/export_openapi.py --check` 与 `npm run check:api`；两者必须退出 0。
5. 同步更新本文与 `docs/handoff/phase-2.md` 中受影响的行为说明。

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
  -d '{"recipe":{"schemaVersion":"1.0","adjustments":{"exposureEv":1,"saturation":-100}},"quality":"final","maxEdge":1600}'

# 导出（把 REVISION_ID 换成会话返回的 activeRevisionId）
curl -sS -D export.headers -o export.jpg \
  -X POST http://127.0.0.1:8000/api/v1/sessions/SESSION_ID/export \
  -H "Content-Type: application/json" \
  -d '{"revisionId":"REVISION_ID","format":"jpeg","quality":92}'
```

端到端自动化见 [tests/e2e/editor.spec.ts](../tests/e2e/editor.spec.ts) 与 [tests/e2e/README.md](../tests/e2e/README.md)。
