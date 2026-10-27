import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WS = ROOT / "workspaces" / "khtn9-m1-real"

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def save_canonical(n, edit):
    path = WS / "release-prep" / f"bai{n}" / "canonical.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    edit(doc)
    doc["contentHash"] = digest({k: v for k, v in doc.items() if k != "contentHash"})
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def lesson11(doc):
    needle = "Vòng màu thứ tư Vòng màu thứ ba Vòng màu thứ hai Vòng màu thứ nhất"
    insert = ("Đối với điện trở 4 vòng màu:\n\nMàu của vòng thứ nhất và của vòng thứ hai cho 2 số đầu của trị số điện trở, "
              "màu của vòng thứ ba cho luỹ thừa của 10 nhân với hai số đầu đã xác định ở trên.\n\n"
              "Vòng màu thứ tư: chỉ giá trị sai số của điện trở. Vòng thứ tư là vòng ở cuối luôn có màu vàng ánh kim hay màu bạc.\n\n"
              "Giá trị điện trở = [Vòng màu 1][Vòng màu 2] × 10^[Vòng màu 3] ± [Vòng màu 4]\n\n"
              "Ví dụ, trên điện trở Hình 11.5 có các vòng màu lần lượt là vàng, tím, đen tương ứng với các số 4, 7, 10^0. "
              "Vòng thứ tư màu vàng ánh kim, giá trị sai số là ± 5%.\n\nTính được: 47 × 10^0 = 47, sai số 5% của 47 là 2,35.\n\n"
              "Giá trị điện trở được viết như sau: 47,00 ± 2,35 (Ω).")
    for section in doc["sections"]:
        if "p0061-b0001" in " ".join(section.get("ownedBlockIds", [])):
            text = section["content"]
            if insert not in text:
                section["content"] = text.replace(needle, insert + "\n\n" + needle)

def lesson32(doc):
    for section in doc["sections"]:
        text = section.get("content", "")
        duplicate = "Chất dẻo dễ bị mềm dẻo ở môi trường nhiệt độ cao, một số bị phân huỷ tạo thành các sản phẩm độc hại. Vì vậy, không để các vật dụng làm từ chất dẻo ở gần nguồn nhiệt cao (bếp gas, lò nướng,...), hạn chế sử dụng các đồ dùng bằng nhựa đựng thức ăn nóng. Trên các vỏ chai, hộp, đồ dùng bằng nhựa thường có các kí hiệu an toàn và kí hiệu phân loại nhựa. Vì vậy, cần lưu ý tìm hiểu thông tin để lựa chọn đồ nhựa phù hợp với mục đích sử dụng (Hình 32.3)."
        if text.count(duplicate) > 1:
            section["content"] = text[:text.find(duplicate)] + duplicate + text[text.rfind(duplicate) + len(duplicate):]
        section["content"] = section["content"].replace("Chất đẻo dễ bị mềm đẻo", "Chất dẻo dễ bị mềm dẻo").replace("chất đẻo ở gần", "chất dẻo ở gần").replace("lò nuống", "lò nướng").replace("nhựa dựng thức ăn", "nhựa đựng thức ăn")

def labels(doc):
    for image in doc.get("images", []):
        label = image.get("figureLabel", "")
        if label == "Hình 42.5": image["description"] = "Bộ nhiễm sắc thể lưỡng bội ở ruồi giấm cái (Drosophila melanogaster)."
        if label == "Hình 43.3": image["description"] = "Sơ đồ phép lai hai cặp gene ở đậu Hà Lan."
        if label == "Hình 47.3": image["description"] = "Bảng 47.3 về tình huống giả định hôn nhân cận huyết trong phạm vi từ 1 đến 5 đời."

save_canonical(11, lesson11)
save_canonical(32, lesson32)
for n in (40, 42, 43, 47): save_canonical(n, labels)
for n in (11, 32, 40, 42, 43, 47):
    c = json.loads((WS / "release-prep" / f"bai{n}" / "canonical.json").read_text(encoding="utf-8"))
    sp = WS / "exports" / "structured" / f"src-lesson-khtn9-{n}.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    lc = s["learningContent"]
    by_id = {x["id"]: x for x in c["sections"]}
    for section in lc.get("sections", []):
        if section.get("id") in by_id:
            section["content"] = by_id[section["id"]]["content"]
    lc["summary"] = c["summary"]["text"]
    lc["formulas"] = c["formulas"]
    lc["tables"] = c["tables"]
    s["resolvedFrom"] = {"canonicalContentHash": c["contentHash"], "inputFingerprint": c["inputFingerprint"], "appliedContentDigest": digest(lc)}
    sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("P0 canonical corrections written: 11, 32, 40, 42, 43, 47")
