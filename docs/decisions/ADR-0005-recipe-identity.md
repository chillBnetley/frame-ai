# ADR-0005：Revision 身份与配方哈希口径（v2.1）

- 状态：已接受并实现（2026-11-05，阶段三/四复审整改 G5-D5-a）
- 适用：`services/api/app/models/recipe.py`（`canonical_recipe_json` / `pixel_recipe_json` / `recipe_hash`）、`services/api/app/repositories/session_repo.py`、所有写入 revision 的路径
- 相关文档：[架构](../architecture.md)、[API 契约](../api-contract.md)、[已知问题](../known-issues.md)、[整改计划](../plans/stage-3-4-review-remediation.md)、[ADR-0002](ADR-0002-phase-2-decisions.md)

## 背景

修复前的 `canonical_recipe_json` 直接 `model_dump` 整个 `EditRecipe`，因此 revision 身份包含 `output`（导出格式/质量/色彩空间）、`style_id` 与 `style_strength`。这三者对像素完全惰性：

- `output` 来自每次导出请求，渲染管线从不读取配方里的 `output`；`pixel_recipe_json` 早已把它排除。
- `style_id` / `style_strength` 在 `app/` 内没有任何读取点，引擎尚未应用风格。

后果是改一次导出格式就会追加一个“像素完全相同”的 revision，污染撤销栈与历史摘要。P3-5 要求把三者移出身份。同时 P2-1 已确认 `schema_version` 参与哈希：从 `1.0` 重标到 `2.0` 会改变同一旧配方在新代码下算出的摘要，因此“旧 revision 哈希逐字节不变”从未成立。

## 决策

### D1 身份只覆盖影响像素或影响解释的字段

`canonical_recipe_json` 在 `model_dump` 之后显式移除：

- `output`
- `style_id`
- `style_strength`

保留在身份中的字段：

- `schema_version`（决定字段语义，必须参与）
- `adjustments`（含规范化后的 `crop`）
- `curve`、`hsl`、`color_grading`
- `masks`（非空时；空 `masks` 被省略，是唯一的惰性省略）
- `local_adjustments`
- `rationale`、`warnings`（当前仍参与 canonical 哈希；它们不含像素语义，但改动会改变摘要——这是已知口径，未在本轮扩大修改面）

`pixel_recipe_json`（供 `render_key` / 预览缓存）继续只含像素字段，与 canonical 的差异保持不变。

### D2 哈希口径命名为 v2.1

阶段四之后，revision 身份的哈希口径为 **v2.1**：

- 同一配方在 v2.1 实现下重复计算结果稳定；
- 与 v2.0（阶段四 Task 1 的 `schemaVersion:"2.0"` + 含 style/output 的 canonical）**不承诺相等**；
- 旧 revision 的 `recipe_hash` 列只是缓存。`reset`、幂等命中等比较路径都通过 `_current_recipe_hash` 从已存 `recipe_json` 用当前代码重算，因此升级不会让旧会话“看起来不同”，只会得到当前口径下的摘要。

### D3 不新增数据库迁移

不重写历史 `recipe_hash` 列。读取路径已经是“重新推导并比较”，缓存与新口径不一致时按当前值处理；写入路径写入当前口径。这样避免一次性迁移全部历史行，也避免在迁移脚本里复制一份哈希实现。

## 影响

- 只修改 `output` / `styleId` / `styleStrength` 不再产生新 revision；修改任一像素字段仍会产生新 revision。
- `render_key` 与预览缓存键本就不含这三项，行为不变。
- 已存 revision 的摘要值在读取时按 v2.1 重算；依赖“历史摘要恒定”的外部假设（无已知调用方）不再成立，文档已如实标注。
- 黄金图不涉及 identity，无需重生成；像素语义变化由 G5 的引擎版本 bump 单独负责。

## 验证

- `tests/test_recipe.py::test_revision_identity_ignores_output_and_style_fields`：仅改 output/style 时 canonical JSON 与 `recipe_hash` 完全一致。
- `tests/test_recipe.py::test_empty_masks_are_omitted_from_the_hashed_payload`：空 `masks` 不进入 canonical；默认配方与仅局部调整配方的哈希被钉死为 v2.1 实测值。
- 全量后端测试在 G7 门禁中运行，结果记录于整改计划“实施记录与偏差”。
