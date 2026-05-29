# coding=utf-8
"""社交媒体采集模块。"""

from .models import SocialItem
from .service import collect_social_media

__all__ = ["SocialItem", "collect_social_media"]
