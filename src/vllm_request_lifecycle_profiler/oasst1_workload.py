from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, BinaryIO

REPO_ROOT = Path(__file__).resolve().parents[2]
OASST1_SUBMODULE = REPO_ROOT / "third_party" / "oasst1"
OASST1_REVISION = "fdf72ae0827c1cda404aff25b6603abec9e3399b"
OASST1_FILENAME = "2023-04-12_oasst_ready.trees.jsonl.gz"
OASST1_RESOLVE_URL = (
    "https://huggingface.co/datasets/OpenAssistant/oasst1/resolve/"
    f"{OASST1_REVISION}/{OASST1_FILENAME}?download=true"
)
DEFAULT_DATA_CACHE = REPO_ROOT / ".benchmarks" / "data" / "oasst1" / OASST1_REVISION
PROJECTION_VERSION = "oasst1-longest-safe-en-v1"
DEFAULT_POOL_SIZE = 640
DEFAULT_REPETITIONS = 10
DEFAULT_REQUESTS_PER_REPETITION = 64
DEFAULT_MAX_OUTPUT_TOKENS = 192
DEFAULT_MAX_MODEL_LEN = 10880


@dataclass(frozen=True)
class LfsPointer:
    oid: str
    size: int


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def as_openai_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Oasst1Request:
    request_id: str
    repetition: int
    ordinal: int
    message_tree_id: str
    source_message_id: str
    prompt_char_count: int
    messages: tuple[ChatMessage, ...]
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    temperature: float = 0.0

    def openai_messages(self) -> list[dict[str, str]]:
        return [message.as_openai_message() for message in self.messages]


@dataclass(frozen=True)
class ContextPreflight:
    request_count: int
    min_input_tokens: int
    median_input_tokens: float
    max_input_tokens: int
    repetition_input_tokens: tuple[int, ...]
    max_output_tokens: int
    max_model_len: int


@dataclass(frozen=True)
class _Candidate:
    message_tree_id: str
    source_message_id: str
    prompt_char_count: int
    messages: tuple[ChatMessage, ...]


def _git_output(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_lfs_pointer(pointer_text: str) -> LfsPointer:
    values: dict[str, str] = {}
    for line in pointer_text.splitlines():
        key, separator, value = line.partition(" ")
        if separator:
            values[key] = value.strip()
    if values.get("version") != "https://git-lfs.github.com/spec/v1":
        raise ValueError("OASST1 source is not a Git LFS v1 pointer")
    algorithm, separator, oid = values.get("oid", "").partition(":")
    if algorithm != "sha256" or not separator or len(oid) != 64:
        raise ValueError("OASST1 Git LFS pointer has an invalid object OID")
    try:
        int(oid, 16)
    except ValueError as exc:
        raise ValueError("OASST1 Git LFS pointer has an invalid object OID") from exc
    try:
        size = int(values["size"])
    except (KeyError, ValueError) as exc:
        raise ValueError("OASST1 Git LFS pointer has an invalid size") from exc
    if size <= 0:
        raise ValueError("OASST1 Git LFS pointer size must be positive")
    return LfsPointer(oid=oid, size=size)


def read_pinned_source(
    submodule: Path = OASST1_SUBMODULE,
) -> tuple[str, LfsPointer]:
    revision = _git_output(submodule, "rev-parse", "HEAD")
    if revision != OASST1_REVISION:
        raise RuntimeError(
            "OASST1 submodule revision mismatch: "
            f"expected {OASST1_REVISION}, found {revision}"
        )
    pointer_text = _git_output(
        submodule, "show", f"{OASST1_REVISION}:{OASST1_FILENAME}"
    )
    return revision, parse_lfs_pointer(pointer_text)


def verify_data_object(path: Path, pointer: LfsPointer) -> None:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    if size != pointer.size:
        raise ValueError(
            f"OASST1 object size mismatch: expected {pointer.size}, found {size}"
        )
    if digest.hexdigest() != pointer.oid:
        raise ValueError("OASST1 object does not match its repository Git LFS OID")
    try:
        with gzip.open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                pass
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ValueError("OASST1 object is not a valid gzip stream") from exc


def _copy_stream(source: BinaryIO, destination: Path) -> None:
    with destination.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)


def materialize_oasst1(
    destination_dir: Path = DEFAULT_DATA_CACHE,
    *,
    submodule: Path = OASST1_SUBMODULE,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> Path:
    _, pointer = read_pinned_source(submodule)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / OASST1_FILENAME
    if destination.exists():
        verify_data_object(destination, pointer)
        return destination

    checked_out_source = submodule / OASST1_FILENAME
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        if (
            checked_out_source.is_file()
            and checked_out_source.stat().st_size == pointer.size
        ):
            with checked_out_source.open("rb") as source:
                _copy_stream(source, temporary)
        else:
            with urlopen(OASST1_RESOLVE_URL, timeout=120) as source:
                _copy_stream(source, temporary)
        verify_data_object(temporary, pointer)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _label_is_safe(message: Mapping[str, Any], label_name: str) -> bool:
    labels = message.get("labels")
    if not isinstance(labels, Mapping) or label_name not in labels:
        return True
    label = labels[label_name]
    if not isinstance(label, Mapping):
        return False
    value = label.get("value")
    return isinstance(value, (int, float)) and value == 0


def _message_is_eligible(message: Mapping[str, Any]) -> bool:
    return (
        message.get("role") in {"prompter", "assistant"}
        and message.get("lang") == "en"
        and message.get("synthetic") is False
        and message.get("deleted") is False
        and message.get("review_result") is not False
        and isinstance(message.get("text"), str)
        and bool(message["text"].strip())
        and _label_is_safe(message, "pii")
        and _label_is_safe(message, "not_appropriate")
    )


def _to_chat_message(message: Mapping[str, Any]) -> ChatMessage:
    role = "user" if message["role"] == "prompter" else "assistant"
    return ChatMessage(role=role, content=str(message["text"]))


def _tree_candidates(tree: Mapping[str, Any]) -> Iterable[_Candidate]:
    if tree.get("tree_state") != "ready_for_export":
        return
    tree_id = tree.get("message_tree_id")
    root = tree.get("prompt")
    if not isinstance(tree_id, str) or not isinstance(root, Mapping):
        return

    def visit(
        message: Mapping[str, Any],
        path: tuple[ChatMessage, ...],
        path_is_eligible: bool,
    ) -> Iterable[_Candidate]:
        eligible = path_is_eligible and _message_is_eligible(message)
        current_path = path
        if eligible:
            current_path = (*path, _to_chat_message(message))
            if message["role"] == "prompter":
                message_id = message.get("message_id")
                if isinstance(message_id, str):
                    yield _Candidate(
                        message_tree_id=tree_id,
                        source_message_id=message_id,
                        prompt_char_count=len(
                            "\n".join(item.content for item in current_path)
                        ),
                        messages=current_path,
                    )
        replies = message.get("replies", [])
        if not isinstance(replies, Sequence) or isinstance(replies, (str, bytes)):
            return
        for reply in replies:
            if isinstance(reply, Mapping):
                yield from visit(reply, current_path, eligible)

    yield from visit(root, (), True)


def _best_candidate(tree: Mapping[str, Any]) -> _Candidate | None:
    candidates = list(_tree_candidates(tree))
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (-item.prompt_char_count, item.source_message_id),
    )


def _load_oasst1_candidates(path: Path) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                tree = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid OASST1 JSON on line {line_number}") from exc
            if not isinstance(tree, Mapping):
                raise TypeError(f"OASST1 line {line_number} is not an object")
            candidate = _best_candidate(tree)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def build_oasst1_repetitions(
    path: Path,
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    repetitions: int = DEFAULT_REPETITIONS,
    requests_per_repetition: int = DEFAULT_REQUESTS_PER_REPETITION,
    verify_source: bool = True,
) -> tuple[tuple[Oasst1Request, ...], ...]:
    if pool_size != repetitions * requests_per_repetition:
        raise ValueError(
            "pool size must equal repetitions times requests per repetition"
        )
    if verify_source:
        _, pointer = read_pinned_source()
        verify_data_object(path, pointer)
    candidates = sorted(
        _load_oasst1_candidates(path),
        key=lambda item: (
            -item.prompt_char_count,
            item.message_tree_id,
            item.source_message_id,
        ),
    )
    if len(candidates) < pool_size:
        raise ValueError(
            f"OASST1 projection needs {pool_size} trees, found {len(candidates)}"
        )
    pool = candidates[:pool_size]
    grouped: list[tuple[Oasst1Request, ...]] = []
    for repetition in range(repetitions):
        selected = sorted(
            pool[repetition::repetitions],
            key=lambda item: (item.message_tree_id, item.source_message_id),
        )
        requests = tuple(
            Oasst1Request(
                request_id=(
                    f"issue19-oasst1-r{repetition:02d}-{ordinal:03d}-"
                    f"{candidate.source_message_id}"
                ),
                repetition=repetition,
                ordinal=ordinal,
                message_tree_id=candidate.message_tree_id,
                source_message_id=candidate.source_message_id,
                prompt_char_count=candidate.prompt_char_count,
                messages=candidate.messages,
            )
            for ordinal, candidate in enumerate(selected)
        )
        if len(requests) != requests_per_repetition:
            raise AssertionError("deterministic OASST1 partition produced a wrong size")
        grouped.append(requests)
    return tuple(grouped)


def _encoded_length(encoded: Any) -> int:
    if isinstance(encoded, Mapping):
        encoded = encoded["input_ids"]
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    if isinstance(encoded, Sequence) and encoded and isinstance(encoded[0], Sequence):
        if len(encoded) != 1:
            raise ValueError("tokenizer returned more than one encoded request")
        encoded = encoded[0]
    if not isinstance(encoded, Sequence):
        raise TypeError("tokenizer did not return a token-id sequence")
    return len(encoded)


def preflight_context_lengths(
    repetitions: Sequence[Sequence[Oasst1Request]],
    tokenizer: Any,
    *,
    max_model_len: int = DEFAULT_MAX_MODEL_LEN,
) -> ContextPreflight:
    token_counts: list[int] = []
    repetition_totals: list[int] = []
    max_output_tokens: int | None = None
    for repetition in repetitions:
        repetition_total = 0
        for request in repetition:
            encoded = tokenizer.apply_chat_template(
                request.openai_messages(),
                tokenize=True,
                add_generation_prompt=True,
            )
            input_tokens = _encoded_length(encoded)
            if input_tokens + request.max_output_tokens > max_model_len:
                raise ValueError(
                    f"request {request.request_id} exceeds the context gate: "
                    f"{input_tokens} + {request.max_output_tokens} > {max_model_len}"
                )
            if max_output_tokens is None:
                max_output_tokens = request.max_output_tokens
            elif max_output_tokens != request.max_output_tokens:
                raise ValueError("requests do not share one max_output_tokens value")
            token_counts.append(input_tokens)
            repetition_total += input_tokens
        repetition_totals.append(repetition_total)
    if not token_counts or max_output_tokens is None:
        raise ValueError("context preflight requires at least one request")
    return ContextPreflight(
        request_count=len(token_counts),
        min_input_tokens=min(token_counts),
        median_input_tokens=median(token_counts),
        max_input_tokens=max(token_counts),
        repetition_input_tokens=tuple(repetition_totals),
        max_output_tokens=max_output_tokens,
        max_model_len=max_model_len,
    )


def build_projection_manifest(
    repetitions: Sequence[Sequence[Oasst1Request]],
) -> dict[str, Any]:
    requests = []
    seen_tree_ids: set[str] = set()
    for repetition in repetitions:
        for request in repetition:
            if request.message_tree_id in seen_tree_ids:
                raise ValueError("OASST1 projection contains a duplicate tree")
            seen_tree_ids.add(request.message_tree_id)
            requests.append(
                {
                    "request_id": request.request_id,
                    "repetition": request.repetition,
                    "ordinal": request.ordinal,
                    "message_tree_id": request.message_tree_id,
                    "source_message_id": request.source_message_id,
                    "prompt_char_count": request.prompt_char_count,
                    "max_output_tokens": request.max_output_tokens,
                    "temperature": request.temperature,
                }
            )
    return {
        "data_source": "OpenAssistant/oasst1",
        "data_revision": OASST1_REVISION,
        "data_file": OASST1_FILENAME,
        "projection_version": PROJECTION_VERSION,
        "repetition_count": len(repetitions),
        "request_count": len(requests),
        "requests": requests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize the pinned OASST1 object into the ignored cache."
    )
    parser.add_argument("--destination-dir", type=Path, default=DEFAULT_DATA_CACHE)
    args = parser.parse_args()
    destination = materialize_oasst1(args.destination_dir)
    print(destination)


__all__ = [
    "DEFAULT_DATA_CACHE",
    "DEFAULT_MAX_MODEL_LEN",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_POOL_SIZE",
    "DEFAULT_REPETITIONS",
    "DEFAULT_REQUESTS_PER_REPETITION",
    "OASST1_FILENAME",
    "OASST1_RESOLVE_URL",
    "OASST1_REVISION",
    "OASST1_SUBMODULE",
    "PROJECTION_VERSION",
    "ChatMessage",
    "ContextPreflight",
    "LfsPointer",
    "Oasst1Request",
    "build_oasst1_repetitions",
    "build_projection_manifest",
    "main",
    "materialize_oasst1",
    "parse_lfs_pointer",
    "preflight_context_lengths",
    "read_pinned_source",
    "verify_data_object",
]


if __name__ == "__main__":
    main()
