# API 契约

`openapi.json` 是阶段 1.1 的稳定接口契约，由 FastAPI 应用生成：

```bash
cd services/api
.venv/Scripts/python.exe scripts/export_openapi.py          # 重新生成
.venv/Scripts/python.exe scripts/export_openapi.py --check  # 检查是否过期
```

前端类型由 `openapi-typescript` 生成，不要手改 `apps/web/types/api.d.ts`：

```bash
cd apps/web
npm run gen:api    # 重新生成
npm run check:api  # 检查是否过期
```

`apps/web/types/image.ts` 只从生成类型中导出别名，手写的只有 `ApiStatus` 与 `UploadError` 这类非契约类型。
