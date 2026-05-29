# coding=utf-8
"""
AI 分析器模块

调用 AI 大模型对热点新闻进行深度分析
基于 LiteLLM 统一接口，支持 100+ AI 提供商
"""

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from trendradar.ai.client import AIClient


@dataclass
class AIAnalysisResult:
    """AI 分析结果。

    当前首页 AI 洞察主渲染优先使用 `today_judgement + event_clusters`。
    下方保留的旧字段主要用于兼容历史推送格式、旧 schema 解析和失败回退链路。
    """
    # 当前首页 AI 洞察主结构（首页主渲染使用）
    today_judgement: str = ""             # 今日总判断
    event_clusters: List[Dict[str, Any]] = field(default_factory=list)  # 重点事件簇

    # 兼容旧推送/旧 schema 的保留字段（首页主渲染不直接使用）
    core_trends: str = ""                # 核心热点与舆情态势
    sentiment_controversy: str = ""      # 舆论风向与争议
    signals: str = ""                    # 异动与弱信号
    rss_insights: str = ""               # RSS 深度洞察
    outlook_strategy: str = ""           # 研判与策略建议
    standalone_summaries: Dict[str, str] = field(default_factory=dict)  # 独立展示区概括 {源ID: 概括}

    # 基础元数据
    raw_response: str = ""               # 原始响应
    success: bool = False                # 是否成功
    error: str = ""                      # 错误信息

    # 新闻数量统计
    total_news: int = 0                  # 总新闻数（热榜+RSS）
    analyzed_news: int = 0               # 实际分析的新闻数
    max_news_limit: int = 0              # 分析上限配置值
    hotlist_count: int = 0               # 热榜新闻数
    rss_count: int = 0                   # RSS 新闻数
    social_count: int = 0                # 社交媒体条目数
    ai_mode: str = ""                    # AI 分析使用的模式 (daily/current/incremental)


class AIAnalyzer:
    """AI 分析器"""

    CLUSTER_STOP_TOKENS = {
        "中国", "美国", "公司", "企业", "事件", "回应", "发布", "网友", "平台", "视频",
        "市场", "行业", "今天", "今日", "热搜", "新闻", "官方", "媒体", "网站", "社交",
        "观察", "讨论", "问题", "情况", "内容", "相关", "消息", "表示", "原因", "为何",
    }

    def __init__(
        self,
        ai_config: Dict[str, Any],
        analysis_config: Dict[str, Any],
        get_time_func: Callable,
        debug: bool = False,
    ):
        """
        初始化 AI 分析器

        Args:
            ai_config: AI 模型配置（LiteLLM 格式）
            analysis_config: AI 分析功能配置（language, prompt_file 等）
            get_time_func: 获取当前时间的函数
            debug: 是否开启调试模式
        """
        self.ai_config = ai_config
        self.analysis_config = analysis_config
        self.get_time_func = get_time_func
        self.debug = debug

        # 创建 AI 客户端（基于 LiteLLM）
        self.client = AIClient(ai_config)

        # 验证配置
        valid, error = self.client.validate_config()
        if not valid:
            print(f"[AI] 配置警告: {error}")

        # 从分析配置获取功能参数
        self.max_news_limit = int(analysis_config.get("MAX_NEWS_FOR_ANALYSIS", 50) or 0)
        self.max_news = self.max_news_limit if self.max_news_limit > 0 else None
        self.include_rss = analysis_config.get("INCLUDE_RSS", True)
        self.include_social = analysis_config.get("INCLUDE_SOCIAL", True)
        self.include_rank_timeline = analysis_config.get("INCLUDE_RANK_TIMELINE", False)
        self.include_standalone = analysis_config.get("INCLUDE_STANDALONE", False)
        self.language = analysis_config.get("LANGUAGE", "Chinese")
        self.empty_response_retries = analysis_config.get("EMPTY_RESPONSE_RETRIES", 2)
        self.empty_response_retry_delay = analysis_config.get("EMPTY_RESPONSE_RETRY_DELAY", 2)
        self.max_program_clusters = int(analysis_config.get("MAX_PROGRAM_CLUSTERS", 8) or 8)
        self._cluster_lookup: Dict[str, Dict[str, Any]] = {}
        self._analysis_item_lookup: Dict[str, Dict[str, Any]] = {}

        # 加载提示词模板
        self.system_prompt, self.user_prompt_template = self._load_prompt_template(
            analysis_config.get("PROMPT_FILE", "ai_analysis_prompt.txt")
        )

    @staticmethod
    def _clean_ai_text(value: Any) -> str:
        """清理 AI 文本字段。"""
        if value is None:
            return ""
        return str(value).replace("\r", "").strip()

    def _derive_cluster_title(self, text: str, fallback: str) -> str:
        """从事件簇摘要中提取短标题。"""
        compact = self._clean_ai_text(text)
        compact = re.sub(r"^\d+\.\s*", "", compact)
        compact = re.sub(r"^[【\[][^】\]]+[】\]][:：]?\s*", "", compact)
        compact = compact.strip()
        if not compact:
            return fallback
        first_segment = next(
            (part for part in re.split(r"[。；;，,:：]", compact) if part.strip()),
            compact,
        )
        title = re.sub(r"\s+", "", first_segment).strip()[:12]
        return title or fallback

    @staticmethod
    def _normalize_cluster_id(value: Any) -> str:
        """标准化事件簇 ID。"""
        text = str(value or "").strip().upper()
        return text if re.fullmatch(r"C\d+", text) else ""

    @staticmethod
    def _normalize_analysis_item_id(value: Any) -> str:
        """标准化 AI 条目编号。"""
        text = str(value or "").strip().upper()
        return text if re.fullmatch(r"N\d+", text) else ""

    def _normalize_similarity_text(self, text: Any) -> str:
        """归一化相似度比较文本。"""
        cleaned = self._clean_ai_text(text).lower()
        cleaned = re.sub(r"https?://\S+", " ", cleaned)
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _extract_similarity_tokens(self, text: Any) -> set[str]:
        """提取中英混合的轻量相似度 token。"""
        normalized = self._normalize_similarity_text(text)
        if not normalized:
            return set()

        tokens = {m.group(0) for m in re.finditer(r"[a-z0-9]{2,}", normalized)}
        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
            if len(segment) <= 4:
                tokens.add(segment)
            for size in (2, 3):
                if len(segment) < size:
                    continue
                for idx in range(len(segment) - size + 1):
                    gram = segment[idx: idx + size]
                    if len(set(gram)) == 1:
                        continue
                    tokens.add(gram)
        return tokens

    @staticmethod
    def _longest_common_span(a: str, b: str) -> int:
        """返回两个字符串的最长公共连续片段长度。"""
        if not a or not b:
            return 0
        return SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b)).size

    def _items_should_merge(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        """判断两个条目是否应归并为同一事件簇。"""
        left_url = str(left.get("url", "")).strip()
        right_url = str(right.get("url", "")).strip()
        if left_url and right_url and left_url == right_url:
            return True

        left_title = left.get("title_norm", "")
        right_title = right.get("title_norm", "")
        if not left_title or not right_title:
            return False
        if left_title == right_title:
            return True

        min_len = min(len(left_title), len(right_title))
        if min_len >= 10 and (left_title in right_title or right_title in left_title):
            return True

        title_ratio = SequenceMatcher(None, left_title, right_title).ratio()
        merge_ratio = SequenceMatcher(None, left.get("merge_norm", ""), right.get("merge_norm", "")).ratio()
        common_span = self._longest_common_span(left_title, right_title)
        left_tokens = left.get("tokens", set())
        right_tokens = right.get("tokens", set())
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        jaccard = (overlap / union) if union else 0.0

        if title_ratio >= 0.88:
            return True
        if common_span >= 12 and merge_ratio >= 0.5:
            return True
        if common_span >= 6 and overlap >= 4 and merge_ratio >= 0.34:
            return True
        if overlap >= 7 and jaccard >= 0.2 and merge_ratio >= 0.42:
            return True
        if overlap >= 5 and title_ratio >= 0.66:
            return True
        return False

    def _cluster_anchor_tokens(
        self,
        items: List[Dict[str, Any]],
        token_counts: Dict[str, int],
    ) -> set[str]:
        """提取簇级锚点 token，用于合并被拆碎的小簇。"""
        anchors = set()
        for item in items:
            for token in item.get("tokens", set()):
                if len(token) < 2:
                    continue
                if token in self.CLUSTER_STOP_TOKENS:
                    continue
                if token_counts.get(token, 0) < 2:
                    continue
                anchors.add(token)
        return anchors

    def _clusters_should_merge(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        """对初始簇做二次合并，修正同一主体下被拆散的小簇。"""
        shared_anchors = left.get("anchor_tokens", set()) & right.get("anchor_tokens", set())
        if not shared_anchors:
            return False

        left_title = self._normalize_similarity_text(left.get("representative", {}).get("title", ""))
        right_title = self._normalize_similarity_text(right.get("representative", {}).get("title", ""))
        title_ratio = SequenceMatcher(None, left_title, right_title).ratio()
        common_span = self._longest_common_span(left_title, right_title)
        small_side = min(int(left.get("event_count", 0)), int(right.get("event_count", 0))) <= 2
        has_strong_anchor = any(len(token) >= 3 for token in shared_anchors)

        if common_span >= 6:
            return True
        if title_ratio >= 0.48:
            return True
        if small_side and has_strong_anchor and common_span >= 2:
            return True
        return False

    @staticmethod
    def _parse_event_count(value: Any) -> int:
        """解析事件数量字段。"""
        try:
            return max(int(str(value or "0").strip() or "0"), 0)
        except (TypeError, ValueError):
            return 0

    def _parse_item_ids(self, value: Any) -> List[str]:
        """解析 AI 返回的条目编号列表。"""
        if isinstance(value, list):
            candidates = value
        else:
            text = self._clean_ai_text(value)
            if not text:
                return []
            candidates = re.split(r"[\s,，;；|]+", text)

        item_ids: List[str] = []
        seen = set()
        for raw in candidates:
            normalized = self._normalize_analysis_item_id(raw)
            if normalized and normalized not in seen:
                seen.add(normalized)
                item_ids.append(normalized)
        return item_ids

    def _build_cluster_meta_from_item_ids(
        self,
        item_ids: List[str],
        *,
        used_item_ids: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """按 AI 选中的编号条目回填事件簇元数据。"""
        used_item_ids = set(used_item_ids or set())
        resolved_items: List[Dict[str, Any]] = []
        seen_ids = set()

        for item_id in item_ids:
            normalized_id = self._normalize_analysis_item_id(item_id)
            if not normalized_id or normalized_id in seen_ids or normalized_id in used_item_ids:
                continue
            payload = self._analysis_item_lookup.get(normalized_id)
            if not payload:
                continue
            seen_ids.add(normalized_id)
            resolved_items.append(payload)

        if not resolved_items:
            return {}

        source_mix_counts = {"hotlist": 0, "rss": 0, "social": 0}
        event_items: List[Dict[str, str]] = []
        seen_event_keys = set()
        representative_title = ""

        for item in resolved_items:
            source_type = str(item.get("source_type") or "")
            if source_type in source_mix_counts:
                source_mix_counts[source_type] += 1

            if not representative_title:
                representative_title = self._clean_ai_text(item.get("title"))

            payload = self._build_cluster_event_item(item)
            event_key = (
                payload.get("title", ""),
                payload.get("source_type", ""),
                payload.get("source_name", ""),
                payload.get("time_label", ""),
            )
            if event_key in seen_event_keys:
                continue
            seen_event_keys.add(event_key)
            event_items.append(payload)

        return {
            "item_ids": [str(item.get("analysis_id")) for item in resolved_items if item.get("analysis_id")],
            "event_count": str(len(resolved_items)),
            "source_mix": self._format_source_mix_text(source_mix_counts),
            "items": event_items,
            "candidate_title": representative_title,
        }

    def _is_strong_cluster_token(self, token: str) -> bool:
        """判断 token 是否足够强，适合用于事件簇合并。"""
        if not token:
            return False
        if re.fullmatch(r"[a-z0-9]{4,}", token):
            return True
        if len(token) >= 3 and all("\u4e00" <= ch <= "\u9fff" for ch in token):
            return True
        return False

    @staticmethod
    def _format_source_mix_text(source_mix: Dict[str, int]) -> str:
        """统一格式化来源混合文案。"""
        parts = []
        if int(source_mix.get("hotlist", 0) or 0):
            parts.append(f"热榜 {int(source_mix['hotlist'])}")
        if int(source_mix.get("rss", 0) or 0):
            parts.append(f"网站 {int(source_mix['rss'])}")
        if int(source_mix.get("social", 0) or 0):
            parts.append(f"媒体 {int(source_mix['social'])}")
        return " / ".join(parts) if parts else "单源 1"

    def _merge_cluster_meta_bundle(self, metas: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并多个程序候选事件簇的元数据。"""
        if not metas:
            return {}

        primary = metas[0]
        source_mix_counts = {"hotlist": 0, "rss": 0, "social": 0}
        merged_titles: List[str] = []
        merged_items: List[Dict[str, Any]] = []
        seen_item_keys = set()
        merged_anchor_tokens = set()
        merged_candidate_tokens = set()
        merged_cluster_ids: List[str] = []
        total_event_count = 0

        for meta in metas:
            cluster_id = str(meta.get("cluster_id") or "").strip()
            if cluster_id and cluster_id not in merged_cluster_ids:
                merged_cluster_ids.append(cluster_id)

            total_event_count += self._parse_event_count(meta.get("event_count"))

            counts = meta.get("source_mix_counts") or {}
            for key in source_mix_counts:
                source_mix_counts[key] += int(counts.get(key, 0) or 0)

            merged_anchor_tokens.update(meta.get("anchor_tokens") or [])
            merged_candidate_tokens.update(meta.get("candidate_tokens") or [])

            candidate_title = self._clean_ai_text(meta.get("candidate_title"))
            if candidate_title:
                merged_titles.append(candidate_title)

            for item in meta.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_key = (
                    self._clean_ai_text(item.get("title")),
                    self._clean_ai_text(item.get("source_type")),
                    self._clean_ai_text(item.get("source_name")),
                    self._clean_ai_text(item.get("time_label")),
                    self._clean_ai_text(item.get("url")),
                )
                if item_key in seen_item_keys:
                    continue
                seen_item_keys.add(item_key)
                merged_items.append(item)

        return {
            **primary,
            "cluster_id": primary.get("cluster_id", ""),
            "merged_cluster_ids": merged_cluster_ids,
            "candidate_title": primary.get("candidate_title") or (merged_titles[0] if merged_titles else ""),
            "event_count": str(total_event_count or self._parse_event_count(primary.get("event_count")) or 1),
            "source_mix_counts": source_mix_counts,
            "source_mix": self._format_source_mix_text(source_mix_counts),
            "match_text": " ".join(merged_titles).strip(),
            "anchor_tokens": sorted(merged_anchor_tokens),
            "candidate_tokens": sorted(merged_candidate_tokens),
            "items": merged_items,
        }

    def _expand_cluster_meta(
        self,
        meta: Dict[str, Any],
        used_cluster_ids: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """将被拆散但明显属于同一主线的小簇合并回主簇。"""
        if not meta:
            return {}

        used_cluster_ids = set(used_cluster_ids or set())
        base_title = self._clean_ai_text(meta.get("candidate_title"))
        base_title_norm = self._normalize_similarity_text(base_title)
        base_tokens = set(meta.get("anchor_tokens") or meta.get("candidate_tokens") or [])
        bundles = [meta]

        for candidate in self._cluster_lookup.values():
            candidate_id = str(candidate.get("cluster_id") or "").strip()
            if not candidate_id or candidate_id == meta.get("cluster_id"):
                continue
            if candidate_id in used_cluster_ids:
                continue

            shared_tokens = base_tokens & set(candidate.get("anchor_tokens") or candidate.get("candidate_tokens") or [])
            strong_shared = {token for token in shared_tokens if self._is_strong_cluster_token(token)}
            if not strong_shared:
                continue

            candidate_title = self._clean_ai_text(candidate.get("candidate_title"))
            candidate_title_norm = self._normalize_similarity_text(candidate_title)
            title_ratio = SequenceMatcher(None, base_title_norm, candidate_title_norm).ratio() if base_title_norm and candidate_title_norm else 0.0
            common_span = self._longest_common_span(base_title_norm, candidate_title_norm)

            if title_ratio >= 0.42 or common_span >= 4 or len(strong_shared) >= 2:
                bundles.append(candidate)
                base_tokens.update(candidate.get("anchor_tokens") or [])

        return self._merge_cluster_meta_bundle(bundles)

    def _split_ai_entries(self, text: str) -> List[str]:
        """将 AI 的编号列表切成独立条目。"""
        cleaned = self._clean_ai_text(text)
        if not cleaned:
            return []
        normalized = re.sub(r"(?<=[^\n])\s+(\d+\.)(?!\d)", r"\n\1", cleaned)
        entries = []
        for part in re.split(r"\n\s*(?=\d+\.)", normalized):
            item = self._clean_ai_text(part)
            if item:
                entries.append(item)
        return entries

    def _normalize_event_clusters(self, clusters: Any) -> List[Dict[str, Any]]:
        """规范化新 schema 的事件簇结构。"""
        if not isinstance(clusters, list):
            return []

        normalized: List[Dict[str, Any]] = []
        used_cluster_ids: set[str] = set()
        used_item_ids: set[str] = set()
        for index, item in enumerate(clusters, start=1):
            if not isinstance(item, dict):
                continue
            title = self._clean_ai_text(
                item.get("title") or item.get("cluster_title") or item.get("name")
            )
            event_count = self._clean_ai_text(
                item.get("event_count") or item.get("related_count") or item.get("count")
            )
            summary = self._clean_ai_text(
                item.get("summary")
                or item.get("judgement")
                or item.get("description")
                or item.get("primary")
            )
            risk = self._clean_ai_text(
                item.get("risk") or item.get("risk_point") or item.get("controversy")
            )
            action = self._clean_ai_text(
                item.get("action")
                or item.get("suggestion")
                or item.get("strategy")
                or item.get("watchpoint")
            )
            if not any([title, summary, risk, action]):
                continue
            cluster_id = self._normalize_cluster_id(item.get("cluster_id")) or f"C{index}"
            cluster_meta = {}

            item_ids = self._parse_item_ids(
                item.get("item_ids") or item.get("news_ids") or item.get("items")
            )
            if item_ids:
                cluster_meta = self._build_cluster_meta_from_item_ids(
                    item_ids,
                    used_item_ids=used_item_ids,
                )
                used_item_ids.update(cluster_meta.get("item_ids") or [])

            if not cluster_meta:
                cluster_meta = self._resolve_cluster_meta(
                    cluster_id,
                    title=title,
                    summary=summary,
                    used_cluster_ids=used_cluster_ids,
                )
                resolved_cluster_id = str(cluster_meta.get("cluster_id") or cluster_id).strip()
                merged_cluster_ids = [
                    str(value).strip()
                    for value in (cluster_meta.get("merged_cluster_ids") or [])
                    if str(value).strip()
                ]
                if merged_cluster_ids:
                    used_cluster_ids.update(merged_cluster_ids)
                elif resolved_cluster_id:
                    used_cluster_ids.add(resolved_cluster_id)
            else:
                resolved_cluster_id = cluster_id

            normalized.append(
                {
                    "cluster_id": resolved_cluster_id,
                    "title": title or cluster_meta.get("candidate_title") or self._derive_cluster_title(summary, f"重点事件簇 {index}"),
                    "event_count": cluster_meta.get("event_count") or event_count or "1",
                    "source_mix": cluster_meta.get("source_mix") or "",
                    "summary": summary or "暂无显著信号",
                    "risk": risk,
                    "action": action,
                    "item_ids": cluster_meta.get("item_ids") or item_ids,
                    "items": cluster_meta.get("items") or [],
                }
            )
        return self._prioritize_security_related_china_cluster(normalized)

    @staticmethod
    def _contains_any_keyword(text: str, keywords: List[str]) -> bool:
        """判断文本是否包含任一关键词。"""
        return any(keyword in text for keyword in keywords)

    def _is_security_related_china_cluster(self, cluster: Dict[str, Any]) -> bool:
        """识别是否属于应优先置顶的涉华安全事件簇。"""
        text_parts = [
            self._clean_ai_text(cluster.get("title")),
            self._clean_ai_text(cluster.get("summary")),
            self._clean_ai_text(cluster.get("risk")),
            self._clean_ai_text(cluster.get("action")),
        ]

        combined = " ".join(part for part in text_parts if part)
        if not combined:
            return False

        china_keywords = [
            "涉华", "对华", "中方", "中国政府", "中国外交", "中国间谍", "中国间谍机构",
            "香港", "港澳", "台湾", "台海", "南海", "东海", "中美", "中欧", "中日",
            "中菲", "中印", "国际涉华", "国际形象",
        ]
        security_keywords = [
            "安全", "国家安全", "外交", "国安", "间谍", "制裁", "反制", "军队", "军方",
            "军演", "演训", "情报", "边境", "执法", "港澳台海", "周边局势", "军事",
            "国防", "网络攻击", "黑客", "司法判决", "定罪", "指控",
        ]

        has_china_signal = self._contains_any_keyword(combined, china_keywords)
        has_security_signal = self._contains_any_keyword(combined, security_keywords)
        return has_china_signal and has_security_signal

    def _prioritize_security_related_china_cluster(
        self,
        clusters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """若存在涉华安全相关事件簇，则将其稳定置于首位。"""
        if len(clusters) <= 1:
            return clusters

        prioritized_index = next(
            (
                index
                for index, cluster in enumerate(clusters)
                if isinstance(cluster, dict) and self._is_security_related_china_cluster(cluster)
            ),
            None,
        )
        if prioritized_index in (None, 0):
            return clusters

        return [clusters[prioritized_index], *clusters[:prioritized_index], *clusters[prioritized_index + 1 :]]

    def _derive_legacy_fields_from_new_schema(self, result: AIAnalysisResult) -> None:
        """将新 schema 反向映射到旧字段，兼容历史推送链路。"""
        clusters = result.event_clusters or []
        if not result.today_judgement and not clusters:
            return

        if not result.core_trends and clusters:
            result.core_trends = "\n".join(
                f"{index}. {cluster['title']}：{cluster['summary']}"
                for index, cluster in enumerate(clusters, start=1)
            )

        if not result.sentiment_controversy:
            risk_lines = [
                f"{index}. {cluster['title']}：{cluster['risk']}"
                for index, cluster in enumerate(clusters, start=1)
                if cluster.get("risk")
            ]
            result.sentiment_controversy = "\n".join(risk_lines)

        if not result.outlook_strategy:
            action_lines = [
                f"{index}. {cluster['title']}：{cluster['action']}"
                for index, cluster in enumerate(clusters, start=1)
                if cluster.get("action")
            ]
            result.outlook_strategy = "\n".join(action_lines)

        if not result.signals and len(clusters) > 1:
            result.signals = "\n".join(
                f"{index}. {cluster['title']}：{cluster['summary']}"
                for index, cluster in enumerate(clusters[1:], start=1)
            )

    def _derive_new_schema_from_legacy_fields(self, result: AIAnalysisResult) -> None:
        """用旧字段推导首页需要的新结构。"""
        if result.event_clusters:
            if not result.today_judgement:
                summary_candidates = [
                    self._clean_ai_text(result.core_trends),
                    self._clean_ai_text(result.rss_insights),
                    self._clean_ai_text(result.sentiment_controversy),
                    self._clean_ai_text(result.signals),
                ]
                result.today_judgement = " ".join(
                    [item for item in summary_candidates[:2] if item]
                ).strip() or "暂无显著信号"
            return

        core_entries = self._split_ai_entries(result.core_trends)
        sentiment_entries = self._split_ai_entries(result.sentiment_controversy)
        signal_entries = self._split_ai_entries(result.signals)
        rss_entries = self._split_ai_entries(result.rss_insights)
        outlook_entries = self._split_ai_entries(result.outlook_strategy)

        summary_candidates = [
            self._clean_ai_text(entry)
            for entry in [*core_entries, *rss_entries, *sentiment_entries, *signal_entries]
            if self._clean_ai_text(entry)
        ]
        if not result.today_judgement:
            result.today_judgement = " ".join(summary_candidates[:2]).strip() or "暂无显著信号"

        used_primary = set()

        def take_unique(candidates: List[str]) -> str:
            for entry in candidates:
                cleaned = self._clean_ai_text(entry)
                if cleaned and cleaned not in used_primary:
                    used_primary.add(cleaned)
                    return cleaned
            return ""

        derived = [
            {
                "title": "",
                "summary": take_unique([*core_entries, *rss_entries]),
                "risk": self._clean_ai_text((sentiment_entries + signal_entries + [""])[0]),
                "action": self._clean_ai_text((outlook_entries + [""])[0]),
            },
            {
                "title": "",
                "summary": take_unique([*sentiment_entries, *signal_entries, *core_entries]),
                "risk": self._clean_ai_text((signal_entries + sentiment_entries[1:] + [""])[0]),
                "action": self._clean_ai_text((outlook_entries[1:] + outlook_entries[:1] + [""])[0]),
            },
            {
                "title": "",
                "summary": take_unique([*rss_entries, *signal_entries, *outlook_entries, *core_entries]),
                "risk": self._clean_ai_text((sentiment_entries[1:] + signal_entries[1:] + [""])[0]),
                "action": self._clean_ai_text((outlook_entries[2:] + rss_entries[1:] + outlook_entries[:1] + [""])[0]),
            },
        ]

        clusters: List[Dict[str, str]] = []
        for index, cluster in enumerate(derived, start=1):
            summary = self._clean_ai_text(cluster["summary"])
            if not summary:
                continue
            title = self._derive_cluster_title(summary, f"重点事件簇 {index}")
            clusters.append(
                {
                    "cluster_id": "",
                    "title": title,
                    "event_count": "1",
                    "summary": summary,
                    "risk": self._clean_ai_text(cluster["risk"]),
                    "action": self._clean_ai_text(cluster["action"]),
                }
            )
        result.event_clusters = self._prioritize_security_related_china_cluster(clusters)

    def _select_analysis_items(
        self,
        stats: List[Dict],
        rss_stats: Optional[List[Dict]] = None,
        social_items: Optional[List[Dict]] = None,
    ) -> tuple[list[dict], int, int, int]:
        """按 AI 实际发送顺序选出分析条目，用于正文与程序聚类共用。"""
        selected_items: List[Dict[str, Any]] = []
        news_count = 0
        rss_count = 0
        social_count = 0
        analysis_index = 1

        hotlist_total = sum(len(s.get("titles", [])) for s in stats) if stats else 0
        rss_total = sum(len(s.get("titles", [])) for s in rss_stats) if rss_stats else 0
        social_total = len(social_items) if social_items else 0

        def append_selected(payload: Dict[str, Any]) -> None:
            nonlocal analysis_index
            selected_items.append(
                {
                    **payload,
                    "analysis_id": f"N{analysis_index}",
                }
            )
            analysis_index += 1

        def normalize_social_comments(raw_comments: Any) -> List[Dict[str, str]]:
            """提取可发送给 AI 的轻量代表性评论。"""
            if not isinstance(raw_comments, list):
                return []

            normalized_comments: List[Dict[str, str]] = []
            for comment in raw_comments[:3]:
                if isinstance(comment, dict):
                    text = self._clean_ai_text(comment.get("text"))
                    stance = self._clean_ai_text(comment.get("stance")) or "评论"
                else:
                    text = self._clean_ai_text(comment)
                    stance = "评论"
                if not text or text == "暂无评论":
                    continue
                text = re.sub(r"^(?:@[A-Za-z0-9_]{1,20}\s*)+", "", text).strip()
                text = re.sub(r"\s+", " ", text)
                if not text:
                    continue
                normalized_comments.append(
                    {
                        "stance": stance,
                        "text": text[:220],
                    }
                )
            return normalized_comments

        if stats:
            for stat in stats:
                word = stat.get("word", "")
                for item in stat.get("titles", []):
                    if self.max_news is not None and news_count >= self.max_news:
                        break
                    if not isinstance(item, dict):
                        continue
                    title = self._clean_ai_text(item.get("title"))
                    if not title:
                        continue
                    append_selected(
                        {
                            "source_type": "hotlist",
                            "group": word,
                            "title": title,
                            "source_name": self._clean_ai_text(item.get("source_name") or item.get("source")),
                            "url": self._clean_ai_text(item.get("url")),
                            "mobile_url": self._clean_ai_text(item.get("mobile_url")),
                            "first_time": self._clean_ai_text(item.get("first_time")),
                            "last_time": self._clean_ai_text(item.get("last_time")),
                            "ranks": item.get("ranks", []) or [],
                            "count": int(item.get("count", 1) or 1),
                            "content": "",
                        }
                    )
                    news_count += 1
                if self.max_news is not None and news_count >= self.max_news:
                    break

        if self.include_rss and rss_stats:
            remaining = None if self.max_news is None else max(self.max_news - news_count, 0)
            for stat in rss_stats:
                if remaining is not None and rss_count >= remaining:
                    break
                word = stat.get("word", "")
                for item in stat.get("titles", []):
                    if remaining is not None and rss_count >= remaining:
                        break
                    if not isinstance(item, dict):
                        continue
                    title = self._clean_ai_text(item.get("title"))
                    if not title:
                        continue
                    append_selected(
                        {
                            "source_type": "rss",
                            "group": word,
                            "title": title,
                            "source_name": self._clean_ai_text(item.get("source_name") or item.get("feed_name")),
                            "url": self._clean_ai_text(item.get("url")),
                            "published_at": self._clean_ai_text(item.get("published_at") or item.get("first_time")),
                            "time_display": self._clean_ai_text(item.get("time_display")),
                            "count": int(item.get("count", 1) or 1),
                            "content": self._clean_ai_text(item.get("summary") or item.get("match_text")),
                        }
                    )
                    rss_count += 1

        if self.include_social and social_items:
            remaining = None if self.max_news is None else max(self.max_news - news_count - rss_count, 0)
            social_iterable = social_items if remaining is None else social_items[:remaining]
            for item in social_iterable:
                if not isinstance(item, dict):
                    continue
                title = self._clean_ai_text(item.get("title")) or self._clean_ai_text(item.get("content"))[:120]
                if not title:
                    continue
                content = self._clean_ai_text(item.get("content"))
                comments = normalize_social_comments(item.get("representative_comments"))
                content_for_analysis = content
                if comments:
                    comments_text = " ".join(
                        f"评论{index}({comment['stance']}): {comment['text']}"
                        for index, comment in enumerate(comments, start=1)
                    )
                    content_for_analysis = f"{content} {comments_text}".strip()
                append_selected(
                    {
                        "source_type": "social",
                        "group": self._clean_ai_text(item.get("source_name")) or "社交媒体",
                        "title": title,
                        "source_name": self._clean_ai_text(item.get("source_name")),
                        "author": self._clean_ai_text(item.get("author")),
                        "url": self._clean_ai_text(item.get("url")),
                        "published_at": self._clean_ai_text(item.get("published_at")),
                        "count": 1,
                        "content": content_for_analysis,
                        "post_content": content,
                        "comments": comments,
                    }
                )
                social_count += 1

        return selected_items, hotlist_total, rss_total, social_total

    def _build_cluster_event_item(self, item: Dict[str, Any]) -> Dict[str, str]:
        """提取事件簇翻转卡片需要的轻量事件条目。"""
        source_type = str(item.get("source_type") or "")
        source_type_label = {
            "hotlist": "热榜",
            "rss": "网站",
            "social": "媒体",
        }.get(source_type, "来源")

        time_label = self._clean_ai_text(item.get("time_display"))
        if not time_label:
            first_time = self._clean_ai_text(item.get("first_time"))
            last_time = self._clean_ai_text(item.get("last_time"))
            published_at = self._clean_ai_text(item.get("published_at"))
            if first_time and last_time and first_time != last_time:
                time_label = f"{first_time}~{last_time}"
            else:
                time_label = last_time or first_time or published_at

        title_candidates = [
            self._clean_ai_text(item.get("translated_title")),
            self._clean_ai_text(item.get("title_zh")),
            self._clean_ai_text(item.get("translated_text")),
            self._clean_ai_text(item.get("title")),
        ]
        content_candidates = [
            self._clean_ai_text(item.get("translated_content")),
            self._clean_ai_text(item.get("content_zh")),
            self._clean_ai_text(item.get("summary_zh")),
            self._clean_ai_text(item.get("summary")),
            self._clean_ai_text(item.get("content")),
        ]

        def has_cjk(text: str) -> bool:
            return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text or ""))

        title_text = ""
        for candidate in title_candidates:
            if candidate and has_cjk(candidate):
                title_text = candidate
                break
        if not title_text:
            for candidate in title_candidates:
                if candidate:
                    title_text = candidate
                    break
        if title_text and not has_cjk(title_text):
            for candidate in content_candidates:
                if candidate and has_cjk(candidate):
                    title_text = candidate[:120].strip()
                    break

        return {
            "title": title_text or self._clean_ai_text(item.get("title")),
            "source_type": source_type,
            "source_type_label": source_type_label,
            "source_name": self._clean_ai_text(item.get("source_name")) or source_type_label,
            "url": self._clean_ai_text(item.get("url") or item.get("mobile_url")),
            "time_label": time_label,
        }

    def _build_analysis_item_index_context(self, selected_items: List[Dict[str, Any]]) -> str:
        """构建给 AI 的编号条目说明，并建立条目编号索引。"""
        self._analysis_item_lookup = {}
        if not selected_items:
            return "无"

        for item in selected_items:
            analysis_id = self._normalize_analysis_item_id(item.get("analysis_id"))
            if not analysis_id:
                continue
            self._analysis_item_lookup[analysis_id] = dict(item)

        if self._analysis_item_lookup:
            print(f"[AI] 已建立 {len(self._analysis_item_lookup)} 条编号候选条目")
        return (
            "下文热榜、RSS 和社交媒体条目都带有唯一编号 [Nxx]。"
            "event_clusters 必须通过 item_ids 直接引用这些编号；"
            "不要引用不存在的编号，也不要把明显无关的编号硬归为同一事件簇。"
        )

    def _build_program_cluster_context(self, selected_items: List[Dict[str, Any]]) -> str:
        """基于已选分析条目做程序预聚类，并生成给 AI 的候选上下文。"""
        self._cluster_lookup = {}
        if not selected_items:
            return "无"

        prepared_items: List[Dict[str, Any]] = []
        for index, item in enumerate(selected_items):
            content = self._clean_ai_text(item.get("content"))
            merge_text = " ".join(part for part in [item.get("title", ""), content[:160]] if part)
            prepared_items.append(
                {
                    **item,
                    "_index": index,
                    "title_norm": self._normalize_similarity_text(item.get("title", "")),
                    "merge_norm": self._normalize_similarity_text(merge_text),
                    "tokens": self._extract_similarity_tokens(merge_text),
                }
            )

        parent = list(range(len(prepared_items)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            root_a = find(a)
            root_b = find(b)
            if root_a != root_b:
                parent[root_b] = root_a

        for left in range(len(prepared_items)):
            for right in range(left + 1, len(prepared_items)):
                if self._items_should_merge(prepared_items[left], prepared_items[right]):
                    union(left, right)

        grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for item in prepared_items:
            grouped[find(item["_index"])].append(item)

        token_counts: Dict[str, int] = defaultdict(int)
        for item in prepared_items:
            for token in item.get("tokens", set()):
                if len(token) >= 2 and token not in self.CLUSTER_STOP_TOKENS:
                    token_counts[token] += 1

        def item_priority(item: Dict[str, Any]) -> tuple:
            source_weight = {"hotlist": 3, "rss": 2, "social": 1}.get(str(item.get("source_type")), 0)
            ranks = item.get("ranks", []) or []
            best_rank = min(ranks) if ranks else 999
            return (
                -source_weight,
                best_rank,
                -int(item.get("count", 1) or 1),
                item.get("published_at", ""),
                item.get("title", ""),
            )

        candidate_clusters = []
        for items in grouped.values():
            ordered_items = sorted(items, key=item_priority)
            representative = ordered_items[0]
            source_type_counts = {
                "hotlist": sum(1 for item in ordered_items if item.get("source_type") == "hotlist"),
                "rss": sum(1 for item in ordered_items if item.get("source_type") == "rss"),
                "social": sum(1 for item in ordered_items if item.get("source_type") == "social"),
            }
            unique_sources = len(
                {
                    (item.get("source_type"), item.get("source_name"))
                    for item in ordered_items
                    if item.get("source_name")
                }
            )
            score = (
                len(ordered_items) * 10
                + source_type_counts["hotlist"] * 5
                + source_type_counts["rss"] * 3
                + source_type_counts["social"] * 2
                + unique_sources
            )
            candidate_clusters.append(
                {
                    "items": ordered_items,
                    "representative": representative,
                    "score": score,
                    "event_count": len(ordered_items),
                    "source_mix": source_type_counts,
                    "anchor_tokens": self._cluster_anchor_tokens(ordered_items, token_counts),
                }
            )

        merge_changed = True
        while merge_changed and len(candidate_clusters) > 1:
            merge_changed = False
            for left_index in range(len(candidate_clusters)):
                if merge_changed:
                    break
                for right_index in range(left_index + 1, len(candidate_clusters)):
                    left_cluster = candidate_clusters[left_index]
                    right_cluster = candidate_clusters[right_index]
                    if not self._clusters_should_merge(left_cluster, right_cluster):
                        continue

                    merged_items = sorted(
                        [*left_cluster["items"], *right_cluster["items"]],
                        key=item_priority,
                    )
                    merged_source_mix = {
                        "hotlist": left_cluster["source_mix"]["hotlist"] + right_cluster["source_mix"]["hotlist"],
                        "rss": left_cluster["source_mix"]["rss"] + right_cluster["source_mix"]["rss"],
                        "social": left_cluster["source_mix"]["social"] + right_cluster["source_mix"]["social"],
                    }
                    merged_unique_sources = len(
                        {
                            (item.get("source_type"), item.get("source_name"))
                            for item in merged_items
                            if item.get("source_name")
                        }
                    )
                    merged_score = (
                        len(merged_items) * 10
                        + merged_source_mix["hotlist"] * 5
                        + merged_source_mix["rss"] * 3
                        + merged_source_mix["social"] * 2
                        + merged_unique_sources
                    )
                    candidate_clusters[left_index] = {
                        "items": merged_items,
                        "representative": merged_items[0],
                        "score": merged_score,
                        "event_count": len(merged_items),
                        "source_mix": merged_source_mix,
                        "anchor_tokens": self._cluster_anchor_tokens(merged_items, token_counts),
                    }
                    del candidate_clusters[right_index]
                    merge_changed = True
                    break

        candidate_clusters.sort(
            key=lambda item: (
                -item["score"],
                -item["event_count"],
                item["representative"].get("title", ""),
            )
        )

        rendered_blocks = []
        for index, cluster in enumerate(candidate_clusters[: self.max_program_clusters], start=1):
            cluster_id = f"C{index}"
            representative = cluster["representative"]
            representative_title = self._clean_ai_text(representative.get("title")) or f"重点事件簇 {index}"
            items = cluster["items"]
            source_mix = cluster["source_mix"]
            mix_text = self._format_source_mix_text(source_mix)

            cluster_event_items: List[Dict[str, str]] = []
            seen_event_keys = set()
            seen_titles = set()
            representative_lines = []
            for item in items:
                title = self._clean_ai_text(item.get("title"))
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                source_type_label = {"hotlist": "热榜", "rss": "网站", "social": "媒体"}.get(
                    str(item.get("source_type", "")),
                    "来源",
                )
                source_name = self._clean_ai_text(item.get("source_name")) or source_type_label
                representative_lines.append(f"- [{source_type_label}][{source_name}] {title}")
                if len(representative_lines) >= 5:
                    break

            for item in items:
                payload = self._build_cluster_event_item(item)
                title = payload.get("title", "")
                if not title:
                    continue
                event_key = (
                    title,
                    payload.get("source_type", ""),
                    payload.get("source_name", ""),
                    payload.get("time_label", ""),
                )
                if event_key in seen_event_keys:
                    continue
                seen_event_keys.add(event_key)
                cluster_event_items.append(payload)

            self._cluster_lookup[cluster_id] = {
                "cluster_id": cluster_id,
                "candidate_title": representative_title,
                "event_count": str(cluster["event_count"]),
                "source_mix": mix_text,
                "source_mix_counts": dict(source_mix),
                "match_text": " ".join(
                    self._clean_ai_text(item.get("title")) for item in items if item.get("title")
                ),
                "anchor_tokens": sorted(cluster.get("anchor_tokens") or []),
                "candidate_tokens": sorted(self._extract_similarity_tokens(representative_title)),
                "items": cluster_event_items,
            }

            rendered_blocks.append(
                "\n".join(
                    [
                        f"### [{cluster_id}] {representative_title}",
                        f"- event_count: {cluster['event_count']}",
                        f"- source_mix: {mix_text}",
                        "- representative_items:",
                        *representative_lines,
                    ]
                )
            )

        if self._cluster_lookup:
            print(f"[AI] 程序预聚类生成 {len(self._cluster_lookup)} 个候选事件簇")
        return "\n\n".join(rendered_blocks) if rendered_blocks else "无"

    def _resolve_cluster_meta(
        self,
        cluster_id: str,
        title: str = "",
        summary: str = "",
        used_cluster_ids: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """按 cluster_id 优先，必要时按标题/摘要回查程序候选。"""
        used_cluster_ids = set(used_cluster_ids or set())
        normalized_id = self._normalize_cluster_id(cluster_id)
        if normalized_id and normalized_id in self._cluster_lookup:
            if normalized_id in used_cluster_ids:
                return {}
            return self._expand_cluster_meta(
                self._cluster_lookup[normalized_id],
                used_cluster_ids=used_cluster_ids | {normalized_id},
            )

        title_query = self._normalize_similarity_text(title)
        summary_query = self._normalize_similarity_text(summary)
        query = title_query or summary_query
        if not query:
            return {}

        query_tokens = self._extract_similarity_tokens(title if title_query else summary)
        require_shared_tokens = bool(query_tokens and title_query)

        best_meta: Dict[str, Any] = {}
        best_score = 0.0
        for meta in self._cluster_lookup.values():
            candidate_id = str(meta.get("cluster_id") or "").strip()
            if candidate_id in used_cluster_ids:
                continue

            target = self._normalize_similarity_text(meta.get("candidate_title"))
            if not target:
                continue

            candidate_tokens = set(meta.get("candidate_tokens") or meta.get("anchor_tokens") or [])
            shared_tokens = query_tokens & candidate_tokens
            strong_shared = {token for token in shared_tokens if self._is_strong_cluster_token(token)}
            if require_shared_tokens and not strong_shared:
                continue

            ratio = SequenceMatcher(None, query, target).ratio()
            common_span = self._longest_common_span(query, target)
            score = ratio + min(common_span, 10) / 18 + min(len(strong_shared), 3) * 0.12
            if title_query and ratio < 0.44 and common_span < 4:
                continue
            if score > best_score:
                best_meta = meta
                best_score = score

        if not best_meta:
            return {}

        threshold = 1.0 if require_shared_tokens else 1.06
        if best_score < threshold:
            return {}

        best_cluster_id = str(best_meta.get("cluster_id") or "").strip()
        return self._expand_cluster_meta(
            best_meta,
            used_cluster_ids=used_cluster_ids | ({best_cluster_id} if best_cluster_id else set()),
        )

    def _load_prompt_template(self, prompt_file: str) -> tuple:
        """加载提示词模板"""
        config_dir = Path(__file__).parent.parent.parent / "config"
        prompt_path = config_dir / prompt_file

        if not prompt_path.exists():
            print(f"[AI] 提示词文件不存在: {prompt_path}")
            return "", ""

        content = prompt_path.read_text(encoding="utf-8")

        # 解析 [system] 和 [user] 部分
        system_prompt = ""
        user_prompt = ""

        if "[system]" in content and "[user]" in content:
            parts = content.split("[user]")
            system_part = parts[0]
            user_part = parts[1] if len(parts) > 1 else ""

            # 提取 system 内容
            if "[system]" in system_part:
                system_prompt = system_part.split("[system]")[1].strip()

            user_prompt = user_part.strip()
        else:
            # 整个文件作为 user prompt
            user_prompt = content

        return system_prompt, user_prompt

    def analyze(
        self,
        stats: List[Dict],
        rss_stats: Optional[List[Dict]] = None,
        social_items: Optional[List[Dict]] = None,
        report_mode: str = "daily",
        report_type: str = "当日汇总",
        platforms: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        standalone_data: Optional[Dict] = None,
    ) -> AIAnalysisResult:
        """
        执行 AI 分析

        Args:
            stats: 热榜统计数据
            rss_stats: RSS 统计数据
            report_mode: 报告模式
            report_type: 报告类型
            platforms: 平台列表
            keywords: 关键词列表

        Returns:
            AIAnalysisResult: 分析结果
        """
        
        # 打印配置信息方便调试
        model = self.ai_config.get("MODEL", "unknown")
        api_key = self.client.api_key or ""
        api_base = self.ai_config.get("API_BASE", "")
        masked_key = f"{api_key[:5]}******" if len(api_key) >= 5 else "******"
        model_display = model.replace("/", "/\u200b") if model else "unknown"

        print(f"[AI] 模型: {model_display}")
        print(f"[AI] Key : {masked_key}")

        if api_base:
            print(f"[AI] 接口: 存在自定义 API 端点")

        timeout = self.ai_config.get("TIMEOUT", 120)
        max_tokens = self.ai_config.get("MAX_TOKENS", 5000)
        print(f"[AI] 参数: timeout={timeout}, max_tokens={max_tokens}")

        if not self.client.api_key:
            return AIAnalysisResult(
                success=False,
                error="未配置 AI API Key，请在 config.yaml 或环境变量 AI_API_KEY 中设置"
            )

        # 准备新闻内容并获取统计数据
        (
            news_content,
            rss_content,
            social_content,
            hotlist_total,
            rss_total,
            social_total,
            analyzed_count,
            item_index_content,
        ) = self._prepare_news_content(
            stats, rss_stats, social_items
        )
        total_news = hotlist_total + rss_total + social_total

        if not news_content and not rss_content and not social_content:
            return AIAnalysisResult(
                success=False,
                error="没有可分析的新闻内容",
                total_news=total_news,
                hotlist_count=hotlist_total,
                rss_count=rss_total,
                social_count=social_total,
                analyzed_news=0,
                max_news_limit=self.max_news_limit
            )

        # 构建提示词
        current_time = self.get_time_func().strftime("%Y-%m-%d %H:%M:%S")

        # 提取关键词
        if not keywords:
            keywords = [s.get("word", "") for s in stats if s.get("word")] if stats else []

        # 使用安全的字符串替换，避免模板中其他花括号（如 JSON 示例）被误解析
        user_prompt = self.user_prompt_template
        user_prompt = user_prompt.replace("{report_mode}", report_mode)
        user_prompt = user_prompt.replace("{report_type}", report_type)
        user_prompt = user_prompt.replace("{current_time}", current_time)
        user_prompt = user_prompt.replace("{news_count}", str(hotlist_total))
        user_prompt = user_prompt.replace("{rss_count}", str(rss_total))
        user_prompt = user_prompt.replace("{social_count}", str(social_total))
        user_prompt = user_prompt.replace("{platforms}", ", ".join(platforms) if platforms else "多平台")
        user_prompt = user_prompt.replace("{keywords}", ", ".join(keywords[:20]) if keywords else "无")
        user_prompt = user_prompt.replace("{item_index_content}", item_index_content or "无")
        user_prompt = user_prompt.replace("{news_content}", news_content)
        user_prompt = user_prompt.replace("{rss_content}", rss_content)
        user_prompt = user_prompt.replace("{social_content}", social_content)
        user_prompt = user_prompt.replace("{language}", self.language)

        # 构建独立展示区内容
        standalone_content = ""
        if self.include_standalone and standalone_data:
            standalone_content = self._prepare_standalone_content(standalone_data)
        user_prompt = user_prompt.replace("{standalone_content}", standalone_content)

        if self.debug:
            print("\n" + "=" * 80)
            print("[AI 调试] 发送给 AI 的完整提示词")
            print("=" * 80)
            if self.system_prompt:
                print("\n--- System Prompt ---")
                print(self.system_prompt)
            print("\n--- User Prompt ---")
            print(user_prompt)
            print("=" * 80 + "\n")

        # 调用 AI API（使用 LiteLLM）
        try:
            response = self._call_ai_with_retry(user_prompt)
            result = self._parse_response(response)

            # JSON 解析失败时的重试兜底（仅重试一次）
            if result.error and "JSON 解析错误" in result.error:
                print(f"[AI] JSON 解析失败，尝试让 AI 修复...")
                retry_result = self._retry_fix_json(response, result.error)
                if retry_result and retry_result.success and not retry_result.error:
                    print("[AI] JSON 修复成功")
                    retry_result.raw_response = response
                    result = retry_result
                else:
                    print("[AI] JSON 修复失败，使用原始文本兜底")

            # 如果配置未启用 RSS 分析，强制清空 AI 返回的 RSS 洞察
            if not self.include_rss:
                result.rss_insights = ""

            # 如果配置未启用 standalone 分析，强制清空
            if not self.include_standalone:
                result.standalone_summaries = {}

            # 填充统计数据
            result.total_news = total_news
            result.hotlist_count = hotlist_total
            result.rss_count = rss_total
            result.social_count = social_total
            result.analyzed_news = analyzed_count
            result.max_news_limit = self.max_news_limit
            return result
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            # 截断过长的错误消息
            if len(error_msg) > 200:
                error_msg = error_msg[:200] + "..."
            friendly_msg = f"AI 分析失败 ({error_type}): {error_msg}"

            return AIAnalysisResult(
                success=False,
                error=friendly_msg
            )

    def _prepare_news_content(
        self,
        stats: List[Dict],
        rss_stats: Optional[List[Dict]] = None,
        social_items: Optional[List[Dict]] = None,
    ) -> tuple:
        """
        准备新闻内容文本（增强版）

        热榜新闻包含：来源、标题、排名范围、时间范围、出现次数
        RSS 包含：来源、标题、发布时间

        Returns:
            tuple: (news_content, rss_content, social_content, hotlist_total, rss_total, social_total, analyzed_count)
        """
        news_lines = []
        rss_lines = []
        social_lines = []
        news_count = 0
        rss_count = 0
        social_count = 0

        # 计算总新闻数
        hotlist_total = sum(len(s.get("titles", [])) for s in stats) if stats else 0
        rss_total = sum(len(s.get("titles", [])) for s in rss_stats) if rss_stats else 0
        social_total = len(social_items) if social_items else 0

        selected_items, hotlist_total, rss_total, social_total = self._select_analysis_items(
            stats, rss_stats, social_items
        )

        item_index_content = self._build_analysis_item_index_context(selected_items)

        hotlist_group_sizes: Dict[str, int] = defaultdict(int)
        rss_group_sizes: Dict[str, int] = defaultdict(int)
        for item in selected_items:
            if item.get("source_type") == "hotlist":
                hotlist_group_sizes[str(item.get("group", ""))] += 1
            elif item.get("source_type") == "rss":
                rss_group_sizes[str(item.get("group", ""))] += 1

        rendered_hotlist_groups = set()
        rendered_rss_groups = set()

        for item in selected_items:
            source_type = item.get("source_type")
            if source_type == "hotlist":
                analysis_id = self._clean_ai_text(item.get("analysis_id"))
                word = str(item.get("group", ""))
                if word and word not in rendered_hotlist_groups:
                    news_lines.append(f"\n**{word}** ({hotlist_group_sizes.get(word, 0)}条)")
                    rendered_hotlist_groups.add(word)

                title = item.get("title", "")
                source = item.get("source_name", "")
                line = f"- [{analysis_id}] "
                line += f"[{source}] {title}" if source else title

                ranks = item.get("ranks", []) or []
                if ranks:
                    min_rank = min(ranks)
                    max_rank = max(ranks)
                    rank_str = f"{min_rank}" if min_rank == max_rank else f"{min_rank}-{max_rank}"
                else:
                    rank_str = "-"

                time_str = self._format_time_range(item.get("first_time", ""), item.get("last_time", ""))
                appear_count = item.get("count", 1)
                line += f" | 排名:{rank_str} | 时间:{time_str} | 出现:{appear_count}次"
                news_lines.append(line)
                news_count += 1

            elif source_type == "rss":
                analysis_id = self._clean_ai_text(item.get("analysis_id"))
                word = str(item.get("group", ""))
                if word and word not in rendered_rss_groups:
                    rss_lines.append(f"\n**{word}** ({rss_group_sizes.get(word, 0)}条)")
                    rendered_rss_groups.add(word)

                title = item.get("title", "")
                source = item.get("source_name", "")
                line = f"- [{analysis_id}] "
                line += f"[{source}] {title}" if source else title
                time_display = item.get("time_display", "")
                if time_display:
                    line += f" | {time_display}"
                rss_lines.append(line)
                rss_count += 1

            elif source_type == "social":
                analysis_id = self._clean_ai_text(item.get("analysis_id"))
                source = str(item.get("source_name", "")).strip()
                author = str(item.get("author", "")).strip()
                title = str(item.get("title", "")).strip()
                content = str(item.get("post_content") or item.get("content", "")).strip()
                comments = item.get("comments") or []
                published_at = str(item.get("published_at", "")).strip()

                line = f"- [{analysis_id}] "
                if source:
                    line += f"[{source}] "
                if author:
                    line += f"{author} "
                line += title or content[:120]
                if published_at:
                    line += f" | {published_at}"
                if content and content != title:
                    line += f"\n  摘要: {content.replace(chr(10), ' ').strip()[:180]}"
                if comments:
                    comment_parts = []
                    for index, comment in enumerate(comments[:3], start=1):
                        if not isinstance(comment, dict):
                            continue
                        comment_text = self._clean_ai_text(comment.get("text"))
                        if not comment_text:
                            continue
                        stance = self._clean_ai_text(comment.get("stance")) or "评论"
                        comment_parts.append(f"评论{index}({stance}): {comment_text[:160]}")
                    if comment_parts:
                        line += "\n  代表性评论: " + "；".join(comment_parts)
                social_lines.append(line)
                social_count += 1

        news_content = "\n".join(news_lines) if news_lines else ""
        rss_content = "\n".join(rss_lines) if rss_lines else ""
        social_content = "\n".join(social_lines) if social_lines else ""
        total_count = news_count + rss_count + social_count

        return (
            news_content,
            rss_content,
            social_content,
            hotlist_total,
            rss_total,
            social_total,
            total_count,
            item_index_content,
        )

    def _call_ai(self, user_prompt: str) -> str:
        """调用 AI API（使用 LiteLLM）"""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        return self.client.chat(messages)

    def _call_ai_with_retry(self, user_prompt: str) -> str:
        """调用 AI API，并对空响应做有限重试。"""
        attempts = max(1, int(self.empty_response_retries) + 1)
        last_response = ""

        for attempt in range(1, attempts + 1):
            response = self._call_ai(user_prompt)
            if response and response.strip():
                return response

            last_response = response or ""
            if attempt < attempts:
                print(
                    f"[AI] 第 {attempt} 次返回空响应，"
                    f"{self.empty_response_retry_delay} 秒后重试..."
                )
                time.sleep(max(0, self.empty_response_retry_delay))

        return last_response

    def _retry_fix_json(self, original_response: str, error_msg: str) -> Optional[AIAnalysisResult]:
        """
        JSON 解析失败时，请求 AI 修复 JSON（仅重试一次）

        使用轻量 prompt，不重复原始分析的 system prompt，节省 token。

        Args:
            original_response: AI 原始响应（JSON 格式有误）
            error_msg: JSON 解析的错误信息

        Returns:
            修复后的分析结果，失败时返回 None
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个 JSON 修复助手。用户会提供一段格式有误的 JSON 和错误信息，"
                    "你需要修复 JSON 格式错误并返回正确的 JSON。\n"
                    "常见问题：字符串值内的双引号未转义、缺少逗号、字符串未正确闭合等。\n"
                    "只返回纯 JSON，不要包含 markdown 代码块标记（如 ```json）或任何说明文字。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"以下 JSON 解析失败：\n\n"
                    f"错误：{error_msg}\n\n"
                    f"原始内容：\n{original_response}\n\n"
                    f"请修复以上 JSON 中的格式问题（如值中的双引号改用中文引号「」或转义 \\\"、"
                    f"缺少逗号、不完整的字符串等），保持原始内容语义不变，只修复格式。"
                    f"直接返回修复后的纯 JSON。"
                ),
            },
        ]

        try:
            response = self.client.chat(messages)
            return self._parse_response(response)
        except Exception as e:
            print(f"[AI] 重试修复 JSON 异常: {type(e).__name__}: {e}")
            return None

    def _format_time_range(self, first_time: str, last_time: str) -> str:
        """格式化时间范围（简化显示，只保留时分）"""
        def extract_time(time_str: str) -> str:
            if not time_str:
                return "-"
            # 尝试提取 HH:MM 部分
            if " " in time_str:
                parts = time_str.split(" ")
                if len(parts) >= 2:
                    time_part = parts[1]
                    if ":" in time_part:
                        return time_part[:5]  # HH:MM
            elif ":" in time_str:
                return time_str[:5]
            # 处理 HH-MM 格式
            result = time_str[:5] if len(time_str) >= 5 else time_str
            if len(result) == 5 and result[2] == '-':
                result = result.replace('-', ':')
            return result

        first = extract_time(first_time)
        last = extract_time(last_time)

        if first == last or last == "-":
            return first
        return f"{first}~{last}"

    def _format_rank_timeline(self, rank_timeline: List[Dict]) -> str:
        """格式化排名时间线"""
        if not rank_timeline:
            return "-"

        parts = []
        for item in rank_timeline:
            time_str = item.get("time", "")
            if len(time_str) == 5 and time_str[2] == '-':
                time_str = time_str.replace('-', ':')
            rank = item.get("rank")
            if rank is None:
                parts.append(f"0({time_str})")
            else:
                parts.append(f"{rank}({time_str})")

        return "→".join(parts)

    def _prepare_standalone_content(self, standalone_data: Dict) -> str:
        """
        将独立展示区数据转为文本，注入 AI 分析 prompt

        Args:
            standalone_data: 独立展示区数据 {"platforms": [...], "rss_feeds": [...]}

        Returns:
            格式化的文本内容
        """
        lines = []

        # 热榜平台
        for platform in standalone_data.get("platforms", []):
            platform_id = platform.get("id", "")
            platform_name = platform.get("name", platform_id)
            items = platform.get("items", [])
            if not items:
                continue

            lines.append(f"### [{platform_name}]")
            for item in items:
                title = item.get("title", "")
                if not title:
                    continue

                line = f"- {title}"

                # 排名信息
                ranks = item.get("ranks", [])
                if ranks:
                    min_rank = min(ranks)
                    max_rank = max(ranks)
                    rank_str = f"{min_rank}" if min_rank == max_rank else f"{min_rank}-{max_rank}"
                    line += f" | 排名:{rank_str}"

                # 时间范围
                first_time = item.get("first_time", "")
                last_time = item.get("last_time", "")
                if first_time:
                    time_str = self._format_time_range(first_time, last_time)
                    line += f" | 时间:{time_str}"

                # 出现次数
                count = item.get("count", 1)
                if count > 1:
                    line += f" | 出现:{count}次"

                # 排名轨迹（如果启用）
                if self.include_rank_timeline:
                    rank_timeline = item.get("rank_timeline", [])
                    if rank_timeline:
                        timeline_str = self._format_rank_timeline(rank_timeline)
                        line += f" | 轨迹:{timeline_str}"

                lines.append(line)
            lines.append("")

        # RSS 源
        for feed in standalone_data.get("rss_feeds", []):
            feed_id = feed.get("id", "")
            feed_name = feed.get("name", feed_id)
            items = feed.get("items", [])
            if not items:
                continue

            lines.append(f"### [{feed_name}]")
            for item in items:
                title = item.get("title", "")
                if not title:
                    continue

                line = f"- {title}"
                published_at = item.get("published_at", "")
                if published_at:
                    line += f" | {published_at}"

                lines.append(line)
            lines.append("")

        return "\n".join(lines)

    def _parse_response(self, response: str) -> AIAnalysisResult:
        """解析 AI 响应"""
        result = AIAnalysisResult(raw_response=response)

        if not response or not response.strip():
            result.error = "AI 返回空响应"
            return result

        # 提取 JSON 文本（去掉 markdown 代码块标记）
        json_str = response

        if "```json" in response:
            parts = response.split("```json", 1)
            if len(parts) > 1:
                code_block = parts[1]
                end_idx = code_block.find("```")
                if end_idx != -1:
                    json_str = code_block[:end_idx]
                else:
                    json_str = code_block
        elif "```" in response:
            parts = response.split("```", 2)
            if len(parts) >= 2:
                json_str = parts[1]

        json_str = json_str.strip()
        if not json_str:
            result.error = "提取的 JSON 内容为空"
            result.core_trends = response[:500] + "..." if len(response) > 500 else response
            result.success = True
            return result

        # 第一步：标准 JSON 解析
        data = None
        parse_error = None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            parse_error = e

        # 第二步：json_repair 本地修复
        if data is None:
            try:
                from json_repair import repair_json
                repaired = repair_json(json_str, return_objects=True)
                if isinstance(repaired, dict):
                    data = repaired
                    print("[AI] JSON 本地修复成功（json_repair）")
            except Exception:
                pass

        # 两步都失败，记录错误（后续由 analyze 方法的重试机制处理）
        if data is None:
            if parse_error:
                error_context = json_str[max(0, parse_error.pos - 30):parse_error.pos + 30] if json_str and parse_error.pos else ""
                result.error = f"JSON 解析错误 (位置 {parse_error.pos}): {parse_error.msg}"
                if error_context:
                    result.error += f"，上下文: ...{error_context}..."
            else:
                result.error = "JSON 解析失败"
            # 兜底：使用已提取的 json_str（不含 markdown 标记），避免推送中出现 ```json
            result.core_trends = json_str[:500] + "..." if len(json_str) > 500 else json_str
            result.success = True
            return result

        # 解析成功，提取字段
        try:
            result.today_judgement = self._clean_ai_text(data.get("today_judgement", ""))
            result.event_clusters = self._normalize_event_clusters(data.get("event_clusters", []))

            result.core_trends = data.get("core_trends", "")
            result.sentiment_controversy = data.get("sentiment_controversy", "")
            result.signals = data.get("signals", "")
            result.rss_insights = data.get("rss_insights", "")
            result.outlook_strategy = data.get("outlook_strategy", "")

            # 解析独立展示区概括
            summaries = data.get("standalone_summaries", {})
            if isinstance(summaries, dict):
                result.standalone_summaries = {
                    str(k): str(v) for k, v in summaries.items()
                }

            if result.today_judgement or result.event_clusters:
                self._derive_legacy_fields_from_new_schema(result)
            else:
                self._derive_new_schema_from_legacy_fields(result)

            result.event_clusters = self._prioritize_security_related_china_cluster(
                result.event_clusters or []
            )

            result.success = True
        except (KeyError, TypeError, AttributeError) as e:
            result.error = f"字段提取错误: {type(e).__name__}: {e}"
            result.core_trends = json_str[:500] + "..." if len(json_str) > 500 else json_str
            result.success = True

        return result
