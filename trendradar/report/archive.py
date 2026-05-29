# coding=utf-8
"""HTML archive page generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


MODERN_ARCHIVE_START_DATE = "2026-04-29"


def _safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _collect_archive_days(html_root: Path) -> List[Dict[str, object]]:
    days: List[Dict[str, object]] = []
    if not html_root.exists():
        return days

    for day_dir in sorted(html_root.iterdir(), reverse=True):
        if not day_dir.is_dir() or day_dir.name == "latest":
            continue

        snapshot_files = [
            html_file
            for html_file in sorted(day_dir.glob("*.html"), reverse=True)
            if not html_file.name.startswith("rss_")
        ]

        if not snapshot_files:
            continue

        latest_snapshot = snapshot_files[0]

        days.append(
            {
                "date": day_dir.name,
                "latest_time": latest_snapshot.stem,
                "latest_snapshot": {
                    "time_label": latest_snapshot.stem,
                    "filename": latest_snapshot.name,
                    # Use an absolute path so the viewer works both inside /archive/*
                    # and inside the homepage hash sections at /.
                    "relative_report_path": f"/html/{day_dir.name}/{latest_snapshot.name}",
                },
            }
        )

    return days


def _render_archive_index(days: List[Dict[str, object]]) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redirecting...</title>
    <meta http-equiv="refresh" content="0; url=/#archive">
</head>
<body>
    <script>
        window.location.replace('/#archive');
    </script>
</body>
</html>
"""


def _module_shell(icon: str, icon_class: str, title: str, desc: str) -> str:
    icon_class_name = f"icon {icon_class}".strip()
    return f"""
        <button class="accordion-toggle" type="button" aria-expanded="false">
            <div class="module-head">
                <div class="{icon_class_name}">{icon}</div>
                <div>
                    <div class="module-title">{title}</div>
                    <div class="module-desc">{desc}</div>
                </div>
            </div>
            <div class="module-meta">
                <span class="chip" data-role="count">加载中</span>
                <span class="arrow">⌃</span>
            </div>
        </button>
        <div class="accordion-panel">
            <div class="box">正在读取当天最后一份快照内容...</div>
            <div class="module-body"></div>
        </div>
    """


def _render_day_page(day: Dict[str, object]) -> str:
    date_label = str(day["date"])
    snapshot = dict(day["latest_snapshot"])
    snapshot_path = json.dumps(str(snapshot["relative_report_path"]))
    snapshot_time = json.dumps(str(snapshot["time_label"]))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{date_label} Archive</title>
    <style>
        :root {{
            --bg: #edf3f9; --card: rgba(255,255,255,.96); --line: rgba(207,218,232,.92);
            --text: #20314c; --muted: #6f819c; --blue: #5677b8; --blue-soft: #ebf1ff;
            --warm-soft: #fff0e3; --warm-text: #ab6431; --green-soft: #ebf7ee; --green-text: #3f7a56;
            --cyan-soft: #e9f7f8; --cyan-text: #276e7f;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color: var(--text);
            background: radial-gradient(circle at 8% 12%, rgba(238,217,191,.36), transparent 18%), radial-gradient(circle at 88% 8%, rgba(202,222,247,.46), transparent 18%), linear-gradient(180deg, var(--bg) 0%, #f8fbff 100%); }}
        .page {{ width: min(1180px, calc(100% - 28px)); margin: 0 auto; padding: 20px 0 36px; }}
        .topbar, .board, .card, .accordion {{ border: 1px solid var(--line); background: var(--card); box-shadow: 0 18px 40px rgba(90,111,150,.08); }}
        .topbar {{ position: sticky; top: 16px; z-index: 5; display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; padding: 18px 20px; border-radius: 28px; backdrop-filter: blur(16px); }}
        .eyebrow {{ color: var(--blue); font-size: 12px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }}
        h1 {{ margin: 8px 0 0; font-size: 34px; line-height: 1.04; letter-spacing: -.04em; }}
        .meta {{ margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.8; max-width: 760px; }}
        .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
        .action {{ display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 16px; border-radius: 999px; border: 1px solid var(--line); background: rgba(255,255,255,.98); color: var(--text); text-decoration: none; font-size: 14px; font-weight: 800; }}
        .board {{ margin-top: 16px; padding: 18px; border-radius: 32px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }}
        .summary-card {{ padding: 15px 16px; border-radius: 22px; border: 1px solid rgba(223,231,241,.96); background: rgba(255,255,255,.98); }}
        .summary-label {{ color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
        .summary-value {{ margin-top: 8px; font-size: 25px; line-height: 1.05; font-weight: 850; letter-spacing: -.03em; }}
        .summary-note {{ margin-top: 7px; color: var(--muted); font-size: 12px; line-height: 1.6; }}
        .card {{ padding: 18px; border-radius: 24px; }}
        .label {{ color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }}
        .value {{ margin-top: 10px; font-size: 30px; font-weight: 800; letter-spacing: -.04em; }}
        .note, .copy {{ margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.8; }}
        .title {{ font-size: 24px; font-weight: 800; line-height: 1.42; }}
        .section-grid {{ display: grid; gap: 14px; }}
        .accordion {{ border-radius: 28px; overflow: hidden; }}
        .accordion-toggle {{ width: 100%; border: 0; padding: 18px 20px; display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: center; background: transparent; color: inherit; text-align: left; cursor: pointer; }}
        .accordion-toggle:hover {{ background: rgba(245,249,255,.88); }}
        .module-head {{ display: flex; gap: 14px; align-items: flex-start; }}
        .icon {{ width: 44px; height: 44px; border-radius: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 800; background: var(--blue-soft); color: #355892; flex: 0 0 auto; }}
        .icon.hot {{ background: var(--warm-soft); color: var(--warm-text); }}
        .icon.ai {{ background: var(--green-soft); color: var(--green-text); }}
        .icon.media {{ background: var(--cyan-soft); color: var(--cyan-text); }}
        .module-title {{ font-size: 21px; font-weight: 800; line-height: 1.18; }}
        .module-desc {{ margin-top: 6px; color: var(--muted); font-size: 14px; line-height: 1.75; }}
        .module-meta {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; align-items: center; }}
        .chip {{ display: inline-flex; align-items: center; min-height: 34px; padding: 0 12px; border-radius: 999px; background: var(--blue-soft); color: #4e6584; font-size: 12px; font-weight: 800; white-space: nowrap; }}
        .arrow {{ width: 38px; height: 38px; border-radius: 999px; border: 1px solid rgba(215,224,236,.96); display: inline-flex; align-items: center; justify-content: center; font-size: 18px; color: #355892; transition: transform .18s ease; background: rgba(255,255,255,.96); }}
        .accordion.open .arrow {{ transform: rotate(180deg); }}
        .accordion-panel {{ display: none; padding: 0 20px 20px; }}
        .accordion.open .accordion-panel {{ display: block; }}
        .box {{ margin-bottom: 14px; padding: 16px 18px; border-radius: 20px; border: 1px solid rgba(223,231,241,.96); background: linear-gradient(180deg, rgba(247,250,255,.96) 0%, rgba(255,255,255,.98) 100%); color: var(--muted); font-size: 14px; line-height: 1.8; }}
        .group-list, .news-list {{ display: grid; gap: 12px; }}
        .group {{ padding: 16px; border: 1px solid rgba(223,231,241,.96); border-radius: 22px; background: rgba(255,255,255,.98); }}
        .group-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 12px; }}
        .group-title {{ font-size: 18px; font-weight: 800; line-height: 1.35; }}
        .group-count {{ color: var(--muted); font-size: 12px; font-weight: 800; white-space: nowrap; }}
        .item {{ padding: 16px; border: 1px solid rgba(223,231,241,.96); border-radius: 22px; background: rgba(255,255,255,.98); }}
        .item-top {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }}
        .source {{ display: inline-flex; align-items: center; min-height: 28px; padding: 0 10px; border-radius: 999px; background: var(--blue-soft); color: #4d6483; font-size: 12px; font-weight: 800; }}
        .source.hot {{ background: var(--warm-soft); color: var(--warm-text); }}
        .source.ai {{ background: var(--green-soft); color: var(--green-text); }}
        .source.media {{ background: var(--cyan-soft); color: var(--cyan-text); }}
        .time, .rank {{ color: var(--muted); font-size: 12px; font-weight: 700; }}
        .item-title {{ font-size: 17px; font-weight: 800; line-height: 1.55; }}
        .item-title-link {{ color: inherit; text-decoration: none; }}
        .item-title-link:hover {{ color: #355892; }}
        .item-copy {{ margin-top: 8px; color: var(--muted); font-size: 14px; line-height: 1.82; }}
        .comment-list {{ display: grid; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(222,230,239,.72); }}
        .comment-line {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; align-items: start; color: #496174; font-size: 13px; line-height: 1.65; }}
        .comment-tag {{ color: var(--cyan-text); font-size: 11px; font-weight: 850; white-space: nowrap; }}
        .hidden {{ display: none !important; }}
        @media (max-width: 980px) {{ .topbar {{ position: static; flex-direction: column; }} .module-meta {{ justify-content: flex-start; }} .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
        @media (max-width: 560px) {{ .summary-grid {{ grid-template-columns: 1fr; }} }}
        @media (max-width: 720px) {{ .accordion-toggle {{ grid-template-columns: 1fr; }} h1 {{ font-size: 28px; }} }}
    </style>
</head>
<body>
    <main class="page">
        <section class="topbar">
            <div>
                <div class="eyebrow">Archive Detail</div>
                <h1>{date_label}</h1>
                <div class="meta">这一天只保留最后一个时间点的归档快照。新版详情页会按当前站点结构展开热榜、网站、媒体观测和 AI 洞察。</div>
            </div>
            <div class="actions">
                <a class="action" href="/#archive">返回归档列表</a>
                <a class="action" href="/">返回首页</a>
            </div>
        </section>
        <section class="board">
            <section class="summary-grid" aria-label="归档概览">
                <div class="summary-card"><div class="summary-label">HOTLIST</div><div class="summary-value" data-summary="hotlist">读取中</div><div class="summary-note">当天热榜入选条目</div></div>
                <div class="summary-card"><div class="summary-label">WEBSITE</div><div class="summary-value" data-summary="website">读取中</div><div class="summary-note">网站监测入选条目</div></div>
                <div class="summary-card"><div class="summary-label">MEDIA</div><div class="summary-value" data-summary="media">读取中</div><div class="summary-note">媒体观测卡片与评论</div></div>
                <div class="summary-card"><div class="summary-label">AI</div><div class="summary-value" data-summary="ai">读取中</div><div class="summary-note">当天 AI 研判结论</div></div>
            </section>
            <section class="section-grid">
                <article class="accordion" data-module="hotlist">{_module_shell("热", "hot", "热榜监测", "从当天最后一份快照中抽取热榜分组与具体新闻条目，按模块展开查看。")}</article>
                <article class="accordion" data-module="website">{_module_shell("站", "", "网站监测", "展示 RSS / 网站更新里真正落到当天归档中的具体条目，适合回看站点内容。")}</article>
                <article class="accordion" data-module="media">{_module_shell("媒", "media", "媒体观测", "展示当天进入观察台的 X / Reddit 内容，保留代表性评论，方便回看社交反馈。")}</article>
                <article class="accordion" data-module="ai">{_module_shell("AI", "ai", "AI 洞察", "保留当天 AI 总结出的主题线索、争议点与策略建议，展开后直接阅读。")}</article>
            </section>
        </section>
    </main>
    <script>
        const snapshotPath = {snapshot_path};
        const snapshotTime = {snapshot_time};
        document.querySelectorAll('.accordion-toggle').forEach((button) => button.addEventListener('click', () => {{
            const accordion = button.closest('.accordion'); const isOpen = accordion.classList.contains('open');
            accordion.classList.toggle('open', !isOpen); button.setAttribute('aria-expanded', String(!isOpen));
        }}));
        const escapeHtml = (value) => String(value || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
        const setCount = (module, text) => {{ const chip = document.querySelector(`.accordion[data-module="${{module}}"] [data-role="count"]`); if (chip) chip.textContent = text; }};
        const setSummary = (key, text) => {{ const el = document.querySelector(`[data-summary="${{key}}"]`); if (el) el.textContent = text; }};
        const renderEmpty = (message) => `<div class="box">${{escapeHtml(message)}}</div>`;
        const renderTitle = (item) => item.href
            ? `<a class="item-title-link" href="${{escapeHtml(item.href)}}" target="_blank" rel="noreferrer noopener">${{escapeHtml(item.title)}}</a>`
            : escapeHtml(item.title);
        const renderGroups = (groups, kind, showTime = true) => `<div class="group-list">${{groups.map((group) => `<section class="group"><div class="group-head"><div class="group-title">${{escapeHtml(group.title)}}</div><div class="group-count">${{escapeHtml(group.count || `${{group.items.length}} 条`)}}</div></div><div class="news-list">${{group.items.map((item) => `<article class="item"><div class="item-top"><span class="source ${{kind === 'hot' ? 'hot' : ''}}">${{escapeHtml(item.source)}}</span>${{item.rank ? `<span class="rank">排名：${{escapeHtml(item.rank)}}</span>` : ''}}${{showTime && item.time ? `<span class="time">${{escapeHtml(item.time)}}</span>` : ''}}</div><div class="item-title">${{renderTitle(item)}}</div>${{item.copy ? `<div class="item-copy">${{item.copy}}</div>` : ''}}</article>`).join('')}}</div></section>`).join('')}}</div>`;
        const renderHotlist = (doc) => {{
            const groups = Array.from(doc.querySelectorAll('.hotlist-section .word-group')).map((group) => ({{
                title: group.querySelector('.word-name')?.textContent?.trim() || '未命名分组',
                count: group.querySelector('.word-count')?.textContent?.trim() || '',
                items: Array.from(group.querySelectorAll('.news-item')).map((item) => ({{
                    source: item.querySelector('.source-name')?.textContent?.trim() || '热榜来源',
                    rank: item.querySelector('.rank-num')?.textContent?.trim() || '',
                    time: item.querySelector('.time-info')?.textContent?.trim() || snapshotTime,
                    title: item.querySelector('.news-link')?.textContent?.trim() || item.querySelector('.news-title')?.textContent?.trim() || '未命名条目',
                    href: item.querySelector('.news-link')?.getAttribute('href') || '',
                }})),
            }})).filter((group) => group.items.length);
            setCount('hotlist', `${{groups.reduce((sum, g) => sum + g.items.length, 0)}} 条重点`);
            setSummary('hotlist', `${{groups.reduce((sum, g) => sum + g.items.length, 0)}} 条`);
            return groups.length ? renderGroups(groups, 'hot', false) : renderEmpty('当天最后一份快照里没有可展示的热榜条目。');
        }};
        const renderWebsite = (doc) => {{
            const groups = Array.from(doc.querySelectorAll('.rss-section .feed-group')).map((group) => ({{
                title: group.querySelector('.feed-name')?.textContent?.trim() || '未命名分组',
                count: group.querySelector('.feed-count')?.textContent?.trim() || '',
                items: Array.from(group.querySelectorAll('.rss-item')).map((item) => ({{
                    source: Array.from(item.querySelectorAll('.rss-author')).map((node) => node.textContent?.trim()).filter(Boolean).join(' / ') || '网站监测',
                    time: item.querySelector('.rss-time')?.textContent?.trim() || snapshotTime,
                    title: item.querySelector('.rss-link')?.textContent?.trim() || item.querySelector('.rss-title')?.textContent?.trim() || '未命名条目',
                    href: item.querySelector('.rss-link')?.getAttribute('href') || '',
                }})),
            }})).filter((group) => group.items.length);
            setCount('website', `${{groups.reduce((sum, g) => sum + g.items.length, 0)}} 条重点`);
            setSummary('website', `${{groups.reduce((sum, g) => sum + g.items.length, 0)}} 条`);
            return groups.length ? renderGroups(groups, '', false) : renderEmpty('当天最后一份快照里没有可展示的网站监测条目。');
        }};
        const renderMedia = (doc) => {{
            const cards = Array.from(doc.querySelectorAll('.dashboard-social .social-item, .social-grid .social-item')).map((card) => {{
                const comments = Array.from(card.querySelectorAll('.social-comment-text'))
                    .map((node) => node.textContent?.trim() || '')
                    .filter((text) => text && text !== '暂无评论')
                    .slice(0, 3);
                const href = card.querySelector('.social-text-link')?.getAttribute('href') || '';
                return {{
                    source: card.querySelector('.social-author')?.textContent?.trim() || '媒体观测',
                    time: card.querySelector('.social-time')?.textContent?.trim() || snapshotTime,
                    title: card.querySelector('.social-excerpt')?.textContent?.trim() || card.querySelector('.rss-link, .rss-title')?.textContent?.trim() || '未命名媒体条目',
                    href,
                    comments,
                }};
            }}).filter((item) => item.title);
            const withComments = cards.filter((item) => item.comments.length).length;
            setCount('media', `${{cards.length}} 张卡 / ${{withComments}} 有评论`);
            setSummary('media', `${{cards.length}} 张`);
            if (!cards.length) return renderEmpty('当天最后一份快照里没有可展示的媒体观测内容。');
            return `<div class="news-list">${{cards.map((item) => `<article class="item"><div class="item-top"><span class="source media">${{escapeHtml(item.source)}}</span><span class="time">${{escapeHtml(item.time)}}</span>${{item.comments.length ? `<span class="rank">${{item.comments.length}} 条评论</span>` : ''}}</div><div class="item-title">${{renderTitle(item)}}</div>${{item.comments.length ? `<div class="comment-list">${{item.comments.map((comment, index) => `<div class="comment-line"><span class="comment-tag">评论${{index + 1}}</span><span>${{escapeHtml(comment)}}</span></div>`).join('')}}</div>` : `<div class="item-copy">暂无代表性评论。</div>`}}</article>`).join('')}}</div>`;
        }};
        const renderAi = (doc) => {{
            const directCards = Array.from(doc.querySelectorAll('.dashboard-ai .ai-grid-card')).map((card) => ({{
                title: card.querySelector('.ai-grid-title, .ai-overview-summary-title')?.textContent?.trim() || 'AI 洞察',
                copy: card.querySelector('.ai-grid-content, .ai-overview-summary-text, .ai-overview-detail-grid')?.innerHTML?.trim() || '',
            }})).filter((block) => block.title || block.copy);
            const legacyBlocks = Array.from(doc.querySelectorAll('.ai-section .ai-block')).map((block) => ({{
                title: block.querySelector('.ai-block-title')?.textContent?.trim() || 'AI 洞察',
                copy: block.querySelector('.ai-block-content')?.innerHTML?.trim() || '',
            }})).filter((block) => block.title || block.copy);
            const blocks = directCards.length ? directCards : legacyBlocks;
            setCount('ai', `${{blocks.length}} 条结论`);
            setSummary('ai', blocks.length ? '已完成' : '暂无');
            return blocks.length ? `<div class="news-list">${{blocks.map((item) => `<article class="item"><div class="item-top"><span class="source ai">AI 洞察</span><span class="time">当天汇总</span></div><div class="item-title">${{escapeHtml(item.title)}}</div><div class="item-copy">${{item.copy}}</div></article>`).join('')}}</div>` : renderEmpty('当天最后一份快照里没有可展示的 AI 洞察内容。');
        }};
        const fail = () => ['hotlist','website','media','ai'].forEach((module) => {{
            setCount(module, '加载失败');
            setSummary(module, '失败');
            const card = document.querySelector(`.accordion[data-module="${{module}}"]`); const state = card?.querySelector('.box'); const body = card?.querySelector('.module-body');
            if (state) state.classList.add('hidden'); if (body) body.innerHTML = `<div class="box">归档详情加载失败，请稍后重试。</div>`;
        }});
        fetch(snapshotPath, {{ cache: 'no-store' }}).then((resp) => {{ if (!resp.ok) throw new Error(String(resp.status)); return resp.text(); }}).then((html) => {{
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const rendered = {{ hotlist: renderHotlist(doc), website: renderWebsite(doc), media: renderMedia(doc), ai: renderAi(doc) }};
            Object.entries(rendered).forEach(([module, markup]) => {{
                const card = document.querySelector(`.accordion[data-module="${{module}}"]`); const state = card?.querySelector('.box'); const body = card?.querySelector('.module-body');
                if (state) state.classList.add('hidden'); if (body) body.innerHTML = markup;
            }});
        }}).catch(fail);
    </script>
</body>
</html>
"""


def generate_archive_pages(output_dir: str = "output") -> Dict[str, str]:
    output_root = Path(output_dir)
    html_root = output_root / "html"
    output_archive_root = output_root / "archive"
    repo_archive_root = Path("archive")

    days = _collect_archive_days(html_root)
    archive_index_html = _render_archive_index(days)

    _safe_write(output_archive_root / "index.html", archive_index_html)
    _safe_write(repo_archive_root / "index.html", archive_index_html)

    manifest = {
        "version": 1,
        "days": days,
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    _safe_write(output_archive_root / "manifest.json", manifest_json)
    _safe_write(repo_archive_root / "manifest.json", manifest_json)

    for day in days:
        day_html = _render_day_page(day)
        day_filename = f'{day["date"]}.html'
        if str(day["date"]) < MODERN_ARCHIVE_START_DATE and (output_archive_root / day_filename).exists() and (repo_archive_root / day_filename).exists():
            continue
        _safe_write(output_archive_root / day_filename, day_html)
        _safe_write(repo_archive_root / day_filename, day_html)

    return {
        "archive_index": str(output_archive_root / "index.html"),
        "archive_manifest": str(output_archive_root / "manifest.json"),
        "day_count": str(len(days)),
    }
