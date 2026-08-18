# A股量化分析工作台 MVP

一个可直接部署到 Render 的 A 股数据分析网站。第一版包含：

- 市场总览
- 行业 / 个股资金雷达
- 条件选股
- 策略模板
- 个股诊断
- 同花顺问财语句生成
- iFinD HTTP API 连接骨架
- 15 秒前端自动刷新
- Demo 数据模式（无需账号即可完整预览）

> 这是研究分析工具，不构成投资建议。

## 1. 本地运行

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload
```

浏览器打开：`http://127.0.0.1:8000`

默认 `DATA_MODE=demo`，无需 iFinD 即可运行。

## 2. 切换 iFinD

项目采用同花顺官方 HTTP API，而不是依赖本机 Windows SDK。

复制 `.env.example` 的变量到运行环境：

```text
DATA_MODE=ifind
IFIND_REFRESH_TOKEN=你的refresh_token
IFIND_WATCHLIST=300750.SZ,600519.SH,000858.SZ
```

`refresh_token` 请从同花顺“超级命令/账号详情”获取，不要写进代码或提交到 Git。

### 当前真实模式已经接通的能力

- 获取 access token
- 实时行情 `real_time_quotation`
- 问财 `smart_stock_picking`
- 指数实时行情
- 重点股票池实时行情

### 为什么资金字段没有在代码里硬编码？

主力资金、DDE、资金强度等属于同花顺特色指标，不同账号权限和具体指标参数可能不同。正确做法是在“超级命令”里按你的 iFinD 权限生成取数命令，再把返回字段映射到：

- `main_inflow`
- `main_inflow_rate`
- `turnover`
- `volume_ratio`
- `ma20_gap`

这样不会因为猜错指标 ID 导致线上数据错位。

## 3. Render 部署

仓库已经包含 `render.yaml`。

推荐流程：

1. 将整个项目推送到 GitHub。
2. Render → New → Blueprint / Web Service。
3. 连接 GitHub 仓库。
4. Render 会读取 `render.yaml`：
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Health: `/api/health`
5. 第一次先使用 `DATA_MODE=demo` 部署，确认页面正常。
6. 在 Render → Environment 增加：
   - `DATA_MODE=ifind`
   - `IFIND_REFRESH_TOKEN=...`
7. 保存并重新部署。

## 4. 下一阶段建议

### Phase 2：真正的全市场盘中扫描

- 用 `data_pool` 获取全 A 股票池
- 10~30 秒轮询全市场基础实时字段
- 重点候选股 2~5 秒刷新
- Redis 缓存
- 1 分钟资金快照入库
- PostgreSQL 保存策略与历史命中记录
- 自动标记“新进入 / 新移除”

### Phase 3：研究与同花顺深度联动

- 回测中心
- 策略交集
- 自选板块同步（视 SuperMind / 账户能力）
- 多策略打分
- 盘中告警
