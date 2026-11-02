# ADR-0002：开发阶段 2 决策（D-01…D-13）

- 状态：已接受（2026-11-02，用户确认全部采用审查报告推荐方案）
- 适用：开发阶段 2 —— 图像管线与非破坏编辑

## 决策

| 编号 | 采用方案 | 实施要点 |
| --- | --- | --- |
| D-01 | 阶段 2 起点引入 SQLite | 标准库 `sqlite3` + 自写 SQL 迁移运行器；只建 `image_asset / edit_session / edit_revision`；提供幂等 JSON→SQLite 导入器；阶段 3 再补分析/导出表 |
| D-02 | 新增 `redo` 与 `activate` | `edit_session.head_revision_id`；undo 沿 `parent_id` 回退，redo 沿通往 head 的路径前进；在非 head 位置提交形成分支并把 head 移到新节点 |
| D-03 | `Idempotency-Key` 幂等 | `source ∈ {initial,user,ai,reset}`；`UNIQUE(session_id, idempotency_key)`；同 key 重放返回 200 原 revision；`parentRevisionId ≠ active` → 409 `revision_conflict` |
| D-04 | 旋转取最大同比例内接矩形 | 无填充；crop 坐标定义在旋转内接后的画布；render 返回画布 `width/height` |
| D-05 | 保持阶段 1 状态码 | 无法解码/类型不符 → 415；请求体本身错误（空文件、缺字段）→ 400 |
| D-06 | 新增 `GET /previews/{previewId}` | 内容寻址、JPEG、`private, max-age`；文件位于 `data/tmp/previews/`，按 TTL 清理 |
| D-07 | 显示方向 | 已实现：登记 `exif_orientation`，`width/height` 为显示方向；阶段 2 渲染前将方向烘焙进像素 |
| D-08 | 颗粒位于锐化/降噪之后、色彩模式转换之前 | 固定管线顺序写入 `pipeline.py` |
| D-09 | 导出剥离全部元数据并嵌入 sRGB ICC | JPEG 清 EXIF/XMP/IPTC；PNG 不写 `eXIf`/文本块；JPEG 质量 ≥ 90 时 `subsampling=0` |
| D-10 | `adjustments` 是唯一渲染权威 | 渲染器不读取 `styleId/styleStrength`；风格只作为来源元数据 |
| D-11 | 前端统一两位小数，服务端严格拒绝 | 前端 `roundTo2` 并归一 `-0`；服务端拒绝超过两位小数，不四舍五入 |
| D-12 | 对外 camelCase，内部 snake_case | Pydantic `alias_generator=to_camel` + `populate_by_name=True`；DB/配方存储/日志使用 snake_case |
| D-13 | 仅本机、无鉴权 | 文档固定 `--host 127.0.0.1`；不得暴露公网 |

## 后果

- 阶段 2 的会话与 revision 具备事务性；阶段 1 的 JSON 登记表只作为导入来源保留备份。
- API 新增 409 状态码，需写入 `docs/api-contract.md`。
- 预览缓存和导出均可能占用大量磁盘/内存，需 TTL 清理与导出串行化。
- 任何像素算法或常数的改动都必须提升 `ENGINE_VERSION` 并重新生成黄金图。
