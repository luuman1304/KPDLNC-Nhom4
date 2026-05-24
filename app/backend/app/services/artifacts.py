from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from app.core.config import ARTIFACT_DIR


class ArtifactRegistry:
    def __init__(self, artifact_dir: Path = ARTIFACT_DIR) -> None:
        self.artifact_dir = artifact_dir
        self.manifest_path = artifact_dir / "metadata" / "artifact_manifest.json"
        self.manifest = self._load_manifest()
        self.cluster_profiles = self._load_cluster_profiles()

    def _load_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {"mode": "demo", "note": "Artifact manifest not found."}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    @property
    def mode(self) -> str:
        return str(self.manifest.get("mode", "demo"))

    def _load_cluster_profiles(self) -> pd.DataFrame:
        path = self.artifact_dir / "metadata" / "cluster_profiles.csv"
        if path.exists():
            df = pd.read_csv(path)
            if "origin" in df.columns:
                max_origin = df["origin"].max()
                df = df[df["origin"] == max_origin].copy()
            return df
        return pd.DataFrame(
            [
                {"cluster_label": 0, "n_series": 0, "mean_sales": 0.5, "zero_sales_ratio": 0.72, "adi": 5.4, "cv2": 0.31},
                {"cluster_label": 1, "n_series": 0, "mean_sales": 2.3, "zero_sales_ratio": 0.34, "adi": 1.6, "cv2": 0.58},
                {"cluster_label": 2, "n_series": 0, "mean_sales": 10.6, "zero_sales_ratio": 0.17, "adi": 1.2, "cv2": 0.56},
            ]
        )

    def metric_summary(self) -> list[dict]:
        path = self.artifact_dir / "metadata" / "model_metric_summary.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path)
        return df.to_dict(orient="records")

    @property
    def model_origin_dir(self) -> Path:
        candidates = sorted((self.artifact_dir / "models").glob("origin_*"))
        if not candidates:
            return self.artifact_dir / "models"
        return candidates[-1]

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def load_cluster_artifacts(self):
        cluster_dir = self.model_origin_dir / "cluster"
        model_path = cluster_dir / "minibatch_kmeans_k3.joblib"
        scaler_path = cluster_dir / "robust_scaler.joblib"
        schema_path = cluster_dir / "clustering_feature_schema.json"
        if not (model_path.exists() and scaler_path.exists() and schema_path.exists()):
            return None
        return {
            "model": joblib.load(model_path),
            "scaler": joblib.load(scaler_path),
            "schema": self.load_json(schema_path),
        }


registry = ArtifactRegistry()
