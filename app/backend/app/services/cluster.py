from __future__ import annotations

from app.schemas.forecast import ClusterInfo, SalesRecord
from app.services.artifacts import registry
from app.services.features import demand_features


def cluster_name(cluster_id: int) -> str:
    names = {
        0: "Nhu cầu thấp/đứt quãng",
        1: "Nhu cầu ổn định hơn",
        2: "Nhu cầu cao/biến động",
    }
    return names.get(cluster_id, f"Cụm {cluster_id}")


def interpretation(cluster_id: int) -> str:
    texts = {
        0: "Chuỗi có doanh số trung bình thấp và nhiều ngày không bán; cần thận trọng với spike ngắn hạn.",
        1: "Chuỗi có nhu cầu đều hơn, phù hợp hơn với replenishment định kỳ.",
        2: "Chuỗi có doanh số cao hơn hoặc biến động mạnh; cần theo dõi forecast jump và yếu tố lịch/giá.",
    }
    return texts.get(cluster_id, "Chưa có diễn giải cụm.")


def predict_cluster(records: list[SalesRecord]) -> ClusterInfo:
    features = demand_features(records)
    # Demo-compatible assignment. Replace with pretrained clustering_model.predict after artifacts are exported.
    if features["zero_sales_ratio"] >= 0.6 or features["adi"] >= 3:
        cluster_id = 0
    elif features["mean_sales"] >= 5 or features["cv2"] >= 1.0:
        cluster_id = 2
    else:
        cluster_id = 1

    profile = registry.cluster_profiles
    matched = profile[profile["cluster_label"].astype(int) == int(cluster_id)]
    if not matched.empty:
        row = matched.iloc[0].to_dict()
        mean_sales = float(row.get("mean_sales", features["mean_sales"]))
        zero_sales_ratio = float(row.get("zero_sales_ratio", features["zero_sales_ratio"]))
        adi = float(row.get("adi", features["adi"]))
        cv2 = float(row.get("cv2", features["cv2"]))
    else:
        mean_sales = features["mean_sales"]
        zero_sales_ratio = features["zero_sales_ratio"]
        adi = features["adi"]
        cv2 = features["cv2"]

    return ClusterInfo(
        cluster_id=int(cluster_id),
        cluster_name=cluster_name(int(cluster_id)),
        mean_sales=mean_sales,
        zero_sales_ratio=zero_sales_ratio,
        adi=adi,
        cv2=cv2,
        interpretation=interpretation(int(cluster_id)),
    )


def cluster_info_for_id(cluster_id: int, records: list[SalesRecord]) -> ClusterInfo:
    features = demand_features(records)
    profile = registry.cluster_profiles
    matched = profile[profile["cluster_label"].astype(int) == int(cluster_id)]
    if not matched.empty:
        row = matched.iloc[0].to_dict()
        mean_sales = float(row.get("mean_sales", features["mean_sales"]))
        zero_sales_ratio = float(row.get("zero_sales_ratio", features["zero_sales_ratio"]))
        adi = float(row.get("adi", features["adi"]))
        cv2 = float(row.get("cv2", features["cv2"]))
    else:
        mean_sales = features["mean_sales"]
        zero_sales_ratio = features["zero_sales_ratio"]
        adi = features["adi"]
        cv2 = features["cv2"]
    return ClusterInfo(
        cluster_id=int(cluster_id),
        cluster_name=cluster_name(int(cluster_id)),
        mean_sales=mean_sales,
        zero_sales_ratio=zero_sales_ratio,
        adi=adi,
        cv2=cv2,
        interpretation=interpretation(int(cluster_id)),
    )
