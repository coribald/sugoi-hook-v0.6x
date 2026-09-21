"""Thread-safe hook records and event-sequence ownership."""

import threading


class HookRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.records = {}
        self.event_sequence = 0

    def record_text(self, hook_id, function, context_info, text, now, max_texts):
        hook_id = str(hook_id)
        with self.lock:
            is_new = hook_id not in self.records
            if is_new:
                self.records[hook_id] = {
                    'id': hook_id, 'function': function, 'context_info': context_info,
                    'texts': [], 'latest_text': '', 'last_seen_monotonic': 0.0,
                    'latest_event_sequence': 0, 'last_pipeline_sequence': 0,
                    'last_processed_sequence': 0,
                }
            self.event_sequence += 1
            sequence = self.event_sequence
            record = self.records[hook_id]
            record['latest_text'] = text
            record['last_seen_monotonic'] = now
            record['latest_event_sequence'] = sequence
            record['latest_event_snapshot'] = (text, now, sequence)
            if len(record['texts']) < max_texts:
                record['texts'].append(text)
            return is_new, sequence

    def snapshot(self):
        with self.lock:
            return {hook_id: {**record, 'texts': list(record.get('texts', []))} for hook_id, record in self.records.items()}

    def mark_submitted(self, hook_id, sequence): self._mark(hook_id, sequence, 'last_pipeline_sequence')
    def mark_processed(self, hook_id, sequence): self._mark(hook_id, sequence, 'last_processed_sequence')

    def _mark(self, hook_id, sequence, field):
        with self.lock:
            record = self.records.get(str(hook_id))
            if record is not None: record[field] = max(int(record.get(field) or 0), int(sequence))

    def clear(self):
        with self.lock: self.records.clear()
