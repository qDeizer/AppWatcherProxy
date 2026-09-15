import time

import pytest

from backend.store.search import matches_search


def test_regex_escape_case_is_preserved():
    assert matches_search("hello", r"/\S+/")
    assert not matches_search("   ", r"/\S+/")
    assert matches_search("selam", "SELAM")


def test_pathological_regex_has_bounded_execution():
    started = time.monotonic()
    with pytest.raises(ValueError, match="Arama deseni"):
        matches_search("a" * 100_000 + "!", r"/(a+)+$/")
    assert time.monotonic() - started < 2
