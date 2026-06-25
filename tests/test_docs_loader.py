"""Tests for src/docs_loader.py — caching behavior of load_doc."""

from __future__ import annotations

import pytest

from src import docs_loader


def test_load_doc_caches_disk_reads(monkeypatch, tmp_path):
    docs_loader.load_doc.cache_clear()
    doc = tmp_path / "CALLOUT.md"
    doc.write_text("callout docs", encoding="utf-8")

    calls = {"n": 0}
    real_read = type(doc).read_text

    def counting_read(self, *args, **kwargs):
        calls["n"] += 1
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(docs_loader._cfg, "docs_dir", tmp_path)
    monkeypatch.setattr(type(doc), "read_text", counting_read)

    first = docs_loader.load_doc("CALLOUT.md")
    second = docs_loader.load_doc("CALLOUT.md")

    assert first == second == "callout docs"
    assert calls["n"] == 1  # second call served from cache, no second disk read
    docs_loader.load_doc.cache_clear()


def test_load_doc_missing_raises(monkeypatch, tmp_path):
    docs_loader.load_doc.cache_clear()
    monkeypatch.setattr(docs_loader._cfg, "docs_dir", tmp_path)
    with pytest.raises(FileNotFoundError):
        docs_loader.load_doc("does-not-exist.md")
    docs_loader.load_doc.cache_clear()
