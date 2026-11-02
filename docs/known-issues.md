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
- Next.js 16 开发期曾出现一次 Turbopack panic（Windows）。已保留 `npm run dev:webpack` 作为官方备用开发方式；生产构建不受影响。
- `next.config.ts` 的 rewrites 在构建时求值。[待 R-15 实测后填写行为结论。]
- 当前无鉴权、限流、病毒扫描；API 只应绑定 `127.0.0.1`，不得暴露公网。
- 真实 iOS Safari / Android Chrome 真机回归尚未执行；阶段 1 只做了桌面浏览器与窄视口检查。
