# Shared Workload Smoke Report

- seed: 7
- supported cases: 23
- skipped cases: 2

## shared_session_affine_multi_turn

- label: Shared workload: session-affine multi-turn
- dataset: session-affine-multi-turn
- requests: 64
- family: session-affine-multi-turn
- anchors: 16 primary / 9 secondary
- anchor rank coverage: 8
- mean prompt len: 868
- mean output len: 96

## shared_session_affine_bursty

- label: Shared workload: session-affine bursty regime
- dataset: session-affine-bursty
- requests: 64
- family: session-affine-bursty
- anchors: 16 primary / 14 secondary
- anchor rank coverage: 8
- mean prompt len: 930
- mean output len: 128

## shared_rag_followup

- label: Shared workload: RAG follow-up
- dataset: rag-followup
- requests: 64
- family: rag-followup
- anchors: 16 primary / 64 secondary
- anchor rank coverage: 8
- mean prompt len: 2623
- mean output len: 48

## shared_long_context_doc_analysis

- label: Shared workload: long-context document analysis
- dataset: long-context-doc-analysis
- requests: 48
- family: long-context-doc-analysis
- anchors: 12 primary / 36 secondary
- anchor rank coverage: 8
- mean prompt len: 4442
- mean output len: 64

## shared_tool_scaffold_agent

- label: Shared workload: tool-scaffold agent program
- dataset: tool-scaffold-agent
- requests: 64
- family: tool-scaffold-agent
- anchors: 16 primary / 28 secondary
- anchor rank coverage: 8
- mean prompt len: 932
- mean output len: 160

## shared_repo_aware_coding_assistant

- label: Shared workload: repo-aware coding assistant
- dataset: repo-aware-coding-assistant
- requests: 64
- family: repo-aware-coding-assistant
- anchors: 16 primary / 76 secondary
- anchor rank coverage: 8
- mean prompt len: 1268
- mean output len: 128

## shared_experiment_planning_assistant

- label: Shared workload: experiment-planning assistant
- dataset: experiment-planning-assistant
- requests: 64
- family: experiment-planning-assistant
- anchors: 16 primary / 45 secondary
- anchor rank coverage: 8
- mean prompt len: 1216
- mean output len: 192

## shared_simulation_analysis_verification

- label: Shared workload: simulation-analysis-verification pipeline
- dataset: simulation-analysis-verification
- requests: 64
- family: simulation-analysis-verification
- anchors: 16 primary / 35 secondary
- anchor rank coverage: 8
- mean prompt len: 1095
- mean output len: 128

## shared_async_document_pipeline

- label: Shared workload: async document pipeline
- dataset: async-document-pipeline
- requests: 80
- family: async-document-pipeline
- anchors: 20 primary / 35 secondary
- anchor rank coverage: 8
- mean prompt len: 932
- mean output len: 96

## shared_realtime_voice_assistant

- label: Shared workload: realtime voice assistant proxy
- dataset: realtime-voice-assistant
- requests: 64
- family: realtime-voice-assistant
- anchors: 16 primary / 16 secondary
- anchor rank coverage: 8
- mean prompt len: 1128
- mean output len: 72

## shared_session_continuation_maintenance

- label: Shared workload: session continuation with maintenance
- dataset: session-continuation-maintenance
- requests: 80
- family: session-continuation-maintenance
- anchors: 16 primary / 14 secondary
- anchor rank coverage: 8
- mean prompt len: 928
- mean output len: 112

## shared_shared_prefix_multi_tenant_assistant

- label: Shared workload: shared-prefix multi-tenant assistant
- dataset: shared-prefix-multi-tenant-assistant
- requests: 72
- family: shared-prefix-multi-tenant-assistant
- anchors: 18 primary / 16 secondary
- anchor rank coverage: 8
- mean prompt len: 1424
- mean output len: 130.667

## shared_dynamic_rag_corpus_update

- label: Shared workload: dynamic RAG corpus update
- dataset: dynamic-rag-corpus-update
- requests: 64
- family: dynamic-rag-corpus-update
- anchors: 16 primary / 54 secondary
- anchor rank coverage: 8
- mean prompt len: 2974
- mean output len: 72

## shared_memory_write_then_reuse

- label: Shared workload: memory write then reuse
- dataset: memory-write-then-reuse
- requests: 64
- family: memory-write-then-reuse
- anchors: 16 primary / 38 secondary
- anchor rank coverage: 8
- mean prompt len: 816
- mean output len: 96

## shared_preemption_resume_long_decode

- label: Shared workload: preemption resume long decode
- dataset: preemption-resume-long-decode
- requests: 48
- family: preemption-resume-long-decode
- anchors: 12 primary / 33 secondary
- anchor rank coverage: 8
- mean prompt len: 1536
- mean output len: 236

## shared_scenario_multi_turn_knowledge_service

- label: Scenario: multi-turn knowledge service
- dataset: session-affine-multi-turn
- requests: 32
- family: session-affine-multi-turn
- anchors: 8 primary / 9 secondary
- anchor rank coverage: 8
- mean prompt len: 633
- mean output len: 64

## shared_scenario_rag_followup_long_context

- label: Scenario: RAG follow-up long context
- dataset: rag-followup
- requests: 32
- family: rag-followup
- anchors: 8 primary / 32 secondary
- anchor rank coverage: 8
- mean prompt len: 1792
- mean output len: 32

## shared_scenario_structured_agent_decode

- label: Scenario: structured agent decode
- dataset: tool-scaffold-agent
- requests: 32
- family: tool-scaffold-agent
- anchors: 8 primary / 20 secondary
- anchor rank coverage: 8
- mean prompt len: 419
- mean output len: 128

## session_continuation_with_maintenance

- label: Scenario: session continuation with maintenance
- dataset: session-continuation-maintenance
- requests: 40
- family: session-continuation-maintenance
- anchors: 8 primary / 11 secondary
- anchor rank coverage: 8
- mean prompt len: 928
- mean output len: 112

## shared_prefix_multi_tenant_assistant

- label: Scenario: shared-prefix multi-tenant assistant
- dataset: shared-prefix-multi-tenant-assistant
- requests: 40
- family: shared-prefix-multi-tenant-assistant
- anchors: 10 primary / 12 secondary
- anchor rank coverage: 8
- mean prompt len: 1637
- mean output len: 129

## dynamic_rag_corpus_update

- label: Scenario: dynamic RAG corpus update
- dataset: dynamic-rag-corpus-update
- requests: 32
- family: dynamic-rag-corpus-update
- anchors: 8 primary / 38 secondary
- anchor rank coverage: 8
- mean prompt len: 2974
- mean output len: 72

## memory_write_then_reuse

- label: Scenario: memory write then reuse
- dataset: memory-write-then-reuse
- requests: 32
- family: memory-write-then-reuse
- anchors: 8 primary / 22 secondary
- anchor rank coverage: 8
- mean prompt len: 816
- mean output len: 96

## preemption_resume_long_decode

- label: Scenario: preemption resume long decode
- dataset: preemption-resume-long-decode
- requests: 24
- family: preemption-resume-long-decode
- anchors: 6 primary / 21 secondary
- anchor rank coverage: 6
- mean prompt len: 1536
- mean output len: 236

## Skipped Cases

- shared_synthetic_shared_prefix_microbenchmark: non_repo_local_boundary_case
- shared_public_sharegpt_boundary: non_repo_local_boundary_case
