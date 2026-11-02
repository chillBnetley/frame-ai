# FRAME AI 阶段 2 性能测量

- 日期：2026-11-02T22:33:47+08:00
- commit：`38ee7213d322368c7fdcf82ae5a14ea53b182ac0`
- 工作区：M .gitignore,  M services/api/app/imaging/loader.py,  M services/api/app/imaging/output.py,  M services/api/app/imaging/pipeline.py,  M services/api/app/imaging/tone.py,  M services/api/app/services/preview_store.py,  M services/api/requirements-dev.txt,  M services/api/tests/test_preview_store.py,  M tests/e2e/README.md, ?? docs/performance.md, ?? package-lock.json, ?? package.json, ?? playwright.config.ts, ?? scripts/bench_render.py, ?? tests/e2e/editor.spec.ts, ?? tests/e2e/generate_fixture.py, ?? tests/e2e/global-setup.ts, ?? tests/e2e/support.ts, ?? tests/e2e/verify_export.py
- 机器：Windows-11-10.0.26200-SP0
- CPU：Intel64 Family 6 Model 198 Stepping 2, GenuineIntel（14 逻辑核）
- 内存：15.4 GiB
- Python：3.14.7；Pillow 12.3.0；NumPy 2.5.4；psutil 7.2.2
- 方法：本脚本自启单进程 uvicorn（临时数据目录），预览与导出项先热身一次，上传项直接测量；再取 20 次 p50/p95；导出 40 MP 使用 1 次 RSS 采样。

## §7.8 对照

| 项目 | 源图 | n | p50 | p95 | 目标 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| final 预览 1600 px，不含降噪 | 1 MP | 20 | 148 ms | 152 ms | p95 ≤ 500 ms | PASS |
| final 预览 1600 px，不含降噪 | 6 MP | 20 | 260 ms | 268 ms | p95 ≤ 500 ms | PASS |
| final 预览 1600 px，不含降噪 | 12 MP | 20 | 288 ms | 298 ms | p95 ≤ 500 ms | PASS |
| final 预览 1600 px，不含降噪 | 24 MP | 20 | 254 ms | 262 ms | p95 ≤ 500 ms | PASS |
| draft 预览 960 px，含降噪 | 6 MP | 20 | 186 ms | 226 ms | p95 ≤ 400 ms | PASS |
| final 预览 1600 px，含降噪 | 12 MP | 20 | 792 ms | 865 ms | p95 ≤ 2500 ms | PASS |
| 导出 24 MP | 24 MP | 20 | 1700 ms | 1725 ms | p95 ≤ 20 s | PASS |
| 单次上传 19.5 MiB 解码 | 12 MP noisy（19.2 MiB） | 20 | 239 ms | 254 ms | p95 ≤ 3000 ms | PASS |

## 导出峰值内存

| 源图 | 基线 RSS | 采样峰值 RSS | 上限 | 用时 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 40 MP | 96 MB | 1577 MB | 3072 MB | 2967 ms | PASS |

峰值 RSS 由 10 ms 间隔采样得到，统计 API 进程树（venv 启动器及其子进程）；上限取 `FRAME_EXPORT_MAX_RSS_MB`。该值包含 API 进程基线，是绝对工作集而不是增量。

## 备注

- 预览项目均检查 `cacheHit=false`，避免缓存命中污染计时。
- 导出尺寸由响应头 `X-Export-Width/Height` 核对。
- 全表总耗时 92.0 s。
- 未达标项目保留原始目标值，原因与建议见阶段 2 交接文档。
