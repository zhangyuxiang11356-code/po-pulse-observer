# coding=utf-8
"""
AI 客户端模块

基于 LiteLLM 的统一 AI 模型接口
支持 100+ AI 提供商（OpenAI、DeepSeek、Gemini、Claude、国内模型等）
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from litellm import completion


class AIClient:
    """统一的 AI 客户端（基于 LiteLLM）"""

    _rate_limit_lock = threading.Lock()
    _global_last_request_time = 0.0

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 AI 客户端

        Args:
            config: AI 配置字典
                - MODEL: 模型标识（格式: provider/model_name）
                - API_KEY: API 密钥
                - API_BASE: API 基础 URL（可选）
                - TEMPERATURE: 采样温度
                - MAX_TOKENS: 最大生成 token 数
                - TIMEOUT: 请求超时时间（秒）
                - NUM_RETRIES: 重试次数（可选）
                - FALLBACK_MODELS: 备用模型列表（可选）
        """
        self.model = config.get("MODEL", "deepseek/deepseek-chat")
        self.api_key = config.get("API_KEY") or os.environ.get("AI_API_KEY", "")
        self.api_base = config.get("API_BASE", "")
        self.temperature = config.get("TEMPERATURE", 1.0)
        self.max_tokens = config.get("MAX_TOKENS", 5000)
        self.timeout = config.get("TIMEOUT", 120)
        self.num_retries = config.get("NUM_RETRIES", 2)
        self.fallback_models = config.get("FALLBACK_MODELS", [])
        self.extra_params = config.get("EXTRA_PARAMS", {}) or {}
        self.force_stream = config.get("FORCE_STREAM", False)
        self.auto_stream_fallback = config.get("AUTO_STREAM_FALLBACK", True)
        self.use_responses_api = config.get("USE_RESPONSES_API", False)
        self.min_request_interval_seconds = float(
            config.get("MIN_REQUEST_INTERVAL_SECONDS", 0) or 0
        )
        self.fallback_model = config.get("FALLBACK_MODEL") or os.environ.get("AI_FALLBACK_MODEL", "")
        self.fallback_api_key = config.get("FALLBACK_API_KEY") or os.environ.get("AI_FALLBACK_API_KEY", "")
        self.fallback_api_base = config.get("FALLBACK_API_BASE") or os.environ.get("AI_FALLBACK_API_BASE", "")

        self.primary_profile = {
            "label": "主接口",
            "model": self.model,
            "api_key": self.api_key,
            "api_base": self.api_base,
        }
        self.backup_profile = None
        if self.fallback_model and self.fallback_api_key and self.fallback_api_base:
            self.backup_profile = {
                "label": "备用接口",
                "model": self.fallback_model,
                "api_key": self.fallback_api_key,
                "api_base": self.fallback_api_base,
            }

    def _apply_rate_limit(self) -> None:
        """统一控制 AI 请求频率。"""
        if self.min_request_interval_seconds <= 0:
            return

        with self._rate_limit_lock:
            now = time.monotonic()
            elapsed = now - self._global_last_request_time
            wait_seconds = self.min_request_interval_seconds - elapsed
            if wait_seconds > 0:
                print(f"[AI] 请求间隔保护：等待 {wait_seconds:.1f} 秒")
                time.sleep(wait_seconds)
            self.__class__._global_last_request_time = time.monotonic()

    @staticmethod
    def _resolve_model_name(model: str) -> str:
        """为 OpenAI 兼容 responses API 提取裸模型名。"""
        if model.startswith("openai/"):
            return model.split("/", 1)[1]
        return model

    def _should_use_responses_api(self, profile: Dict[str, str]) -> bool:
        """是否启用 responses API。"""
        if not self.use_responses_api:
            return False
        return bool(profile.get("api_base") and str(profile.get("model") or "").startswith("openai/"))

    @staticmethod
    def _responses_endpoint(api_base: str) -> str:
        base = api_base.rstrip("/")
        if base.endswith("/responses"):
            return base
        return f"{base}/responses"

    def _stream_responses(
        self,
        messages: List[Dict[str, str]],
        params: Dict[str, Any],
        profile: Dict[str, str],
    ) -> str:
        """使用 OpenAI Responses API 的流式输出。"""
        api_key = str(profile.get("api_key") or "")
        api_base = str(profile.get("api_base") or "")
        model = str(profile.get("model") or "")

        if not api_key:
            raise ValueError("未配置 AI API Key")
        if not api_base:
            raise ValueError("未配置 AI API Base")

        payload: Dict[str, Any] = {
            "model": self._resolve_model_name(model),
            "input": messages,
            "stream": True,
        }

        temperature = params.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature

        max_tokens = params.get("max_tokens")
        if max_tokens and max_tokens > 0:
            payload["max_output_tokens"] = max_tokens

        payload.update(self.extra_params)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        self._apply_rate_limit()

        chunks: List[str] = []
        with requests.post(
            self._responses_endpoint(api_base),
            headers=headers,
            json=payload,
            timeout=params.get("timeout", self.timeout),
            stream=True,
        ) as response:
            response.raise_for_status()
            # SSE 响应通常不带 charset，requests 可能回退到 latin-1，导致中文流式内容乱码。
            response.encoding = "utf-8"
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type", "")
                if event_type == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        chunks.append(delta)
                elif event_type == "response.failed":
                    raise RuntimeError(json.dumps(event, ensure_ascii=False))
                elif event_type == "response.completed":
                    error = ((event.get("response") or {}).get("error")) or None
                    if error:
                        raise RuntimeError(json.dumps(error, ensure_ascii=False))

        return "".join(chunks)

    @staticmethod
    def _extract_content_from_response(response: Any) -> str:
        """从非流式响应中提取文本内容。"""
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", str(item)) if isinstance(item, dict) else str(item)
                for item in content
            )
        return content or ""

    @staticmethod
    def _extract_content_from_stream_chunk(chunk: Any) -> str:
        """从流式 chunk 中提取增量文本。"""
        try:
            delta = chunk.choices[0].delta
        except (AttributeError, IndexError, TypeError):
            return ""

        if delta is None:
            return ""

        if isinstance(delta, dict):
            content = delta.get("content", "")
        else:
            content = getattr(delta, "content", "")

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text", ""))
                else:
                    parts.append(str(item))
            return "".join(parts)

        return content or ""

    def _stream_chat(self, params: Dict[str, Any]) -> str:
        """以流式方式调用模型，并将分片拼接为完整文本。"""
        stream_params = dict(params)
        stream_params["stream"] = True

        self._apply_rate_limit()

        chunks = []
        for chunk in completion(**stream_params):
            text = self._extract_content_from_stream_chunk(chunk)
            if text:
                chunks.append(text)
        return "".join(chunks)

    def _build_params(
        self,
        messages: List[Dict[str, str]],
        profile: Dict[str, str],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        params = {
            "model": profile["model"],
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "timeout": kwargs.get("timeout", self.timeout),
            "num_retries": kwargs.get("num_retries", self.num_retries),
        }

        params.update(self.extra_params)

        if profile.get("api_key"):
            params["api_key"] = profile["api_key"]
        if profile.get("api_base"):
            params["api_base"] = profile["api_base"]

        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = max_tokens

        if self.fallback_models and profile is self.primary_profile:
            params["fallbacks"] = self.fallback_models

        for key, value in kwargs.items():
            if key not in params:
                params[key] = value
        return params

    def _chat_once(
        self,
        messages: List[Dict[str, str]],
        profile: Dict[str, str],
        **kwargs,
    ) -> str:
        params = self._build_params(messages, profile, kwargs)

        if self._should_use_responses_api(profile):
            return self._stream_responses(messages, params, profile)

        use_stream = kwargs.get("stream", self.force_stream)
        if use_stream:
            return self._stream_chat(params)

        self._apply_rate_limit()
        response = completion(**params)
        content = self._extract_content_from_response(response)
        if content:
            return content

        if self.auto_stream_fallback:
            return self._stream_chat(params)
        return ""

    def _run_with_profile(
        self,
        messages: List[Dict[str, str]],
        profile: Dict[str, str],
        **kwargs,
    ) -> str:
        attempts = max(1, int(kwargs.get("num_retries", self.num_retries)) + 1)
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                content = self._chat_once(messages, profile, **kwargs)
                if content and content.strip():
                    return content
                raise RuntimeError(f"{profile['label']} 返回空响应")
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                print(
                    f"[AI] {profile['label']} 第 {attempt} 次失败，准备重试: "
                    f"{type(exc).__name__}: {exc}"
                )
                time.sleep(1)
        if last_error:
            raise last_error
        raise RuntimeError(f"{profile['label']} 未返回有效内容")

    def _profiles_are_same(self) -> bool:
        if not self.backup_profile:
            return True
        return (
            self.primary_profile.get("model") == self.backup_profile.get("model")
            and self.primary_profile.get("api_base") == self.backup_profile.get("api_base")
            and self.primary_profile.get("api_key") == self.backup_profile.get("api_key")
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """
        调用 AI 模型进行对话

        Args:
            messages: 消息列表，格式: [{"role": "system/user/assistant", "content": "..."}]
            **kwargs: 额外参数，会覆盖默认配置

        Returns:
            str: AI 响应内容

        Raises:
            Exception: API 调用失败时抛出异常
        """
        try:
            return self._run_with_profile(messages, self.primary_profile, **kwargs)
        except Exception as primary_error:
            if not self.backup_profile or self._profiles_are_same():
                raise
            print(f"[AI] 主接口失败，切换备用接口: {type(primary_error).__name__}: {primary_error}")
            return self._run_with_profile(messages, self.backup_profile, **kwargs)

    def validate_config(self) -> tuple[bool, str]:
        """
        验证配置是否有效

        Returns:
            tuple: (是否有效, 错误信息)
        """
        if not self.model:
            return False, "未配置 AI 模型（model）"

        if not self.api_key:
            return False, "未配置 AI API Key，请在 config.yaml 或环境变量 AI_API_KEY 中设置"

        # 验证模型格式（应该包含 provider/model）
        if "/" not in self.model:
            return False, f"模型格式错误: {self.model}，应为 'provider/model' 格式（如 'deepseek/deepseek-chat'）"

        return True, ""
