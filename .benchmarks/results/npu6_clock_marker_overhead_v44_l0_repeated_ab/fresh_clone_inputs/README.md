# Fresh-clone idle-evidence inputs

This bundle makes the accepted v4.4 serving evidence executable from a fresh
checkout without publishing the 2.6 GB of derived SQLite sidecars.

- `raw_msprof/` contains deterministic, lossless gzip archives of the six raw
  msprof databases used by the three matched A/B pairs.
- `manifest.json` binds those archives, the 39 directly committed inputs, all
  51 acceptance-input hashes, analyzer commit
  `9a816aaeda5d937c07d04e13901df1462d12f979`, and the audit SQL hash.
- `.benchmarks/verify_idle_evidence_fresh_clone.py` decompresses each raw
  database, regenerates all six sidecars, executes the cross-clock SQL audit,
  reruns all three pair analyzers and the repeated A/B aggregator, regenerates
  the three calibration micro-capture sidecars, and compares both serving and
  calibration outputs with the committed summaries. Existing PASS badges are
  never treated as acceptance authority.

With the pinned analyzer checked out and built in the sibling directory, run:

```bash
make idle-evidence-fresh-clone-audit PYTHON=python3
```

The repeated gate also requires six distinct raw-source hashes,
non-overlapping capture intervals, the frozen A/B–B/A–A/B order, and one
cross-pair configuration digest. The original derived sidecar byte layout is
not archived. The acceptance claim is reproducibility from lossless raw
profiler inputs plus exact tool and audit provenance, not byte-identical
reproduction of incidental SQLite IDs or source-path metadata.
