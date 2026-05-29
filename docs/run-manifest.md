# Run Manifest

`output/meta/run_manifest.json` 现在是 TrendRadar 的统一运行清单。

它承担三类职责：

1. 运行真相源
   - 当前轮次状态
   - 发布结果
   - 生成产物路径
   - 核心步骤执行顺序

2. 信源真相源
   - 统一信源目录
   - 每个信源的运行状态
   - 最近同步时间
   - 失败原因与抓取方式

3. 兼容旧链路
   - 仍会同步生成 `output/meta/latest_run_report.json`
   - 旧脚本可继续工作

## 结构约定

- `source_catalog.entries`
  - 配置真相源
  - 定义信源的 `id / name / kind / group / strategy / health_policy`

- `source_status`
  - 运行真相源
  - 定义信源在本轮的 `status / healthy / count / last_synced / error / fetch_mode`

- `publish`
  - 定义本轮是否允许覆盖 `latest` 和入口页

- `artifacts`
  - 定义 HTML、manifest、兼容 run report 的产物路径

## 当前状态枚举

- `pending`
- `live_ok`
- `cache_fallback`
- `stale_cache`
- `failed`

## 维护原则

- 页面展示优先读取 `run_manifest.json`
- 排障优先读取 `run_manifest.json`
- 手动补跑脚本 `tools/run_round.ps1` 优先读取 `run_manifest.json`，旧版 `latest_run_report.json` 仅作兼容兜底
- 新增信源优先改 `config/config.yaml`，由 `trendradar/sources/catalog.py` 统一收敛
- 若必须兼容旧逻辑，只从 manifest 派生，不再反向拼接多份状态
