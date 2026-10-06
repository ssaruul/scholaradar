from scholaradar.textract import extract_pdf, guess_language


def test_truncated_pdf_returns_none() -> None:
    assert extract_pdf(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n") is None


def test_guess_language() -> None:
    assert guess_language("Монгол Улсын иргэн байх шаардлагатай. Өргөдөл гаргагч нь үүнийг бүрдүүлнэ.") == "mn"
    assert guess_language("Стипендия для граждан иностранных государств предоставляется ежегодно.") == "ru"
    assert guess_language("外国人留学生のための奨学金募集について") == "ja"
    assert guess_language("외국인 유학생 장학금 모집 안내") == "ko"
    assert guess_language("中国政府奖学金申请通知，欢迎符合条件的申请者提交材料，详情请见附件说明。") == "zh"
    assert guess_language("Applications are open to international students from all countries.") == "en"
