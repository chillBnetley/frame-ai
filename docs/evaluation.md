# 阶段三分析评估指南

本文件定义 FRAME AI 阶段三分析结果的人工标注集规范、评估脚本用法与指标口径。评估只测量**已标注数据上的实际表现**，不预设、不推断、不虚构准确率或成本数字。

> 当前仓库不附带人工标注图片集，也没有已测量的准确率/成本结果。在用户提供授权图片、人工标签与真实 Provider 密钥之前，正式质量指标与费用均为“未测量”。

> 本文件只覆盖阶段三的分析质量。阶段五（AI 摄影师方案）的 14 类测试图、10 维评分表、A/B/C/D 对照与失败案例分类见 [阶段五摄影方案评估表](evaluation/stage-5-evaluation.md)。

## 1. 数据集目录规范

建议把评估数据放在仓库之外，或放在不进入版本控制的目录中：

```text
eval-data/
├── manifest.json
└── images/
    ├── portrait-001.jpg
    ├── landscape-001.jpg
    └── ...
```

- `manifest.json` 中 `image` 字段使用相对 manifest 的路径。
- 支持格式：JPEG、PNG、WebP；单张图片需满足上传限制（默认 ≤ 20 MiB、≤ 40 MP）。
- 图片必须获得使用授权。评估脚本只上传到本机 API，不直接发送到第三方。
- 不要在评估集目录中存放密钥或个人信息清单。

## 2. manifest schema

```json
{
  "dataset": "stage3-human-labels",
  "version": "2026-11-03",
  "notes": "10 类场景，室内外人像与风光为主。",
  "cases": [
    {
      "id": "portrait-001",
      "image": "images/portrait-001.jpg",
      "expected": {
        "scene": {
          "primary": "portrait",
          "secondary": ["indoor"]
        },
        "subjects": ["person"],
        "lighting": {
          "direction": "side",
          "type": "natural"
        },
        "issues": ["underexposure", "highlight_clipping"]
      }
    }
  ]
}
```

约束：

- `cases` 必须是非空数组，`id` 唯一，`image` 必须存在且扩展名受支持。
- `expected` 至少包含一个标签字段。
- `scene.primary`、`scene.secondary`、`subjects`、`lighting.direction`、`lighting.type`、`issues` 均可按需省略；省略的字段不参与该项评分，输出为 `null`。
- `subjects` 是主体类型的字符串数组。当前评估只比较**类型集合**，不评估 bbox IoU 或角色。
- `issues` 是问题类型的字符串数组，评估集合级 precision/recall/F1。
- 脚本对未知字段直接报错，避免拼写错误导致指标被静默跳过。

枚举取值与 `shared/contracts/openapi.json` 一致：

- 场景：`portrait`、`landscape`、`street`、`architecture`、`night`、`indoor`、`food`、`nature`、`other`
- 主体：`person`、`building`、`sky`、`road`、`plant`、`animal`、`food`、`vehicle`、`other`
- 光线方向：`front`、`side`、`back`、`side_back`、`diffuse`、`overcast`、`artificial`、`mixed`、`unknown`
- 光线类型：`natural`、`artificial`、`mixed`、`unknown`
- 问题类型：见 `docs/api-contract.md` 的 `IssueType`。

## 3. 运行评估

先启动本机 API（脚本通过 HTTP 调用真实任务流程）：

```bash
services/api/.venv/Scripts/python.exe -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000
```

然后在仓库根目录运行：

```bash
services/api/.venv/Scripts/python.exe scripts/eval_analysis.py \
  --manifest eval-data/manifest.json \
  --output eval-data/result.json
```

可选参数：

- `--api-url`：默认 `http://127.0.0.1:8000`。
- `--timeout`：单个用例等待分析完成的上限，默认 120 秒。
- `--poll-interval`：状态轮询间隔，默认 0.5 秒。

脚本对每个用例执行：上传原图 → 创建分析任务（`force=true`，避免复用旧结果）→ 轮询至 `completed`/`failed` → 与标签比较。

### 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 全部用例完成并已评分 |
| 1 | 至少一个用例失败（上传、超时或分析失败）；已完成用例仍会输出指标 |
| 2 | manifest 缺失/非法、图片缺失，或 API 不可达；不输出任何指标 |

## 4. 指标口径

| 指标 | 定义 |
|---|---|
| `scenePrimaryAccuracy` | 主场景完全匹配的比例 |
| `sceneSecondaryExactMatchAccuracy` | 次要场景集合完全一致的比例 |
| `subjectMicroPrecision/Recall/F1` | 跨用例汇总的主体类型集合 P/R/F1；`TP=预测∩标签` |
| `lightingDirectionAccuracy` | 光线方向完全匹配的比例 |
| `lightingTypeAccuracy` | 光线类型完全匹配的比例 |
| `issueMicroPrecision/Recall/F1` | 跨用例汇总的问题类型集合 P/R/F1；`TP=预测∩标签` |
| `latencySeconds` | 从创建任务到终态的实际耗时（含排队）；输出 mean/p50/p95/max |

- 所有指标保留 4 位小数；某项没有带标签的用例时输出 `null`，不会用 0 或猜测值填充。P 与 R 同时为 0 时 F1 记为 0。
- `summary.mock` 明确区分 Mock 与真实 Provider 用例数。若全部结果来自 Mock，`warnings` 会注明“指标只验证流程，不代表真实模型质量”。
- 每个用例的 `predicted` 只包含场景、主体类型、光线方向和问题类型；不写入证据全文、图片或 Provider 原始响应。

## 5. 真实 Provider 冒烟验证

`scripts/smoke_live_provider.py` 在不写数据库的情况下跑通“视觉模型 → 特征 → 候选诊断 → 决策模型”，用于确认真实 Provider 的鉴权、schema 兼容性与延迟。

需要设置以下环境变量（或写入 `.env`）：

```text
FRAME_VISION_PROVIDER=openai
FRAME_VISION_API_KEY=...
FRAME_VISION_MODEL=...
FRAME_VISION_API_BASE_URL=https://...
FRAME_DECISION_PROVIDER=openai
FRAME_DECISION_API_KEY=...
FRAME_DECISION_MODEL=...
FRAME_DECISION_API_BASE_URL=https://...
```

运行：

```bash
services/api/.venv/Scripts/python.exe scripts/smoke_live_provider.py
```

- 未配置时输出 `SKIPPED` 并以 0 退出；`--require-live` 会让未配置变成退出码 2。
- `--image path/to/photo.jpg` 可指定图片；默认生成一张本地合成测试图。
- 脚本只输出 provider/model 名称、各阶段耗时、主体/问题/建议数量，不输出 prompt、图片字节、Base64、密钥或原始响应。
- 该脚本验证连通性，不代表画面理解质量；质量需要第 3 节的标注集评估。

## 6. 尚未测量的内容

以下项目必须有真实数据与密钥后才能给出数字，当前一律视为未测量：

- 真实视觉/决策模型在 10 类场景上的人工评估准确率。
- 问题检测与建议质量的正式 precision/recall/F1。
- 单次分析的 token 用量与费用。
- 真实 Provider 在目标网络环境下的 p95 延迟。

`.env`、评估结果与标注图片不得提交到版本库。