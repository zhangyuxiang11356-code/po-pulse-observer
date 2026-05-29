# coding=utf-8
"""
AI 分析结果格式化模块

将 AI 分析结果格式化为各推送渠道的样式
"""

import html as html_lib
import re
from .analyzer import AIAnalysisResult


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符，防止 XSS 攻击"""
    return html_lib.escape(text) if text else ""


def _format_list_content(text: str) -> str:
    """
    格式化列表内容，确保序号前有换行
    例如将 "1. xxx 2. yyy" 转换为:
    1. xxx
    2. yyy
    """
    if not text:
        return ""
    
    # 去除首尾空白，防止 AI 返回的内容开头就有换行导致显示空行
    text = text.strip()

    # 0. 合并序号与紧随的【标签】（防御性处理）
    # 将 "1.\n【投资者】：" 或 "1. 【投资者】：" 合并为 "1. 投资者："
    text = re.sub(r'(\d+\.)\s*【([^】]+)】([:：]?)', r'\1 \2：', text)

    # 1. 规范化：确保 "1." 后面有空格
    result = re.sub(r'(\d+)\.([^ \d])', r'\1. \2', text)

    # 2. 强制换行：匹配 "数字."，且前面不是换行符
    #    (?!\d) 排除版本号/小数（如 2.0、3.5），避免将其误判为列表序号
    result = re.sub(r'(?<=[^\n])\s+(\d+\.)(?!\d)', r'\n\1', result)
    
    # 3. 处理 "1.**粗体**" 这种情况（虽然 Prompt 要求不输出 Markdown，但防御性处理）
    result = re.sub(r'(?<=[^\n])(\d+\.\*\*)', r'\n\1', result)

    # 4. 处理中文标点后的换行（排除版本号/小数）
    result = re.sub(r'([：:;,。；，])\s*(\d+\.)(?!\d)', r'\1\n\2', result)

    # 5. 处理 "XX方面："、"XX领域：" 等子标题换行
    # 只有在中文标点（句号、逗号、分号等）后才触发换行，避免破坏 "1. XX领域：" 格式
    result = re.sub(r'([。！？；，、])\s*([a-zA-Z0-9\u4e00-\u9fa5]+(方面|领域)[:：])', r'\1\n\2', result)

    # 6. 处理 【标签】 格式
    # 6a. 标签前确保空行分隔（文本开头除外）
    result = re.sub(r'(?<=\S)\n*(【[^】]+】)', r'\n\n\1', result)
    # 6b. 合并标签与被换行拆开的冒号：【tag】\n： → 【tag】：
    result = re.sub(r'(【[^】]+】)\n+([:：])', r'\1\2', result)
    # 6c. 标签后（含可选冒号），如果紧跟非空白非冒号内容则另起一行
    # 用 (?=[^\s:：]) 避免正则回溯将冒号误判为"内容"而拆开 【tag】：
    result = re.sub(r'(【[^】]+】[:：]?)[ \t]*(?=[^\s:：])', r'\1\n', result)

    # 7. 在列表项之间增加视觉空行（排除版本号/小数）
    # 排除 【标签】 行（以】结尾）和子标题行（以冒号结尾）之后的情况，避免标题与首项之间出现空行
    result = re.sub(r'(?<![:：】])\n(\d+\.)(?!\d)', r'\n\n\1', result)

    return result


def _format_standalone_summaries(summaries: dict) -> str:
    """格式化独立展示区概括为纯文本行，每个源名称单独一行"""
    if not summaries:
        return ""
    lines = []
    for source_name, summary in summaries.items():
        if summary:
            lines.append(f"[{source_name}]:\n{summary}")
    return "\n\n".join(lines)


def _render_cluster_event_list(items: list[dict]) -> str:
    """渲染事件簇背面的具体事件列表。"""
    if not items:
        return '<div class="ai-cluster-event-placeholder">暂无具体事件</div>'

    rendered = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _escape_html(str(item.get("title") or "").strip())
        if not title:
            continue
        source_type = _escape_html(str(item.get("source_type_label") or item.get("source_type") or "来源").strip())
        source_name = _escape_html(str(item.get("source_name") or "").strip())
        href = _escape_html(str(item.get("url") or "").strip())
        meta_left = f"{source_type} · {source_name}" if source_name else source_type
        title_html = (
            f'<a class="ai-cluster-event-link" href="{href}" target="_blank" rel="noreferrer noopener">{title}</a>'
            if href
            else f'<div class="ai-cluster-event-text">{title}</div>'
        )
        rendered.append(
            f"""
                                <li class="ai-cluster-event-item">
                                    <div class="ai-cluster-event-meta">
                                        <span class="ai-cluster-event-source">{meta_left}</span>
                                    </div>
                                    {title_html}
                                </li>"""
        )

    return (
        '<ul class="ai-cluster-event-list" tabindex="0" data-ai-cluster-event-list="1">'
        + "".join(rendered)
        + "</ul>"
        if rendered
        else '<div class="ai-cluster-event-placeholder">暂无具体事件</div>'
    )


def _render_ai_overview_cards(result: AIAnalysisResult) -> str:
    """按首页定稿结构直接渲染 AI 洞察卡片。"""
    clusters = result.event_clusters or []
    if not result.today_judgement and not clusters:
        return ""

    summary_text = _escape_html(result.today_judgement or "暂无显著信号")
    cluster_html = ""
    for index, cluster in enumerate(clusters or [], start=1):
        title = _escape_html(cluster.get("title") or f"重点事件簇 {index}")
        event_count_raw = str(
            cluster.get("event_count") or cluster.get("related_count") or cluster.get("count") or "1"
        ).strip()
        event_count = event_count_raw if event_count_raw.isdigit() else "1"
        summary = _escape_html(cluster.get("summary") or "暂无显著信号")
        risk = _escape_html(cluster.get("risk") or "暂无显著争议风险。")
        action = _escape_html(cluster.get("action") or "暂无显著后续观察建议。")
        cluster_id = _escape_html(cluster.get("cluster_id") or f"cluster-{index}")
        source_mix = _escape_html(cluster.get("source_mix") or "")
        combined_meta = (
            f'''
            <span class="ai-overview-pill-combined-label">相关事件数 {event_count} 条</span>
            {f'<span class="ai-overview-pill-divider" aria-hidden="true"></span><span class="ai-overview-pill-combined-label">{source_mix}</span>' if source_mix else ''}
            '''
        )
        items_html = _render_cluster_event_list(cluster.get("items") or [])
        cluster_html += f"""
                        <div class="ai-grid-card ai-flip-card" data-ai-flip-card="{cluster_id}">
                            <div class="ai-flip-card-inner">
                                <div class="ai-flip-card-face ai-flip-card-front">
                                    <div class="ai-grid-head">
                                        <div class="ai-grid-title">{title}</div>
                                        <div class="ai-overview-event-meta">
                                            <button type="button" class="ai-overview-pill ai-overview-pill-button ai-overview-pill-combined" data-ai-flip-card-toggle aria-label="查看{title}相关事件" aria-pressed="false">{combined_meta}</button>
                                        </div>
                                    </div>
                                    <div class="ai-overview-event-row">
                                        <div class="ai-overview-main">
                                            <div class="ai-grid-content">{summary}</div>
                                        </div>
                                        <div class="ai-overview-detail-grid">
                                            <div class="ai-overview-detail">
                                                <div class="ai-overview-detail-label">风险点</div>
                                                <div class="ai-overview-detail-text">{risk}</div>
                                            </div>
                                            <div class="ai-overview-detail">
                                                <div class="ai-overview-detail-label">建议动作</div>
                                                <div class="ai-overview-detail-text">{action}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="ai-flip-card-face ai-flip-card-back">
                                    <div class="ai-grid-head ai-flip-card-back-head">
                                        <div>
                                            <div class="ai-grid-title">{title}</div>
                                            <div class="ai-flip-card-back-subtitle">具体事件列表</div>
                                        </div>
                                        <button type="button" class="ai-flip-card-back-button" data-ai-flip-card-back>返回研判</button>
                                    </div>
                                    <div class="ai-cluster-event-shell">
                                        {items_html}
                                    </div>
                                </div>
                            </div>
                        </div>"""

    if not cluster_html:
        cluster_html = """
                                <div class="ai-grid-card">
                                    <div class="ai-grid-head">
                                        <div class="ai-grid-title">重点事件簇</div>
                                        <div class="ai-overview-event-meta">
                                            <span class="ai-overview-pill">相关事件数 1 条</span>
                                        </div>
                                    </div>
                            <div class="ai-overview-event-row">
                                <div class="ai-overview-main">
                                    <div class="ai-grid-content">暂无显著信号</div>
                                </div>
                                <div class="ai-overview-detail-grid">
                                    <div class="ai-overview-detail">
                                        <div class="ai-overview-detail-label">风险点</div>
                                        <div class="ai-overview-detail-text">暂无显著争议风险。</div>
                                    </div>
                                    <div class="ai-overview-detail">
                                        <div class="ai-overview-detail-label">建议动作</div>
                                        <div class="ai-overview-detail-text">暂无显著后续观察建议。</div>
                                    </div>
                                </div>
                            </div>
                        </div>"""

    return f"""
                <div class="ai-section" data-ai-schema="v2">
                    <div class="ai-section-header">
                        <div class="ai-section-title">✨ AI 热点分析</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-grid ai-panel" data-ai-direct="1">
                        <div class="ai-grid-card ai-overview-summary">
                            <div class="ai-overview-summary-text">{summary_text}</div>
                        </div>
                        <div class="ai-overview-events">
                            {cluster_html}
                        </div>
                    </div>
                </div>"""


def render_ai_analysis_markdown(result: AIAnalysisResult) -> str:
    """渲染为通用 Markdown 格式（Telegram、企业微信、ntfy、Bark、Slack）"""
    if not result.success:
        return f"⚠️ AI 分析失败: {result.error}"

    lines = ["**✨ AI 热点分析**", ""]

    if result.core_trends:
        lines.extend(["**核心热点态势**", _format_list_content(result.core_trends), ""])

    if result.sentiment_controversy:
        lines.extend(
            ["**舆论风向争议**", _format_list_content(result.sentiment_controversy), ""]
        )

    if result.signals:
        lines.extend(["**异动与弱信号**", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(
            ["**RSS 深度洞察**", _format_list_content(result.rss_insights), ""]
        )

    if result.outlook_strategy:
        lines.extend(
            ["**研判策略建议**", _format_list_content(result.outlook_strategy), ""]
        )

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["**独立源点速览**", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_feishu(result: AIAnalysisResult) -> str:
    """渲染为飞书卡片 Markdown 格式"""
    if not result.success:
        return f"⚠️ AI 分析失败: {result.error}"

    lines = ["**✨ AI 热点分析**", ""]

    if result.core_trends:
        lines.extend(["**核心热点态势**", _format_list_content(result.core_trends), ""])

    if result.sentiment_controversy:
        lines.extend(
            ["**舆论风向争议**", _format_list_content(result.sentiment_controversy), ""]
        )

    if result.signals:
        lines.extend(["**异动与弱信号**", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(
            ["**RSS 深度洞察**", _format_list_content(result.rss_insights), ""]
        )

    if result.outlook_strategy:
        lines.extend(
            ["**研判策略建议**", _format_list_content(result.outlook_strategy), ""]
        )

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["**独立源点速览**", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_dingtalk(result: AIAnalysisResult) -> str:
    """渲染为钉钉 Markdown 格式"""
    if not result.success:
        return f"⚠️ AI 分析失败: {result.error}"

    lines = ["### ✨ AI 热点分析", ""]

    if result.core_trends:
        lines.extend(
            ["#### 核心热点态势", _format_list_content(result.core_trends), ""]
        )

    if result.sentiment_controversy:
        lines.extend(
            [
                "#### 舆论风向争议",
                _format_list_content(result.sentiment_controversy),
                "",
            ]
        )

    if result.signals:
        lines.extend(["#### 异动与弱信号", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(
            ["#### RSS 深度洞察", _format_list_content(result.rss_insights), ""]
        )

    if result.outlook_strategy:
        lines.extend(
            ["#### 研判策略建议", _format_list_content(result.outlook_strategy), ""]
        )

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["#### 独立源点速览", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_html(result: AIAnalysisResult) -> str:
    """渲染为 HTML 格式（邮件）"""
    if not result.success:
        return (
            f'<div class="ai-error">⚠️ AI 分析失败: {_escape_html(result.error)}</div>'
        )

    html_parts = ['<div class="ai-analysis">', "<h3>✨ AI 热点分析</h3>"]

    if result.core_trends:
        content = _format_list_content(result.core_trends)
        content_html = _escape_html(content).replace("\n", "<br>")
        html_parts.extend(
            [
                '<div class="ai-section">',
                "<h4>核心热点态势</h4>",
                f'<div class="ai-content">{content_html}</div>',
                "</div>",
            ]
        )

    if result.sentiment_controversy:
        content = _format_list_content(result.sentiment_controversy)
        content_html = _escape_html(content).replace("\n", "<br>")
        html_parts.extend(
            [
                '<div class="ai-section">',
                "<h4>舆论风向争议</h4>",
                f'<div class="ai-content">{content_html}</div>',
                "</div>",
            ]
        )

    if result.signals:
        content = _format_list_content(result.signals)
        content_html = _escape_html(content).replace("\n", "<br>")
        html_parts.extend(
            [
                '<div class="ai-section">',
                "<h4>异动与弱信号</h4>",
                f'<div class="ai-content">{content_html}</div>',
                "</div>",
            ]
        )

    if result.rss_insights:
        content = _format_list_content(result.rss_insights)
        content_html = _escape_html(content).replace("\n", "<br>")
        html_parts.extend(
            [
                '<div class="ai-section">',
                "<h4>RSS 深度洞察</h4>",
                f'<div class="ai-content">{content_html}</div>',
                "</div>",
            ]
        )

    if result.outlook_strategy:
        content = _format_list_content(result.outlook_strategy)
        content_html = _escape_html(content).replace("\n", "<br>")
        html_parts.extend(
            [
                '<div class="ai-section ai-conclusion">',
                "<h4>研判策略建议</h4>",
                f'<div class="ai-content">{content_html}</div>',
                "</div>",
            ]
        )

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            summaries_html = _escape_html(summaries_text).replace("\n", "<br>")
            html_parts.extend(
                [
                    '<div class="ai-section">',
                    "<h4>独立源点速览</h4>",
                    f'<div class="ai-content">{summaries_html}</div>',
                    "</div>",
                ]
            )

    html_parts.append("</div>")
    return "\n".join(html_parts)


def render_ai_analysis_plain(result: AIAnalysisResult) -> str:
    """渲染为纯文本格式"""
    if not result.success:
        return f"AI 分析失败: {result.error}"

    lines = ["【✨ AI 热点分析】", ""]

    if result.core_trends:
        lines.extend(["[核心热点态势]", _format_list_content(result.core_trends), ""])

    if result.sentiment_controversy:
        lines.extend(
            ["[舆论风向争议]", _format_list_content(result.sentiment_controversy), ""]
        )

    if result.signals:
        lines.extend(["[异动与弱信号]", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(["[RSS 深度洞察]", _format_list_content(result.rss_insights), ""])

    if result.outlook_strategy:
        lines.extend(["[研判策略建议]", _format_list_content(result.outlook_strategy), ""])

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["[独立源点速览]", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_telegram(result: AIAnalysisResult) -> str:
    """渲染为 Telegram HTML 格式（配合 parse_mode: HTML）

    Telegram Bot API 的 HTML 模式仅支持有限标签：
    <b>, <i>, <u>, <s>, <code>, <pre>, <a href="">, <blockquote>
    换行直接使用 \\n，不支持 <br>, <div>, <h1>-<h6> 等标签。
    """
    if not result.success:
        return f"⚠️ AI 分析失败: {_escape_html(result.error)}"

    lines = ["<b>✨ AI 热点分析</b>", ""]

    if result.core_trends:
        lines.extend(["<b>核心热点态势</b>", _escape_html(_format_list_content(result.core_trends)), ""])

    if result.sentiment_controversy:
        lines.extend(["<b>舆论风向争议</b>", _escape_html(_format_list_content(result.sentiment_controversy)), ""])

    if result.signals:
        lines.extend(["<b>异动与弱信号</b>", _escape_html(_format_list_content(result.signals)), ""])

    if result.rss_insights:
        lines.extend(["<b>RSS 深度洞察</b>", _escape_html(_format_list_content(result.rss_insights)), ""])

    if result.outlook_strategy:
        lines.extend(["<b>研判策略建议</b>", _escape_html(_format_list_content(result.outlook_strategy)), ""])

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["<b>独立源点速览</b>", _escape_html(summaries_text)])

    return "\n".join(lines)


def get_ai_analysis_renderer(channel: str):
    """根据渠道获取对应的渲染函数"""
    renderers = {
        "feishu": render_ai_analysis_feishu,
        "dingtalk": render_ai_analysis_dingtalk,
        "wework": render_ai_analysis_markdown,
        "telegram": render_ai_analysis_telegram,
        "email": render_ai_analysis_html_rich,  # 邮件使用丰富样式，配合 HTML 报告的 CSS
        "ntfy": render_ai_analysis_markdown,
        "bark": render_ai_analysis_plain,
        "slack": render_ai_analysis_markdown,
    }
    return renderers.get(channel, render_ai_analysis_markdown)


def render_ai_analysis_html_rich(result: AIAnalysisResult) -> str:
    """渲染为丰富样式的 HTML 格式（HTML 报告用）"""
    if not result:
        return ""

    # 检查是否成功
    if not result.success:
        error_msg = result.error or "未知错误"
        return f"""
                <div class="ai-section">
                    <div class="ai-error">⚠️ AI 分析失败: {_escape_html(str(error_msg))}</div>
                </div>"""

    overview_html = _render_ai_overview_cards(result)
    if overview_html:
        return overview_html

    ai_html = """
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">✨ AI 热点分析</div>
                        <span class="ai-section-badge">AI</span>
                    </div>"""

    if result.core_trends:
        content = _format_list_content(result.core_trends)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">核心热点态势</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.sentiment_controversy:
        content = _format_list_content(result.sentiment_controversy)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">舆论风向争议</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.signals:
        content = _format_list_content(result.signals)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">异动与弱信号</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.rss_insights:
        content = _format_list_content(result.rss_insights)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">RSS 深度洞察</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.outlook_strategy:
        content = _format_list_content(result.outlook_strategy)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">研判策略建议</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            summaries_html = _escape_html(summaries_text).replace("\n", "<br>")
            ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">独立源点速览</div>
                        <div class="ai-block-content">{summaries_html}</div>
                    </div>"""

    ai_html += """
                </div>"""
    return ai_html
