# PO | Pulse Observer

> 一个面向新闻、RSS、X、Reddit 和公开网页信号的 AI 趋势观察系统。

PO | Pulse Observer 是基于开源项目 [TrendRadar](https://github.com/sansan0/TrendRadar) 二次开发的可部署观察台。它会收集公开信号，用关键词和 AI 做筛选、聚类、研判，并生成每日 HTML 观察报告。

这是一个干净的开源发行版，包含公开信源配置、提示词、模板、Docker 文件和通用部署脚本；不包含私钥、Cookie、Token、运行日志或个人云服务器凭据。

## 核心能力

- 抓取配置好的新闻、RSS、X 和 Reddit 信源
- 支持关键词过滤和 AI 辅助分析
- 生成每日 HTML 趋势观察报告
- 支持 Docker 部署
- 必须配置 AI，用于筛选、翻译和趋势研判
- 支持通过本地 `secrets/x_storage_state.json` 使用 X 登录态

## 默认信源

默认信源名单是公开且可修改的：

- 新闻和 RSS 信源：`config/config.yaml`
- X 观察名单：`social_media.sources[x-watchlist]`
- Reddit 社区：`social_media.sources[reddit-watchlist]`
- AI 提示词：`config/ai_analysis_prompt.txt` 和 `config/ai_filter/`

你可以直接使用默认信源，也可以删掉或替换成自己的观察名单。

## 快速开始

### 本地 Python 运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m trendradar
```

### Docker 运行

```bash
cd docker
cp .env.example .env
docker compose up -d --build
```

真实密钥只放在 `docker/.env` 或运行环境变量里，不要提交到 Git。

## AI 配置

AI 配置是必需项。项目依赖 AI 完成信源筛选、内容翻译和趋势研判；没有可用的 `AI_API_KEY`，完整流程无法正常工作。

可以通过环境变量或 `docker/.env` 配置：

```text
AI_API_KEY=
AI_MODEL=
AI_API_BASE=
```

`config/config.yaml` 里的 `ai.api_key` 默认保持为空，推荐使用环境变量或 `docker/.env` 管理密钥。

## X 登录态

如果需要更稳定地抓取 X，可以使用浏览器登录态文件：

```text
secrets/x_storage_state.json
```

这个文件包含 Cookie，绝对不要提交到仓库。项目在 `tools/` 目录里提供了导出和清洗本地浏览器登录态的辅助脚本。

## 不包含什么

- 真实 AI Key
- GitHub Token
- SSH 私钥
- X Cookie 或登录态
- 代理订阅地址
- `output/` 下的运行产物
- 个人云服务器部署记录

## 与 TrendRadar 的关系

本项目是 [TrendRadar](https://github.com/sansan0/TrendRadar) 的定制化二次开发版本。原项目采用 GPL-3.0 协议。

## License

GPL-3.0。详见 [LICENSE](LICENSE)。
