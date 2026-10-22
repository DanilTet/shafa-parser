import pytest
from src.publisher.category_matcher import (
    detect_gender_profile,
    get_category_synonyms,
    score_category_candidate,
)

def test_detect_gender_profile():
    # Мужская одежда
    assert detect_gender_profile("Сорочка чоловіча boss блакитна m з ліоцеллу", ["Сорочки", "Чоловічий одяг"]) == "men"
    assert detect_gender_profile("Джинсы men levis 501", ["Джинсы"]) == "men"
    
    # Женская одежда
    assert detect_gender_profile("Сукня жіноча zara міді", ["Сукні", "Жіночий одяг"]) == "women"
    assert detect_gender_profile("Женская кофта atmosphere", ["Кофты"]) == "women"
    
    # Детская одежда (имеет приоритет даже если есть 'для мальчика')
    assert detect_gender_profile("Дитяча куртка для хлопчика", ["Куртки", "Дитячий одяг"]) == "kids"
    
    # Неопределенный
    assert detect_gender_profile("Шарф синий теплый", ["Аксессуары"]) == "unknown"


def test_user_case_mens_boss_shirt():
    """
    Тестирование точного случая пользователя:
    Товар: мужская сорочка
    Категории из парсера: ['Сорочки', 'Чоловічий одяг', 'Сорочки та теніски']
    Рекомендации от Шафы (на русском языке):
      1. Рубашки | Мужская одежда/Рубашки и тенниски/Рубашки
      2. Рубашки | Женская одежда/Рубашки и блузы/Рубашки
      3. Платья миди | Женская одежда/Платья/Платья миди
      4. Рубашки и блузы | Женская одежда/Для беременных/Рубашки и блузы
    """
    title = "Сорочка чоловіча boss блакитна m з ліоцеллу"
    target_cats = ["Сорочки", "Чоловічий одяг", "Сорочки та теніски"]
    gender = detect_gender_profile(title, target_cats)
    assert gender == "men"

    # Кандидат 1: Мужская рубашка (должен выиграть с большим отрывом)
    score1 = score_category_candidate(
        btn_title="Рубашки",
        btn_path="Мужская одежда/Рубашки и тенниски/Рубашки",
        target_categories=target_cats,
        gender=gender
    )
    assert score1 > 100.0

    # Кандидат 2: Женская рубашка (должна быть отклонена из-за несовместимого гендера)
    score2 = score_category_candidate(
        btn_title="Рубашки",
        btn_path="Женская одежда/Рубашки и блузы/Рубашки",
        target_categories=target_cats,
        gender=gender
    )
    assert score2 < 0

    # Кандидат 3: Платья миди
    score3 = score_category_candidate(
        btn_title="Платья миди",
        btn_path="Женская одежда/Платья/Платья миди",
        target_categories=target_cats,
        gender=gender
    )
    assert score3 < 0

    # Кандидат 4: Для беременных
    score4 = score_category_candidate(
        btn_title="Рубашки и блузы",
        btn_path="Женская одежда/Для беременных/Рубашки и блузы",
        target_categories=target_cats,
        gender=gender
    )
    assert score4 < 0

    # Кандидат 1 побеждает всех
    assert score1 > score2
    assert score1 > score3
    assert score1 > score4


def test_womens_dress():
    title = "Сукня жіноча чорна вечірня"
    target_cats = ["Сукні", "Жіночий одяг", "Плаття"]
    gender = detect_gender_profile(title, target_cats)
    assert gender == "women"

    score_dress = score_category_candidate(
        btn_title="Платья миди",
        btn_path="Женская одежда/Платья/Платья миди",
        target_categories=target_cats,
        gender=gender
    )
    assert score_dress > 100.0

    score_mens = score_category_candidate(
        btn_title="Рубашки",
        btn_path="Мужская одежда/Рубашки и тенниски/Рубашки",
        target_categories=target_cats,
        gender=gender
    )
    assert score_mens < 0
