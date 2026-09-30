"""cli.build_input_context lifts the structured request out of the latest user message."""

from __future__ import annotations

import json

from cli import build_input_context

_REQUEST = {
    "product_sku": "SKU-1",
    "own_price": 2980,
    "claim_text": "業界最安値",
    "target_platforms": ["rakuten", "amazon_jp"],
}


def test_extracts_request_fields_from_latest_user_message():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": json.dumps({**_REQUEST, "ignored": "x"})},
    ]
    assert build_input_context(history=history) == _REQUEST


def test_non_json_message_contributes_nothing():
    assert build_input_context(history=[{"role": "user", "content": "just chatting"}]) == {}


def test_json_that_is_not_an_object_contributes_nothing():
    assert build_input_context(history=[{"role": "user", "content": "[1, 2]"}]) == {}


def test_only_the_latest_user_message_is_used():
    history = [
        {"role": "user", "content": json.dumps(_REQUEST)},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "thanks"},
    ]
    assert build_input_context(history=history) == {}


def test_empty_or_missing_history():
    assert build_input_context(history=[]) == {}
    assert build_input_context(history=None) == {}
