# 端到端流程（阶段 2 / 阶段 3）

Playwright 用生成的合成 JPEG 走完整条链路：上传 → 自动创建会话 → 曝光 +1、饱和度 −100 →
前后对比（含按住空格查看原图）→ 撤销 → 重做 → 重置 → 导出 JPEG。导出后用 Pillow 校验可解码、
尺寸正确、无 EXIF/GPS、含 sRGB ICC，并核对原图字节的 sha256 未变。阶段 3 另加 AI 分析链路：
上传 → 打开分析面板 → 模拟首次请求失败并重试 → 查看报告与主体框 → 重新分析 → 更换照片。

- `editor.spec.ts`：完整编辑与导出闭环，在桌面 `1280×800` 与窄屏 `390×844` 各跑一遍。
- `preview-visibility.spec.ts`：预览可见性专项。桌面在参数面板滚到底部时校验预览仍可见且不被导航遮挡；
  矮桌面 `1280×640` 校验至少一半预览可见；手机 `390×844` 校验迷你预览出现、返回主预览、对比/裁切/导出时隐藏；
  最窄 `320×568` 校验无横向滚动且迷你预览不遮挡滑杆。非目标视口的用例会跳过。
- `analysis.spec.ts`：AI 分析闭环，桌面与手机各跑一遍；首次 POST 由 Playwright 拦截返回 503，
  验证失败提示与 `重试`，随后走 mock provider 的真实 202 → 轮询完成 → 校验六个区域、模拟标记、
  主体框叠加、`构图与遮挡`（构图平衡、遮挡）、`重新分析`（`force: true`）与更换照片后的状态重置。
  不同项目使用不同内容的分析样本，避免跨视口命中同一去重任务。2026-11-04 实测 11 passed / 5 skipped（21.8 s）。

## 覆盖范围与维护提示

- 本套件走的是阶段 2/3 的链路（手动参数、裁切、对比、历史、导出、AI 分析）。阶段 4 新增的曲线、HSL、
  颜色分级、局部调整面板**没有 e2e 用例**，由前端单测、后端黄金图与手动视觉核对覆盖。
- 参数面板底部控件的用例按**位置**取最后一个数字输入（`bottomSlider()`），不再写死“颗粒/旋转”：
  阶段 4 在这些控件下方继续追加了面板，写死名字的用例会滚到底部后落在视口外。
- 工具栏“重置”的用例必须用 `{ name: "重置", exact: true }`：阶段 4 各面板带来了 6 个“重置××”按钮，
  非精确匹配会命中 7 个元素并触发 strict mode violation。
- `analysis.spec.ts` 直接轮询 `E2E_API_URL`，而浏览器上传走的是 `E2E_BASE_URL` 的 Next 代理。
  两者必须指向**同一个 API 进程**，否则任务查不到，表现为 `http_404` 而不是真实缺陷。
- 复用了上一轮遗留的 dev 服务器时要确认它的 `API_INTERNAL_URL` 指向仍然存活的数据目录：
  指向已删除的临时目录时上传会返回 `500 storage_error`，用例会卡在上传步骤。

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

如果本机已有 Next.js 开发服务器（例如 `apps/web` 上的 3000 端口），Next 16 会拒绝在同一项目目录再启动第二个 dev server。
不要结束现有进程，而是复制一份隔离副本（排除 `node_modules`、`.next` 与副本自身），让子目录复用父目录的 `node_modules`：

```bash
MSYS_NO_PATHCONV=1 robocopy "apps/web" "apps/web/.e2e-web" /E /XD node_modules .next .e2e-web
```

先在副本中启动指向隔离 API 的 Next（3010），再由 Playwright 启动 API（8010）：

```bash
(cd apps/web/.e2e-web && API_INTERNAL_URL=http://127.0.0.1:8010 npm run dev -- --port 3010)
E2E_BASE_URL=http://127.0.0.1:3010 E2E_API_PORT=8010 E2E_API_URL=http://127.0.0.1:8010 \
  E2E_BROWSER_CHANNEL=msedge npm run test:e2e
```

结束后停止 3010 上的进程并删除 `apps/web/.e2e-web`（Windows 上若提示占用，稍后重试）。也可以让现有 3000 服务
复用其 `API_INTERNAL_URL` 指向的 API 端口，只由 Playwright 启动该 API：

```bash
E2E_BASE_URL=http://127.0.0.1:3000 E2E_API_PORT=8001 E2E_API_URL=http://127.0.0.1:8001 npm run test:e2e
```

`E2E_BROWSER_CHANNEL=msedge` 可改用系统 Edge（无需下载 Chromium）。`E2E_PYTHON` 可指定
Python 解释器；默认使用 `services/api/.venv`。`E2E_MOCK_SCENARIO` 控制 Playwright 启动的 API
使用哪个 mock 场景（默认 `backlit`，断言中会检查人物主体与模拟局限说明）。

测试产物写入 `tests/e2e/.artifacts/`（已忽略），报告写入 `playwright-report/`。
