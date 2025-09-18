# Run Index Rebuild Utility

Use `tools/rebuild_run_index.py` to regenerate `run_index.json` and optionally migrate legacy run directories into the new organization-aware layout.

```bash
python tools/rebuild_run_index.py artifacts/runs --move-legacy --pretty
```

- `storage_root` (positional) defaults to `artifacts/runs`.
- `--move-legacy` moves any `artifacts/runs/RUN-*` directories into `artifacts/runs/<organization_slug>/` based on `run_manifest.json` metadata.
- `--pretty` prints the rebuilt index with indentation for readability.

The command writes the refreshed `run_index.json` and returns the in-memory index for scripting. See `tests/test_maintenance.py` for example usage.
