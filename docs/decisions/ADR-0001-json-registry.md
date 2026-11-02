# ADR-0001：阶段 1 使用 JSON 登记表，阶段 2 迁移到 SQLite

- 状态：已接受（阶段 1.1）；阶段 2 已按此实现（见 [ADR-0002 D-01](ADR-0002-phase-2-decisions.md)）
- 日期：2026-11-02

## 背景

阶段 1 只需要保存上传图片的元数据。任务书把 SQLite 放在开发阶段 3，但阶段 2 的会话、revision、撤销/重做/重置需要事务性和有序历史。若阶段 2 继续使用 JSON 或在内存中保存会话，阶段 3 将整体重写数据层。

## 决策

阶段 1 保留 `data/image_registry.json`，但：

1. `ImageService` 只依赖 `ImageRepository` 协议（`add/get/exists/list_ids`），JSON 只是其中一个实现。
2. 写入使用进程内锁、临时文件、`fsync` 与 `os.replace`，保证单进程内读-改-写不丢更新。
3. 启动时对 `originals/` 与登记表做一致性扫描，只记录孤儿文件与悬空记录，不删除用户文件。

阶段 2 起点按审查建议 D-01 引入 SQLite（仅 `image_asset`、`edit_session`、`edit_revision` 三表）与标准库迁移运行器，并提供幂等的 JSON→SQLite 导入器；阶段 3 再补 `analysis_result` 与 `export_record`。

## 后果

- 阶段 1 的持久化能力有限，但接口边界已经稳定，SQLite 实现可替换 JSON 而不改业务编排。
- 多进程部署不支持；README 明确单进程假设。
- 迁移时必须保留原图文件与旧登记表备份，不得删除用户数据。
