# Minimum Runtime Contract — Owner Review Draft

- Status: `freeze_candidate`
- Evidence status: `NOT_M0_PROVEN`
- Proposed schema version: `rlp.trace/v1alpha1`
- Proposed parent API major: `1`

This is the smallest concrete contract needed to start P1. Every value below
is a proposed default for owner approval; it is not active merely because the
file exists. The larger external staging contract remains a design reference,
not a P1 prerequisite.

## Invariants

1. Tracing is disabled by default and must not change scheduling or request
   output.
2. The hot path performs bounded in-memory work only. It never opens, flushes,
   or synchronously writes a file.
3. Exporter initialization, enqueue, serialization, writer, and close failures
   are fail-open for serving and fail-closed for formal evidence.
4. Each process owns one shard and one monotonically increasing data-record
   sequence; processes never append to the same shard.
5. Missing, duplicate, inverted, dropped, or cross-domain events are reported,
   never repaired by guessing timestamps.
6. Payload text, token contents, messages, authorization data, client IPs, and
   raw model output are forbidden by default.

## Record encoding and per-type schemas

JSONL records use deterministic UTF-8 JSON with sorted object keys, compact
separators, no NaN/Infinity, and exactly one trailing LF byte. Every encoded
record, including that LF, is at most `4096` bytes. Every record has exactly
these common fields: `schema_version` (the exact string
`rlp.trace/v1alpha1`), `record_type`, and `process_uuid` (32 lowercase hex
characters generated once per process). All fields not required or explicitly
nullable by the applicable table are forbidden.

`record_type` is one of `process_start`, `event`, `edge`, `loss_interval`, or
`process_summary`. The first record in a shard is exactly one `process_start`;
the last is exactly one `process_summary`. Their required fields are:

| Type | Additional required fields |
| --- | --- |
| `process_start` | `pid` (uint32), `started_timestamp_ns` (uint64), `clock_source` (`CLOCK_MONOTONIC`), `clock_domain_id`, `profiler_parent_commit`, `runtime_core_commit`, `device_plugin_commit`, `parent_api_major` (1), and `limits` containing every value in the exporter table below |
| `process_summary` | `ended_timestamp_ns` (uint64), `attempted_data_count`, `written_event_count`, `written_edge_count`, `written_loss_interval_count`, `dropped_data_count`, `dropped_control_count`, `first_data_record_seq`, `last_data_record_seq`, `writer_failure_count`, `close_outcome`, and `content_sha256` |

The three explicitly named commit fields are exact 40-character lowercase Git
object IDs for formal evidence; workload and configuration commits remain in
the run environment manifest and are not overloaded into these names.
`close_outcome` is `drained`, `timeout`, or `writer_failure`.
When `attempted_data_count=0`, `first_data_record_seq` and
`last_data_record_seq` are both null. Otherwise both are uint64,
`first_data_record_seq=0`, and
`last_data_record_seq=attempted_data_count-1`. Counts are uint64;
`content_sha256` is 64 lowercase hex characters.

`limits` has exactly these keys and no others:
`data_capacity_records` (uint32, 4096), `reserved_capacity_records` (uint32,
64), `max_record_bytes` (uint32, 4096), `max_queued_bytes` (uint64, 17039360),
`max_batch_records` (uint32, 128), `max_batch_bytes` (uint32, 262144),
`write_interval_ms` (uint32, 100), `close_timeout_ms` (uint32, 2000), and
`shard_ownership` (the exact string
`one_process_one_append_only_shard`). These are wire values, not derived or
implementation-defined additions.

Every attempted `event` or `edge` is a data record. It has a `record_seq`
(uint64) allocated atomically in producer-observation order, starting at zero,
**before** validation, serialization, or enqueue. The sequence is an audit
order only and never establishes happens-before. A failed or not-fully-written
attempt consumes its sequence number and, for any shard that reaches a valid
summary, must be covered by a `loss_interval`.

An `event` has exactly these additional fields:

| Field | Required value and bound |
| --- | --- |
| `record_seq` | The allocated data-record sequence |
| `event_id` | ASCII `process_uuid:e:record_seq`, at most 55 bytes |
| `trace_id` | 32 lowercase hex characters generated at the earliest root request boundary |
| `lifecycle_id` | Root `trace_id:r`, engine `trace_id:e:sample_index`, or response `trace_id:s`; at most 96 bytes |
| `parent_lifecycle_id` | Null for the root; otherwise an existing lifecycle in the same trace |
| `scope` | `root_request`, `engine_sample`, or `response` |
| `component` | `frontend`, `tokenizer`, `engine_client`, `engine_core`, `output_processor`, `response`, `transport`, or `external_evidence` |
| `event_name` | One event from the frozen vocabulary below |
| `timestamp_ns` | uint64 `CLOCK_MONOTONIC` nanoseconds |
| `clock_domain_id` | 32 lowercase hex characters identifying one host boot and clock source |
| `preemption_epoch` | uint32 for engine events; null otherwise |
| `start_span_id` | Null or ASCII `creator_process_uuid:s:local_span_seq`, at most 55 bytes; creator UUID must equal this start event's `process_uuid` |
| `end_span_id` | Null or a previously started span ID; the span normally ended or preempted at this boundary |
| `closing_span_ids` | Lexicographically sorted unique array of at most 16 span IDs; `[]` unless an abnormal terminal closes open spans |
| `sample_index` | uint32 in engine scope; null otherwise |
| `handoff_index` | uint32 for engine `output_batch_ready` and root `output_ready`; null otherwise |
| `chunk_index` | uint32 for response serialization/delivery events; null otherwise |
| `handoff_id` | ASCII `trace_id:h:handoff_index` for `output_batch_ready`, root `output_ready`, and the dependent `serialization_started`; null otherwise |
| `metadata` | Object satisfying the bounded rules below; `{}` when unused |

Every integer embedded in an ID is canonical unsigned base-10 ASCII with no
leading zero except the value `0`. `local_span_seq` is a per-creator-process
uint64 counter starting at zero; it is allocated atomically and never reused.
A duplicate span start or duplicate event/edge ID is invalid.

An `edge` is emitted by the runtime only after both endpoint event IDs are
known. It has `record_seq`, `edge_id` (`process_uuid:g:record_seq`, at most 55
bytes), `trace_id`, `from_event_id`, `to_event_id`, `edge_kind`, and
`evidence_source`. Endpoint IDs are at most 55 bytes and must resolve to events
in the same trace. `edge_kind` is `program_order`, `data_dependency`,
`submission`, `parent_child`, `transport_handoff`, or
`correlated_same_clock_domain`. `evidence_source` is
`instrumented_execution_context`, `engine_submission`,
`lifecycle_creation`, `engine_output_handoff`, `engine_abort_handoff`,
`transport_send_await`, or a
profiler-issue-2 code matching `issue2:[a-z0-9_.-]+:[a-z0-9_.-]+` and at most
64 ASCII bytes. Issue-2 codes are forbidden until that version is frozen.

A `loss_interval` has `loss_interval_seq` (uint64 control-record counter),
`loss_interval_id` (`process_uuid:l:loss_interval_seq`), `reason`
(`serialization_failure`, `queue_overflow`, `writer_failure`, or
`close_timeout`),
`first_dropped_record_seq`, `last_dropped_record_seq`, `dropped_count`,
`event_count`, `edge_count`, `first_observed_timestamp_ns`, and
`last_observed_timestamp_ns`. All numeric fields are uint64 and
`dropped_count == event_count + edge_count ==
last_dropped_record_seq - first_dropped_record_seq + 1`.
`loss_interval_seq` starts at zero, is contiguous, and is assigned when an
interval is sealed.

Loss accounting is deterministic: consecutive dropped data sequences with the
same reason extend one open interval. A reason change, a nonconsecutive
sequence, the next successfully enqueued data record, or `close()` seals it and
enqueues it through reserved control capacity. Noncontiguous intervals are
never merged. Serialization failure includes schema, metadata-budget, and
4096-byte-limit failures. Enqueued data whose complete LF-terminated bytes were
not written is dropped data under `writer_failure`; data still pending when the
bounded close cutoff expires is dropped data under `close_timeout`. The writer
seals maximal contiguous intervals from its retained record sequences and
attempts their control records and summary only if the shard remains writable.
If it cannot, the missing or invalid summary fails the shard closed rather than
fabricating a balanced ledger. Failure to serialize or enqueue a loss record
counts as dropped control and invalidates the shard.

Metadata keys match `[a-z][a-z0-9_]{0,47}`. Values are null, booleans, integers
in the closed uint64 range `[0, 18446744073709551615]`, or printable ASCII
strings of at most 128 bytes; negative integers, floats, nested values, and
control characters are forbidden. Token, chunk, sampling, and count metadata,
including `sampling_n`, `prompt_tokens_total`, `prompt_tokens_cached`,
`prompt_tokens_to_compute`, `prompt_tokens_computed`, and
`prefill_chunk_count`, `cache_block_size_tokens`, and
`generated_tokens_total` and `prompt_count` use that uint64 domain. The complete canonically
encoded metadata object is at most `1024` bytes. A metadata or total-record
overflow consumes the allocated `record_seq`, opens a
`serialization_failure` interval, and makes the shard ineligible for formal
evidence.

To construct `clock_domain_id`, read `/proc/sys/kernel/random/boot_id` as
ASCII, remove exactly one trailing LF, require the lowercase canonical UUID
form `8-4-4-4-12`, then compute SHA-256 over those 36 ASCII bytes, one `0x00`
byte, and the 15 ASCII bytes `CLOCK_MONOTONIC`. The first 16 SHA-256 digest
bytes encoded as lowercase hex are the ID. P1 supports a single host. A missing
or noncanonical boot ID, or records from different clock-domain IDs, is
unsupported for critical-path ordering.

External and internal request IDs may appear only as bounded, noncanonical
metadata after privacy review. `trace_id` and `lifecycle_id` are the canonical
join keys.

## Lifecycle topology

One trace contains exactly one root lifecycle, zero or more engine-sample
children, and zero or one response lifecycle. Parallel samples use separate
engine lifecycle IDs. An engine child does not exist until submission succeeds;
a response child does not exist until response handling begins.

Every span is identified by `(trace_id, lifecycle_id, span_id)`. Dependency
edges are represented by `edge` records; the normalizer does not manufacture
them from global `record_seq` or timestamp order. Program-order edges are
allowed only between observations in one explicitly instrumented logical
execution context, never merely because two coroutines share a process. The
normalizer rejects the entire trace if an endpoint is missing, crosses traces,
uses an unsupported evidence source, or would make the graph cyclic.

The minimum cross-lifecycle edges are root `submitted` to initial engine
`queued` (`submission`), engine `output_batch_ready` to matching root
`output_ready`, root `output_ready` to dependent response
`serialization_started` (both `data_dependency` with
`engine_output_handoff`), response final `stream_done` to root
`request_done` (`parent_child`), engine `generation_done` to root
`request_done` (`parent_child`) in every normal mode, and every
`serialization_done` to its matching `delivery_started` (`transport_handoff`).
`output_batch_ready` is emitted in EngineCore once the output token batch and
finish state are known but before any final `_free_request`; it does not claim
that the eventual `EngineCoreOutput` object has been constructed. That object
carries a discriminated trace sidecar. Both variants have exactly
`sidecar_kind`, `trace_id`, `engine_lifecycle_id`, `sample_index`, `is_final`,
nullable `handoff_index`, `handoff_id`, `output_batch_ready_event_id`,
`engine_terminal_event_id`, and `engine_cleanup_done_event_id`:

- `sidecar_kind=output_batch` requires the three handoff/output fields. Its
  terminal and cleanup IDs are required exactly when `is_final=true` and null
  otherwise.
- `sidecar_kind=terminal_only` requires `is_final=true`, null handoff/output
  fields, and nonnull terminal and cleanup IDs. It represents an empty-token
  error/cancel/abort output and never creates root `output_ready`.

The terminal ID references `generation_done`, `aborted`, `cancelled`, or
`error`; the cleanup ID references the real engine cleanup end. Frontend output
processing emits root-scope `output_ready` only after consuming an output-batch
variant, with the same handoff identity, and retains
the IDs until it emits response/direct-handoff edges and root-terminal
dependencies. Timestamp or index equality alone is insufficient.

After consuming an output-batch variant, OutputProcessor attaches a bounded
RequestOutput-side trace sidecar with exactly `trace_id`, `root_lifecycle_id`,
`handoff_index`, `handoff_id`, `latest_root_output_ready_event_id`, and
`is_final`. DELTA output carries the latest consumed handoff; FINAL_ONLY and
RequestOutputCollector merges retain the greatest contiguous handoff index and
its IDs. The explicit root-output program-order chain makes that latest event
depend on every earlier merged handoff. AsyncLLM yield, LLMEngine return, and
HTTP serialization consume this sidecar rather than consulting a process-wide
request map. A gap, nonmonotonic merge, missing sidecar, or ID mismatch makes
the trace incomplete. Direct final return propagates the same sidecar to
`request_done`.

When tracing is enabled, the submitting AsyncLLM/LLMEngine side emits root
`submitted`, creates the engine child, emits initial `queued`, and writes their
`submission` edge after acceptance into its queue. It then sends EngineCore a
sidecar containing exactly `trace_id`, `engine_lifecycle_id`, `sample_index`,
`queued_event_id`, and `queue_span_id`, with the bounds above. EngineCore uses
that propagated span ID when scheduler selection emits `admission_started`, so
the queue span includes client/IPC wait without moving the initial boundary.
The sidecar contains no request payload; construction, transport, or
consumption failure is fail-open for serving and makes that trace incomplete.
Frontend/client cancellation that initiates an engine abort sends a separate
bounded control sidecar with exactly `trace_id`, `engine_lifecycle_id`,
`source_root_terminal_event_id`, and `abort_reason_code`. The reason is
`client_cancel`, `frontend_error`, `deadline`, or `response_disconnect`.
EngineCore emits the resulting `aborted/cancelled` terminal and the explicit
abort edge; the control sidecar never carries error text or request payload.

## Required edge roster

The runtime emits, rather than the normalizer infers, every applicable edge in
this closed P1 roster:

| Source | Target | Kind / evidence |
| --- | --- | --- |
| Each span start except initial `queued` | Its normal end, `preempted`, or listed abnormal terminal | `program_order` / `instrumented_execution_context` |
| `received` | `render_started` | `program_order` / `instrumented_execution_context` |
| `render_done` | text `tokenization_started`, or pretokenized `submitted` | `program_order` / `instrumented_execution_context` |
| `tokenization_done` | `submitted` | `program_order` / `instrumented_execution_context` |
| `submitted` | initial `queued` | `submission` / `engine_submission` |
| Initial `queued` | Cross-process `admission_started` or engine terminal closing that queue span | `data_dependency` / `engine_submission` |
| `scheduled` or `resumed` | That epoch's `prefill_started`, or `decode_started` when resuming later-token work | `program_order` / `instrumented_execution_context` |
| `preempted` | Next `requeued`, or suspended engine terminal | `program_order` / `instrumented_execution_context` |
| First completed `prefill_done` | `first_token` | `data_dependency` / `instrumented_execution_context` |
| Recompute `prefill_done` after `first_token` already exists | Resumed `decode_started` | `data_dependency` / `instrumented_execution_context` |
| `first_token` | First `output_batch_ready`, and `decode_started` when more-token work exists | `data_dependency` / `instrumented_execution_context` |
| Active `decode_started` | Every later `output_batch_ready` produced in that epoch | `data_dependency` / `instrumented_execution_context` |
| Final `output_batch_ready`, and final `decode_done` when present | `generation_done` | `program_order` / `instrumented_execution_context` |
| Engine `output_batch_ready` | Matching root `output_ready` | `data_dependency` / `engine_output_handoff` |
| Final engine `cleanup_done` | Matching final root `output_ready` | `data_dependency` / `engine_output_handoff` |
| Previous root `output_ready` | Next root `output_ready` in the same frontend context | `program_order` / `instrumented_execution_context` |
| Root `output_ready` selected for a response chunk | Its `serialization_started` | `data_dependency` / `engine_output_handoff` |
| `serialization_done` | Matching `delivery_started` | `transport_handoff` / `transport_send_await` |
| Nonfinal `delivery_done` at chunk i | `serialization_started` at chunk i+1 in the same response loop | `program_order` / `instrumented_execution_context` |
| Engine effective terminal | Root `request_done`, when the supported normal root waits for it | `parent_child` / `lifecycle_creation` |
| Terminal-only engine event | Root abnormal terminal when that sidecar caused it | `parent_child` / `lifecycle_creation` |
| Root `cancelled/error` that initiates abort | Resulting engine `aborted/cancelled` | `parent_child` / `engine_abort_handoff` |
| Response `stream_done` | Root `request_done` | `parent_child` / `lifecycle_creation` |
| Final root `output_ready` | Root `request_done` in direct mode | `program_order` / `instrumented_execution_context` |
| Any lifecycle terminal | Its own `cleanup_started` | `program_order` / `instrumented_execution_context` |

Shared span boundaries use one event with both `end_span_id` and
`start_span_id`; they do not create a self-edge. Issue-2 communication child
edges additionally connect active execution to communication start and
communication end back to execution using its frozen evidence code. If any
applicable required edge cannot be emitted, that trace is incomplete; no
timestamp or adjacent sequence substitutes for it. One edge satisfies one
applicable source-target obligation; duplicate identical edges are invalid.

## Event vocabulary and ownership

Root request:

- frontend: `received`, `render_started`, `render_done`,
  `tokenization_started`, `tokenization_done`, `submitted`;
- output handoff: `output_ready` after frontend output processing consumes an
  EngineCoreOutput;
- terminal: `request_done`, `cancelled`, or `error`;
- diagnostic-only: `unsupported_mode`, exactly once with metadata key
  `reason_code` from the frozen unsupported enum;
- cleanup: `cleanup_started`, `cleanup_done` with
  `cleanup_component=frontend_request`.

Engine sample:

- queue/admission: `queued`, `requeued`, `admission_started`, `scheduled`,
  `resumed`;
- execution: `prefill_started`, `prefill_done`, `first_token`,
  `decode_started`, `decode_done`, `output_batch_ready`, `preempted`;
- communication child spans: absent only in frozen `communication_mode=none`;
  otherwise required by the selected issue-2 profile;
- terminal: `generation_done`, `aborted`, `cancelled`, or `error`;
- cleanup: `cleanup_started`, `cleanup_done` with
  `cleanup_component=engine_request`.

Response:

- per chunk: `serialization_started`, `serialization_done`,
  `delivery_started`, and either non-final `delivery_done` or final
  `stream_done`;
- terminal: final `stream_done`, `cancelled`, or `error`;
- cleanup: `cleanup_started`, `cleanup_done` with
  `cleanup_component=response_stream`.

`component` is the authoritative logical observation point, while
`process_uuid` identifies the actual emitter process. The allowed mapping is
closed for P1:

| Events | Required `component` | Span rule |
| --- | --- | --- |
| `received`, render pair, root terminals, `unsupported_mode` | `frontend` | Render is owned by `frontend`; other listed events are instantaneous |
| tokenization pair | `tokenizer` | Owned by `tokenizer` |
| `submitted`, initial `queued` | `engine_client` | Initial queue span is owned by `engine_client` |
| `requeued` | `engine_core` | Post-preemption queue span is owned by `engine_core` |
| `admission_started`, `scheduled`, `resumed` | `engine_core` | `admission_started` closes the propagated queue span and starts an `engine_core` admission span; `scheduled/resumed` closes it |
| prefill pair, decode pair, `preempted` | `engine_core` | Prefill/decode spans are owned by `engine_core`; later model-runner detail requires a versioned child span, not a silent boundary move |
| `first_token`, `output_batch_ready` | `output_processor` | EngineCore-side instantaneous output boundaries before final resource release |
| `generation_done` | `engine_core` | Normal engine terminal emitted immediately before real `_free_request` cleanup |
| root `output_ready` | `output_processor` | Frontend-side handoff observation in the root lifecycle after consuming EngineCoreOutput |
| communication pair | `external_evidence` | Owned by the versioned issue-2 adapter; its concrete emitter is preserved by `process_uuid` and evidence code |
| engine `aborted/cancelled/error` and engine cleanup pair | `engine_core` | Terminal is instantaneous; cleanup is owned by `engine_core` |
| serialization pair | `response` | Owned by `response` |
| delivery pair and `stream_done` | `transport` | Owned by `transport` |
| response `cancelled/error` and response cleanup pair | `response` | Terminal is instantaneous; cleanup is owned by `response` |

Root cleanup uses `frontend`. A start registers the span's owner from this
table; a permitted cross-component boundary such as `admission_started` may
close a propagated span on that owner's behalf but never changes its owner.
Any other component/event pairing or start/end phase mismatch is invalid.

For streaming and one-shot responses, `stream_done` means the final HTTP/ASGI
send awaitable returned. It proves server-side transport acceptance, not client
receipt. The old prototype's internal-output-queue `stream_done` must be mapped
to a differently named diagnostic event or omitted; it cannot retain the new
meaning silently.

Communication operation/subtype semantics are an explicit dependency on
profiler issue #2. `communication_mode=none` is legal only for TP=1, PP=1,
local homogeneous KV cache, no connector/offload, and a configuration in which
the frozen issue-2 profile expects no operation. A mode matching
`issue2:[a-z0-9_.-]+` is legal only after that version is frozen; every
operation required by that profile emits its paired span and required child
edges. Any potentially communicating configuration without one of those modes
emits `communication_subtype_unfrozen` and is incomplete. Communication is
therefore never silently omitted or invented locally.

## Terminal, preemption, and cleanup rules

- Each lifecycle has exactly one effective terminal. If competing terminal
  signals are visible before emission, precedence is `error`, `cancelled`,
  `aborted`, then normal completion. Once emitted, a terminal is immutable;
  any later terminal makes the lifecycle invalid for formal evidence.
- `preempted` closes the active execution epoch without terminating the engine
  lifecycle. `requeued` begins epoch `e+1`; `resumed` ends its admission span.
  Event and span IDs are never reused across epochs.
- `request_done` is emitted when the API request coroutine reaches its normal
  terminal after final response handoff. Cleanup completeness is evaluated
  separately and must not be inferred from `request_done`.
- After an effective terminal, only that lifecycle's own cleanup events are
  allowed. A started span ends exactly once by its normal paired end,
  `preempted` where allowed, or a terminal valid for that scope.
- A start event sets `start_span_id`; a normal end or `preempted` sets
  `end_span_id`. Either is null when unused. One shared boundary may end one
  span and start another: `admission_started`, for example, carries the queue
  span in `end_span_id` and a fresh admission span in `start_span_id`.
  Non-abnormal events leave `closing_span_ids=[]`. An abnormal `error`,
  `cancelled`, or `aborted` has both singular fields null and lists **every**
  then-open span in its own lifecycle in `closing_span_ids`; an omitted, extra,
  cross-lifecycle, or more-than-16 open span makes the lifecycle incomplete.
  Cleanup spans begin only after the terminal and are never in that list.
  Final `stream_done` carries its delivery span in `end_span_id` and an empty
  closing list.
- The cleanup roster is scoped, not copied to the root: a root owns exactly one
  `frontend_request` pair, an activated engine child owns exactly one
  `engine_request` pair, and an activated response child owns exactly one
  `response_stream` pair.
- On normal engine completion, EngineCore emits `generation_done`, then wraps
  the existing `_free_request` resource release with the engine cleanup pair,
  and only afterward constructs/returns the final EngineCoreOutput. The later
  root-scope `output_ready` is not an engine event. Instrumentation must never
  delay cleanup for a frontend acknowledgement or timestamp cleanup after the
  resources were actually released.

## Supported-mode path grammar

These rules are normative for a P1 completeness claim. Every root `received`
event declares bounded `entry_mode`, `input_mode`, `response_mode`,
`sampling_n`, `prompt_count`, `model_mode`, `kv_cache_mode`,
`frontend_stop_mode`, and `communication_mode` metadata.
The supported values are:

- `entry_mode=openai_http|async_llm|llm_engine`;
- `input_mode=text|pretokenized`;
- `response_mode=streaming|non_streaming` for OpenAI HTTP and `none` for a
  direct AsyncLLM/LLMEngine entry;
- `sampling_n=1`;
- `prompt_count=1`; OpenAI completion batch prompts are diagnostic-only because
  they create multiple engine children and need a later fan-out profile;
- `model_mode=decoder_only`; multimodal input, prompt embeddings, and
  encoder-decoder execution are diagnostic-only because their encoder/MM work
  is not in this phase graph;
- `kv_cache_mode=disabled|local_homogeneous`, with no KVConnector and exactly
  one positive `cache_block_size_tokens` when caching is enabled;
- `frontend_stop_mode=none`. Frontend stop-string termination is
  diagnostic-only because it can produce a normal public response followed by
  an asynchronous core abort and needs a later profile;
- `communication_mode=none|issue2:<version>` under the exact rules above.

A normal root path is exactly `received`, one render span, the conditional
tokenization span, `submitted`, a mode-specific handoff, `request_done`, and
the root cleanup pair. Text input has exactly one tokenization span;
pretokenized input has none and declares `input_mode=pretokenized` at
`render_done`. `submitted` means accepted engine submission. Before it there
is no engine child; after it there is exactly one engine child.

OpenAI HTTP normal completion requires one response child and its final
`stream_done` before `request_done`. Direct AsyncLLM/LLMEngine with
`response_mode=none` forbids a response child; `request_done` occurs when the
instrumented public API hands the final engine output to its caller. The final
root `output_ready` to direct `request_done` dependency is an explicit
`program_order` edge.

Engine epoch numbers start at zero, are contiguous, and are never reused.
Epoch zero begins `queued`, `admission_started`, `scheduled`; each later epoch
begins `requeued`, `admission_started`, `resumed`. `queued` occurs once per
engine lifecycle. Every scheduling end event records
`prompt_tokens_total`, `prompt_tokens_cached`, and
`prompt_tokens_to_compute` as uint64 metadata. Each prefill end or preemption
records the actual `prompt_tokens_computed` and `prefill_chunk_count` for that
epoch.

Each epoch has at most one aggregate prefill span and at most one aggregate
decode span. Every supported normal trace has at least one completed prefill
span. On the frozen current runtime, a maximal prefix-cache hit still
recomputes a nonempty suffix for logits and block-aligned slot allocation. Its
initial counters satisfy `0 <= prompt_tokens_cached < prompt_tokens_total`,
`prompt_tokens_to_compute = prompt_tokens_total - prompt_tokens_cached >= 1`,
and `prompt_tokens_cached % cache_block_size_tokens = 0`; a normally completed
unpreempted prefill has
`prompt_tokens_computed=prompt_tokens_to_compute`. It emits one prefill pair
from cache resolution/work start to KV readiness; equal timestamps are allowed.
A true zero-compute full hit is diagnostic-only until a runtime version
explicitly supports it. Chunked prefill uses one aggregate span per epoch and
records
`prefill_chunk_count>1`; a preempted aggregate records work completed so far.
A resumed/recomputed epoch uses a new span ID and reconciles counters across
epochs without reusing a span.

`first_token` occurs exactly once per normally completing engine lifecycle and
never repeats after resume. Each actual output-token batch that will construct
an EngineCoreOutput emits
`output_batch_ready` with a contiguous `handoff_index` before any final engine
terminal. Frontend consumption emits the matching root `output_ready`; those
root events are explicitly chained in frontend program order. An OpenAI
handoff carries the same `handoff_id` into its dependent response serialization
event. Response `chunk_index` is a separate contiguous sequence. A
non-streaming response has one final response chunk at index zero even when it
consumed multiple engine handoffs.

The normal `generation_done` terminal carries required uint64
`generated_tokens_total`; chunk count never substitutes for this value. When
that count is one, including `max_tokens=1`, no decode span is legal and the
engine suffix is `prefill_done`, `first_token`, `output_batch_ready`,
`generation_done`, and the engine cleanup pair. The matching root
`output_ready` occurs later after frontend consumption.
When it is greater than one, the final execution epoch has exactly one normally
completed aggregate decode span; earlier decode spans may end only by
preemption or an abnormal terminal. `output_batch_ready` events may occur while
a decode span is open. The single `generation_done` after the final
`output_batch_ready` is the normal engine terminal and is distinct from the
decode-span end.

`preempted` is valid only while exactly one prefill or decode span is open. It
ends that epoch and is followed by either `requeued` in epoch `e+1` or an engine
terminal while suspended. It is not a lifecycle terminal. Communication may
not remain open across preemption.

A supported OpenAI request activates exactly one response lifecycle when
response handling starts. Chunk indexes are contiguous from zero. Each chunk
has exactly `serialization_started`, `serialization_done`, and
`delivery_started`, followed by `delivery_done` for a nonfinal chunk or the
single final `stream_done`; the final chunk must not contain `delivery_done`.
A non-streaming response has exactly one final chunk at index zero.

An `error`, `cancelled`, or scope-valid `aborted` terminal may short-circuit a
legal path at any point. It removes future phase obligations, but not that
lifecycle's terminal and cleanup obligations. A root abnormal terminal before
`submitted` requires no engine child. Once a child is activated, it must
independently terminate and clean up even if its parent terminates first.

## Completeness levels

A lifecycle is complete only if it matches the grammar above or a legal
short-circuit; has exactly one terminal and its own cleanup pair; closes every
started span; and has no duplicate identity, illegal epoch, post-terminal
event, unresolved edge, or `unsupported_mode` marker. It never requires a
sibling or child's cleanup record.

A trace is complete only if it has exactly one complete root; its child roster
matches activation; every activated child is complete; all parent and handoff
edges resolve; and its dependency graph is acyclic. Normal root completion
requires engine `generation_done` and, when a response child exists,
`stream_done`. Abnormal child outcomes may differ because of races, but all
activated children must terminate and clean up.

A shard is complete only if it has one valid first `process_start` and one
valid final `process_summary` for the same process; schema, API, configuration,
and clock values agree; close reports `drained`; counts and digest reconcile;
there are no writer/serialization failures, loss intervals, data/control
drops, or unexplained data-record sequence gaps; and every record is valid and
within bounds. Any violation makes the whole shard ineligible, and any trace
touching it incomplete. Formal run evidence additionally requires every
expected process shard to be complete.

## Bounded exporter proposal

| Parameter | Proposed P1 value |
| --- | ---: |
| Pre-serialized data capacity per process | 4096 records |
| Reserved terminal/control capacity | 64 records |
| Maximum encoded record | 4096 bytes including newline |
| Maximum queued encoded bytes | 17,039,360 bytes |
| Writer batch | at most 128 records or 262,144 bytes |
| Maximum periodic write interval | 100 ms |
| Close/drain timeout | 2000 ms |
| File ownership | one persistent append-only shard per process UUID |

The existing configured export path is a base path, not a shared output file.
After generating `process_uuid`, a process opens exactly
`<base>.rlp.<process_uuid>.jsonl` with create-exclusive, write-only, append
semantics and mode `0600`; it never writes `<base>` itself. A collision retries
UUID generation at most three times, then records `init_failure` through normal
logging and disables tracing fail-open. The run environment manifest records
the lexicographically sorted explicit shard paths. Expected-shard discovery
uses only that manifest; the convenience glob `<base>.rlp.*.jsonl` may audit
unexpected files but cannot define the expected set.

Emission uses a non-waiting enqueue. On data-capacity overflow it drops the
newest nonterminal event or edge and opens or extends the exact loss interval.
Terminal events, loss records, process start, and process summary use reserved
capacity; ordinary edges do not. If reserved capacity is exhausted, serving
still proceeds; a dropped event/edge increments data loss, a dropped control
increments `dropped_control_count`, and the shard is ineligible.

The writer owns the persistent file descriptor. It may combine records into a
bounded batch, but never calls `fsync` per event. `close()` requests a drain and
waits at most 2000 ms. Timeout, write failure, missing summary, count mismatch,
or digest mismatch marks the shard incomplete; no serving exception escapes.

`attempted_data_count` must equal written event plus written edge plus dropped
data counts. `written_loss_interval_count` equals the number of actual written
loss records, and `dropped_data_count` equals the sum of their `dropped_count`
values in any shard with a valid summary. `content_sha256` hashes, in file
order, the exact raw bytes of the
single `process_start` and every successfully written `event`, `edge`, and
`loss_interval` record, including each trailing LF. It excludes only
`process_summary`, so it is non-self-referential. A missing summary never means
zero loss.

## Supported P1 modes

Supported for completeness claims:

- OpenAI chat/completion backed by AsyncLLM or LLMEngine, streaming or
  non-streaming, with `n=1` and `prompt_count=1`;
- direct AsyncLLM and LLMEngine text-generation entry with `n=1` and no HTTP
  response lifecycle; and
- decoder-only text or pretokenized input, prefix-cache hit/miss, chunked
  prefill, and preemption/resume under the exact grammar above.

Diagnostic-only until a later version explicitly adds them:

- parallel sampling `n>1`, batched prompts, beam search, pooling/embedding,
  streaming input, cross-host serving, a true zero-compute prefix hit,
  KVConnector-backed or
  heterogeneous-block KV cache, frontend stop-string termination, multimodal
  input, prompt embeddings, encoder-decoder execution, and an HTTP response
  path that bypasses the instrumented HTTP/ASGI boundary.

An unsupported mode emits a bounded reason code once for the root lifecycle
and is excluded from completeness and formal scoring. It must not emit a
plausible-looking partial DAG: after the marker, only that root's effective
terminal and cleanup pair plus process-control records may be emitted.

The unsupported reason enum is `parallel_sampling`, `beam_search`, `pooling`,
`streaming_input`, `cross_host`, `response_boundary_uninstrumented`,
`communication_subtype_unfrozen`, `zero_compute_prefix_hit`,
`kv_connector_enabled`, `heterogeneous_kv_cache`, `frontend_stop_string`,
`multimodal_input`, `prompt_embeds`, `encoder_decoder_model`, or
`batched_prompts`. The exporter diagnostic/error enum is
`init_failure`, `schema_incompatible`, `serialization_failure`,
`queue_overflow`, `writer_failure`, `close_timeout`,
`clock_domain_unavailable`, `terminal_conflict`, `invalid_metadata`, or
`unsupported_mode`. Human detail is optional bounded metadata and never a new
reason code.

## Compatibility and failure behavior

The runtime shim declares supported parent API major versions before emitting.
Disabled tracing, absent parent package, incompatible major version,
initialization failure, and writer failure all preserve serving behavior. Each
case has a focused test and an observable bounded diagnostic through normal
runtime logging; it must not retry imports or allocate unbounded error strings
per token.

P1 changes the existing `JsonlTraceSink` path rather than creating a second
exporter. The historical nine-event JSONL remains readable through an explicit
legacy normalizer; no existing event silently acquires a new boundary.

## Approval record

Owner approval must name this file's blob/content digest and explicitly accept
or replace:

1. schema/API version, every per-record field, and every
   size/capacity/timeout;
2. identity topology, cross-process span/sidecar rules, and same-host clock;
3. Queue/Admission split, event/component map, required edge roster, and
   response-layer `stream_done` boundary;
4. terminal precedence, preemption epochs, scoped cleanup roster, and the real
   EngineCore terminal/free/output-handoff order;
5. supported versus diagnostic-only modes, including KV-cache and frontend
   stop-string exclusions;
6. privacy exclusions, loss semantics, and formal shard invalidation rules;
7. profiler issue #2 as the communication-subtype dependency;
8. the exact current runtime/device base used for P1.
