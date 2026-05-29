# coding=utf-8
"""社交媒体统一数据模型。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SocialItem:
    """统一的社交媒体条目。"""

    platform: str
    source_id: str
    source_name: str
    author: str = ""
    external_id: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    published_at: str = ""
    engagement: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    representative_comments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "author": self.author,
            "external_id": self.external_id,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "published_at": self.published_at,
            "engagement": self.engagement,
            "tags": self.tags,
            "risk_flags": self.risk_flags,
            "representative_comments": self.representative_comments,
            "metadata": self.metadata,
        }
