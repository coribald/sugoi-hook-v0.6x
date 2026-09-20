"""
OpenAI Translate Plugin
=======================

Translates extracted text with the OpenAI Responses API using optional
source-material context provided directly in the plugin settings UI.
"""

import json
import os
import sys
import time
import unicodedata
from collections import deque
import requests
from typing import Optional

from plugins import HookPlugin


def runtime_debug_logging_enabled() -> bool:
    import os
    import sys
    env_enabled = os.environ.get('SUGOIHOOK_DEBUG_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    argv_enabled = any(str(arg).strip().lower() == '--debug' for arg in sys.argv[1:])
    return env_enabled or argv_enabled


class OpenAITranslatePlugin(HookPlugin):
    name = "OpenAI Translate"
    description = "Translates text using OpenAI with optional story and character context"
    version = "1.0"
    author = "OpenAI Codex"
    is_translation_plugin = True

    MODELS = {
        "gpt-5-mini": "GPT-5 mini",
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o mini",
        "gpt-4.1": "GPT-4.1",
        "gpt-4.1-mini": "GPT-4.1 mini",
    }

    REASONING_EFFORTS = {
        "minimal": "Minimal",
        "low": "Low",
        "medium": "Medium",
        "high": "High",
    }

    VERBOSITY_LEVELS = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
    }

    LOGGING_LEVELS = {
        "minimal": "Minimal",
        "debug": "Debug",
        "noisy": "Noisy",
    }

    LANGUAGES = {
        "auto": "Auto-detect",
        "english": "English",
        "japanese": "Japanese",
        "korean": "Korean",
        "chinese": "Chinese",
        "traditional chinese": "Traditional Chinese",
        "spanish": "Spanish",
        "french": "French",
        "german": "German",
        "italian": "Italian",
        "portuguese": "Portuguese",
        "russian": "Russian",
        "vietnamese": "Vietnamese",
    }

    def __init__(self):
        super().__init__()
        self.api_key = ""
        self.model = "gpt-5-mini"
        self.source_lang = "japanese"
        self.target_lang = "english"
        self.context_doc = ""
        self.extra_instructions = (
            "Prefer faithful translation over paraphrase. Preserve ambiguity when the "
            "Japanese is genuinely ambiguous. Use neutral phrasing instead of guessing "
            "gender or pronouns when context is insufficient."
        )
        self.reasoning_effort = "minimal"
        self.verbosity = "low"
        self.timeout_seconds = 45
        self.timeout_retry_count = 1
        self.max_output_tokens = 300
        self.previous_context_lines = 3
        self.recent_original_lines = deque(maxlen=6)
        self.session = None
        self.logging_level = "noisy"

    def on_enable(self):
        if self.session is None:
            self.session = requests.Session()

    def on_disable(self):
        if self.session:
            self.session.close()
            self.session = None

    def reset_session(self):
        """Drop any stale keep-alive connection and create a fresh session lazily."""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None

    def process_text(self, text: str) -> str:
        if not text or not text.strip():
            return text

        stripped_text = text.strip()
        if self.is_system_or_ui_text(stripped_text):
            return text

        translated = self.translate_text(stripped_text)
        self.remember_original_line(stripped_text)
        if not translated:
            return text

        return f"{text.rstrip()}\n{translated}\n\n"

    def process_clipboard_text(self, text: str) -> str:
        """Keep clipboard text untranslated while other cleanup plugins run."""
        return text

    def translate_text(self, text: str) -> Optional[str]:
        if not self.enabled or not self.api_key.strip():
            self.log_debug("Skipped request because plugin is disabled or API key is missing.", level="minimal")
            return None

        if not self.should_translate_text(text.strip()):
            return None

        if self.session is None:
            self.on_enable()

        recent_context = self.build_recent_context()
        instructions = self.build_instructions(recent_context)
        effective_verbosity = self.get_effective_verbosity()
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": text,
            "max_output_tokens": self.max_output_tokens,
            "text": {
                "format": {
                    "type": "text"
                },
                "verbosity": effective_verbosity
            },
        }
        if self.model_supports_reasoning():
            payload["reasoning"] = {
                "effort": self.reasoning_effort
            }

        total_attempts = max(1, int(self.timeout_retry_count) + 1)

        for attempt in range(total_attempts):
            try:
                if self.session is None:
                    self.on_enable()
                self.log_payload(payload)
                if self.should_log("debug") and recent_context:
                    self.log_debug("Recent original context:")
                    print(json.dumps(recent_context, ensure_ascii=False, indent=2), flush=True)
                self.log_debug(
                    f"Sending request. attempt={attempt + 1}/{total_attempts}, model={self.model}, input_len={len(text)}, "
                    f"context_len={len(self.context_doc)}, recent_context_lines={len(recent_context)}, "
                    f"max_output_tokens={self.max_output_tokens}, "
                    f"reasoning_effort={self.reasoning_effort}, verbosity={effective_verbosity}",
                    level="debug"
                )
                response = self.session.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                self.log_debug(f"HTTP {response.status_code}", level="minimal")
                response.raise_for_status()
                data = response.json()
                self.log_response(data)
                output_text = self.extract_output_text(data)
                if output_text:
                    cleaned_output = output_text.strip()
                    if self.is_noop_translation(text, cleaned_output):
                        self.log_debug("Model returned the source text unchanged; treating as no translation.", level="minimal")
                        return None
                    preview = cleaned_output.replace("\n", "\\n")
                    self.log_debug(f"Translation OK: {preview[:200]}", level="minimal")
                    return cleaned_output
                if data.get("status") == "incomplete":
                    incomplete_reason = data.get("incomplete_details", {}).get("reason")
                    self.log_debug(f"Response incomplete. reason={incomplete_reason}", level="minimal")
                self.log_debug("Response parsed but no output_text was found.", level="minimal")
                return None
            except requests.exceptions.HTTPError as exc:
                response_text = ""
                try:
                    response_text = exc.response.text[:2000] if exc.response is not None else ""
                except Exception:
                    response_text = "<unable to read response body>"
                self.log_debug(f"HTTP error: {exc}. Body: {response_text}", level="minimal")
                return None
            except requests.exceptions.Timeout as exc:
                error_type = type(exc).__name__
                self.log_debug(f"{error_type} on attempt {attempt + 1}/{total_attempts}: {exc}", level="minimal")
                if attempt < total_attempts - 1:
                    self.log_debug("Resetting HTTP session and retrying after timeout.", level="minimal")
                    self.reset_session()
                    continue
                return None
            except requests.exceptions.ConnectionError as exc:
                error_type = type(exc).__name__
                self.log_debug(f"{error_type} on attempt {attempt + 1}/{total_attempts}: {exc}", level="minimal")
                if attempt < total_attempts - 1:
                    self.log_debug("Resetting HTTP session and retrying after connection error.", level="minimal")
                    self.reset_session()
                    continue
                return None
            except Exception as exc:
                self.log_debug(f"Unexpected error: {type(exc).__name__}: {exc}", level="minimal")
                return None

        return None

    def should_log(self, level: str) -> bool:
        if not runtime_debug_logging_enabled():
            return False

        level_order = {
            "minimal": 1,
            "debug": 2,
            "noisy": 3,
        }
        configured_level = str(getattr(self, "logging_level", "noisy") or "noisy").strip().lower()
        configured_rank = level_order.get(configured_level, 3)
        requested_rank = level_order.get(level, 3)
        return configured_rank >= requested_rank

    def log_debug(self, message: str, level: str = "debug"):
        if not self.should_log(level):
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[OpenAI Translate][{timestamp}] {message}", flush=True)

    def log_payload(self, payload: dict):
        if not self.should_log("noisy"):
            return

        payload_for_logging = self._truncate_instructions_for_logging(payload)
        self.log_debug("Outbound payload:", level="noisy")
        print(json.dumps(payload_for_logging, ensure_ascii=False, indent=2), flush=True)

    def log_response(self, data: dict):
        if not self.should_log("noisy"):
            return

        try:
            sanitized_data = self._truncate_instructions_for_logging(data)
            response_text = json.dumps(sanitized_data, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.log_debug(f"Failed to JSON-format response: {exc}", level="debug")
            return

        if len(response_text) > 6000:
            response_text = response_text[:6000] + "\n... [truncated]"

        self.log_debug("Raw response:", level="noisy")
        print(response_text, flush=True)

    def _truncate_instructions_for_logging(self, value):
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                if key == "instructions" and isinstance(item, str):
                    single_line_instructions = " ".join(item.split())
                    if len(single_line_instructions) > 120:
                        sanitized[key] = single_line_instructions[:120] + "... [truncated]"
                    else:
                        sanitized[key] = single_line_instructions
                else:
                    sanitized[key] = self._truncate_instructions_for_logging(item)
            return sanitized

        if isinstance(value, list):
            return [self._truncate_instructions_for_logging(item) for item in value]

        return value

    def should_translate_text(self, stripped_text: str) -> bool:
        if not stripped_text:
            return False
        if self.is_punctuation_only_text(stripped_text):
            self.log_debug(f"Skipping punctuation-only text: {stripped_text}", level="minimal")
            return False
        return not self.is_system_or_ui_text(stripped_text)

    def is_system_or_ui_text(self, stripped_text: str) -> bool:
        if stripped_text.startswith('[Hook ') or stripped_text.startswith('[Hook #'):
            return True

        system_keywords = (
            'Selected Hook', 'Attached to', 'Detached', 'Waiting for',
            'Function:', 'Manual hook', 'Process Name', 'PID:',
            'Interact with', 'Hook at', 'Console'
        )

        if any(keyword in stripped_text for keyword in system_keywords):
            return True

        if stripped_text.startswith('[Console]'):
            return True

        if stripped_text and stripped_text[0] in '✓●○🎮🎯🔌📝⏳🔗⏹️🗑️💾🔄📂🔽':
            return True

        if len(stripped_text) > 3:
            separator_chars = '─═━-_'
            separator_count = sum(1 for c in stripped_text if c in separator_chars)
            if separator_count / len(stripped_text) > 0.8:
                return True

        return False

    def is_punctuation_only_text(self, stripped_text: str) -> bool:
        meaningful_char_found = False

        for char in stripped_text:
            if char.isspace():
                continue

            category = unicodedata.category(char)
            if category.startswith('P') or category.startswith('S'):
                meaningful_char_found = True
                continue

            return False

        return meaningful_char_found

    def remember_original_line(self, text: str):
        stripped = text.strip()
        if not stripped:
            return
        self.recent_original_lines.append(stripped)

    def build_recent_context(self) -> list[str]:
        if self.previous_context_lines <= 0:
            return []
        recent_lines = list(self.recent_original_lines)
        if not recent_lines:
            return []
        return recent_lines[-self.previous_context_lines:]

    def build_instructions(self, recent_context: Optional[list[str]] = None) -> str:
        source_label = self.LANGUAGES.get(self.source_lang, self.source_lang)
        target_label = self.LANGUAGES.get(self.target_lang, self.target_lang)

        instruction_parts = [
            f"You are translating from {source_label} to {target_label}.",
            "Return the English translation only. Do not include the original Japanese text.",
            "Never echo or repeat the source line.",
            "Output exactly one translated line in English.",
            self.extra_instructions.strip(),
        ]

        if self.context_doc.strip():
            instruction_parts.append("Source material context:")
            instruction_parts.append(self.context_doc.strip())

        if recent_context:
            context_lines = [f"{idx}. {line}" for idx, line in enumerate(recent_context, start=1)]
            instruction_parts.append("Recent original text context (use only to resolve tone, references, and continuity):")
            instruction_parts.append("\n".join(context_lines))

        return "\n\n".join(part for part in instruction_parts if part)

    def model_supports_reasoning(self) -> bool:
        model_name = (self.model or "").lower()
        return model_name.startswith("gpt-5")

    def get_effective_verbosity(self) -> str:
        model_name = (self.model or "").lower()
        if model_name in {"gpt-4o", "gpt-4o-mini"} and self.verbosity == "low":
            return "medium"
        return self.verbosity

    def is_noop_translation(self, source_text: str, translated_text: str) -> bool:
        source_clean = source_text.strip()
        translated_clean = translated_text.strip()
        if not source_clean or not translated_clean:
            return False
        return source_clean == translated_clean

    def extract_output_text(self, data: dict) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = data.get("output", [])
        text_parts = []

        for item in output:
            if item.get("type") != "message":
                continue

            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text_value = content.get("text", "")
                    if text_value:
                        text_parts.append(text_value)

        return "\n".join(part.strip() for part in text_parts if part.strip())

    def get_settings(self) -> dict:
        return {
            "api_key": (
                self.api_key,
                "secret",
                "OpenAI API Key"
            ),
            "model": (
                self.model,
                "choice",
                "Model",
                self.MODELS
            ),
            "source_lang": (
                self.source_lang,
                "choice",
                "Source Language",
                self.LANGUAGES
            ),
            "target_lang": (
                self.target_lang,
                "choice",
                "Target Language",
                {k: v for k, v in self.LANGUAGES.items() if k != "auto"}
            ),
            "context_doc": (
                self.context_doc,
                "multiline_str",
                "Story / character context"
            ),
            "extra_instructions": (
                self.extra_instructions,
                "multiline_str",
                "Additional translation instructions"
            ),
            "reasoning_effort": (
                self.reasoning_effort,
                "choice",
                "Reasoning Effort",
                self.REASONING_EFFORTS
            ),
            "verbosity": (
                self.verbosity,
                "choice",
                "Response Verbosity",
                self.VERBOSITY_LEVELS
            ),
            "timeout_seconds": (
                self.timeout_seconds,
                "int",
                "Request timeout (seconds)"
            ),
            "timeout_retry_count": (
                self.timeout_retry_count,
                "int",
                "How many times to retry after a timeout or connection error"
            ),
            "max_output_tokens": (
                self.max_output_tokens,
                "int",
                "Max output tokens"
            ),
            "previous_context_lines": (
                self.previous_context_lines,
                "int",
                "Previous original lines to send as context (0-6)"
            ),
            "logging_level": (
                self.logging_level,
                "choice",
                "Debug logging level (only logs when the app is in debug mode)",
                self.LOGGING_LEVELS
            ),
        }

    def set_setting(self, name: str, value) -> bool:
        if name == "api_key":
            self.api_key = str(value).strip()
            return True

        if name == "model" and value in self.MODELS:
            self.model = value
            return True

        if name == "source_lang" and value in self.LANGUAGES:
            self.source_lang = value
            return True

        if name == "target_lang" and value in self.LANGUAGES and value != "auto":
            self.target_lang = value
            return True

        if name == "context_doc":
            self.context_doc = str(value)
            return True

        if name == "extra_instructions":
            self.extra_instructions = str(value)
            return True

        if name == "reasoning_effort" and value in self.REASONING_EFFORTS:
            self.reasoning_effort = value
            return True

        if name == "verbosity" and value in self.VERBOSITY_LEVELS:
            self.verbosity = value
            return True

        if name == "timeout_seconds":
            try:
                timeout = int(value)
                if timeout >= 1:
                    self.timeout_seconds = timeout
                    return True
            except (TypeError, ValueError):
                return False
            return False

        if name == "timeout_retry_count":
            try:
                retry_count = int(value)
                if 0 <= retry_count <= 10:
                    self.timeout_retry_count = retry_count
                    return True
            except (TypeError, ValueError):
                return False
            return False

        if name == "max_output_tokens":
            try:
                max_tokens = int(value)
                if max_tokens >= 50:
                    self.max_output_tokens = max_tokens
                    return True
            except (TypeError, ValueError):
                return False
            return False

        if name == "previous_context_lines":
            try:
                context_lines = int(value)
                if 0 <= context_lines <= 6:
                    self.previous_context_lines = context_lines
                    return True
            except (TypeError, ValueError):
                return False
            return False

        if name == "logging_level" and value in self.LOGGING_LEVELS:
            self.logging_level = value
            return True

        return False

    def reset(self):
        self.recent_original_lines.clear()


plugin = OpenAITranslatePlugin()

