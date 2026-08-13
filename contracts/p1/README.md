# Historical KV-recovery design notes

The files retained here describe event semantics, bounded capacities, and
runtime observation points used while designing the KV-recovery profiler.
References inside them to approval candidates, owners, authority splits,
content freezes, attestations, digests, joint admission, or activation
permission are obsolete and non-normative.

Do not use these notes to block implementation or request a co-signature.
Current behavior is defined by source code and tests; activation is controlled
only by the explicit runtime and profiler configuration documented in the
repository root README.
