# 前后端契约

- `openapi.json` 由后端导出：`python -m app.tools.export_openapi`。
- 前端类型由 `openapi-typescript` 生成到 `apps/web/types/api.d.ts`。
- `scripts/verify.py` 会重新导出并生成到临时目录，与已提交文件比较；不一致即失败。

修改后端路由或响应模型后，运行：

```bash
cd services/api
.venv/Scripts/python.exe -m app.tools.export_openapi
cd ../../apps/web
npm run types:api
```
