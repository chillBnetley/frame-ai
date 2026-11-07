# 阶段五摄影方案评估表

本文件是 FRAME AI 阶段五（AI 摄影师与智能后期决策系统）的人工评估规范：14 类测试图（任务书 §15.1）、功能检查（§15.2）、10 个维度 1–5 分评分表（§15.3）、A/B/C/D 对照实验（§15.4）、稳定性（§15.5）、失败案例分类，以及逐图记录模板。

> **当前状态（2026-11-06）**
> 自动化回归集已建立并通过：`services/api/tests/test_photographer_regression.py`，14 个场景夹具 + 5 类共享不变量 + 逐场景行为断言 + 3 个负面用例，共 **33 项**。
> **真实照片人工评分：未评估（待补）**。仓库不附带授权照片集，也没有人工评分记录；在用户提供照片、授权与评分人之前，本文件 §4–§7 的所有分数栏位保持空白，不得填写推断值。

## 1. 口径与诚实原则

1. **“AI 成功返回 JSON”不等于“方案合理”**（任务书 §十五）。协议层的通过与否由自动化测试覆盖；方案是否成立只能由 §4 的人工评分与 §5 的对照实验得出。
2. **用户接受 ≠ 客观更优**（任务书 §十四）。接受/拒绝/修改/重置只是行为统计，任何“质量提升”“更好”的结论都不得由接受率推出。后端汇总响应本身携带三条 disclaimer，前端反馈区固定展示其中第一条（见 §8）。
3. **mock 与真实 Provider 必须分开**。当前所有自动化结果均来自 `mock-planner`（`prompt_version = stage5-planner/1`），只能证明流程与规则边界，不能代表模型效果。每条记录都必须写明 `provider` / `model` / `is_mock` / `degraded`。
4. **未测量的指标一律写“未评估/待补”**，不预设目标数字（例如“接受率 ≥ 80%”“评分 ≥ 4.0”）。本文件给出的是记录方法与判定口径，不是承诺的结果阈值。

## 2. 14 类测试图（任务书 §15.1）

每一类建议在真实照片中至少准备 3 张（同场景、不同曝光/光比），逐张按 §4 模板记录。

“期望行为”列同时是回归夹具的断言口径；括号内的参数值是 `mock-planner` 在默认偏好（自然度 0.7、调整强度 0.5、允许风格化=false、保留原始色彩=true）下的实际输出，可在 `services/api/tests/test_photographer_regression.py` 中复现。数值会随偏好与真实 Provider 变化，**不作为人工评估的判分依据**，人工判分只看 §4 的维度描述。

| # | 类别 | 关键风险 | 期望行为 | 回归夹具 key |
|---|---|---|---|---|
| 1 | 正常人像 | 没病乱投医 | 不产生任何参数改动；识别为“已较平衡”，方向强度压到 ≤0.3；模型若额外提参数则忽略并告警 | `portrait_balanced` |
| 2 | 逆光人像 | 只提主体或只压背景 | 背景高光回收 + 主体暗部lift 同时成立，曝光只做微幅（highlights −11、whites −4、shadows +6、exposureEv +0.07）；两个问题都以真实 issue/region 为证据 | `portrait_backlit` |
| 3 | 室内人像 | 把现场暖光当色偏硬纠 | 只在测量色偏超过阈值（\|cast\| ≥ 0.08）时校正，且幅度受“保留原始色彩”上限约束（temperature −6.5，\|Δ\| ≤ 8） | `portrait_indoor` |
| 4 | 风光 | 用几何操作“修”地平线 | 只动 highlights / vibrance / clarity；地平线倾斜仅作为诊断证据呈现，不改 `rotationDeg`、不加裁剪 | `landscape` |
| 5 | 日落 | 冷化暖调、天空死白 | 色温保持不动（0.0），保留暖色环境约束；天空高光回收（highlights −17、whites −6） | `landscape_sunset` |
| 6 | 夜景 | 把暗调强行提亮 | 低基调保护：曝光不动（上限 +0.2）、阴影温和（≤6）、只加降噪（denoise +17） | `night` |
| 7 | 建筑 | 锐化过头、越界裁剪 | 细节恢复（sharpen +9、clarity +4.88）且 `sharpen ≤ 100`；`crop` 保持为空 | `architecture` |
| 8 | 街头 | 构图问题被当作像素任务 | 三个构图问题全部记录为证据，但不产生裁剪/旋转；只允许克制的对比与清晰度（+1.62） | `street` |
| 9 | 高反差 | 机械压低反差 | 已判定为高反差的画面把“强反差”视为创作选择：不生成任何改动 | `high_contrast` |
| 10 | 低饱和度 | 强行抬饱和 | 不产生改动，饱和度/自然饱和度保持 0 | `low_saturation` |
| 11 | 高饱和度 | 越推越艳 | 只降不升：saturation −1.95、vibrance −0.33，且绝不出现正向饱和改动 | `high_saturation` |
| 12 | 混合光源 | 单一白平衡抹平现场光 | 无强测量色偏时不强制中性化：temperature/tint 保持 0，色温不一致作为“可能问题”而非“已确认”呈现 | `mixed_light` |
| 13 | 特意低调的照片 | 提亮毁掉暗调 | 曝光保持 0，阴影 ≤6、黑位 ≤4 的温和恢复，并标注低调意图 | `low_key` |
| 14 | 已完成后期的照片 | 在成片上重复处理 | 在用户既有配方上叠加：highlights −45 → −59，用户已有的阴影、对比、裁剪、旋转、曲线、蒙版、局部调整、输出设置逐项保持 | `already_edited` |

### 2.1 数据集放置

评估数据放在仓库之外或不进入版本控制的目录：

```text
eval-data/stage5/
├── manifest.json
├── images/<category>-001.jpg
├── renders/<case-id>-<arm>.png      # A/B/C/D 四臂成图
└── results/<日期>.csv
```

- 图片必须获得使用授权；`manifest.json` 不存放密钥、姓名等个人信息。
- 每条 case 记录：`id`、`category`（§2 的 14 类之一）、`image`、可选的 `notes`（拍摄条件）。
- 评估过程只把图片上传到本机 API；是否调用真实 Provider、会向第三方发送什么，遵循 §9。

## 3. 功能检查（任务书 §15.2）

| 检查项 | 自动化位置 | 人工复核方式 |
|---|---|---|
| 能获得视觉分析结果 | `services/api/tests/test_photographer_service.py`、`test_photographer_plan_api.py` | 上传后方案面板显示 `analysisId` 对应的诊断 |
| 场景识别正确 | `test_photographer_diagnosis.py`、`test_photographer_rules.py` | 对照照片实际场景，记失败码 `F01` |
| 生成结构化方案 | `test_photographer_models.py`、`test_photographer_service.py`（模型输出不可解析 → 确定性规则回退）、`test_photographer_plan_api.py`（`degraded` 标识） | 面板出现方向/诊断/参数/理由，`degraded` 标识符合实际 |
| 映射到阶段四配方 | `test_photographer_generator.py` | 接受后编辑面板滑杆/曲线/局部实际变化 |
| 通过参数校验 | `test_photographer_generator.py`、`test_photographer_regression.py`（范围/蒙版/证据/最小修改） | 无“参数越界”报错；越界草稿被裁剪而非落库 |
| 生成预览 | `apps/web/tests/*.test.tsx`、Playwright 编辑器流程 | 接受前预览与接受后成图一致 |
| 显示调整原因 | `apps/web/tests/photographer-panel.test.tsx` | 每条改动都有可读理由与证据引用 |
| 响应自然语言修改 | `test_photographer_patch.py`、`test_photographer_chat_api.py`、`apps/web/tests/use-photographer-chat.test.tsx` | 指令只改被要求的参数，未提及参数保持 |

## 4. 摄影质量评估表（任务书 §15.3）

10 个维度，逐项 1–5 分。分数锚点固定如下，评估人不得自行放宽：

| 维度 | JSON 键 | 评价内容 | 1 分 | 3 分 | 5 分 |
|---|---|---|---|---|---|
| 曝光 | `exposure` | 是否改善主要曝光问题 | 明显变糟（过曝/欠曝加重或裁切增加） | 主曝光持平 | 主要曝光问题解决且无新裁切 |
| 色彩 | `color` | 是否保留合理色彩关系 | 色彩关系被破坏（串色、断层） | 关系未破坏但无改善 | 关系更清楚且忠于现场 |
| 肤色 | `skinTone` | 是否自然 | 明显发灰/发红/塑料感 | 可接受但略假 | 自然，保留纹理与层次 |
| 高光 | `highlights` | 是否保留可用细节 | 高光进一步死白 | 持平 | 死白恢复且未发灰 |
| 阴影 | `shadows` | 是否保留层次 | 暗部糊死或发灰 | 层次略少 | 层次恢复且不发雾 |
| 主体 | `subject` | 是否更突出 | 主体更弱或与背景混淆 | 突出度持平 | 主体明显更突出 |
| 局部调整 | `localAdjustment` | 是否准确 | 局部作用在错误区域/边界可见 | 区域正确但边缘生硬 | 区域与羽化都恰当 |
| 风格 | `style` | 是否符合用户选择 | 与所选风格相反 | 沾边但弱 | 与所选风格一致且克制 |
| 自然度 | `naturalness` | 是否存在过度处理 | 明显 HDR 味/涂抹/光晕 | 近看可见处理痕迹 | 看不出被机器处理过 |
| 创作意图 | `creativeIntent` | 是否保留原有表达 | 刻意效果被“纠正”掉 | 保留大半 | 完全保留并强化原意 |

判分规则：

- 每个维度独立打分；不适用（例如无人像的“肤色”）记 `null` 并在“问题说明”写明原因，不得记 0 或 3 顶替。
- 打分前先看 A（原图），再看待评成图，避免“因为动了参数所以更好”的锚定偏差。
- 两位评估人分差 ≥ 2 的维度必须复评并记录结论。

### 4.1 单图记录模板（任务书 §15.3 要求的六项）

```markdown
### case: <id> （类别：14 类之一）

- 原图：images/<file>（尺寸、拍摄条件一句话）
- AI 方案：
  - provider / model / promptVersion：mock / mock-planner / stage5-planner/1
  - isMock / degraded：true / false
  - 场景与方向：<scene.primary> → <direction.name>（强度 <direction.strength>）
  - 诊断：已确认 <n> 项 / 可能 <n> 项 / 创作选择 <n> 项（列 issueId 与证据）
  - 参数改动：`exposureEv 0.00 → +0.07`、`highlights 0.00 → -11.00` …（逐条列，含 reason）
  - 方案给出的警告与局限：原文照抄
- AI 处理结果：renders/<id>-C.png（渲染编码版本，例如 frame-engine/10）
- 人工调整结果：renders/<id>-D.png + 手改了哪些参数（`path: C 值 → D 值`）
- 评价（1–5，不适用记 null）：
  exposure / color / skinTone / highlights / shadows / subject / localAdjustment / style / naturalness / creativeIntent
- 问题说明：
  - 失败码（§6，可多个）+ 一句话事实描述；没有则写“无”
  - 复现方式（同一 case 重新请求一次的差异）
```

## 5. A/B/C/D 对照实验（任务书 §15.4）

同一张图片比较四臂：

| 臂 | 内容 | 在本产品中如何产生 |
|---|---|---|
| A | 原图 | 不应用任何配方（默认 `EditRecipe`）直接渲染 |
| B | 普通固定参数优化 | 一套**不读取诊断**的手动固定参数，整轮评估保持不变。建议起始值：`exposureEv +0.2`、`contrast +10`、`highlights −10`、`shadows +10`、`vibrance +6`。这是评估协议，不是产品功能，不得写进代码或文案 |
| C | AI 自动优化 | `POST /ai/photographer/plan`（`mode=auto`，不选风格）→ 接受方案 → 渲染 |
| D | AI 自动优化后人工微调 | 在 C 之上由评估人自由微调后另存 |

流程要求：

1. 四臂输出同尺寸、同色彩空间、同编码版本，导出时不写文件名提示。
2. **盲评**：去掉 A/B/C/D 标签、随机顺序；同一轮内评估人不参与该轮方案生成。
3. 逐维度比较 `A→C`、`B→C`、`C→D` 三组，记录每张图的差值而不是平均值。
4. 结论口径示例：“在 n=3 张夜景图上，`highlights` 维度中位分 A/B/C/D = 3/3/4/5”。样本不足或分数缺失时写“未评估/待补”，不得给出总体提升百分比。
5. 当前状态：**未评估**（无授权照片集，四臂均未产出成图）。

## 6. 稳定性测试（任务书 §15.5）

要求：同一张照片、相同输入与相同模型版本应尽量得到稳定且可解释的结果。

- **mock 路径**：已由 `test_plans_are_reproducible_for_the_same_analysis` 断言 14 个场景两次运行的配方逐字段相同。
- **真实 Provider 路径**（待补）：
  1. 固定 `provider` / `model` / `promptVersion` / 采样参数（temperature、top_p），并写入记录。
  2. 同一张图连续运行 3 次，逐次记录：改动路径集合、每条 delta、诊断项数量。
  3. 记录三项差异指标：路径集合是否一致、同一路径 delta 的极差、方向 id 是否变化。
  4. 出现波动时按 §7 记 `F10`（输出不可解析→降级）或 `F06`（改动幅度异常），并把输入与分析结果一并存档。
- 本轮只记录差异，不预设“波动阈值”；阈值需在真实集跑通后与产品负责人共同确定。当前状态：**未评估**（无真实 Provider 运行条件）。

## 7. 失败案例分类

每个失败案例必须记录：案例 id、失败码、一句话事实描述、复现输入、期望与实际、归属模块。严重度：`S` 阻断使用、`A` 明显错误、`B` 可用但欠佳。

| 码 | 名称 | 判定线索 | 归属模块 |
|---|---|---|---|
| F01 | 场景/主体误判 | 阶段三场景或主体与实际不符，导致方向选错 | 视觉分析（阶段三） |
| F02 | 证据缺失 | 诊断成立但没有可指认的测量/区域依据 | `app/photographer/diagnosis.py` |
| F03 | 证据编造 | 引用了不存在的 issueId / regionId / maskId | `app/photographer/validator.py`（回归集已断言会被拒） |
| F04 | 参数越界 | 草稿越出引擎区间；记录是被裁剪还是报错 | `validator.clamp_adjustment` / `generator` |
| F05 | 创作意图被机械纠正 | 低调/高反差/暖光/低饱和被“修好” | `rules._protect_creative_choices` / `validator.enforce_conflicts` |
| F06 | 最小修改违背 | 无关参数被改动，或改动条数明显偏多 | `app/photographer/generator.py` |
| F07 | 局部调整错位 | 蒙版选错、边界生硬、使用了 v1 不支持的字段 | `generator._merge_local_adjustments` |
| F08 | 风格不符 | 与用户所选风格/强度不一致，或强度语义错误 | `app/photographer/styles.py` |
| F09 | 过度处理 | 自然度维度 ≤ 2：HDR 味、涂抹、光晕、色带 | 配方幅度与引擎呈现 |
| F10 | 输出不可解析 / 降级 | `degraded=true`、回退到确定性规则方案 | `service.plan` 回退链 |
| F11 | 指令理解偏差 | 自然语言只改对了部分参数，或动了未提及参数 | `app/photographer/patch.py` |
| F12 | 点评空泛或失据 | 点评与图无关、无证据引用、建议无法执行 | `app/photographer/critique.py` |
| F13 | 预览/成图异常 | 预览与接受后结果不一致、闪烁、空白帧 | 前端预览与引擎 |
| F14 | 性能/超时 | 方案、预览或导出耗时超出预期 | `service` 并发与渲染层 |
| F15 | 其他 | 不属于以上任一类的观察，必须写清现象 | 视情况 |

统计口径：按类别与失败码计数，附案例链接。`F10` 的降级率可以报告为“本轮 n 张中 k 张降级”，但不得换算成质量结论。

## 8. 偏好记录与质量评分的边界（任务书 §十四 / §14.1）

系统当前记录的内容（`POST /ai/photographer/feedback`，无自由文本字段）：

| 字段 | 语义 |
|---|---|
| `sessionId` / `imageId` | 反馈归属，级联删除的锚点 |
| `action` | `accepted` / `rejected` / `modified` / `reset` |
| `source` | `plan`（自动方案）/ `chat`（对话调整）/ `critique`（点评应用） |
| `planId` | 该决策针对的方案或补丁；点评应用不带 id |
| `revisionId` | 决策落地后的活动版本；`rejected` 不允许携带 |
| `changedPaths` | 服务端计算的差异路径（基线见下） |
| `rubric` | 可选人工评分，10 个维度、每项 1–5、可留空 |
| `isMock` / `degraded` | 该次方案来自 mock 还是真实 Provider，是否走了回退链 |

行为语义：

- `modified` **由服务端派生**：客户端只能提交 `accepted`，若接受后的最终配方与方案配方不一致，记录自动升级为 `modified`。
- `changedPaths` 基线：带 `planId` 时以该方案配方为基线；否则以该 revision 的父 revision 为基线。`reset` 因此记录的是“重置这一步移动了哪些参数”。
- 幂等：同一 `(planId, action)` 只有一行，补写评分（如接受后再提交 `rubric`）更新原行并返回原行 id，不新增记录，因此计数不会因为反复评分而虚高；不带 `planId` 的行（`reset`）各自独立。
- 录入路径：接受方案后弹出 10×5 的可选评分对话框（portal 挂到 `document.body`，因此不受工作区卡片 `backdrop-filter` 的定位影响）；`Esc` 与“跳过”等价——决策已经记录，只是不带 `rubric`。评分提交失败时对话框保留输入，并在反馈记录里提供重试。
- 汇总：`GET /ai/photographer/feedback`（可按 `sessionId` / `imageId` / `planId` 过滤，`limit ≤ 200`）的响应固定携带 `summary`，它对本次扫描窗口（上限 500 条）给出动作计数、`bySource` 计数、`mockCount` / `realCount` / `degradedCount`、`ratedCount`、参数变化频率 `changeFrequency`、维度均分 `rubricAverages`，以及固定三条 disclaimer。
- 汇总响应与前端文案都不输出“质量提升”类结论；固定 disclaimer 原文：
  1. “接受、拒绝、修改与重置只记录用户行为，不代表方案在客观质量上更优。”
  2. “评分是人工主观打分，没有质量基准校准，也不与自动指标混用。”
  3. “mock 分组来自模拟 Provider，只用于流程验证，不能代表真实模型效果。”

因此：**偏好（§8 的行为记录）与质量（§4 的人工评分 + §5 的对照）是两套数据**，不得互相替代，也不得由前者推算后者。

## 9. 隐私原则（任务书 §14.1）

- 用户原图默认不用于训练；当前仓库内没有任何训练流程。
- 反馈记录不保存原图、不保存指令原文；请求体结构上就没有自由文本字段。
- 只有真实 Provider 调用才会把图片数据发给第三方；调用前必须明确告知并取得同意。默认 mock 不联网。
- API 密钥只在服务端；`GET /settings/providers` 只回显 `hasApiKey` / `apiKeySource`，永不回显密钥本身，前端也不持有密钥。
- 日志不记录图片内容，只记录 id、耗时、错误码。
- 用户可管理自己的记录：单条删除 `DELETE /ai/photographer/feedback/{feedback_id}`（204），图片/会话删除时反馈级联清除。
- 评估数据（照片、评分 CSV）留在仓库之外，manifest 不含密钥与个人信息。

## 10. 运行方式

```bash
# 14 类回归集（快速）
cd services/api && .venv/Scripts/python.exe -m pytest tests/test_photographer_regression.py -q

# 全部门槛（后端 ruff/mypy/pytest + 前端 lint/typecheck/test/契约/构建 + OpenAPI 同步 + Playwright）
services/api/.venv/Scripts/python.exe scripts/verify.py
```

评估轮次的产出写到 `eval-data/stage5/results/<日期>.csv`，并把 §4.1 模板的 Markdown 汇总粘贴到 `STAGE_5_*` 报告；本文件只维护方法与已验证事实。

## 11. 覆盖与待补清单

| 项 | 状态 |
|---|---|
| 14 类场景夹具 + 结构化/范围/蒙版/最小修改/无编造断言 | 已完成（33 项，全绿） |
| 越界草稿被裁剪而非落库 | 已完成（负面用例） |
| 编造 maskId / 编造证据引用被拒 | 已完成（负面用例） |
| 同输入结果可复现（mock） | 已完成 |
| 反馈可记录 / 可查询 / 可删除 / 级联 | 已完成（API 与服务层测试） |
| 评分对话框的真实浏览器可用性（视口居中、评分落库、拒绝与待重发重试） | 已完成（2026-11-06 Playwright 7 项 + 手工实测；Escape 即“跳过”，决策仍保留） |
| 评分维度完整性与 1–5 范围 | 已完成（模型约束 + 前端 10×5 单选结构测试） |
| 不把接受等同于质量提升 | 已完成（汇总 disclaimer + 前端文案断言） |
| 14 类真实照片 × §4 评分 | **未评估（待用户照片与授权）** |
| §5 A/B/C/D 四臂对照 | **未评估（依赖真实照片集）** |
| §6 真实 Provider 稳定性（3 次重复） | **未评估（依赖真实 Provider 与上传同意）** |
| §7 失败案例分类的实际计数 | **未评估（尚无真实轮次记录）** |
