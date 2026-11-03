# 已知问题与限制

更新日期：2026-11-03。每阶段结束时复查一次。

阶段 2 已解决阶段 1 的以下问题：JSON 登记表迁移到 SQLite；EXIF 方向在渲染前烘焙进像素；导出剥离元数据并嵌入 sRGB ICC；Playwright 端到端补齐。以下为阶段 2 结束时仍存在的限制。

## 数据与并发

- SQLite、原图存储与预览缓存都按**单进程**设计。没有跨进程锁；不要用多个 uvicorn worker 同时写同一数据目录。
- 会话提交使用 `BEGIN IMMEDIATE` 保证进程内串行；多进程下仍可能冲突，未测试。
- 预览是本地内容寻址缓存，不是共享缓存；多实例部署需要共享存储与清理协调。
- 原图写入成功、SQLite 写入失败时会回滚删除文件；进程若恰好在两步之间崩溃，可能留下孤儿文件。启动扫描只告警，不自动删除。
- 没有删除图片/会话的 API，也没有 `scripts/purge_data.py`。删除整个 `data/` 会清空所有数据；手工清理需同时处理 SQLite 与原图文件。
- 阶段 1 的 `image_registry.json` 首次导入后改名为 `*.imported.bak`；导入器幂等，但备份文件不会自动清理。

## 预览与导出

- **导出 PNG 没有 alpha 通道。** 任务书要求 PNG 保留 alpha、JPEG 合成白底；当前 loader 对所有带 alpha 的输入统一合成到白底并转 RGB，因此 PNG 导出语义等同于白底合成。这是已记录的实现缺口，修复需要区分导出格式或在管线中保留 alpha 蒙版。
- 预览缓存按 mtime 超过 `FRAME_PREVIEW_TTL_SECONDS` 清理；正在被读取的文件可能先被删除，前端会收到 `404 preview_expired` 并自动重渲染。
- Windows 上 `os.replace` 目标被浏览器/杀毒软件占用时会失败。`PreviewStore` 使用进程内锁、短重试与“回退到已存在目标”兜底；这不是跨进程一致性方案。
- 导出串行化只限制单进程（`BoundedSemaphore(1)`）；第二个请求返回 `503 server_busy` 与 `Retry-After: 2`。多进程下可能同时执行多个大图导出。
- `FRAME_EXPORT_MAX_RSS_MB` 只由 `scripts/bench_render.py` 读取并断言，API 不会按 RSS 拒绝导出。
- 40 MP 导出峰值 RSS（本机 1577 MB）是单次采样、单机、单 Pillow/NumPy 版本结果；不能视为所有环境的硬保证。

## 上传与图像

- 单次上传只接受一个 `file` 字段；多个文件返回 `400 invalid_upload`。
- 动画 WebP/APNG 返回 `415 animated_not_supported`；不处理多帧。
- 16 位/高位深输入会在 loader 中转为 8-bit sRGB RGB 后处理；没有 HDR/16-bit 管线，可能损失高光余量。
- 带 ICC 配置的输入会尽力转换到 sRGB；无效或不可解析的配置会回退为直接 `convert("RGB")`，颜色可能与预期不同。
- 带 alpha 的输入统一合成到白底（见上）；没有“保留透明背景”的选项。
- 原图下载返回上传时的原始字节，可能包含 EXIF/GPS；只有导出会剥离元数据。界面已提示。
- 渲染不保留原图的 EXIF 方向标签以外的元数据；方向在渲染前烘焙。

## 编辑器与前端

- 没有真实 iOS Safari / Android Chrome 真机回归；E2E 覆盖桌面 Chromium 引擎（本机使用系统 Edge）的 1280×800、1280×640 与 390×844、320×568 视口，浏览器缩放与软键盘仍以手工检查为主。
- 桌面端左列使用固定视口高度（`100dvh`）承载预览与历史栏，参数面板内部滚动；高度 ≤680 px 时历史列表隐藏，只保留撤销/重做/重置按钮以给预览让位。
- 窄屏迷你预览由 `IntersectionObserver` 触发，固定挂载到 `document.body` 以避开 `backdrop-filter` 的定位影响；极旧且不支持该 API 的浏览器不会显示迷你预览，但主预览与编辑流程不受影响。
- 迷你预览在前后对比、裁切与导出对话框打开时强制隐藏；退出后由观察器重新判断。不支持手动收起，避免与主预览的显示状态产生额外状态机。
- 对比视图依赖两张代理图尺寸一致；极端 crop/旋转组合下前端裁切框与后端画布尺寸仍需人工核对。
- 参数面板的两位小数规范化在前端完成；第三方客户端必须自行 `roundTo2`，否则服务端返回 422。
- 没有离线草稿或本地持久化；刷新页面依赖 URL 中的会话信息恢复。

## AI 与分析

- `/analyze` 是本地启发式特征，`features.isHeuristic=true`，不调用任何模型；结果只在进程内 LRU 缓存，不持久化。
- 没有 DeepSeek provider、stub、自动配方或失败回退；阶段 3 才实现。
- 阶段 2 的配方来源允许 `ai`，但没有 AI 客户端会生成它。

## 安全与部署

- **API 无鉴权、无限流、无病毒扫描**；只应绑定 `127.0.0.1`（D-13），不得暴露公网或反向代理到公网。
- 本机其他进程可以访问 API；这是当前接受的本机信任边界。
- 日志不记录图片字节、原始文件名、配方内容或密钥；错误响应不返回绝对路径。新增日志点必须继续遵守。
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
