# Foundation spikes

Each `s0_NN_*.py` script validates one risky stack assumption (Kùzu, LanceDB, ColQwen, Nomic, encrypted SQLite, tantivy). Run with the project venv:

```bash
.venv/bin/python spikes/s0_01_kuzu.py
```

Each script self-reports `PASS` / `FAIL` and writes a one-line result to `spikes/results.json`.
