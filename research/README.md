# Research Source Area

The research implementation currently remains in the existing top-level folders to avoid breaking paths used by the experiment scripts:

- `src/`: research pipeline, diagnostics, figure/report generation.
- `configs/`: research experiment configurations.
- `Document/`: proposal, paper/report, SRS, and research notes.

The web application is intentionally isolated under `app/`.

When preparing a clean GitHub release, keep research data and generated outputs outside Git unless they are small curated artifacts:

- Do not commit `Data/`.
- Do not commit `outputs*/` or `reports*/`.
- Commit only source scripts, selected configs, and final documents needed for reproducibility.
