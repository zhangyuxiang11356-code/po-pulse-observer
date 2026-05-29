# coding=utf-8
"""
数据获取器模块

负责从 NewsNow API 抓取新闻数据，支持：
- 单个平台数据获取
- 批量平台数据爬取
- 自动重试机制
- 代理支持
"""

import json
import random
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

import requests


class DataFetcher:
    """数据获取器"""

    # 默认 API 地址
    DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"

    # 默认请求头
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        api_url: Optional[str] = None,
    ):
        """
        初始化数据获取器

        Args:
            proxy_url: 代理服务器 URL（可选）
            api_url: API 基础 URL（可选，默认使用 DEFAULT_API_URL）
        """
        self.proxy_url = proxy_url
        self.api_url = api_url or self.DEFAULT_API_URL
        self.cache_dir = Path(__file__).resolve().parents[2] / "output" / "hotlist_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, platform_id: str) -> Path:
        return self.cache_dir / f"{platform_id}.json"

    def _save_platform_cache(self, platform_id: str, results: Dict[str, Dict[str, Union[List[int], str]]]) -> None:
        try:
            self._cache_path(platform_id).write_text(
                json.dumps(results, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_platform_cache(self, platform_id: str) -> Optional[Dict[str, Dict[str, Union[List[int], str]]]]:
        cache_path = self._cache_path(platform_id)
        if not cache_path.exists():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:
            return None
        return None

    @staticmethod
    def _decode_text_response(response: requests.Response) -> str:
        """优先按响应内容声明的编码解码，避免 requests 误判导致中文乱码。"""
        content = response.content or b""
        if not content:
            return ""

        xml_match = re.search(br'encoding=["\']([\w-]+)["\']', content[:200])
        candidates = []
        if xml_match:
            try:
                candidates.append(xml_match.group(1).decode("ascii", errors="ignore"))
            except Exception:
                pass
        if getattr(response, "apparent_encoding", None):
            candidates.append(response.apparent_encoding)
        if getattr(response, "encoding", None):
            candidates.append(response.encoding)
        candidates.extend(["utf-8", "utf-8-sig"])

        seen = set()
        for encoding in candidates:
            if not encoding:
                continue
            normalized = encoding.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            try:
                return content.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue

        return content.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_rss_hotlist(content: str) -> Dict[str, Dict[str, Union[List[int], str]]]:
        """解析 RSS/XML 形式的热榜，按条目顺序生成排名。"""
        results: Dict[str, Dict[str, Union[List[int], str]]] = {}
        root = ET.fromstring(content)

        for index, item in enumerate(root.findall(".//item"), 1):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue

            url = (item.findtext("link") or "").strip()
            if title in results:
                results[title]["ranks"].append(index)
                continue

            results[title] = {
                "ranks": [index],
                "url": url,
                "mobileUrl": url,
            }

        return results

    def fetch_rss_hotlist(
        self,
        platform: Dict[str, str],
    ) -> Tuple[Optional[Dict[str, Dict[str, Union[List[int], str]]]], str, str]:
        """抓取 RSS/XML 形式的热榜平台。"""
        id_value = platform["id"]
        alias = platform.get("name", id_value)
        url = platform.get("fetch_url", "")

        proxies = None
        if self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}

        try:
            response = requests.get(
                url,
                proxies=proxies,
                headers=self.DEFAULT_HEADERS,
                timeout=10,
            )
            response.raise_for_status()
            content = self._decode_text_response(response)
            results = self._parse_rss_hotlist(content)
            print(f"获取 {id_value} 成功（RSS 热榜）")
            return results, id_value, alias
        except Exception as e:
            print(f"请求 {id_value} 失败: {e}")
            return None, id_value, alias

    def fetch_data(
        self,
        id_info: Union[str, Tuple[str, str]],
        max_retries: int = 2,
        min_retry_wait: int = 3,
        max_retry_wait: int = 5,
    ) -> Tuple[Optional[str], str, str]:
        """
        获取指定ID数据，支持重试

        Args:
            id_info: 平台ID 或 (平台ID, 别名) 元组
            max_retries: 最大重试次数
            min_retry_wait: 最小重试等待时间（秒）
            max_retry_wait: 最大重试等待时间（秒）

        Returns:
            (响应文本, 平台ID, 别名) 元组，失败时响应文本为 None
        """
        if isinstance(id_info, tuple):
            id_value, alias = id_info
        else:
            id_value = id_info
            alias = id_value

        url = f"{self.api_url}?id={id_value}&latest"

        proxies = None
        if self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}

        retries = 0
        while retries <= max_retries:
            try:
                response = requests.get(
                    url,
                    proxies=proxies,
                    headers=self.DEFAULT_HEADERS,
                    timeout=10,
                )
                response.raise_for_status()

                data_text = response.text
                data_json = json.loads(data_text)

                status = data_json.get("status", "未知")
                if status not in ["success", "cache"]:
                    raise ValueError(f"响应状态异常: {status}")

                status_info = "最新数据" if status == "success" else "缓存数据"
                print(f"获取 {id_value} 成功（{status_info}）")
                return data_text, id_value, alias

            except Exception as e:
                retries += 1
                if retries <= max_retries:
                    base_wait = random.uniform(min_retry_wait, max_retry_wait)
                    additional_wait = (retries - 1) * random.uniform(1, 2)
                    wait_time = base_wait + additional_wait
                    print(f"请求 {id_value} 失败: {e}. {wait_time:.2f}秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"请求 {id_value} 失败: {e}")
                    return None, id_value, alias

        return None, id_value, alias

    def crawl_websites(
        self,
        ids_list: List[Union[str, Tuple[str, str], Dict[str, str]]],
        request_interval: int = 100,
    ) -> Tuple[Dict, Dict, List]:
        """
        爬取多个网站数据

        Args:
            ids_list: 平台ID列表，每个元素可以是字符串或 (平台ID, 别名) 元组
            request_interval: 请求间隔（毫秒）

        Returns:
            (结果字典, ID到名称的映射, 失败ID列表) 元组
        """
        results = {}
        id_to_name = {}
        failed_ids = []

        for i, id_info in enumerate(ids_list):
            response = None
            if isinstance(id_info, dict):
                id_value = id_info["id"]
                name = id_info.get("name", id_value)
            elif isinstance(id_info, tuple):
                id_value, name = id_info
            else:
                id_value = id_info
                name = id_value

            id_to_name[id_value] = name
            if isinstance(id_info, dict) and id_info.get("fetch_format") == "rss":
                rss_results, _, _ = self.fetch_rss_hotlist(id_info)
                if rss_results is not None:
                    results[id_value] = rss_results
                    self._save_platform_cache(id_value, rss_results)
                else:
                    cached_results = self._load_platform_cache(id_value)
                    if cached_results is not None:
                        print(f"获取 {id_value} 失败，已回退到本地缓存")
                        results[id_value] = cached_results
                    else:
                        failed_ids.append(id_value)
            else:
                response, _, _ = self.fetch_data(id_info)
                if response:
                    try:
                        data = json.loads(response)
                        results[id_value] = {}

                        for index, item in enumerate(data.get("items", []), 1):
                            title = item.get("title")
                            # 跳过无效标题（None、float、空字符串）
                            if title is None or isinstance(title, float) or not str(title).strip():
                                continue
                            title = str(title).strip()
                            url = item.get("url", "")
                            mobile_url = item.get("mobileUrl", "")

                            if title in results[id_value]:
                                results[id_value][title]["ranks"].append(index)
                            else:
                                results[id_value][title] = {
                                    "ranks": [index],
                                    "url": url,
                                    "mobileUrl": mobile_url,
                                }
                        if results[id_value]:
                            self._save_platform_cache(id_value, results[id_value])
                    except json.JSONDecodeError:
                        print(f"解析 {id_value} 响应失败")
                        cached_results = self._load_platform_cache(id_value)
                        if cached_results is not None:
                            print(f"解析 {id_value} 响应失败，已回退到本地缓存")
                            results[id_value] = cached_results
                        else:
                            failed_ids.append(id_value)
                    except Exception as e:
                        print(f"处理 {id_value} 数据出错: {e}")
                        cached_results = self._load_platform_cache(id_value)
                        if cached_results is not None:
                            print(f"处理 {id_value} 数据出错，已回退到本地缓存")
                            results[id_value] = cached_results
                        else:
                            failed_ids.append(id_value)
                else:
                    cached_results = self._load_platform_cache(id_value)
                    if cached_results is not None:
                        print(f"获取 {id_value} 失败，已回退到本地缓存")
                        results[id_value] = cached_results
                    else:
                        failed_ids.append(id_value)

            # 请求间隔（除了最后一个）
            if i < len(ids_list) - 1:
                actual_interval = request_interval + random.randint(-10, 20)
                actual_interval = max(50, actual_interval)
                time.sleep(actual_interval / 1000)

        print(f"成功: {list(results.keys())}, 失败: {failed_ids}")
        return results, id_to_name, failed_ids
