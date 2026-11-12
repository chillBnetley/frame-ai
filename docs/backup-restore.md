# 备份与恢复

FRAME AI 的持久数据都在本机 `FRAME_DATA_DIR`（默认仓库下 `data/`）。应用没有云端账户，也没有自动备份服务；请把备份当成用户自己的责任，并定期验证。

## 备份什么

`scripts/backup_data.py` 默认复制：

- `frame.db`：通过 SQLite backup API 复制，包含 WAL 中尚未合并的内容；
- `originals/`：原图（编辑从不改写原图）；
- `masks/`、`generated/`、`generative/results/`：蒙版与生成式资产；
- `provider-settings.json`、`provider-master-key`、`onboarding.json`：模型 Provider 配置与完成标记。

默认不复制：

- `tmp/previews/`：可再生的预览与代理缓存（需要时加 `--include-previews`）；
- `tmp/exports/`：导出作业的临时结果；
- `api-token`：每次 API 启动都会轮换，备份它没有意义；
- `models/`：可重新下载的语义模型权重（需要时加 `--include-models`）。

每个备份目录都会写 `manifest.json`，记录文件大小、SHA-256、数据库版本与主要表行数，便于校验完整性。

## 创建备份

先停止写操作（建议先关闭 API，或至少不要同时导出/分析），然后：

```bash
services/api/.venv/Scripts/python.exe scripts/backup_data.py \
  --output D:/backups/frame-ai-2026-11-12
```

可用参数：

- `--data-dir <path>`：源数据目录，默认 `FRAME_DATA_DIR` 或 `<repo>/data`；
- `--include-previews` / `--include-models`：包含再生缓存或模型权重；
- `--verify <backup>`：只校验已有备份，不创建新备份。

目标目录必须不存在，脚本不会覆盖已有备份。

## 校验备份

```bash
services/api/.venv/Scripts/python.exe scripts/backup_data.py --verify D:/backups/frame-ai-2026-11-12
```

校验会逐文件重新计算 SHA-256，并对复制出的数据库执行 `PRAGMA integrity_check`。任何缺失、大小或哈希不一致都会返回非 0。

## 恢复

1. 关闭 API 与前端进程。
2. 把现有数据目录整体改名保留（例如 `data -> data.before-restore`），不要就地覆盖。
3. 把备份目录内容复制回 `FRAME_DATA_DIR`，保留 `frame.db`、`originals/` 与配置文件在同一层。
4. 启动 API。迁移会按 `schema_migrations` 继续执行；如果备份来自更高版本，应用会拒绝启动，请使用对应版本的代码。
5. 打开一张图片确认原图与历史可见；如需清理解析/预览缓存，可运行 `scripts/purge_orphans.py`（默认 dry-run）。

### Provider 密钥

- `provider-settings.json` 中的 API Key 是 AES-256-GCM 密文，主密钥由 Windows DPAPI / macOS Keychain / POSIX `0600` 文件保护。
- **两个文件必须成对恢复**；DPAPI 主密钥通常无法在另一台机器或另一个用户下解开。换机后最稳妥的做法是删除这两个文件并重新输入 API Key。
- 备份脚本会提示“只有 settings 没有 master key”的配对风险，但不会导出明文密钥。

## 建议

- 在每次大批量导入/删除、升级版本前创建一次备份，并至少保留最近 3 份。
- 定期执行 `--verify`；备份文件损坏比没有备份更危险。
- 删除是硬删除，没有回收站；备份是误删后唯一的恢复途径。
