#!/usr/bin/env python3
"""
Native dictionary backend for Sugoi Hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

DICTIONARY_CACHE_SCHEMA_VERSION = "3"


def _normalize_whitespace(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def _flatten_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten_text(item) for item in node)
    if isinstance(node, dict):
        tag = str(node.get("tag", "")).lower()
        content = _flatten_text(node.get("content"))
        if tag == "li":
            return f"- {content}\n"
        if tag in {"div", "ul", "ol", "table", "tr", "p"}:
            return f"{content}\n"
        if tag in {"th", "td", "span", "ruby", "rt", "a"}:
            return content
        return content
    return str(node)


def _extract_glossary_fragments(node: Any, fragments: list[str]) -> None:
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict):
            content_key = str(data.get("content", "")).lower()
            if content_key in {
                "glossary",
                "xref-glossary",
                "info-gloss-content",
                "sense-note-content",
                "example-sentence-b",
                "reference-label",
            }:
                text = _normalize_whitespace(_flatten_text(node.get("content")))
                if text:
                    fragments.append(text)
        _extract_glossary_fragments(node.get("content"), fragments)
        return
    if isinstance(node, list):
        for item in node:
            _extract_glossary_fragments(item, fragments)


def extract_entry_summary(definitions: Any) -> str:
    fragments: list[str] = []
    _extract_glossary_fragments(definitions, fragments)
    if fragments:
        deduped: list[str] = []
        seen = set()
        for fragment in fragments:
            if fragment not in seen:
                seen.add(fragment)
                deduped.append(fragment)
        return "\n".join(deduped)
    return _normalize_whitespace(_flatten_text(definitions))


def extract_entry_display_tags(definitions: Any) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    allowed_content_types = {
        "part-of-speech-info",
        "misc-info",
        "dialect-info",
        "field-info",
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                content_type = str(data.get("content", "")).lower()
                if content_type in allowed_content_types:
                    text = _normalize_whitespace(_flatten_text(node.get("content")))
                    if text and text not in seen:
                        seen.add(text)
                        tags.append(text)
            walk(node.get("content"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(definitions)
    return tags


def extract_redirect_targets(definitions: Any) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()

    def add_target(value: str) -> None:
        value = _normalize_whitespace(value).strip()
        if value and value not in seen:
            seen.add(value)
            targets.append(value)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict) and str(data.get("content", "")).lower() == "redirect-glossary":
                content = node.get("content")
                href = str(node.get("href", "")).strip()
                if href:
                    try:
                        parsed = urlparse(href)
                        query = parse_qs(parsed.query)
                        for value in query.get("query", []):
                            add_target(unquote(value))
                    except Exception:
                        pass
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            item_href = str(item.get("href", "")).strip()
                            if item_href:
                                try:
                                    parsed = urlparse(item_href)
                                    query = parse_qs(parsed.query)
                                    for value in query.get("query", []):
                                        add_target(unquote(value))
                                except Exception:
                                    pass
                            add_target(_flatten_text(item.get("content")))
                        elif isinstance(item, str):
                            stripped = item.strip()
                            if stripped and stripped != "⟶":
                                add_target(stripped)
            walk(node.get("content"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(definitions)
    return targets


def extract_entry_glossaries_and_examples(definitions: Any) -> tuple[list[str], list[tuple[str, str]]]:
    glossaries: list[str] = []
    examples: list[tuple[str, str]] = []
    seen_glossaries: set[str] = set()
    seen_examples: set[tuple[str, str]] = set()

    def add_glossary(value: str) -> None:
        value = _normalize_whitespace(value).strip()
        if value and value not in seen_glossaries:
            seen_glossaries.add(value)
            glossaries.append(value)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            data = node.get("data")
            content_key = ""
            if isinstance(data, dict):
                content_key = str(data.get("content", "")).lower()

            if content_key == "glossary":
                content = node.get("content")
                if isinstance(content, list):
                    for item in content:
                        add_glossary(_flatten_text(item))
                else:
                    add_glossary(_flatten_text(content))

            if content_key == "example-sentence":
                jp = ""
                en = ""
                content = node.get("content")
                if isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        item_data = item.get("data")
                        item_key = str(item_data.get("content", "")).lower() if isinstance(item_data, dict) else ""
                        if item_key == "example-sentence-a":
                            jp = _normalize_whitespace(_flatten_text(item.get("content"))).strip()
                        elif item_key == "example-sentence-b":
                            en = _normalize_whitespace(_flatten_text(item.get("content"))).strip()
                if jp or en:
                    key = (jp, en)
                    if key not in seen_examples:
                        seen_examples.add(key)
                        examples.append(key)

            walk(node.get("content"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(definitions)
    return glossaries, examples


def _parse_rule_tags(rules_text: str) -> set[str]:
    if not rules_text:
        return set()
    normalized = rules_text.replace(";", ",").replace("/", ",").replace("|", ",")
    tokens = []
    for part in normalized.split(","):
        part = part.strip()
        if not part:
            continue
        tokens.extend(piece for piece in part.split() if piece)
    return set(tokens)


def _entry_matches_pos(entry_rules_text: str, allowed_pos: set[str] | None) -> bool:
    if not allowed_pos:
        return True
    entry_rules = _parse_rule_tags(entry_rules_text)
    if not entry_rules:
        return False
    if entry_rules & allowed_pos:
        return True
    if "v" in allowed_pos and any(rule.startswith("v") for rule in entry_rules):
        return True
    return False


ICHIDAN_STEM_ENDINGS = frozenset("いきぎしじちぢにひびぴみりえけげせぜてでねへべぺめれ")


@dataclass(frozen=True)
class DeinflectionRule:
    suffix: str
    replacement: str
    allowed_pos: frozenset[str]
    reason: str
    cost: int = 1


@dataclass(frozen=True)
class DeinflectedVariant:
    text: str
    allowed_pos: frozenset[str] | None
    cost: int
    reasons: tuple[str, ...]


COMMON_DEINFLECTION_RULES: tuple[DeinflectionRule, ...] = (
    DeinflectionRule("ませんでした", "る", frozenset({"v1"}), "polite_negative_past"),
    DeinflectionRule("ました", "る", frozenset({"v1"}), "polite_past"),
    DeinflectionRule("ません", "る", frozenset({"v1"}), "polite_negative"),
    DeinflectionRule("ます", "る", frozenset({"v1"}), "polite"),
    DeinflectionRule("ない", "る", frozenset({"v1"}), "negative"),
    DeinflectionRule("なかった", "る", frozenset({"v1"}), "negative_past"),
    DeinflectionRule("られる", "る", frozenset({"v1"}), "potential_or_passive"),
    DeinflectionRule("られ", "る", frozenset({"v1"}), "potential_or_passive_stem", 2),
    DeinflectionRule("させる", "る", frozenset({"v1"}), "causative"),
    DeinflectionRule("させ", "る", frozenset({"v1"}), "causative_stem", 2),
    DeinflectionRule("ろ", "る", frozenset({"v1"}), "imperative"),
    DeinflectionRule("た", "る", frozenset({"v1"}), "past"),
    DeinflectionRule("て", "る", frozenset({"v1"}), "te_form"),
    DeinflectionRule("ている", "る", frozenset({"v1"}), "progressive"),
    DeinflectionRule("てる", "る", frozenset({"v1"}), "progressive_contracted"),
    DeinflectionRule("ちゃう", "る", frozenset({"v1"}), "chau_contraction"),
    DeinflectionRule("ちゃった", "る", frozenset({"v1"}), "chau_past_contraction"),
    DeinflectionRule("よう", "る", frozenset({"v1"}), "volitional"),
    DeinflectionRule("れば", "る", frozenset({"v1"}), "conditional"),

    DeinflectionRule("行った", "行く", frozenset({"v5"}), "past_irregular_iku", 0),
    DeinflectionRule("いった", "いく", frozenset({"v5"}), "past_irregular_iku", 0),
    DeinflectionRule("逝った", "逝く", frozenset({"v5"}), "past_irregular_iku", 0),
    DeinflectionRule("往った", "往く", frozenset({"v5"}), "past_irregular_iku", 0),
    DeinflectionRule("行って", "行く", frozenset({"v5"}), "te_irregular_iku", 0),
    DeinflectionRule("いって", "いく", frozenset({"v5"}), "te_irregular_iku", 0),
    DeinflectionRule("逝って", "逝く", frozenset({"v5"}), "te_irregular_iku", 0),
    DeinflectionRule("往って", "往く", frozenset({"v5"}), "te_irregular_iku", 0),

    DeinflectionRule("わなかった", "う", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("かなかった", "く", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("がなかった", "ぐ", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("さなかった", "す", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("たなかった", "つ", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("らなかった", "る", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("まなかった", "む", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("ばなかった", "ぶ", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("ななかった", "ぬ", frozenset({"v5"}), "negative_past"),
    DeinflectionRule("わない", "う", frozenset({"v5"}), "negative"),
    DeinflectionRule("かない", "く", frozenset({"v5"}), "negative"),
    DeinflectionRule("がない", "ぐ", frozenset({"v5"}), "negative"),
    DeinflectionRule("さない", "す", frozenset({"v5"}), "negative"),
    DeinflectionRule("たない", "つ", frozenset({"v5"}), "negative"),
    DeinflectionRule("らない", "る", frozenset({"v5"}), "negative"),
    DeinflectionRule("まない", "む", frozenset({"v5"}), "negative"),
    DeinflectionRule("ばない", "ぶ", frozenset({"v5"}), "negative"),
    DeinflectionRule("なない", "ぬ", frozenset({"v5"}), "negative"),
    DeinflectionRule("いました", "う", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("きました", "く", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("ぎました", "ぐ", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("しました", "す", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("ちました", "つ", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("りました", "る", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("みました", "む", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("びました", "ぶ", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("にました", "ぬ", frozenset({"v5"}), "polite_past"),
    DeinflectionRule("いません", "う", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("きません", "く", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("ぎません", "ぐ", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("しません", "す", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("ちません", "つ", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("りません", "る", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("みません", "む", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("びません", "ぶ", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("にません", "ぬ", frozenset({"v5"}), "polite_negative"),
    DeinflectionRule("います", "う", frozenset({"v5"}), "polite"),
    DeinflectionRule("きます", "く", frozenset({"v5"}), "polite"),
    DeinflectionRule("ぎます", "ぐ", frozenset({"v5"}), "polite"),
    DeinflectionRule("します", "す", frozenset({"v5"}), "polite"),
    DeinflectionRule("ちます", "つ", frozenset({"v5"}), "polite"),
    DeinflectionRule("ります", "る", frozenset({"v5"}), "polite"),
    DeinflectionRule("みます", "む", frozenset({"v5"}), "polite"),
    DeinflectionRule("びます", "ぶ", frozenset({"v5"}), "polite"),
    DeinflectionRule("にます", "ぬ", frozenset({"v5"}), "polite"),
    DeinflectionRule("い", "う", frozenset({"v5"}), "stem"),
    DeinflectionRule("き", "く", frozenset({"v5"}), "stem"),
    DeinflectionRule("ぎ", "ぐ", frozenset({"v5"}), "stem"),
    DeinflectionRule("し", "す", frozenset({"v5"}), "stem"),
    DeinflectionRule("ち", "つ", frozenset({"v5"}), "stem"),
    DeinflectionRule("り", "る", frozenset({"v5"}), "stem"),
    DeinflectionRule("み", "む", frozenset({"v5"}), "stem"),
    DeinflectionRule("び", "ぶ", frozenset({"v5"}), "stem"),
    DeinflectionRule("に", "ぬ", frozenset({"v5"}), "stem"),
    DeinflectionRule("わせる", "う", frozenset({"v5"}), "causative"),
    DeinflectionRule("かせる", "く", frozenset({"v5"}), "causative"),
    DeinflectionRule("がせる", "ぐ", frozenset({"v5"}), "causative"),
    DeinflectionRule("させる", "す", frozenset({"v5"}), "causative"),
    DeinflectionRule("たせる", "つ", frozenset({"v5"}), "causative"),
    DeinflectionRule("らせる", "る", frozenset({"v5"}), "causative"),
    DeinflectionRule("ませる", "む", frozenset({"v5"}), "causative"),
    DeinflectionRule("ばせる", "ぶ", frozenset({"v5"}), "causative"),
    DeinflectionRule("なせる", "ぬ", frozenset({"v5"}), "causative"),
    DeinflectionRule("わせ", "う", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("かせ", "く", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("がせ", "ぐ", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("させ", "す", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("たせ", "つ", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("らせ", "る", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("ませ", "む", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("ばせ", "ぶ", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("なせ", "ぬ", frozenset({"v5"}), "causative_stem", 2),
    DeinflectionRule("われる", "う", frozenset({"v5"}), "passive"),
    DeinflectionRule("かれる", "く", frozenset({"v5"}), "passive"),
    DeinflectionRule("がれる", "ぐ", frozenset({"v5"}), "passive"),
    DeinflectionRule("される", "す", frozenset({"v5"}), "passive"),
    DeinflectionRule("たれる", "つ", frozenset({"v5"}), "passive"),
    DeinflectionRule("られる", "る", frozenset({"v5"}), "passive"),
    DeinflectionRule("まれる", "む", frozenset({"v5"}), "passive"),
    DeinflectionRule("ばれる", "ぶ", frozenset({"v5"}), "passive"),
    DeinflectionRule("なれる", "ぬ", frozenset({"v5"}), "passive"),
    DeinflectionRule("われ", "う", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("かれ", "く", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("がれ", "ぐ", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("され", "す", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("たれ", "つ", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("られ", "る", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("まれ", "む", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("ばれ", "ぶ", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("なれ", "ぬ", frozenset({"v5"}), "passive_stem", 3),
    DeinflectionRule("え", "う", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("け", "く", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("げ", "ぐ", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("せ", "す", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("て", "つ", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("れ", "る", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("め", "む", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("べ", "ぶ", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("ね", "ぬ", frozenset({"v5"}), "imperative_or_e_stem", 4),
    DeinflectionRule("った", "う", frozenset({"v5"}), "past"),
    DeinflectionRule("った", "つ", frozenset({"v5"}), "past"),
    DeinflectionRule("った", "る", frozenset({"v5"}), "past"),
    DeinflectionRule("いた", "く", frozenset({"v5"}), "past"),
    DeinflectionRule("いだ", "ぐ", frozenset({"v5"}), "past"),
    DeinflectionRule("した", "す", frozenset({"v5"}), "past"),
    DeinflectionRule("んだ", "ぬ", frozenset({"v5"}), "past"),
    DeinflectionRule("んだ", "ぶ", frozenset({"v5"}), "past"),
    DeinflectionRule("んだ", "む", frozenset({"v5"}), "past"),
    DeinflectionRule("って", "う", frozenset({"v5"}), "te_form"),
    DeinflectionRule("って", "つ", frozenset({"v5"}), "te_form"),
    DeinflectionRule("って", "る", frozenset({"v5"}), "te_form"),
    DeinflectionRule("いて", "く", frozenset({"v5"}), "te_form"),
    DeinflectionRule("いで", "ぐ", frozenset({"v5"}), "te_form"),
    DeinflectionRule("して", "す", frozenset({"v5"}), "te_form"),
    DeinflectionRule("んで", "ぬ", frozenset({"v5"}), "te_form"),
    DeinflectionRule("んで", "ぶ", frozenset({"v5"}), "te_form"),
    DeinflectionRule("んで", "む", frozenset({"v5"}), "te_form"),
    DeinflectionRule("っている", "う", frozenset({"v5"}), "progressive"),
    DeinflectionRule("っている", "つ", frozenset({"v5"}), "progressive"),
    DeinflectionRule("っている", "る", frozenset({"v5"}), "progressive"),
    DeinflectionRule("いている", "く", frozenset({"v5"}), "progressive"),
    DeinflectionRule("いでいる", "ぐ", frozenset({"v5"}), "progressive"),
    DeinflectionRule("している", "す", frozenset({"v5"}), "progressive"),
    DeinflectionRule("んでいる", "ぬ", frozenset({"v5"}), "progressive"),
    DeinflectionRule("んでいる", "ぶ", frozenset({"v5"}), "progressive"),
    DeinflectionRule("んでいる", "む", frozenset({"v5"}), "progressive"),
    DeinflectionRule("ってる", "う", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("ってる", "つ", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("ってる", "る", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("いてる", "く", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("いでる", "ぐ", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("してる", "す", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("んでる", "ぬ", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("んでる", "ぶ", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("んでる", "む", frozenset({"v5"}), "progressive_contracted"),
    DeinflectionRule("っちゃう", "う", frozenset({"v5"}), "chau_contraction"),
    DeinflectionRule("っちゃう", "つ", frozenset({"v5"}), "chau_contraction"),
    DeinflectionRule("っちゃう", "る", frozenset({"v5"}), "chau_contraction"),
    DeinflectionRule("いちゃう", "く", frozenset({"v5"}), "chau_contraction"),
    DeinflectionRule("いじゃう", "ぐ", frozenset({"v5"}), "jau_contraction"),
    DeinflectionRule("しちゃう", "す", frozenset({"v5"}), "chau_contraction"),
    DeinflectionRule("んじゃう", "ぬ", frozenset({"v5"}), "jau_contraction"),
    DeinflectionRule("んじゃう", "ぶ", frozenset({"v5"}), "jau_contraction"),
    DeinflectionRule("んじゃう", "む", frozenset({"v5"}), "jau_contraction"),
    DeinflectionRule("っちゃった", "う", frozenset({"v5"}), "chau_past_contraction"),
    DeinflectionRule("っちゃった", "つ", frozenset({"v5"}), "chau_past_contraction"),
    DeinflectionRule("っちゃった", "る", frozenset({"v5"}), "chau_past_contraction"),
    DeinflectionRule("いちゃった", "く", frozenset({"v5"}), "chau_past_contraction"),
    DeinflectionRule("いじゃった", "ぐ", frozenset({"v5"}), "jau_past_contraction"),
    DeinflectionRule("しちゃった", "す", frozenset({"v5"}), "chau_past_contraction"),
    DeinflectionRule("んじゃった", "ぬ", frozenset({"v5"}), "jau_past_contraction"),
    DeinflectionRule("んじゃった", "ぶ", frozenset({"v5"}), "jau_past_contraction"),
    DeinflectionRule("んじゃった", "む", frozenset({"v5"}), "jau_past_contraction"),
    DeinflectionRule("おう", "う", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("こう", "く", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("ごう", "ぐ", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("そう", "す", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("とう", "つ", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("ろう", "る", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("もう", "む", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("ぼう", "ぶ", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("のう", "ぬ", frozenset({"v5"}), "volitional", 2),
    DeinflectionRule("える", "う", frozenset({"v5"}), "potential"),
    DeinflectionRule("ける", "く", frozenset({"v5"}), "potential"),
    DeinflectionRule("げる", "ぐ", frozenset({"v5"}), "potential"),
    DeinflectionRule("せる", "す", frozenset({"v5"}), "potential"),
    DeinflectionRule("てる", "つ", frozenset({"v5"}), "potential"),
    DeinflectionRule("れる", "る", frozenset({"v5"}), "potential"),
    DeinflectionRule("める", "む", frozenset({"v5"}), "potential"),
    DeinflectionRule("べる", "ぶ", frozenset({"v5"}), "potential"),
    DeinflectionRule("ねる", "ぬ", frozenset({"v5"}), "potential"),

    DeinflectionRule("しなかった", "する", frozenset({"vs"}), "negative_past"),
    DeinflectionRule("しない", "する", frozenset({"vs"}), "negative"),
    DeinflectionRule("し", "する", frozenset({"vs"}), "stem"),
    DeinflectionRule("しました", "する", frozenset({"vs"}), "polite_past"),
    DeinflectionRule("しませんでした", "する", frozenset({"vs"}), "polite_negative_past"),
    DeinflectionRule("しません", "する", frozenset({"vs"}), "polite_negative"),
    DeinflectionRule("します", "する", frozenset({"vs"}), "polite"),
    DeinflectionRule("した", "する", frozenset({"vs"}), "past"),
    DeinflectionRule("して", "する", frozenset({"vs"}), "te_form"),
    DeinflectionRule("している", "する", frozenset({"vs"}), "progressive"),
    DeinflectionRule("してる", "する", frozenset({"vs"}), "progressive_contracted"),
    DeinflectionRule("しちゃう", "する", frozenset({"vs"}), "chau_contraction"),
    DeinflectionRule("しちゃった", "する", frozenset({"vs"}), "chau_past_contraction"),
    DeinflectionRule("させる", "する", frozenset({"vs"}), "causative"),
    DeinflectionRule("させ", "する", frozenset({"vs"}), "causative_stem", 2),
    DeinflectionRule("される", "する", frozenset({"vs"}), "passive"),
    DeinflectionRule("され", "する", frozenset({"vs"}), "passive_stem", 2),
    DeinflectionRule("しろ", "する", frozenset({"vs"}), "imperative"),
    DeinflectionRule("せよ", "する", frozenset({"vs"}), "imperative"),
    DeinflectionRule("しよう", "する", frozenset({"vs"}), "volitional", 1),
    DeinflectionRule("できる", "する", frozenset({"vs"}), "potential", 1),
    DeinflectionRule("でき", "する", frozenset({"vs"}), "potential_stem", 1),

    DeinflectionRule("こなかった", "くる", frozenset({"vk"}), "negative_past"),
    DeinflectionRule("こない", "くる", frozenset({"vk"}), "negative"),
    DeinflectionRule("来なかった", "来る", frozenset({"vk"}), "negative_past"),
    DeinflectionRule("来ない", "来る", frozenset({"vk"}), "negative"),
    DeinflectionRule("き", "くる", frozenset({"vk"}), "stem"),
    DeinflectionRule("来", "来る", frozenset({"vk"}), "stem", 2),
    DeinflectionRule("きました", "くる", frozenset({"vk"}), "polite_past"),
    DeinflectionRule("きませんでした", "くる", frozenset({"vk"}), "polite_negative_past"),
    DeinflectionRule("きません", "くる", frozenset({"vk"}), "polite_negative"),
    DeinflectionRule("きます", "くる", frozenset({"vk"}), "polite"),
    DeinflectionRule("来ました", "来る", frozenset({"vk"}), "polite_past"),
    DeinflectionRule("来ませんでした", "来る", frozenset({"vk"}), "polite_negative_past"),
    DeinflectionRule("来ません", "来る", frozenset({"vk"}), "polite_negative"),
    DeinflectionRule("来ます", "来る", frozenset({"vk"}), "polite"),
    DeinflectionRule("きた", "くる", frozenset({"vk"}), "past"),
    DeinflectionRule("きて", "くる", frozenset({"vk"}), "te_form"),
    DeinflectionRule("きている", "くる", frozenset({"vk"}), "progressive"),
    DeinflectionRule("きてる", "くる", frozenset({"vk"}), "progressive_contracted"),
    DeinflectionRule("きちゃう", "くる", frozenset({"vk"}), "chau_contraction"),
    DeinflectionRule("きちゃった", "くる", frozenset({"vk"}), "chau_past_contraction"),
    DeinflectionRule("来た", "来る", frozenset({"vk"}), "past"),
    DeinflectionRule("来て", "来る", frozenset({"vk"}), "te_form"),
    DeinflectionRule("来ている", "来る", frozenset({"vk"}), "progressive"),
    DeinflectionRule("来てる", "来る", frozenset({"vk"}), "progressive_contracted"),
    DeinflectionRule("来ちゃう", "来る", frozenset({"vk"}), "chau_contraction"),
    DeinflectionRule("来ちゃった", "来る", frozenset({"vk"}), "chau_past_contraction"),
    DeinflectionRule("こさせる", "くる", frozenset({"vk"}), "causative"),
    DeinflectionRule("こさせ", "くる", frozenset({"vk"}), "causative_stem", 2),
    DeinflectionRule("こられる", "くる", frozenset({"vk"}), "potential_or_passive"),
    DeinflectionRule("こられ", "くる", frozenset({"vk"}), "potential_or_passive_stem", 2),
    DeinflectionRule("これる", "くる", frozenset({"vk"}), "potential_colloquial", 1),
    DeinflectionRule("これ", "くる", frozenset({"vk"}), "potential_colloquial_stem", 2),
    DeinflectionRule("来させる", "来る", frozenset({"vk"}), "causative"),
    DeinflectionRule("来させ", "来る", frozenset({"vk"}), "causative_stem", 2),
    DeinflectionRule("来られる", "来る", frozenset({"vk"}), "potential_or_passive"),
    DeinflectionRule("来られ", "来る", frozenset({"vk"}), "potential_or_passive_stem", 2),
    DeinflectionRule("来れる", "来る", frozenset({"vk"}), "potential_colloquial", 1),
    DeinflectionRule("来れ", "来る", frozenset({"vk"}), "potential_colloquial_stem", 2),
    DeinflectionRule("こい", "くる", frozenset({"vk"}), "imperative"),
    DeinflectionRule("こよう", "くる", frozenset({"vk"}), "volitional", 1),
    DeinflectionRule("来い", "来る", frozenset({"vk"}), "imperative"),
    DeinflectionRule("来よう", "来る", frozenset({"vk"}), "volitional", 1),

    DeinflectionRule("くなかった", "い", frozenset({"adj-i"}), "negative_past"),
    DeinflectionRule("くない", "い", frozenset({"adj-i"}), "negative"),
    DeinflectionRule("かった", "い", frozenset({"adj-i"}), "past"),
    DeinflectionRule("くて", "い", frozenset({"adj-i"}), "te_form"),
    DeinflectionRule("ければ", "い", frozenset({"adj-i"}), "conditional"),
    DeinflectionRule("かろう", "い", frozenset({"adj-i"}), "presumptive", 2),
    DeinflectionRule("く", "い", frozenset({"adj-i"}), "adverbial_stem"),
    DeinflectionRule("げ", "い", frozenset({"adj-i"}), "stem_like", 2),
)


class JitendexDictionary:
    def __init__(self, dictionary_dir: Path, cache_dir: Path):
        self.dictionary_dir = Path(dictionary_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_db_path = self.cache_dir / "jitendex.sqlite3"

        self._status_lock = threading.Lock()
        self._build_thread: threading.Thread | None = None
        self._ready = False
        self._building = False
        self._error = ""
        self._progress_message = "Waiting to initialize dictionary index"
        self._progress_current = 0
        self._progress_total = 0
        self._entry_count = 0
        self._revision = ""

    def get_status(self) -> dict[str, Any]:
        with self._status_lock:
            return {
                "ready": self._ready,
                "building": self._building,
                "error": self._error,
                "progress_message": self._progress_message,
                "progress_current": self._progress_current,
                "progress_total": self._progress_total,
                "entry_count": self._entry_count,
                "revision": self._revision,
                "cache_db_path": str(self.cache_db_path),
            }

    def ensure_index_async(self) -> None:
        if not self.dictionary_dir.exists():
            self._set_error(f"Dictionary folder not found: {self.dictionary_dir}")
            return
        if self._cache_is_current():
            with self._status_lock:
                self._ready = True
                self._building = False
                self._error = ""
                if not self._progress_message:
                    self._progress_message = "Dictionary ready"
            return
        with self._status_lock:
            if self._building:
                return
            self._building = True
            self._ready = False
            self._error = ""
            self._progress_message = "Indexing Jitendex..."
            self._progress_current = 0
            self._progress_total = len(list(self.dictionary_dir.glob("term_bank_*.json")))
        self._build_thread = threading.Thread(
            target=self._build_index,
            name="jitendex-index-builder",
            daemon=True,
        )
        self._build_thread.start()

    def lookup_run_covering_offset(self, run_text: str, clicked_offset: int, max_results: int = 3, entries_per_match: int = 3) -> dict[str, Any] | None:
        status = self.get_status()
        if not status["ready"]:
            return None

        normalized_run = run_text.strip()
        if not normalized_run:
            return None

        connection = sqlite3.connect(self.cache_db_path)
        search_start = max(0, clicked_offset - 8)
        candidates: list[tuple[tuple[int, int, int, int, int], dict[str, Any]]] = []
        seen_keys: set[tuple[int, int, str, str]] = set()
        try:
            for start in range(search_start, clicked_offset + 1):
                segment = normalized_run[start:start + 24]
                if not segment:
                    continue
                surface_matches = self._lookup_best_matches_for_segment(
                    connection,
                    segment,
                    max_matches=max_results,
                    entries_per_match=entries_per_match,
                )
                for match in surface_matches:
                    match_length = len(match["surface_text"])
                    if start + match_length <= clicked_offset:
                        continue
                    distance = clicked_offset - start
                    top_score = int(match["entries"][0].get("score", 0)) if match["entries"] else 0
                    exact_priority = 1 if match["is_exact"] else 0
                    cost_penalty = -int(match["cost"])
                    rank = (match_length, exact_priority, cost_penalty, -distance, top_score)
                    key = (start, start + match_length, match["surface_text"], match["dictionary_form"])
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    candidate = {
                        "match_start": start,
                        "match_end": start + match_length,
                        "matched_text": match["surface_text"],
                        "dictionary_form": match["dictionary_form"],
                        "entries": match["entries"],
                        "is_exact": match["is_exact"],
                        "cost": match["cost"],
                        "reasons": match["reasons"],
                    }
                    candidates.append((rank, candidate))

            if not candidates:
                return None

            candidates.sort(key=lambda item: item[0], reverse=True)
            best_result = candidates[0][1]
            forward_candidates = [
                candidate
                for _, candidate in candidates
                if candidate["match_start"] == clicked_offset
            ]
            if forward_candidates:
                forward_best = forward_candidates[0]
                best_length = len(best_result["matched_text"])
                forward_length = len(forward_best["matched_text"])
                if (
                    forward_length == best_length and
                    forward_best["is_exact"] and
                    not best_result["is_exact"] and
                    int(forward_best["cost"]) <= int(best_result["cost"]) + 1
                ):
                    best_result = forward_best
            best_span = (best_result["match_start"], best_result["match_end"])
            span_candidates = [
                candidate
                for _, candidate in candidates
                if (candidate["match_start"], candidate["match_end"]) == best_span
            ]
            top_matches = span_candidates[:max_results]
            return {
                "match_start": best_result["match_start"],
                "match_end": best_result["match_end"],
                "matched_text": best_result["matched_text"],
                "entries": best_result["entries"],
                "matches": top_matches,
            }
        finally:
            connection.close()

    def _set_error(self, message: str) -> None:
        with self._status_lock:
            self._ready = False
            self._building = False
            self._error = message
            self._progress_message = message

    def _compute_source_signature(self) -> tuple[str, str]:
        index_path = self.dictionary_dir / "index.json"
        with open(index_path, "r", encoding="utf-8") as handle:
            index_data = json.load(handle)
        revision = str(index_data.get("revision", "")).strip()

        digest = hashlib.sha256()
        for path in [index_path, *sorted(self.dictionary_dir.glob("tag_bank_*.json")), *sorted(self.dictionary_dir.glob("term_bank_*.json"))]:
            stat = path.stat()
            digest.update(path.name.encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        return digest.hexdigest(), revision

    def _cache_is_current(self) -> bool:
        if not self.cache_db_path.exists():
            return False
        try:
            source_signature, revision = self._compute_source_signature()
            connection = sqlite3.connect(self.cache_db_path)
            try:
                row = connection.execute("SELECT value FROM metadata WHERE key = 'source_signature'").fetchone()
                rev_row = connection.execute("SELECT value FROM metadata WHERE key = 'revision'").fetchone()
                schema_row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
                count_row = connection.execute("SELECT COUNT(*) FROM terms").fetchone()
            finally:
                connection.close()
            if row is None or rev_row is None or schema_row is None or count_row is None:
                return False
            current = (
                row[0] == source_signature and
                rev_row[0] == revision and
                schema_row[0] == DICTIONARY_CACHE_SCHEMA_VERSION and
                int(count_row[0]) > 0
            )
            if current:
                with self._status_lock:
                    self._revision = revision
                    self._entry_count = int(count_row[0])
                    self._progress_message = f"Dictionary ready ({count_row[0]:,} entries)"
            return current
        except Exception:
            return False

    def _build_index(self) -> None:
        temp_db_path = self.cache_db_path.with_suffix(".tmp.sqlite3")
        if temp_db_path.exists():
            try:
                temp_db_path.unlink()
            except OSError:
                pass

        try:
            source_signature, revision = self._compute_source_signature()
            term_files = sorted(
                self.dictionary_dir.glob("term_bank_*.json"),
                key=lambda path: int(path.stem.split("_")[-1]),
            )

            connection = sqlite3.connect(temp_db_path)
            try:
                connection.execute("PRAGMA journal_mode=OFF")
                connection.execute("PRAGMA synchronous=OFF")
                connection.execute("PRAGMA temp_store=MEMORY")
                connection.execute(
                    """
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE terms (
                        id INTEGER PRIMARY KEY,
                        expression TEXT NOT NULL,
                        reading TEXT,
                        term_tags TEXT,
                        rules TEXT,
                        score INTEGER,
                        sequence_id INTEGER,
                        summary_text TEXT,
                        display_tags TEXT,
                        definitions_json TEXT
                    )
                    """
                )
                connection.execute("CREATE INDEX idx_terms_expression ON terms(expression)")
                connection.execute("CREATE INDEX idx_terms_reading ON terms(reading)")

                total_entries = 0
                for file_index, term_file in enumerate(term_files, start=1):
                    with self._status_lock:
                        self._progress_current = file_index
                        self._progress_total = len(term_files)
                        self._progress_message = f"Indexing Jitendex ({file_index}/{len(term_files)}): {term_file.name}"

                    with open(term_file, "r", encoding="utf-8") as handle:
                        rows = json.load(handle)

                    batch = []
                    for row in rows:
                        if not isinstance(row, list) or len(row) < 6:
                            continue
                        expression = str(row[0] or "").strip()
                        if not expression:
                            continue
                        reading = str(row[1] or "").strip()
                        term_tags = str(row[2] or "").strip() if len(row) > 2 else ""
                        rules = str(row[3] or "").strip() if len(row) > 3 else ""
                        try:
                            score = int(row[4]) if len(row) > 4 else 0
                        except Exception:
                            score = 0
                        definitions = row[5]
                        try:
                            sequence_id = int(row[6]) if len(row) > 6 else 0
                        except Exception:
                            sequence_id = 0
                        summary_text = extract_entry_summary(definitions)
                        display_tags = json.dumps(extract_entry_display_tags(definitions), ensure_ascii=False)
                        definitions_json = json.dumps(definitions, ensure_ascii=False)
                        batch.append(
                            (
                                expression,
                                reading,
                                term_tags,
                                rules,
                                score,
                                sequence_id,
                                summary_text,
                                display_tags,
                                definitions_json,
                            )
                        )

                    connection.executemany(
                        """
                        INSERT INTO terms (
                            expression,
                            reading,
                            term_tags,
                            rules,
                            score,
                            sequence_id,
                            summary_text,
                            display_tags,
                            definitions_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        batch,
                    )
                    total_entries += len(batch)
                    connection.commit()

                connection.executemany(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    [
                        ("source_signature", source_signature),
                        ("revision", revision),
                        ("schema_version", DICTIONARY_CACHE_SCHEMA_VERSION),
                        ("entry_count", str(total_entries)),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            os.replace(temp_db_path, self.cache_db_path)
            with self._status_lock:
                self._ready = True
                self._building = False
                self._error = ""
                self._revision = revision
                self._entry_count = total_entries
                self._progress_message = f"Dictionary ready ({total_entries:,} entries)"
        except Exception as exc:
            self._set_error(f"Dictionary indexing failed: {type(exc).__name__}: {exc}")
            try:
                if temp_db_path.exists():
                    temp_db_path.unlink()
            except OSError:
                pass

    def _lookup_best_matches_for_segment(self, connection: sqlite3.Connection, segment: str, max_matches: int = 3, entries_per_match: int = 3) -> list[dict[str, Any]]:
        candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        max_length = min(len(segment), 24)

        for length in range(max_length, 0, -1):
            surface_text = segment[:length]
            for variant in self._generate_deinflected_variants(surface_text):
                rows = connection.execute(
                    """
                    SELECT expression, reading, term_tags, rules, score, sequence_id, summary_text, display_tags, definitions_json
                    FROM terms
                    WHERE expression = ? OR reading = ?
                    ORDER BY
                        CASE WHEN expression = ? THEN 0 ELSE 1 END,
                        score DESC,
                        sequence_id ASC
                    LIMIT ?
                    """,
                    (variant.text, variant.text, variant.text, entries_per_match * 2),
                ).fetchall()
                if not rows:
                    continue

                entries = [
                    {
                        "expression": row[0],
                        "reading": row[1],
                        "term_tags": row[2],
                        "rules": row[3],
                        "score": row[4],
                        "sequence_id": row[5],
                        "summary_text": row[6],
                        "display_tags": row[7],
                        "definitions_json": row[8],
                    }
                    for row in rows
                    if _entry_matches_pos(row[3], variant.allowed_pos)
                ][:entries_per_match]
                if not entries:
                    continue
                entries = self._expand_redirect_entries(connection, entries, variant.allowed_pos, entries_per_match)

                dictionary_form = entries[0]["expression"]
                key = (surface_text, dictionary_form)
                if key in seen:
                    continue
                seen.add(key)

                top_score = int(entries[0].get("score", 0))
                is_exact = len(variant.reasons) == 0
                exact_priority = 1 if is_exact else 0
                rank = (length, exact_priority, -variant.cost, top_score)
                candidates.append(
                    (
                        rank,
                        {
                            "surface_text": surface_text,
                            "dictionary_form": dictionary_form,
                            "entries": entries,
                            "is_exact": is_exact,
                            "cost": variant.cost,
                            "reasons": list(variant.reasons),
                        },
                    )
                )

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in candidates[:max_matches]]

    def _expand_redirect_entries(
        self,
        connection: sqlite3.Connection,
        entries: list[dict[str, Any]],
        allowed_pos: frozenset[str] | None,
        entries_per_match: int,
    ) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, int]] = set()

        for entry in entries:
            redirect_targets: list[str] = []
            try:
                definitions = json.loads(entry.get("definitions_json", "null"))
                redirect_targets = extract_redirect_targets(definitions)
            except Exception:
                redirect_targets = []

            if redirect_targets:
                for target in redirect_targets:
                    for target_entry in self._lookup_entries_for_term(connection, target, allowed_pos, entries_per_match):
                        key = (
                            target_entry.get("expression", ""),
                            target_entry.get("reading", ""),
                            int(target_entry.get("sequence_id", 0)),
                        )
                        if key not in seen_keys:
                            seen_keys.add(key)
                            expanded.append(target_entry)

            key = (
                entry.get("expression", ""),
                entry.get("reading", ""),
                int(entry.get("sequence_id", 0)),
            )
            if key not in seen_keys:
                seen_keys.add(key)
                expanded.append(entry)

        return expanded[:entries_per_match]

    def _lookup_entries_for_term(
        self,
        connection: sqlite3.Connection,
        term: str,
        allowed_pos: frozenset[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT expression, reading, term_tags, rules, score, sequence_id, summary_text, display_tags, definitions_json
            FROM terms
            WHERE expression = ? OR reading = ?
            ORDER BY
                CASE WHEN expression = ? THEN 0 ELSE 1 END,
                score DESC,
                sequence_id ASC
            LIMIT ?
            """,
            (term, term, term, limit * 2),
        ).fetchall()
        return [
            {
                "expression": row[0],
                "reading": row[1],
                "term_tags": row[2],
                "rules": row[3],
                "score": row[4],
                "sequence_id": row[5],
                "summary_text": row[6],
                "display_tags": row[7],
                "definitions_json": row[8],
            }
            for row in rows
            if _entry_matches_pos(row[3], allowed_pos)
        ][:limit]

    def _generate_deinflected_variants(self, text: str, max_depth: int = 3) -> list[DeinflectedVariant]:
        initial = DeinflectedVariant(text=text, allowed_pos=None, cost=0, reasons=())
        queue = [initial]
        best_seen: dict[tuple[str, frozenset[str] | None], int] = {(text, None): 0}
        ordered: list[DeinflectedVariant] = [initial]

        while queue:
            current = queue.pop(0)
            if len(current.reasons) >= max_depth:
                continue
            for rule in COMMON_DEINFLECTION_RULES:
                if not current.text.endswith(rule.suffix):
                    continue
                stem = current.text[:len(current.text) - len(rule.suffix)]
                candidate_text = stem + rule.replacement
                if not candidate_text or candidate_text == current.text:
                    continue
                allowed_pos = rule.allowed_pos if current.allowed_pos is None else frozenset(current.allowed_pos & rule.allowed_pos)
                if current.allowed_pos is not None and not allowed_pos:
                    continue
                cost = current.cost + rule.cost
                reasons = current.reasons + (rule.reason,)
                key = (candidate_text, allowed_pos)
                previous_cost = best_seen.get(key)
                if previous_cost is not None and previous_cost <= cost:
                    continue
                best_seen[key] = cost
                variant = DeinflectedVariant(
                    text=candidate_text,
                    allowed_pos=allowed_pos,
                    cost=cost,
                    reasons=reasons,
                )
                ordered.append(variant)
                queue.append(variant)

            if current.text and current.text[-1] in ICHIDAN_STEM_ENDINGS:
                candidate_text = current.text + "る"
                allowed_pos = frozenset({"v1"})
                cost = current.cost + 2
                reasons = current.reasons + ("stem",)
                key = (candidate_text, allowed_pos)
                previous_cost = best_seen.get(key)
                if previous_cost is None or previous_cost > cost:
                    best_seen[key] = cost
                    variant = DeinflectedVariant(
                        text=candidate_text,
                        allowed_pos=allowed_pos,
                        cost=cost,
                        reasons=reasons,
                    )
                    ordered.append(variant)
                    queue.append(variant)

        ordered.sort(key=lambda variant: (variant.cost, -len(variant.text), len(variant.reasons)))
        return ordered
