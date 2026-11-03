# ADR-0003：前后对比的“原图”应用几何变换

- 状态：已接受并实现（2026-11-03，阶段 2.1 审查 R2-06）
- 适用：`GET /api/v1/sessions/{sessionId}/compare` 与前端前后对比视图
- 相关文档：[API 契约](../api-contract.md)、[ADR-0002](ADR-0002-phase-2-decisions.md)、[阶段 2.1 交接](../handoff/phase-2.1.md)

## 背景

任务书 §7.5 要求对比时“原图不含任何编辑”。但 revision 可能包含旋转与裁切：若“原图”始终是未裁切的整图，两侧宽高比不同；前端容器按编辑版比例显示并用 `object-fill`，未裁切的原图会被拉伸，分割线两侧既不对齐也变形。

## 决策

“原图”一侧改为**仅应用 revision 的几何变换**（`rotationDeg` 与 `crop`），不做任何色调、色彩、细节调整：

- 后端 `RenderService.compare` 用 `EditRecipe(adjustments=Adjustments(rotation_deg=..., crop=...))` 走与编辑版相同的 `render()` 管线，`maxEdge` 一致，复用内容寻址缓存。
- 两张图因此尺寸相同，对比的是“调整效果”，而不是“裁切效果”。
- 前端文案改为“左侧：原图（仅应用旋转/裁切），右侧：编辑版本”；若两侧宽高比差异超过 1%，回退到 `object-contain` 并提示，避免任何拉伸。
- 移除旧的 `_original_preview` 路径。

## 理由

- 像素严格对齐，分割线两侧的同一物体位置重合。
- 只多一次几何渲染请求，且与裁切模式已有缓存可复用。
- 仍满足“对比能看出调整前后的差异”的核心目的。

## 后果

- 这是对任务书 §7.5 字面表述的有意偏离；“原图”不再是完全未编辑的代理图，而是几何归一后的基准图。
- API 形状不变（仍返回两个 `previewUrl/width/height`），文档与测试同步更新。
- 已由 `services/api/tests/test_compare_export_api.py` 的几何对比用例与 `apps/web/tests/compare-view.test.tsx` 的宽高比回退用例覆盖。
