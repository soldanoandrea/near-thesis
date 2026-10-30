"""Phase 2a models. Each model is a pure function over processed tables (polars DataFrames / plain parameters):
no I/O, no network, no global state, deterministic for fixed seeds. `nearthesis.phase2` prepares the inputs from
data/processed and writes the outputs."""
