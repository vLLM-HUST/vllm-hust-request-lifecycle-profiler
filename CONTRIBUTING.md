# Contributing

## Upstream Safety Rule

- This template must not encourage direct edits to `/home/shuhao/reference-repos/vllm`.
- If a derived plugin eventually needs upstream-local changes, that derived repository should vendor or clone vLLM inside itself and patch there.

## Expected Workflow

1. Keep the template minimal.
2. Keep example logic under `src/`.
3. Update `README.md` if the recommended plugin boundary changes.
4. Record structure or workflow changes in this repository's `CHANGELOG.md` only.
5. Do not record template-repo changes in `/home/shuhao/sagellm/CHANGELOG.md`.

## Unified Local Commands

```bash
make install-dev
make smoke
make test
make lint
make format
make build
make bench
make paper
make paper-assets
make paper-pdf
```

## Testing

```bash
make test
```