# NPU6 v4.4 calibration audit bundle

This directory commits the bracket TSV, source `msprof` SQLite database, and
probe summary for each accepted repeated capture. Derived TraceLoom sidecars,
loop trees, and result JSON are regenerated and are not committed.
`audit_inputs_manifest.json` binds every retained input and acceptance summary
to its byte size and SHA-256 digest, and pins the analyzer to TraceLoom commit
`9a816aaeda5d937c07d04e13901df1462d12f979`.

Verify the committed bundle from the repository root:

```bash
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

manifest = json.loads(Path(
    ".benchmarks/results/npu6_host_device_clock_calibration/"
    "audit_inputs_manifest.json"
).read_text())
artifacts = []
for capture in manifest["captures"]:
    artifacts.extend(capture["artifacts"].values())
artifacts.extend(manifest["summary_artifacts"].values())
for artifact in artifacts:
    path = Path(artifact["path"])
    payload = path.read_bytes()
    assert len(payload) == artifact["size_bytes"], path
    assert hashlib.sha256(payload).hexdigest() == artifact["sha256"], path
print(f"verified {len(artifacts)} content-addressed artifacts")
PY
```

Rebuild the three sidecars with the pinned tool checkout. The commands write
only to a temporary directory and use the committed raw inputs:

```bash
TOOL_ROOT=../vllm-hust-perf-analyzer
cmake --preset dev-tests -S "$TOOL_ROOT"
cmake --build "$TOOL_ROOT/build/native-tests" -j
AUDIT_OUTPUT=$(mktemp -d)

"$TOOL_ROOT/build/native-tests/native/traceloom" \
  --source-db .benchmarks/results/npu6_host_device_clock_calibration/capture_05_v44_real/profile/PROF_000001_20260808111408927_01861962RFGMIPIJ/msprof_20260808111416.db \
  --clock-marker-brackets .benchmarks/results/npu6_host_device_clock_calibration/capture_05_v44_real/clock_marker_brackets.tsv \
  --compat-db-out "$AUDIT_OUTPUT/capture_05.db" \
  --out "$AUDIT_OUTPUT/capture_05.json" \
  --loop-tree-out "$AUDIT_OUTPUT/capture_05.md"
"$TOOL_ROOT/build/native-tests/native/traceloom" \
  --source-db .benchmarks/results/npu6_host_device_clock_calibration/capture_06_v44_real/profile/PROF_000001_20260808111514183_01863898PPCAEOOK/msprof_20260808111521.db \
  --clock-marker-brackets .benchmarks/results/npu6_host_device_clock_calibration/capture_06_v44_real/clock_marker_brackets.tsv \
  --compat-db-out "$AUDIT_OUTPUT/capture_06.db" \
  --out "$AUDIT_OUTPUT/capture_06.json" \
  --loop-tree-out "$AUDIT_OUTPUT/capture_06.md"
"$TOOL_ROOT/build/native-tests/native/traceloom" \
  --source-db .benchmarks/results/npu6_host_device_clock_calibration/capture_07_v44_real/profile/PROF_000001_20260808111531951_01864298RFOJABQC/msprof_20260808111539.db \
  --clock-marker-brackets .benchmarks/results/npu6_host_device_clock_calibration/capture_07_v44_real/clock_marker_brackets.tsv \
  --compat-db-out "$AUDIT_OUTPUT/capture_07.db" \
  --out "$AUDIT_OUTPUT/capture_07.json" \
  --loop-tree-out "$AUDIT_OUTPUT/capture_07.md"

python3 .benchmarks/analyze_host_device_clock_calibration.py \
  --sidecar "$AUDIT_OUTPUT/capture_05.db" \
  --sidecar "$AUDIT_OUTPUT/capture_06.db" \
  --sidecar "$AUDIT_OUTPUT/capture_07.db" \
  --output-dir "$AUDIT_OUTPUT/summary" \
  --require-three
```

CI runs this reconstruction through
`.benchmarks/verify_idle_evidence_fresh_clone.py` and requires the recomputed
JSON and Markdown to match the committed summaries.

The accepted bundle validates the real marker-to-profiler-to-calibration chain.
It does not establish positive serving E4 attribution; correlated duration is
zero in all three captures.
