"""Acceptance regressions for Task 15 — production-path Source D pipeline."""
from pathlib import Path

from ontozense.core.ingest.ingest_d import SourceDIngester


def test_run_skips_non_utf8_python_file_without_raising(tmp_path: Path):
    """A single non-UTF-8 file in the manifest must not abort the
    whole Source D ingestion. v1.1 tolerated this; v1.2 must too.

    Bytes 0xff 0xfe are not a valid UTF-8 sequence; parse_module's
    strict utf-8 read raises UnicodeDecodeError, which run() must catch.
    """
    broken = tmp_path / "broken.py"
    broken.write_bytes(b"\xff\xfe # not utf-8\nclass Foo: pass\n")
    good = tmp_path / "good.py"
    good.write_text("class Bar:\n    name: str\n", encoding="utf-8")

    # Both files are passed in the same manifest. The broken file must
    # be skipped silently (with a log warning), and the good file must
    # still yield its candidates.
    cands = list(SourceDIngester().ingest({"files": [str(broken), str(good)]}))

    # The good file's class is still extracted.
    labels = {c.label for c in cands}
    assert "Bar" in labels, f"good file's class missing; got: {labels}"
    # The broken file produced nothing — no Foo.
    assert "Foo" not in labels


def test_run_skips_unparseable_python_without_raising(tmp_path: Path):
    """SyntaxError tolerance was already covered by test_unparseable_python_skipped
    in test_ingest_d.py, but pin it here too at the run() level so a
    future change to either path can't silently regress."""
    broken = tmp_path / "broken.py"
    broken.write_text("def def def syntax error\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text("class Baz:\n    name: str\n", encoding="utf-8")

    cands = list(SourceDIngester().ingest({"files": [str(broken), str(good)]}))
    labels = {c.label for c in cands}
    assert "Baz" in labels
