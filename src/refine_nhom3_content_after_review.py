from __future__ import annotations

from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "Document" / "Bai_Bao_Nghien_Cuu_M5_Cau_Truc_Chuan_Hoc_Thuat.docx"


REPLACEMENTS = {
    "RQ4: Các nhóm feature calendar/SNAP/event, price và hierarchy/ID ảnh hưởng thế nào đến WRMSSE của C?": (
        "RQ4: Tác động của từng nhóm feature calendar/SNAP/event, price, hierarchy/ID "
        "đến WRMSSE của C là gì?"
    ),
    (
        "Nền tảng phương pháp gồm LightGBM, Mini-batch K-Means, K-Medoids robustness, "
        "ADI-CV2 demand classification và rolling-origin evaluation. LightGBM phù hợp "
        "với dữ liệu tabular lớn; Mini-batch K-Means cung cấp phân cụm có khả năng mở "
        "rộng; K-Medoids đóng vai trò kiểm tra độ nhạy hậu nghiệm."
    ): (
        "Trong ngữ cảnh dữ liệu M5, các thành phần lý thuyết được triển khai thành "
        "một pipeline thực nghiệm gồm LightGBM, Mini-batch K-Means, K-Medoids "
        "robustness, ADI-CV2 demand mapping và rolling-origin evaluation. LightGBM "
        "đảm nhiệm phần dự báo trên dữ liệu tabular lớn; Mini-batch K-Means tạo "
        "cụm có khả năng mở rộng ở full scale; K-Medoids được dùng như kiểm tra "
        "độ nhạy hậu nghiệm của cấu trúc cụm."
    ),
    (
        "ADI đo khoảng cách trung bình giữa các lần bán khác 0, còn CV2 đo mức biến "
        "động tương đối của lượng bán trong các ngày có phát sinh nhu cầu. Theo cách "
        "phân loại nhu cầu kinh điển, ADI cao thường liên quan đến nhu cầu gián đoạn, "
        "trong khi CV2 cao liên quan đến nhu cầu erratic hoặc lumpy. Trong nghiên cứu "
        "này, ADI-CV2 không được dùng như nhãn mục tiêu mà được dùng như nền tảng lý "
        "thuyết để diễn giải cluster và kiểm tra xem các cụm học được có phản ánh khác "
        "biệt demand behavior hay không."
    ): (
        "Bản đồ ADI-CV2 được dùng trong bài như công cụ diễn giải và kiểm tra chất "
        "lượng phân cụm, không phải nhãn mục tiêu huấn luyện. Vì vậy, cluster label "
        "được học từ nhiều đặc trưng lịch sử của chuỗi, còn ADI-CV2 giúp đối chiếu "
        "xem các cụm đó có tương ứng với khác biệt demand behavior hay không."
    ),
    (
        "WRMSSE phản ánh bản chất phân cấp của M5. Metric này đánh giá đồng thời "
        "item-store và các cấp tổng hợp như store, state, category và department, nhờ "
        "đó hạn chế việc tối ưu cục bộ ở bottom level nhưng làm sai lệch các aggregate "
        "quan trọng."
    ): (
        "Do M5 có nhiều cấp phân cấp, đánh giá kết quả không dừng ở item-store mà "
        "được tổng hợp qua các cấp store, state, category và department. Cách đánh "
        "giá này phù hợp với mục tiêu vận hành, nơi sai số ở cấp tổng hợp cũng ảnh "
        "hưởng trực tiếp đến tồn kho và phân bổ hàng hóa."
    ),
}


def main() -> None:
    doc = Document(TARGET)
    changed = 0
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text in REPLACEMENTS:
            paragraph.text = REPLACEMENTS[text]
            changed += 1
    doc.save(TARGET)
    print(f"Updated: {TARGET}")
    print(f"Replacements applied: {changed}")


if __name__ == "__main__":
    main()
