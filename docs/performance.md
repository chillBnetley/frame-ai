# FRAME AI 阶段 2 性能测量

- 日期：2026-11-03T15:41:33+08:00
- commit：`20e862ea9a9a5109bb37a7812056492df440cca3`
- 工作区：M scripts/bench_render.py,  M services/api/tests/golden/detail__color.png,  M services/api/tests/golden/detail__detail.png,  M services/api/tests/golden/detail__neutral.png,  M services/api/tests/golden/detail__tone.png,  M services/api/tests/golden/mixed__color.png,  M services/api/tests/golden/mixed__detail.png,  M services/api/tests/golden/mixed__neutral.png,  M services/api/tests/golden/mixed__tone.png,  M services/api/tests/golden/ramp__color.png,  M services/api/tests/golden/ramp__detail.png,  M services/api/tests/golden/ramp__neutral.png,  M services/api/tests/golden/ramp__tone.png, ?? "\351\230\266\346\256\265\344\270\211.md"
- 机器：Windows-11-10.0.26200-SP0
- CPU：Intel64 Family 6 Model 198 Stepping 2, GenuineIntel（14 逻辑核）
- 内存：15.4 GiB
- Python：3.14.7；Pillow 12.3.0；NumPy 2.5.4；psutil 7.2.2
- 方法：本脚本自启单进程 uvicorn（临时数据目录），预览与导出项先热身一次，上传项直接测量；再取 20 次 p50/p95；导出 40 MP 的中性与满配方各使用 1 次 RSS 采样。
- 满配方：曝光 0.35、对比度 12、高光 -20、阴影 25、色温 8、色调 -5、饱和度 10、自然饱和度 15、清晰度 10、锐化 20、暗角 -15、颗粒 8、旋转 2°，不含降噪。
- 测量时 HEAD 为 `20e862e`（F2-02）；本文件与基准脚本随 F2-03 提交。当时工作区中的 12 张黄金图只有嵌入 ICC 的元数据差异（像素相同），已在 F2-13 固定 ICC 创建时间并重新生成全部黄金图。

## §7.8 对照

| 项目 | 源图 | n | p50 | p95 | 目标 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| final 预览 1600 px，不含降噪 | 1 MP | 20 | 172 ms | 180 ms | p95 ≤ 500 ms | PASS |
| final 预览 1600 px，不含降噪 | 6 MP | 20 | 287 ms | 293 ms | p95 ≤ 500 ms | PASS |
| final 预览 1600 px，不含降噪 | 12 MP | 20 | 312 ms | 319 ms | p95 ≤ 500 ms | PASS |
| final 预览 1600 px，不含降噪 | 24 MP | 20 | 278 ms | 305 ms | p95 ≤ 500 ms | PASS |
| draft 预览 960 px，含降噪 | 6 MP | 20 | 191 ms | 202 ms | p95 ≤ 400 ms | PASS |
| final 预览 1600 px，含降噪 | 12 MP | 20 | 843 ms | 883 ms | p95 ≤ 2500 ms | PASS |
| 导出 12 MP（中性配方） | 12 MP | 20 | 878 ms | 921 ms | 参考（§7.8 仅覆盖 24 MP） | — |
| 导出 24 MP（中性配方，下限） | 24 MP | 20 | 1779 ms | 1802 ms | p95 ≤ 20 s | PASS |
| 导出 40 MP（中性配方） | 40 MP | 20 | 2865 ms | 2968 ms | 参考（§7.8 仅覆盖 24 MP） | — |
| 导出 12 MP（满配方） | 12 MP | 20 | 5730 ms | 5906 ms | 参考（§7.8 仅覆盖 24 MP） | — |
| 导出 24 MP（满配方） | 24 MP | 20 | 11294 ms | 11594 ms | p95 ≤ 20 s | PASS |
| 导出 40 MP（满配方） | 40 MP | 20 | 19446 ms | 19631 ms | 参考（§7.8 仅覆盖 24 MP） | — |
| 单次上传 19.5 MiB 解码 | 12 MP noisy（19.2 MiB） | 20 | 255 ms | 268 ms | p95 ≤ 3000 ms | PASS |

## 导出峰值内存

| 源图 | 配方 | 基线 RSS | 采样峰值 RSS | 上限 | 用时 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| 40 MP | neutral | 99 MB | 1584 MB | 3072 MB | 2636 ms | PASS |
| 40 MP | full | 104 MB | 4700 MB | 3072 MB | 20541 ms | **FAIL** |

峰值 RSS 由 10 ms 间隔采样得到，统计 API 进程树（venv 启动器及其子进程）；上限取 `FRAME_EXPORT_MAX_RSS_MB`。该值包含 API 进程基线，是绝对工作集而不是增量。中性配方是下限；满配方（含旋转、局部调整、锐化、颗粒）才是实际最坏情况。40 MP 内存结果为**单机、单 Pillow/NumPy 版本、每种配方 1 次采样**，不是所有环境的硬保证。

按实测峰值折算：中性配方约 39.6 MB/MP（1584 / 40），满配方约 117.5 MB/MP（4700 / 40），与 12 MP、24 MP 的线性关系一致。**40 MP 满配方 4700 MB 超过默认 `FRAME_EXPORT_MAX_RSS_MB=3072`。** 因此本表同时把 24 MP 中性配方标注为“下限”，并记录 24 MP 满配方 p95 11.6 s（仍在 20 s 目标内）。F2-04 已在导出前按像素数与配方复杂度估算峰值，超限返回 413 `export_too_large`，避免进程被系统杀死；基准脚本仍可临时调高预算复测内存，但该估算是运行期保护而不是实测 RSS 硬限制。

## 备注

- 预览项目均检查 `cacheHit=false`，避免缓存命中污染计时。
- 导出尺寸由响应头 `X-Export-Width/Height` 核对。
- 全表总耗时 985.5 s。
- 未达标项目保留原始目标值，原因与建议见 [阶段 2.1 交接](handoff/phase-2.1.md) 与 [已知问题](known-issues.md)。
