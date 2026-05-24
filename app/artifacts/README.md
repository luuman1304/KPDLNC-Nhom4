# Application Artifacts

Place inference artifacts here when available:

- `models/`: pretrained A0, B1, and C cluster-specific LightGBM models.
- `preprocessors/`: encoders, scalers, feature schema.
- `cluster/`: pretrained clustering model and clustering scaler.
- `metadata/`: artifact manifest, cluster profile, metric summary.

The current repository may not include heavy artifacts. If artifacts are absent, the backend should expose `artifact_mode=demo` and avoid claiming real research-model inference.
