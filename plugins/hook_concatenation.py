"""
Hook Concatenation Plugin
==========================

Concatenates output from multiple selected hooks into a single output.
Supports a required dialogue hook plus optional prefix hooks such as speaker names.
"""

from plugins import HookPlugin


def runtime_debug_logging_enabled() -> bool:
    env_enabled = os.environ.get('SUGOIHOOK_DEBUG_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    argv_enabled = any(str(arg).strip().lower() == '--debug' for arg in sys.argv[1:])
    return env_enabled or argv_enabled


from typing import Optional
import logging
import os
import sys
import re
import time
from collections import deque


class HookConcatenationPlugin(HookPlugin):
    def _log_debug(self, stage: str, **fields):
        if not runtime_debug_logging_enabled():
            return
        try:
            parts = []
            for key, value in fields.items():
                value_str = str(value).replace("\r", "\\r").replace("\n", "\\n")
                if len(value_str) > 160:
                    value_str = value_str[:160] + "..."
                parts.append(f"{key}={value_str}")
            message = f"[HOOK CONCAT] {stage}"
            if parts:
                message += " | " + " | ".join(parts)
            logging.info(message)
            try:
                print(message, flush=True)
            except Exception:
                pass
        except Exception:
            pass
    name = "Hook Concatenation"
    description = "Concatenate output from multiple hooks with optional delayed prefixes"
    version = "1.4"
    author = "Sugoi Hook"

    def _log_resolved_config(self, reason: str):
        if not runtime_debug_logging_enabled():
            return
        config = self._get_concat_config()
        self._log_debug(
            'resolved_config',
            reason=reason,
            enabled_mode=self._state.get('enabled_mode'),
            dialogue_selector=self._state.get('dialogue_hook_id', ''),
            dialogue_hook_id=config.get('dialogue_hook_id', ''),
            prefix_selectors=self._state.get('prefix_hook_ids', ''),
            prefix_hook_ids=config.get('prefix_hook_ids', []),
            all_hook_ids=config.get('all_hook_ids', []),
            speaker_wait_ms=config.get('speaker_wait_ms', 150),
            dialogue_continuation_window_ms=self._state.get('dialogue_continuation_window_ms', 450),
            clipboard_output_mode=self._state.get('clipboard_output_mode', 'combined'),
        )

    def __init__(self):
        super().__init__()
        self._state['enabled_mode'] = False
        self._state['num_hooks'] = 2
        self._state['hook_ids'] = ""
        self._state['dialogue_hook_id'] = ""
        self._state['prefix_hook_ids'] = ""
        self._state['speaker_wait_ms'] = 150
        self._state['dialogue_continuation_window_ms'] = 450
        self._state['clipboard_output_mode'] = 'combined'
        self._state['max_dialogue_length'] = 400
        self._state['burst_stabilization_enabled'] = True
        self._state['burst_window_ms'] = 600
        self._state['burst_line_threshold'] = 4
        self._state['burst_settle_ms'] = 200
        self._state['hook_buffers'] = {}
        self._state['pending_dialogue'] = None
        self._state['pending_timer_id'] = None
        self._state['pending_clipboard_emit'] = None
        self._state['pending_prefix_started_at'] = 0.0
        self._state['pending_dialogue_started_at'] = 0.0
        self._state['pending_dialogue_updated_at'] = 0.0
        self._state['pending_prefix_values'] = {}
        self._state['pending_dialogue_continuation'] = None
        self._state['pending_dialogue_continuation_at'] = 0.0
        self._state['recent_hook_times'] = deque()
        self._state['burst_suppression_active'] = False
        self._state['burst_release_timer_id'] = None
        self._state['post_burst_recovery_active'] = False
        self._state['recovery_prefix_hook_ids'] = set()
        self._hook_pattern = re.compile(r'^\[Hook #?(\d+)(?:\|(\d+))?\]\s*(.*)$', re.IGNORECASE)

    def process_text(self, text: str) -> Optional[str]:
        if not self._state['enabled_mode']:
            return text

        config = self._get_concat_config()
        if not config['all_hook_ids']:
            return text

        text_stripped = text.strip()
        if text_stripped.startswith('[Console]'):
            return text

        if self._state.get('post_burst_recovery_active'):
            match = self._hook_pattern.match(text_stripped)
            if not match:
                self._log_debug('recovery_drop_unstructured', text=text_stripped)
                return None
        else:
            match = self._hook_pattern.match(text_stripped)

        if not match:
            return text

        hook_id = match.group(1)
        event_sequence = int(match.group(2) or 0)
        hook_text = match.group(3).strip()
        app = getattr(self, 'app', None)
        if event_sequence and app and hasattr(app, 'mark_hook_event_processed'):
            app.mark_hook_event_processed(hook_id, event_sequence)

        if hook_id not in config['all_hook_ids']:
            self._log_debug('drop_unconfigured_hook', hook_id=hook_id, text=hook_text)
            return None

        if self._handle_burst_input(config, hook_id, hook_text):
            return None

        if self._handle_post_burst_recovery(config, hook_id, hook_text):
            return None

        if hook_id == config['dialogue_hook_id'] and self._maybe_append_dialogue_continuation(config, hook_text):
            return None

        if hook_id in self._state['hook_buffers'] and hook_id == config['dialogue_hook_id']:
            self._flush_pending_dialogue()
            self._state['hook_buffers'] = {}

        if hook_id in config['prefix_hook_ids']:
            self._log_debug('prefix_received', hook_id=hook_id, text=hook_text, pending_dialogue=self._state.get('pending_dialogue'))
            if self._state['pending_dialogue']:
                now = time.monotonic()
                pending_prefix_values = self._state.get('pending_prefix_values', {})
                pending_prefix = str(pending_prefix_values.get(hook_id, '')).strip()
                pending_continuation = (self._state.get('pending_dialogue_continuation') or '').strip()
                continuation_at = float(self._state.get('pending_dialogue_continuation_at') or now)
                if not pending_prefix or pending_prefix == hook_text:
                    continuation_resolved = self._consume_pending_dialogue_continuation(config)
                    if hook_text:
                        self._state['hook_buffers'][hook_id] = hook_text
                        pending_prefix_values[hook_id] = hook_text
                    self._state['pending_prefix_values'] = pending_prefix_values
                    if not continuation_resolved:
                        self._state['pending_dialogue_updated_at'] = now
                    wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
                    self._log_debug('hold_same_speaker_continuation', hook_id=hook_id, text=hook_text, wait_ms=wait_ms)
                    self._schedule_pending_emit(wait_ms)
                    return None

                self._log_debug('speaker_changed_flush_pending', hook_id=hook_id, previous=pending_prefix, incoming=hook_text)
                self._state['pending_dialogue_continuation'] = None
                self._state['pending_dialogue_continuation_at'] = 0.0
                output_text = self._emit_pending_dialogue_now()
                if hook_text:
                    self._state['hook_buffers'][hook_id] = hook_text
                if pending_continuation:
                    self._state['pending_dialogue'] = pending_continuation
                    self._state['pending_dialogue_started_at'] = continuation_at
                    self._state['pending_dialogue_updated_at'] = continuation_at
                    self._state['hook_buffers'][config['dialogue_hook_id']] = pending_continuation
                    self._state['pending_prefix_values'] = {hook_id: hook_text} if hook_text else {}
                    wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
                    self._schedule_pending_emit(wait_ms)
                else:
                    wait_ms = max(0, int(config['speaker_wait_ms']))
                    self._state['pending_prefix_started_at'] = now
                    self._schedule_pending_emit(wait_ms)
                return output_text

            if hook_text:
                self._state['hook_buffers'][hook_id] = hook_text
            wait_ms = max(0, int(config['speaker_wait_ms']))
            if wait_ms == 0:
                self._log_debug('emit_prefix_no_wait', hook_id=hook_id)
                return self._emit_pending_dialogue_now()

            self._log_debug('schedule_prefix_only_emit', hook_id=hook_id, wait_ms=wait_ms, buffered=list(self._state['hook_buffers'].keys()))
            self._state['pending_prefix_started_at'] = time.monotonic()
            self._schedule_pending_emit(wait_ms)
            return None

        if hook_text:
            self._state['hook_buffers'][hook_id] = hook_text

        if hook_id == config['dialogue_hook_id']:
            now = time.monotonic()
            self._state['pending_dialogue'] = hook_text
            self._state['pending_prefix_started_at'] = 0.0
            self._state['pending_dialogue_started_at'] = now
            self._state['pending_dialogue_updated_at'] = now
            self._state['pending_prefix_values'] = {
                prefix_hook_id: self._state['hook_buffers'][prefix_hook_id]
                for prefix_hook_id in config['prefix_hook_ids']
                if (self._state['hook_buffers'].get(prefix_hook_id) or '').strip()
            }
            self._log_debug('dialogue_received', hook_id=hook_id, text=hook_text, buffered=list(self._state['hook_buffers'].keys()))
            if not hook_text:
                self._log_debug('drop_empty_dialogue', hook_id=hook_id)
                return None

            max_dialogue_length = max(200, int(self._state.get('max_dialogue_length', 400)))
            if len(hook_text) > max_dialogue_length:
                self._log_debug(
                    'drop_oversized_dialogue',
                    hook_id=hook_id,
                    length=len(hook_text),
                    max_dialogue_length=max_dialogue_length,
                    text=hook_text,
                )
                self._discard_pending_concat_state()
                return None

            if not config['prefix_hook_ids']:
                wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
                if wait_ms <= 0:
                    self._log_debug('emit_dialogue_without_prefixes', hook_id=hook_id)
                    return self._emit_pending_dialogue_now()
                self._log_debug('schedule_dialogue_continuation_wait', hook_id=hook_id, wait_ms=wait_ms)
                self._schedule_pending_emit(wait_ms)
                return None

            if self._all_prefixes_ready(config):
                wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
                if wait_ms <= 0:
                    self._log_debug('emit_dialogue_with_ready_prefixes', hook_id=hook_id)
                    return self._emit_pending_dialogue_now()
                self._log_debug('schedule_ready_dialogue_continuation_wait', hook_id=hook_id, wait_ms=wait_ms)
                self._schedule_pending_emit(wait_ms)
                return None

            wait_ms = max(0, int(config['speaker_wait_ms']))
            if wait_ms == 0:
                continuation_wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
                if continuation_wait_ms <= 0:
                    self._log_debug('emit_dialogue_no_wait', hook_id=hook_id)
                    return self._emit_pending_dialogue_now()
                self._log_debug('schedule_dialogue_continuation_only', hook_id=hook_id, wait_ms=continuation_wait_ms)
                self._schedule_pending_emit(continuation_wait_ms)
                return None

            combined_wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
            self._log_debug('schedule_pending_emit', hook_id=hook_id, wait_ms=combined_wait_ms, expected_prefixes=config['prefix_hook_ids'])
            self._schedule_pending_emit(combined_wait_ms)
            return None

        return None

    def process_clipboard_text(self, text: str) -> Optional[str]:
        if not self._state['enabled_mode']:
            return text

        config = self._get_concat_config()
        if not config['all_hook_ids']:
            return text

        text_stripped = text.strip()
        if text_stripped.startswith('[Console]'):
            return text

        if self._state.get('burst_suppression_active'):
            self._log_debug('clipboard_drop_during_burst', text=text_stripped)
            return None

        if self._state.get('post_burst_recovery_active'):
            self._log_debug('clipboard_drop_during_recovery', text=text_stripped)
            return None

        pending_clipboard_emit = self._consume_pending_clipboard_emit()
        if pending_clipboard_emit is not None:
            self._log_debug('clipboard_consume_pending_emit', output=pending_clipboard_emit)
            return pending_clipboard_emit

        match = self._hook_pattern.match(text_stripped)
        if not match:
            return text

        hook_id = match.group(1)
        hook_text = match.group(3).strip()

        if hook_id not in config['all_hook_ids']:
            self._log_debug('clipboard_drop_unconfigured_hook', hook_id=hook_id, text=hook_text)
            return None

        self._log_debug('clipboard_wait_for_display_emit', hook_id=hook_id, text=hook_text, buffered=list(self._state['hook_buffers'].keys()))
        return None

    def _get_concat_config(self):
        dialogue_hook_selector = str(self._state.get('dialogue_hook_id', '')).strip()
        prefix_hook_selectors = self._parse_selector_list(self._state.get('prefix_hook_ids', ''))

        if not dialogue_hook_selector:
            legacy_hook_selectors = self._parse_selector_list(self._state.get('hook_ids', ''))
            if legacy_hook_selectors:
                dialogue_hook_selector = legacy_hook_selectors[-1]
                prefix_hook_selectors = legacy_hook_selectors[:-1]

        dialogue_hook_id = self._resolve_hook_selector(dialogue_hook_selector)
        prefix_hook_ids = []
        for selector in prefix_hook_selectors:
            resolved_hook_id = self._resolve_hook_selector(selector)
            if resolved_hook_id and resolved_hook_id not in prefix_hook_ids:
                prefix_hook_ids.append(resolved_hook_id)

        all_hook_ids = []
        for hook_id in prefix_hook_ids + ([dialogue_hook_id] if dialogue_hook_id else []):
            if hook_id and hook_id not in all_hook_ids:
                all_hook_ids.append(hook_id)

        return {
            'dialogue_hook_id': dialogue_hook_id,
            'dialogue_hook_selector': dialogue_hook_selector,
            'prefix_hook_ids': prefix_hook_ids,
            'prefix_hook_selectors': prefix_hook_selectors,
            'all_hook_ids': all_hook_ids,
            'speaker_wait_ms': self._state.get('speaker_wait_ms', 150),
        }

    def _parse_selector_list(self, selectors_value) -> list:
        hook_ids_str = str(selectors_value).strip()
        if not hook_ids_str:
            return []
        selectors = []
        for selector in hook_ids_str.split(','):
            selector = selector.strip()
            if selector:
                selectors.append(selector)
        return selectors

    def _resolve_hook_selector(self, selector: str) -> str:
        normalized_selector = str(selector or '').strip()
        if not normalized_selector:
            return ''
        if normalized_selector.isdigit():
            return normalized_selector

        app = getattr(self, 'app', None)
        if app and hasattr(app, 'get_hooks_snapshot'):
            hooks = app.get_hooks_snapshot()
        else:
            hooks = getattr(app, 'hooks', {}) if app else {}
        for hook_id, hook_info in hooks.items():
            context_info = str(hook_info.get('context_info', '')).strip()
            function_name = str(hook_info.get('function', '')).strip()
            if context_info and context_info == normalized_selector:
                return str(hook_id)
            if function_name and function_name == normalized_selector:
                return str(hook_id)
        return ''

    def _all_prefixes_ready(self, config) -> bool:
        if not config['prefix_hook_ids']:
            return True
        return all(prefix_hook_id in self._state['hook_buffers'] for prefix_hook_id in config['prefix_hook_ids'])

    def _build_clipboard_output(self, config, hook_text: str) -> str:
        mode = str(self._state.get('clipboard_output_mode', 'combined')).strip().lower()
        dialogue_text = (hook_text or '').strip()
        if not dialogue_text:
            return ""

        if mode == 'dialogue_only':
            return self._strip_wrapping_dialogue_quotes(dialogue_text)

        output_parts = []
        for prefix_hook_id in config['prefix_hook_ids']:
            prefix_text = self._state['hook_buffers'].get(prefix_hook_id, '').strip()
            if prefix_text:
                output_parts.append(prefix_text)
        output_parts.append(dialogue_text)
        return ''.join(output_parts)

    def _build_pending_clipboard_output(self) -> Optional[str]:
        self._maybe_recover_pending_dialogue_from_hook_state()
        config = self._get_concat_config()
        dialogue_text = (self._state.get('pending_dialogue') or '').strip()
        if not dialogue_text:
            return None

        clipboard_output = self._build_clipboard_output(config, dialogue_text)
        if not clipboard_output:
            return None
        return clipboard_output + '\n'

    def _strip_wrapping_dialogue_quotes(self, text: str) -> str:
        stripped = text.strip()
        if len(stripped) < 2:
            return stripped

        quote_pairs = [
            ('「', '」'),
            ('『', '』'),
            ('"', '"'),
            ('“', '”'),
            ("'", "'"),
            ('‘', '’'),
        ]

        for opening_quote, closing_quote in quote_pairs:
            if stripped.startswith(opening_quote) and stripped.endswith(closing_quote):
                inner_text = stripped[len(opening_quote):len(stripped) - len(closing_quote)].strip()
                return inner_text if inner_text else stripped

        return stripped

    def _build_pending_output(self) -> str:
        self._maybe_recover_pending_dialogue_from_hook_state()
        config = self._get_concat_config()
        output_parts = []
        for prefix_hook_id in config['prefix_hook_ids']:
            prefix_text = self._state['hook_buffers'].get(prefix_hook_id, '').strip()
            if prefix_text:
                output_parts.append(prefix_text)
        dialogue_text = (self._state.get('pending_dialogue') or '').strip()
        if dialogue_text:
            output_parts.append(dialogue_text)
        if not output_parts:
            return ""
        return ''.join(output_parts) + '\n'

    def _get_dialogue_continuation_window_ms(self) -> int:
        return max(0, int(self._state.get('dialogue_continuation_window_ms', 450)))

    def _compute_pending_dialogue_emit_wait_ms(self, config, now: Optional[float] = None) -> int:
        now = time.monotonic() if now is None else now
        wait_ms = 0

        pending_dialogue = (self._state.get('pending_dialogue') or '').strip()
        if not pending_dialogue:
            return 0

        continuation_window_ms = self._get_dialogue_continuation_window_ms()
        if continuation_window_ms > 0:
            updated_at = float(self._state.get('pending_dialogue_updated_at') or 0.0)
            if updated_at > 0.0:
                continuation_elapsed_ms = max(0.0, (now - updated_at) * 1000.0)
                wait_ms = max(wait_ms, max(0, int(round(continuation_window_ms - continuation_elapsed_ms))))

        if config.get('prefix_hook_ids') and not self._all_prefixes_ready(config):
            speaker_wait_ms = max(0, int(config.get('speaker_wait_ms', 150)))
            started_at = float(self._state.get('pending_dialogue_started_at') or 0.0)
            if started_at > 0.0:
                prefix_elapsed_ms = max(0.0, (now - started_at) * 1000.0)
                wait_ms = max(wait_ms, max(0, int(round(speaker_wait_ms - prefix_elapsed_ms))))
            else:
                wait_ms = max(wait_ms, speaker_wait_ms)

        return wait_ms

    def _consume_pending_dialogue_continuation(self, config) -> bool:
        continuation = (self._state.get('pending_dialogue_continuation') or '').strip()
        if not continuation:
            return False
        pending_dialogue = (self._state.get('pending_dialogue') or '').strip()
        continuation_at = float(self._state.get('pending_dialogue_continuation_at') or time.monotonic())
        self._state['pending_dialogue_continuation'] = None
        self._state['pending_dialogue_continuation_at'] = 0.0
        combined_dialogue = pending_dialogue + continuation
        max_dialogue_length = max(200, int(self._state.get('max_dialogue_length', 400)))
        if not pending_dialogue or len(combined_dialogue) > max_dialogue_length:
            return False
        self._state['pending_dialogue'] = combined_dialogue
        self._state['pending_dialogue_updated_at'] = continuation_at
        self._state['hook_buffers'][config['dialogue_hook_id']] = combined_dialogue
        self._log_debug('append_speaker_resolved_continuation', incoming=continuation, combined=combined_dialogue)
        return True

    def _resolve_pending_dialogue_continuation(self):
        config = self._get_concat_config()
        if not self._consume_pending_dialogue_continuation(config):
            return
        now = time.monotonic()
        wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
        if wait_ms <= 0:
            self._flush_pending_dialogue()
            return
        self._schedule_pending_emit(wait_ms)

    def _maybe_append_dialogue_continuation(self, config, hook_text: str) -> bool:
        pending_dialogue = (self._state.get('pending_dialogue') or '').strip()
        if not pending_dialogue:
            return False

        continuation_window_ms = self._get_dialogue_continuation_window_ms()
        if continuation_window_ms <= 0:
            return False

        pending_prefix_values = self._state.get('pending_prefix_values', {})
        for prefix_hook_id, pending_prefix in pending_prefix_values.items():
            current_prefix = str(self._state['hook_buffers'].get(prefix_hook_id, '')).strip()
            if current_prefix and current_prefix != str(pending_prefix).strip():
                self._log_debug('skip_dialogue_continuation_speaker_changed', hook_id=prefix_hook_id, previous=pending_prefix, current=current_prefix)
                return False

        now = time.monotonic()
        updated_at = float(self._state.get('pending_dialogue_updated_at') or 0.0)
        if updated_at <= 0.0:
            return False

        elapsed_ms = (now - updated_at) * 1000.0
        if elapsed_ms > continuation_window_ms:
            self._log_debug(
                'dialogue_continuation_window_expired',
                elapsed_ms=round(elapsed_ms, 1),
                continuation_window_ms=continuation_window_ms,
            )
            return False

        pending_continuation = (self._state.get('pending_dialogue_continuation') or '').strip()
        max_dialogue_length = max(200, int(self._state.get('max_dialogue_length', 400)))
        if pending_prefix_values:
            held_continuation = pending_continuation + hook_text
            if len(pending_dialogue + held_continuation) > max_dialogue_length:
                if pending_continuation:
                    self._consume_pending_dialogue_continuation(config)
                return False
            self._state['pending_dialogue_continuation'] = held_continuation
            self._state['pending_dialogue_continuation_at'] = now
            remaining_ms = max(0, int(round(continuation_window_ms - elapsed_ms)))
            speaker_resolution_ms = min(max(0, int(config.get('speaker_wait_ms', 150))), remaining_ms)
            self._log_debug(
                'hold_dialogue_for_speaker_resolution',
                incoming=hook_text,
                held=held_continuation,
                wait_ms=speaker_resolution_ms,
            )
            self._schedule_pending_callback(speaker_resolution_ms, self._resolve_pending_dialogue_continuation)
            return True

        combined_dialogue = pending_dialogue + hook_text
        if len(combined_dialogue) > max_dialogue_length:
            self._log_debug(
                'drop_dialogue_continuation_oversized',
                length=len(combined_dialogue),
                max_dialogue_length=max_dialogue_length,
                existing=pending_dialogue,
                incoming=hook_text,
            )
            return False

        self._state['pending_dialogue'] = combined_dialogue
        self._state['pending_dialogue_updated_at'] = now
        self._state['hook_buffers'][config['dialogue_hook_id']] = combined_dialogue

        wait_ms = self._compute_pending_dialogue_emit_wait_ms(config, now)
        self._log_debug(
            'append_dialogue_continuation',
            incoming=hook_text,
            combined=combined_dialogue,
            elapsed_ms=round(elapsed_ms, 1),
            wait_ms=wait_ms,
        )
        self._schedule_pending_emit(wait_ms)
        return True

    def _emit_pending_dialogue_now(self) -> Optional[str]:
        self._cancel_pending_timer()
        output_text = self._build_pending_output()
        clipboard_output = self._build_pending_clipboard_output()
        self._log_debug('emit_pending_dialogue', output=output_text, buffered=list(self._state['hook_buffers'].keys()))
        self._state['pending_dialogue'] = None
        self._state['pending_prefix_started_at'] = 0.0
        self._state['pending_dialogue_started_at'] = 0.0
        self._state['pending_dialogue_updated_at'] = 0.0
        self._state['pending_prefix_values'] = {}
        self._state['pending_dialogue_continuation'] = None
        self._state['pending_dialogue_continuation_at'] = 0.0
        self._state['hook_buffers'] = {}
        if output_text:
            self._state['pending_clipboard_emit'] = clipboard_output
        else:
            self._state['pending_clipboard_emit'] = None
        return output_text or None

    def _submitted_dialogue_is_waiting_in_pipeline(self) -> bool:
        if self._state.get('pending_dialogue'):
            return False
        if float(self._state.get('pending_prefix_started_at') or 0.0) <= 0.0:
            return False
        config = self._get_concat_config()
        dialogue_hook_id = str(config.get('dialogue_hook_id') or '').strip()
        app = getattr(self, 'app', None)
        if not dialogue_hook_id or not app or not hasattr(app, 'get_hooks_snapshot'):
            return False
        hook_info = app.get_hooks_snapshot().get(dialogue_hook_id)
        if not isinstance(hook_info, dict):
            return False
        latest_event_sequence = int(hook_info.get('latest_event_sequence') or 0)
        last_pipeline_sequence = int(hook_info.get('last_pipeline_sequence') or 0)
        last_processed_sequence = int(hook_info.get('last_processed_sequence') or 0)
        return (
            latest_event_sequence > 0 and
            latest_event_sequence <= last_pipeline_sequence and
            latest_event_sequence > last_processed_sequence
        )

    def _flush_pending_dialogue(self):
        self._log_debug('flush_pending_dialogue')
        if self._submitted_dialogue_is_waiting_in_pipeline():
            self._log_debug('defer_flush_for_submitted_dialogue')
            self._schedule_pending_emit(10)
            return
        output_text = self._emit_pending_dialogue_now()
        if not output_text:
            return
        app = getattr(self, 'app', None)
        if not app:
            return
        try:
            app.submit_output_processing(output_text, True, front=True)
        except Exception:
            pass

    def _schedule_pending_callback(self, wait_ms: int, callback):
        self._cancel_pending_timer()
        app = getattr(self, 'app', None)
        if not app or not hasattr(app, 'schedule_pipeline_callback'):
            return
        self._state['pending_timer_id'] = app.schedule_pipeline_callback(wait_ms, callback)

    def _schedule_pending_emit(self, wait_ms: int):
        self._schedule_pending_callback(wait_ms, self._flush_pending_dialogue)

    def _cancel_pending_timer(self):
        timer_id = self._state.get('pending_timer_id')
        app = getattr(self, 'app', None)
        if timer_id and app and hasattr(app, 'cancel_pipeline_callback'):
            try:
                app.cancel_pipeline_callback(timer_id)
            except Exception:
                pass
        self._state['pending_timer_id'] = None

    def _handle_burst_input(self, config, hook_id: str, hook_text: str) -> bool:
        if not self._state.get('burst_stabilization_enabled', True):
            return False

        now = time.monotonic()
        self._prune_recent_hook_times(now)
        self._state['recent_hook_times'].append(now)

        burst_threshold = max(2, int(self._state.get('burst_line_threshold', 4)))
        hook_count = max(1, len(config.get('all_hook_ids') or []))
        threshold_events = burst_threshold * hook_count
        suppression_active = bool(self._state.get('burst_suppression_active'))
        current_burst_size = len(self._state['recent_hook_times'])
        release_wait_ms = max(
            max(50, int(self._state.get('burst_settle_ms', 200))),
            max(100, int(self._state.get('burst_window_ms', 600))),
        )

        if suppression_active:
            self._discard_pending_concat_state()
            self._schedule_burst_release(release_wait_ms)
            self._log_debug(
                'burst_suppression_refresh',
                hook_id=hook_id,
                burst_size=current_burst_size,
                threshold_events=threshold_events,
                release_wait_ms=release_wait_ms,
                text=hook_text,
            )
            return True

        if current_burst_size >= threshold_events:
            self._state['burst_suppression_active'] = True
            self._cancel_pending_timer()
            self._discard_pending_concat_state()
            self._schedule_burst_release(release_wait_ms)
            self._log_debug(
                'burst_suppression_enter',
                hook_id=hook_id,
                burst_size=current_burst_size,
                threshold_events=threshold_events,
                release_wait_ms=release_wait_ms,
                text=hook_text,
            )
            return True

        return False

    def _handle_post_burst_recovery(self, config, hook_id: str, hook_text: str) -> bool:
        if not self._state.get('post_burst_recovery_active'):
            return False

        if hook_id in config['prefix_hook_ids']:
            if not self._is_valid_recovery_prefix(hook_text):
                self._log_debug('recovery_drop_bad_prefix', hook_id=hook_id, text=hook_text)
                self._discard_pending_concat_state()
                self._state['recovery_prefix_hook_ids'] = set()
                return True

            recovery_prefix_ids = set(self._state.get('recovery_prefix_hook_ids') or set())
            recovery_prefix_ids.add(hook_id)
            self._state['recovery_prefix_hook_ids'] = recovery_prefix_ids
            self._log_debug(
                'recovery_accept_prefix',
                hook_id=hook_id,
                text=hook_text,
                ready_prefixes=sorted(recovery_prefix_ids),
            )
            return False

        if hook_id == config['dialogue_hook_id']:
            if not self._is_valid_recovery_dialogue(hook_text):
                self._log_debug('recovery_drop_bad_dialogue', hook_id=hook_id, text=hook_text)
                self._discard_pending_concat_state()
                self._state['recovery_prefix_hook_ids'] = set()
                return True

            if config['prefix_hook_ids']:
                recovery_prefix_ids = set(self._state.get('recovery_prefix_hook_ids') or set())
                required_prefix_ids = set(config['prefix_hook_ids'])
                if not required_prefix_ids.issubset(recovery_prefix_ids):
                    looks_spoken = any(marker in hook_text for marker in ('「', '」', '『', '』', '"', '“', '”'))
                    if looks_spoken:
                        self._log_debug(
                            'recovery_wait_for_prefix_pair',
                            hook_id=hook_id,
                            text=hook_text,
                            ready_prefixes=sorted(recovery_prefix_ids),
                            required_prefixes=sorted(required_prefix_ids),
                        )
                        self._discard_pending_concat_state()
                        return True
                    self._state['post_burst_recovery_active'] = False
                    self._state['recovery_prefix_hook_ids'] = set()
                    self._log_debug('recovery_complete_narration', hook_id=hook_id, text=hook_text)
                    return False

            self._state['post_burst_recovery_active'] = False
            self._state['recovery_prefix_hook_ids'] = set()
            self._log_debug('recovery_complete', hook_id=hook_id, text=hook_text)
            return False

        self._log_debug('recovery_drop_unexpected_hook', hook_id=hook_id, text=hook_text)
        self._discard_pending_concat_state()
        self._state['recovery_prefix_hook_ids'] = set()
        return True

    def _is_valid_recovery_prefix(self, text: str) -> bool:
        candidate = (text or '').strip()
        if not candidate:
            return False
        if len(candidate) > 20:
            return False
        if any(marker in candidate for marker in ('「', '」', '『', '』', '"', '“', '”')):
            return False
        return True

    def _is_valid_recovery_dialogue(self, text: str) -> bool:
        candidate = (text or '').strip()
        if not candidate:
            return False
        if len(candidate) > 240:
            return False
        quote_markers = candidate.count('「') + candidate.count('『')
        if quote_markers > 2:
            return False
        return True

    def _prune_recent_hook_times(self, now: float):
        window_ms = max(100, int(self._state.get('burst_window_ms', 600)))
        cutoff = now - (window_ms / 1000.0)
        recent_hook_times = self._state['recent_hook_times']
        while recent_hook_times and recent_hook_times[0] < cutoff:
            recent_hook_times.popleft()

    def _schedule_burst_release(self, wait_ms: int):
        self._cancel_burst_release_timer()
        app = getattr(self, 'app', None)
        if not app or not hasattr(app, 'schedule_pipeline_callback'):
            return
        self._state['burst_release_timer_id'] = app.schedule_pipeline_callback(wait_ms, self._release_burst_suppression)

    def _cancel_burst_release_timer(self):
        timer_id = self._state.get('burst_release_timer_id')
        app = getattr(self, 'app', None)
        if timer_id and app and hasattr(app, 'cancel_pipeline_callback'):
            try:
                app.cancel_pipeline_callback(timer_id)
            except Exception:
                pass
        self._state['burst_release_timer_id'] = None

    def _discard_pending_concat_state(self):
        self._state['hook_buffers'] = {}
        self._state['pending_dialogue'] = None
        self._state['pending_clipboard_emit'] = None
        self._state['pending_prefix_started_at'] = 0.0
        self._state['pending_dialogue_started_at'] = 0.0
        self._state['pending_dialogue_updated_at'] = 0.0
        self._state['pending_prefix_values'] = {}
        self._state['pending_dialogue_continuation'] = None
        self._state['pending_dialogue_continuation_at'] = 0.0

    def _maybe_recover_pending_dialogue_from_hook_state(self):
        pending_dialogue = (self._state.get('pending_dialogue') or '').strip()
        if pending_dialogue:
            return

        pending_prefix_started_at = float(self._state.get('pending_prefix_started_at') or 0.0)
        if pending_prefix_started_at <= 0.0:
            return

        if not self._state.get('hook_buffers'):
            return

        config = self._get_concat_config()
        dialogue_hook_id = str(config.get('dialogue_hook_id') or '').strip()
        if not dialogue_hook_id:
            return

        app = getattr(self, 'app', None)
        if app and hasattr(app, 'get_hooks_snapshot'):
            hooks = app.get_hooks_snapshot()
        else:
            hooks = getattr(app, 'hooks', {}) if app else {}
        hook_info = hooks.get(dialogue_hook_id)
        if not isinstance(hook_info, dict):
            return

        latest_event_snapshot = hook_info.get('latest_event_snapshot')
        if isinstance(latest_event_snapshot, (tuple, list)) and len(latest_event_snapshot) == 3:
            latest_text = str(latest_event_snapshot[0] or '').strip()
            last_seen_monotonic = float(latest_event_snapshot[1] or 0.0)
            latest_event_sequence = int(latest_event_snapshot[2] or 0)
        else:
            latest_text = str(hook_info.get('latest_text') or '').strip()
            last_seen_monotonic = float(hook_info.get('last_seen_monotonic') or 0.0)
            latest_event_sequence = int(hook_info.get('latest_event_sequence') or 0)
        last_pipeline_sequence = int(hook_info.get('last_pipeline_sequence') or 0)
        if latest_event_sequence and latest_event_sequence <= last_pipeline_sequence:
            self._log_debug(
                'skip_recovery_for_submitted_dialogue',
                hook_id=dialogue_hook_id,
                latest_event_sequence=latest_event_sequence,
                last_pipeline_sequence=last_pipeline_sequence,
            )
            return
        if not latest_text or last_seen_monotonic <= pending_prefix_started_at:
            return

        now = time.monotonic()
        if now - last_seen_monotonic > 1.5:
            return

        self._state['pending_dialogue'] = latest_text
        self._log_debug(
            'recovered_pending_dialogue_from_hook_state',
            hook_id=dialogue_hook_id,
            text=latest_text,
            last_seen_monotonic=last_seen_monotonic,
            pending_prefix_started_at=pending_prefix_started_at,
        )

    def _release_burst_suppression(self):
        self._state['burst_release_timer_id'] = None
        self._state['burst_suppression_active'] = False
        self._state['recent_hook_times'] = deque()
        self._discard_pending_concat_state()
        self._state['post_burst_recovery_active'] = True
        self._state['recovery_prefix_hook_ids'] = set()
        self._log_debug('burst_suppression_exit_to_recovery')

    def reset(self):
        self._cancel_pending_timer()
        self._cancel_burst_release_timer()
        self._discard_pending_concat_state()
        self._state['recent_hook_times'] = deque()
        self._state['burst_suppression_active'] = False
        self._state['post_burst_recovery_active'] = False
        self._state['recovery_prefix_hook_ids'] = set()

    def _consume_pending_clipboard_emit(self) -> Optional[str]:
        pending_clipboard_emit = self._state.get('pending_clipboard_emit')
        self._state['pending_clipboard_emit'] = None
        return pending_clipboard_emit

    def on_enable(self):
        self.reset()
        self._log_resolved_config('on_enable')

    def on_disable(self):
        self.reset()

    def get_settings(self) -> dict:
        return {
            'enabled_mode': (
                self._state['enabled_mode'],
                'bool',
                'Enable hook concatenation mode'
            ),
            'num_hooks': (
                self._state['num_hooks'],
                'int_slider',
                'Legacy number of hooks setting (kept for compatibility)',
                {'min': 2, 'max': 10}
            ),
            'hook_ids': (
                self._state['hook_ids'],
                'str',
                'Legacy hook order/selectors (fallback only). For Luna you can use numeric IDs, function labels, or full context_info selectors.'
            ),
            'dialogue_hook_id': (
                self._state['dialogue_hook_id'],
                'str',
                'Required dialogue hook selector. Supports a numeric ID like 2, a Luna function label like EXBWX0@25C880, or full Luna context_info.'
            ),
            'prefix_hook_ids': (
                self._state['prefix_hook_ids'],
                'str',
                'Optional prefix hook selectors in order. Supports numeric IDs like 1, Luna function labels, or full Luna context_info selectors.'
            ),
            'speaker_wait_ms': (
                self._state['speaker_wait_ms'],
                'int_slider',
                'How long to wait for optional prefix hooks before emitting dialogue only',
                {'min': 0, 'max': 1000}
            ),
            'dialogue_continuation_window_ms': (
                self._state['dialogue_continuation_window_ms'],
                'int_slider',
                'How long to merge rapid dialogue chunks from the same speaker or narration hook before emitting',
                {'min': 0, 'max': 2000}
            ),
            'clipboard_output_mode': (
                self._state['clipboard_output_mode'],
                'choice',
                'Clipboard output during translation',
                {
                    'combined': 'Combined speaker + dialogue',
                    'dialogue_only': 'Dialogue only',
                }
            ),
            'max_dialogue_length': (
                self._state['max_dialogue_length'],
                'int_slider',
                'Drop any single dialogue-hook payload longer than this many characters',
                {'min': 200, 'max': 1000}
            ),
            'burst_stabilization_enabled': (
                self._state['burst_stabilization_enabled'],
                'bool',
                'Suppress concat output entirely during rapid hook churn, such as game skip mode'
            ),
            'burst_window_ms': (
                self._state['burst_window_ms'],
                'int_slider',
                'How much quiet time is required before burst suppression ends',
                {'min': 100, 'max': 2000}
            ),
            'burst_line_threshold': (
                self._state['burst_line_threshold'],
                'int_slider',
                'How many rapid logical lines trigger burst suppression',
                {'min': 2, 'max': 12}
            ),
            'burst_settle_ms': (
                self._state['burst_settle_ms'],
                'int_slider',
                'Minimum quiet time before burst suppression can end',
                {'min': 50, 'max': 1000}
            )
        }

    def set_setting(self, name: str, value) -> bool:
        if name == 'enabled_mode':
            try:
                self._state['enabled_mode'] = bool(value)
                self.reset()
                self._log_resolved_config(f'set_setting:{name}')
                return True
            except (ValueError, TypeError):
                return False

        elif name == 'num_hooks':
            try:
                num_hooks = int(value)
                if 2 <= num_hooks <= 10:
                    self._state['num_hooks'] = num_hooks
                    return True
                return False
            except (ValueError, TypeError):
                return False

        elif name in ('hook_ids', 'dialogue_hook_id', 'prefix_hook_ids'):
            try:
                self._state[name] = str(value).strip()
                self.reset()
                self._log_resolved_config(f'set_setting:{name}')
                return True
            except (ValueError, TypeError):
                return False

        elif name == 'speaker_wait_ms':
            try:
                wait_ms = int(value)
                if 0 <= wait_ms <= 1000:
                    self._state['speaker_wait_ms'] = wait_ms
                    self.reset()
                    self._log_resolved_config(f'set_setting:{name}')
                    return True
                return False
            except (ValueError, TypeError):
                return False

        elif name == 'dialogue_continuation_window_ms':
            try:
                continuation_window_ms = int(value)
                if 0 <= continuation_window_ms <= 2000:
                    self._state['dialogue_continuation_window_ms'] = continuation_window_ms
                    self.reset()
                    self._log_resolved_config(f'set_setting:{name}')
                    return True
                return False
            except (ValueError, TypeError):
                return False

        elif name == 'clipboard_output_mode':
            mode = str(value).strip().lower()
            if mode in {'combined', 'dialogue_only'}:
                self._state['clipboard_output_mode'] = mode
                self.reset()
                self._log_resolved_config(f'set_setting:{name}')
                return True
            return False

        elif name == 'max_dialogue_length':
            try:
                max_dialogue_length = int(value)
                if 200 <= max_dialogue_length <= 1000:
                    self._state['max_dialogue_length'] = max_dialogue_length
                    self.reset()
                    self._log_resolved_config(f'set_setting:{name}')
                    return True
                return False
            except (ValueError, TypeError):
                return False

        elif name == 'burst_stabilization_enabled':
            try:
                self._state['burst_stabilization_enabled'] = bool(value)
                self.reset()
                self._log_resolved_config(f'set_setting:{name}')
                return True
            except (ValueError, TypeError):
                return False

        elif name == 'burst_window_ms':
            try:
                window_ms = int(value)
                if 100 <= window_ms <= 2000:
                    self._state['burst_window_ms'] = window_ms
                    self.reset()
                    self._log_resolved_config(f'set_setting:{name}')
                    return True
                return False
            except (ValueError, TypeError):
                return False

        elif name == 'burst_line_threshold':
            try:
                threshold = int(value)
                if 2 <= threshold <= 12:
                    self._state['burst_line_threshold'] = threshold
                    self.reset()
                    self._log_resolved_config(f'set_setting:{name}')
                    return True
                return False
            except (ValueError, TypeError):
                return False

        elif name == 'burst_settle_ms':
            try:
                settle_ms = int(value)
                if 50 <= settle_ms <= 1000:
                    self._state['burst_settle_ms'] = settle_ms
                    self.reset()
                    self._log_resolved_config(f'set_setting:{name}')
                    return True
                return False
            except (ValueError, TypeError):
                return False

        return False


plugin = HookConcatenationPlugin()
