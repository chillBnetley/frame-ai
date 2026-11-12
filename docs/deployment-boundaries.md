# 部署边界

本文说明 FRAME AI 当前支持的部署形态与明确不支持的能力，避免把本地单机版本误当作可公网多用户服务。

## 支持形态：本机单实例

| 项目 | 约束 |
| --- | --- |
| 进程 | 一个 API 进程 + 一个 Next.js 进程（开发用 `next dev`，生产用 `next build && next start`） |
| 绑定地址 | API 默认 `127.0.0.1:8000`，仅本机；前端默认 `:3000`/自定义端口 |
| 数据库 | SQLite（WAL），单进程写；无跨进程锁 |
| 文件存储 | 本机 `FRAME_DATA_DIR`；原图、预览、导出、生成式资产都在该目录 |
| 鉴权 | 本机访问令牌：API 每次启动轮换 `api-token`，Next 代理逐请求注入 |
| 多用户 | 不支持；所有数据属于单一本地 owner |
| 多实例/多 worker | 不支持；分析队列、渲染槽位、导出准入都在进程内协调 |
| HTTPS | 未内置；仅本机 HTTP |

## 启动

```bash
# 后端
cd services/api
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（生产）
cd apps/web
npm run build
npm run start
```

首次启动会自动创建数据目录、SQLite 表与迁移、预览/导出目录。环境变量清单见 README。

## 数据与备份

- 升级、批量导入或删除前先备份；使用 `scripts/backup_data.py`，详见 [backup-restore.md](backup-restore.md)。
- `provider-settings.json` 与 `provider-master-key` 必须成对备份；换机通常需要重新输入 API Key。

## 对外发布前必须补齐

若要把 FRAME AI 作为对外服务部署，以下能力不在当前实现范围内：

1. 多用户身份与资源归属（当前只有本地单 owner 令牌）；
2. HTTPS 终止与安全响应头；
3. 进程守护/自动重启（systemd、Windows Service、容器编排均未提供）；
4. 错误监控与告警（当前只有本地日志）；
5. 共享存储与跨进程任务队列（当前 SQLite + 进程内队列）；
6. 限流与配额的服务端集中管理（当前为单进程内存限流）；
7. 真实 Provider 的密钥托管与费用预算策略（当前为本地加密文件 + 可选每日上限，默认不限）。

在这些能力补齐前，请只以本机单实例方式使用。
