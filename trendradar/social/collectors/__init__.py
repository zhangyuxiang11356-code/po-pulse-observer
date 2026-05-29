# coding=utf-8
"""社交媒体 collectors。"""

from .reddit_rss import collect_reddit_items
from .x_playwright import collect_x_items

__all__ = ["collect_reddit_items", "collect_x_items"]
