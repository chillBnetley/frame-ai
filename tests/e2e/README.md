# 端到端流程（阶段 2）

Playwright 用生成的合成 JPEG 走完整条链路：上传 → 自动创建会话 → 曝光 +1、饱和度 −100 →
前后对比（含按住空格查看原图）→ 撤销 → 重做 → 重置 → 导出 JPEG。桌面 `1280×800` 与窄屏
`390×844` 各跑一遍；导出后用 Pillow 校验可解码、尺寸正确、无 EXIF/GPS、含 sRGB ICC，并核对
原图字节的 sha256 未变。

## 运行

首次运行安装 Playwright 与 Chromium（根目录）：

```bash
npm install
npm run test:e2e:install
```

启动隔离的 API 与 Next.js 开发服务器（默认端口 8010 / 3010，数据目录为临时目录），并跑两个视口：

```bash
npm run test:e2e
```

如果本机已有 Next.js 开发服务器（例如 3000 端口），可让它复用其 `API_INTERNAL_URL` 指向的 API 端口，
只由 Playwright 启动该 API：

```bash
E2E_BASE_URL=http://127.0.0.1:3000 E2E_API_PORT=8001 E2E_API_URL=http://127.0.0.1:8001 npm run test:e2e
```

`E2E_BROWSER_CHANNEL=msedge` 可改用系统 Edge（无需下载 Chromium）。`E2E_PYTHON` 可指定
Python 解释器；默认使用 `services/api/.venv`。

测试产物写入 `tests/e2e/.artifacts/`（已忽略），报告写入 `playwright-report/`。
