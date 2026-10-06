from scholaradar.prefilter import keyword_hit, nationality_hits, sentences_mentioning

KEYWORDS = ["scholarship", "тэтгэлэг", "стипенди", "奨学金", "장학금", "奖学金", "stipendium", "burs"]
NAMES = ["Mongolia", "Mongolian", "Монгол Улс", "Монголия", "モンゴル", "몽골", "蒙古", "Mongolei", "Moğolistan"]


def test_keyword_hit_per_language() -> None:
    assert keyword_hit("Fully funded Scholarship 2027", KEYWORDS) == "scholarship"
    assert keyword_hit("2027 оны тэтгэлэгт хөтөлбөр зарлагдлаа", KEYWORDS) == "тэтгэлэг"
    assert keyword_hit("Стипендии для иностранных студентов", KEYWORDS) == "стипенди"
    assert keyword_hit("国費外国人留学生奨学金の募集", KEYWORDS) == "奨学金"
    assert keyword_hit("정부초청 장학금 모집", KEYWORDS) == "장학금"
    assert keyword_hit("中国政府奖学金申请", KEYWORDS) == "奖学金"
    assert keyword_hit("DAAD-Stipendium für Masterstudierende", KEYWORDS) == "stipendium"
    assert keyword_hit("Türkiye Bursları başvuruları", KEYWORDS) == "burs"


def test_keyword_miss() -> None:
    assert keyword_hit("University campus map and parking information", KEYWORDS) is None


def test_nationality_hits_casefold() -> None:
    text = "Open to citizens of MONGOLIA and Kazakhstan. モンゴルからの応募も歓迎。"
    assert nationality_hits(text, NAMES) == ["Mongolia", "モンゴル"]


def test_sentences_mentioning() -> None:
    text = "The programme is open to all nationalities. Citizens of Mongolia are eligible. Deadline is March 1."
    found = sentences_mentioning(text, NAMES)
    assert found == ["Citizens of Mongolia are eligible."]
