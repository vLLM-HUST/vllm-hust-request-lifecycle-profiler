from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from vllm_request_lifecycle_profiler import oasst1_workload
from vllm_request_lifecycle_profiler.oasst1_workload import (
    OASST1_FILENAME,
    OASST1_REVISION,
    LfsPointer,
    build_oasst1_repetitions,
    build_projection_manifest,
    materialize_oasst1,
    parse_lfs_pointer,
    preflight_context_lengths,
    read_pinned_source,
    verify_data_object,
)


def _message(
    message_id: str,
    role: str,
    text: str,
    *,
    replies: list[dict[str, Any]] | None = None,
    lang: str = "en",
    pii: float = 0.0,
    not_appropriate: float = 0.0,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "user_id": f"private-{message_id}",
        "text": text,
        "role": role,
        "lang": lang,
        "review_result": True,
        "deleted": False,
        "synthetic": False,
        "labels": {
            "pii": {"value": pii},
            "not_appropriate": {"value": not_appropriate},
        },
        "replies": replies or [],
    }


def _tree(index: int, *, unsafe: bool = False) -> dict[str, Any]:
    tree_id = f"tree-{index:02d}"
    followup = _message(
        f"user-{index:02d}-b",
        "prompter",
        "u" * (40 + index),
    )
    assistant = _message(
        f"assistant-{index:02d}",
        "assistant",
        "a" * (20 + index),
        replies=[followup],
    )
    root = _message(
        f"user-{index:02d}-a",
        "prompter",
        "r" * (10 + index),
        replies=[assistant],
        pii=1.0 if unsafe else 0.0,
    )
    return {
        "message_tree_id": tree_id,
        "tree_state": "ready_for_export",
        "prompt": root,
    }


def _write_fixture(path: Path, trees: list[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as output:
        for tree in trees:
            output.write(json.dumps(tree) + "\n")


class _WhitespaceChatTokenizer:
    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> list[int]:
        assert tokenize
        assert add_generation_prompt
        return list(range(sum(len(message["content"]) for message in messages)))


def test_checked_in_submodule_and_pointer_match_the_pin() -> None:
    revision, pointer = read_pinned_source()
    assert revision == OASST1_REVISION
    assert pointer == LfsPointer(
        oid="2a9a8fd343e9b28e04a895a669d3253f82d93e9c174d440199ae19d5fafbdff7",
        size=34145252,
    )


def test_parse_lfs_pointer_rejects_non_lfs_content() -> None:
    with pytest.raises(ValueError, match="not a Git LFS"):
        parse_lfs_pointer("raw data")


def test_verify_data_object_checks_repository_lfs_metadata(tmp_path: Path) -> None:
    path = tmp_path / OASST1_FILENAME
    with gzip.open(path, "wb") as output:
        output.write(b"one complete gzip object")
    content = path.read_bytes()
    pointer = LfsPointer(oid=hashlib.sha256(content).hexdigest(), size=len(content))
    verify_data_object(path, pointer)

    with pytest.raises(ValueError, match="size mismatch"):
        verify_data_object(path, LfsPointer(oid=pointer.oid, size=pointer.size + 1))


def test_materialize_downloads_once_and_reuses_verified_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as output:
        output.write(b"fixed OASST1 fixture")
    content = compressed.getvalue()
    pointer = LfsPointer(oid=hashlib.sha256(content).hexdigest(), size=len(content))
    monkeypatch.setattr(
        oasst1_workload,
        "read_pinned_source",
        lambda _submodule: (OASST1_REVISION, pointer),
    )
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "cache"
    download_count = 0

    def open_fixture(*_args: Any, **_kwargs: Any) -> io.BytesIO:
        nonlocal download_count
        download_count += 1
        return io.BytesIO(content)

    first = materialize_oasst1(destination, submodule=source, urlopen=open_fixture)
    second = materialize_oasst1(destination, submodule=source, urlopen=open_fixture)

    assert first == second
    assert first.read_bytes() == content
    assert download_count == 1


def test_projection_is_deterministic_disjoint_and_privacy_minimized(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.jsonl.gz"
    trees = [_tree(index) for index in range(7)]
    trees.append(_tree(99, unsafe=True))
    _write_fixture(source, trees)

    first = build_oasst1_repetitions(
        source,
        pool_size=6,
        repetitions=3,
        requests_per_repetition=2,
        verify_source=False,
    )
    second = build_oasst1_repetitions(
        source,
        pool_size=6,
        repetitions=3,
        requests_per_repetition=2,
        verify_source=False,
    )

    assert first == second
    assert [len(repetition) for repetition in first] == [2, 2, 2]
    all_requests = [request for repetition in first for request in repetition]
    assert len({request.message_tree_id for request in all_requests}) == 6
    assert "tree-99" not in {request.message_tree_id for request in all_requests}
    assert all(request.messages[-1].role == "user" for request in all_requests)
    assert all(len(request.messages) == 3 for request in all_requests)

    manifest_text = json.dumps(build_projection_manifest(first), sort_keys=True)
    assert "private-" not in manifest_text
    assert '"labels"' not in manifest_text
    assert "rrrr" not in manifest_text
    assert "aaaa" not in manifest_text


def test_projection_fails_instead_of_resampling(tmp_path: Path) -> None:
    source = tmp_path / "fixture.jsonl.gz"
    _write_fixture(source, [_tree(0)])
    with pytest.raises(ValueError, match="needs 2 trees, found 1"):
        build_oasst1_repetitions(
            source,
            pool_size=2,
            repetitions=1,
            requests_per_repetition=2,
            verify_source=False,
        )


def test_context_preflight_reports_each_repetition(tmp_path: Path) -> None:
    source = tmp_path / "fixture.jsonl.gz"
    _write_fixture(source, [_tree(index) for index in range(6)])
    repetitions = build_oasst1_repetitions(
        source,
        pool_size=6,
        repetitions=3,
        requests_per_repetition=2,
        verify_source=False,
    )

    result = preflight_context_lengths(
        repetitions, _WhitespaceChatTokenizer(), max_model_len=400
    )

    assert result.request_count == 6
    assert len(result.repetition_input_tokens) == 3
    assert result.max_output_tokens == 192


def test_context_preflight_fails_without_truncation(tmp_path: Path) -> None:
    source = tmp_path / "fixture.jsonl.gz"
    _write_fixture(source, [_tree(0)])
    repetitions = build_oasst1_repetitions(
        source,
        pool_size=1,
        repetitions=1,
        requests_per_repetition=1,
        verify_source=False,
    )

    with pytest.raises(ValueError, match="exceeds the context gate"):
        preflight_context_lengths(
            repetitions, _WhitespaceChatTokenizer(), max_model_len=200
        )
