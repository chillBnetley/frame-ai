# 已知问题与限制

更新日期：2026-11-02。每阶段结束时复查一次。

## 数据与并发

- `image_registry.json` 是阶段 1 的临时持久化方案。写入使用进程内 `threading.Lock` + 临时文件 + `fsync` + `os.replace`，只保证单进程内并发安全，不支持多 uvicorn worker。
- 阶段 2 起按 ADR-0001 的计划迁移到带 checksum 的 SQLite 版本迁移；JSON 只作为导入来源。
- 原图写入成功、登记表写入失败时会回滚删除文件；进程若恰好在两步之间崩溃，可能留下孤儿文件。启动扫描只告警，不自动删除。

## 上传与图像

- 动画 WebP/APNG 返回 `415 animated_not_supported`；阶段 1 不处理多帧。
- 阶段 1 只登记 EXIF 方向与显示尺寸，不旋转像素；浏览器预览 JPEG 时通常会自动按 EXIF 方向显示。真正的方向归一化与导出元数据剥离在阶段 2/5。
- 颜色模式 L/P/RGBA/CMYK/I;16 可以上传并登记尺寸；统一转 RGB、alpha 合成与 ICC 转换属于阶段 2 管线。
- 前端上传上限优先读取 `/api/v1/config`，接口不可用时回落到 `NEXT_PUBLIC_MAX_UPLOAD_BYTES`。前端提示不替代服务端校验。

## 工具链

- Next.js 16 开发代理默认只转发 10 MB 请求体，会先于 FastAPI 截断大图并返回 500。已在 `apps/web/next.config.ts` 设置 `experimental.proxyClientMaxBodySize: "22mb"`；该值必须高于后端 `FRAME_MAX_UPLOAD_BYTES + FRAME_CONTENT_LENGTH_ALLOWANCE`，真实限制仍由后端执行。修改后需重启开发服务器。
- `npm audit` 的完整审计包含 dev-only 的 ESLint/minimatch 工具链 moderate 提示；`npm audit --omit=dev` 为 0。下次复查：2026-12-02。
- 早期 Turbopack 开发期崩溃来自 Turbopack 专用的 `@tailwindcss/turbopack` CSS loader 在 Windows 上拉起的子进程退出（0xc0000142）。已改用标准 `@tailwindcss/postcss` + `postcss.config.mjs`；2026-11-02 实测 Turbopack 与 `npm run dev:webpack` 两种模式都能正确加载样式。`dev:webpack` 继续保留为备用入口。
- 在非交互后台 shell 中启动 `next dev` 时，偶尔会留下孤儿 next-server 进程并占用 3000 端口；重新启动前需结束该 PID。正常交互式终端未复现。
- `next.config.ts` 的 rewrites 在构建时求值：2026-11-02 用 `API_INTERNAL_URL=http://127.0.0.1:9999 npm run build` 验证，`.next/routes-manifest.json` 中的目标固定为 `http://127.0.0.1:9999`。部署到新地址必须重新构建，运行期改环境变量无效。
- 当前无鉴权、限流、病毒扫描；API 只应绑定 `127.0.0.1`，不得暴露公网。
- 真实 iOS Safari / Android Chrome 真机回归尚未执行；阶段 1 只做了桌面浏览器与窄视口检查。
