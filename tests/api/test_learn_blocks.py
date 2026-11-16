"""Learn tab note blocks: validation and repair (shared/learn_blocks.py)."""

import json

import pytest

from shared.learn_blocks import (
    BLOCK_TYPES,
    BlocksError,
    bullet_count,
    parse_blocks,
    read_minutes,
    to_markdown,
)

EVERY_TYPE = [
    {"type": "heading", "text": "1. Mendel's law of segregation"},
    {
        "type": "paragraph",
        "text": "Alleles separate in gamete formation.",
        "highlights": ["Alleles"],
    },
    {"type": "definition", "title": "Definition", "text": "Genotype - the alleles carried"},
    {"type": "tip", "title": "Past-paper tip", "text": "2021 Paper II ..."},
    {"type": "bullet_list", "items": ["one", "two"]},
    {"type": "table", "caption": "RrYy x RrYy", "headers": ["A", "B"], "rows": [["1", "2"]]},
    {"type": "image", "url": "https://example.com/a.png", "caption": "Punnett square"},
]


def test_every_block_type_is_accepted_unchanged():
    assert parse_blocks(EVERY_TYPE) == EVERY_TYPE
    assert {b["type"] for b in parse_blocks(EVERY_TYPE)} == set(BLOCK_TYPES)


def test_json_text_with_code_fences_and_chatter():
    raw = "Here are your notes:\n```json\n" + json.dumps(EVERY_TYPE) + "\n```\nHope it helps!"
    assert len(parse_blocks(raw)) == len(EVERY_TYPE)


def test_object_with_a_blocks_key():
    assert parse_blocks({"blocks": EVERY_TYPE[:2]}) == EVERY_TYPE[:2]


def test_invalid_blocks_are_dropped_and_the_rest_kept():
    raw = [
        {"type": "heading", "text": "Kept"},
        {"type": "video", "url": "x"},  # unknown type
        {"type": "paragraph"},  # no text
        "not a dict",
        {"type": "image", "url": "javascript:alert(1)"},  # unsafe url
        {"type": "bullet_list", "items": []},  # empty list
    ]
    assert parse_blocks(raw) == [{"type": "heading", "text": "Kept"}]


def test_repairs():
    blocks = parse_blocks(
        [
            {"type": "Bullet-List", "items": ["  a  ", "", 3]},
            {"type": "table", "headers": ["A", "B"], "rows": [["1"], ["1", "2", "3"], []]},
            {"type": "paragraph", "text": "Alleles separate.", "highlights": ["alleles", "x", 5]},
            {"type": "heading", "text": "  Trim me  ", "extra": "dropped"},
            {"type": "definition", "text": "Default title"},
        ]
    )
    assert blocks == [
        {"type": "bullet_list", "items": ["a", "3"]},
        {"type": "table", "headers": ["A", "B"], "rows": [["1", ""], ["1", "2"]]},
        {"type": "paragraph", "text": "Alleles separate.", "highlights": ["alleles"]},
        {"type": "heading", "text": "Trim me"},
        {"type": "definition", "title": "Definition", "text": "Default title"},
    ]


@pytest.mark.parametrize(
    "raw", ["not json at all", "{}", '{"blocks": "x"}', "[]", '[{"type": "nope"}]', "[1, 2]"]
)
def test_nothing_valid_is_an_error(raw):
    with pytest.raises(BlocksError):
        parse_blocks(raw)


def test_helpers():
    blocks = parse_blocks(EVERY_TYPE)
    assert bullet_count(blocks) == 2
    assert read_minutes(blocks) == 1
    assert read_minutes([{"type": "paragraph", "text": "word " * 450}]) == 3
    md = to_markdown(blocks)
    assert "## 1. Mendel's law of segregation" in md
    assert "| A | B |" in md and "- one" in md and "![Punnett square]" in md
