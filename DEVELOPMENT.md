# 开发文档 (Development)

> 面向开发者的 API 参考、日志说明与本地开发脚本。安装与配置见 [SETUP.md](SETUP.md)。

---

## API 接口

交互式文档（Swagger UI）：<http://127.0.0.1:8000/docs>
OpenAPI Schema：<http://127.0.0.1:8000/openapi.json>

### 公开接口（无需鉴权）

#### 1. `GET /api/v1/daily/today` — 今日刊概览

```bash
curl -s "http://127.0.0.1:8000/api/v1/daily/today" \
  -H "X-Request-Id: req_$(date +%s)"
```

返回 `{issue, summary, articles[]}`。状态码：`200 ready` / `404 2002 not-generated` / `409 2003 generating`。

#### 2. `GET /api/v1/articles?type=&src=&page=&pageSize=` — 双维筛选

```bash
# Reddit + Agent 组合
curl -s "http://127.0.0.1:8000/api/v1/articles?src=reddit&type=agent&page=1&pageSize=20"
```

返回 `{items[], page, pageSize, total, appliedFilters}`。非法枚举值 → `400 1002`。

#### 3. `GET /api/v1/articles/{id}` — 条目详情

```bash
curl -s "http://127.0.0.1:8000/api/v1/articles/20260812-0003"
```

返回完整 Article（含 `lede/summary/body/quote/points/sourceUrl/...`）。不存在 → `404 2001`。

#### 4. `GET /api/v1/meta` — 信息源/类型元数据

```bash
curl -s "http://127.0.0.1:8000/api/v1/meta"
```

返回 `{sources[4], types[5]}`。供脚本与集成方使用（前端目前硬编码 chips 与开关文案）。

#### 5. `GET /api/v1/healthz` — 健康检查

```bash
curl -s "http://127.0.0.1:8000/api/v1/healthz"
```

```json
{
  "status": "ok",
  "version": "1.0.0",
  "pipeline": { "collector": "up", "summarizer": "up" }
}
```

### 写接口（需 `Authorization: Bearer <token>`）

> 令牌在 `.env` 中设置 `AIDAILY_BEARER_TOKEN`，或从启动 stdout 复制。

#### 6. `GET /api/v1/settings` — 读取偏好

```bash
curl -s "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN"
```

#### 7. `PUT /api/v1/settings` — 保存偏好（下一期生效）

```bash
curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": {"x": true, "github": false, "reddit": true, "web": true},
    "types": {"agent": true, "self_improve": true, "open_source": false, "tools": true, "commentary": true},
    "dailyPush": {"enabled": true, "time": "08:00"},
    "dailyCount": 15
  }' \
  -D -  # 显示响应头以验证 X-Effective-At
```

响应头含 `X-Effective-At: 20260813`（明日刊期生效）。**所有字段必填**（sources/types 键必须齐全，`dailyCount` 取值 `10/15/20/30`）。校验失败 → `422 1005`。

#### 8. `POST /api/v1/settings/reset` — 恢复默认

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/settings/reset" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" -D -
```

#### 9. `POST /api/v1/share` — 生成分享卡片

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/share" \
  -H "Authorization: Bearer $AIDAILY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"articleId": "20260812-0003"}'
```

返回 `{shareId, cardUrl, articleTitle}`。`cardUrl` 可在浏览器直接打开（公开页面，无需鉴权）。

### 公开分享页

```bash
# 浏览器打开 cardUrl 即可
open "http://127.0.0.1:8000/share/shr_9f2c4a71"
```

---

## 日志

| 类型   | 位置                         | 格式                                               |
| ---- | -------------------------- | ------------------------------------------------ |
| 应用日志 | `backend/logs/aidaily.log` | JSON 每行一条；含 `ts/level/logger/message/request_id` |
| 滚动策略 | 10 MB × 5 文件               | `RotatingFileHandler`                            |
| 控制台  | stdout                     | 同 JSON 格式                                        |

每条日志可选字段（按场景填充）：`source` / `issue_id` / `exception_type` / `user` / `module`。

**示例查询**（排查某次失败）：

```bash
# 按 request_id 串联请求链
grep '"request_id":"req_abc123"' backend/logs/aidaily.log

# 找出 X 源采集失败
grep '"source":"x"' backend/logs/aidaily.log | grep ERROR

# 统计今日刊期生成事件
grep '"issue_id":"20260812"' backend/logs/aidaily.log
```

---

## 开发脚本

> 所有命令在 `backend/` 目录下运行。

```bash
# 安装开发依赖（含 pytest, ruff, mypy, respx 等）
pip install -e ".[dev]"

# 跑全部测试（不含 e2e）+ 80% 覆盖率门槛
pytest --cov=app --cov-fail-under=80 --ignore=tests/e2e -v

# 跑 e2e（需先 pip install pytest-playwright && playwright install chromium）
pytest tests/e2e/

# 跑性能基准（标记 @pytest.mark.perf，慢 CI 可跳过）
pytest tests/performance/ -v

# 静态检查
ruff check backend/
mypy backend/app

# 数据库迁移
alembic upgrade head          # 应用至最新
alembic revision --autogenerate -m "msg"  # 生成新迁移

# 启动开发服务器（热重载）
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```