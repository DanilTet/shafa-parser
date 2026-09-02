"""
Тесты для системы защиты от перевыставлений донором (Relisting Protection).
Проверяют:
1. Извлечение и валидацию размеров (XS-5XL, W-размеры, числовые).
2. Блокировку склейки товаров при несовпадении размеров / категорий / цен.
3. Распознавание точного и нечеткого перевыставления (Fuzzy/Token/Slug).
4. Автоматическую перепривязку в аудите без ложной отметки 'продано'.
5. Дедупликацию при повторном сканировании (upsert_scanned_items).
6. Правило уникальности 1-к-1 (один живой товар не может склеиться с двумя старыми).
"""
import pytest
from unittest.mock import MagicMock
from src.sync.matching_utils import (
    extract_item_sizes,
    check_price_proximity,
    detect_garment_type,
    is_relisted_match
)
from src.sync.profile_store import ProfileStore
from src.sync.sold_checker import SoldChecker


# ─────────────────────────────────────────────────────────────
# 1. Тесты извлечения размеров
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected_sizes", [
    ("futbolka-polo-charles-tyrwhitt-bila-xxl-bavovna", {"xxl"}),
    ("svitshot-polo-ralph-lauren-biliy-xxl-3xl-bavovna", {"xxl", "xxxl"}),
    ("sorochka-cholovicha-ff-bila-xl-poliester", {"xl"}),
    ("sorochka-zhinocha-hm-bila-l-ml-bavovnyana", {"l"}),
    ("cholovichi-dzhinsi-charles-tyrwhitt-bezhevi-rozmir-m-30w30l", {"m", "w30"}),
    ("shtani-george-siri-rozmir-xl-w38", {"xl", "w38"}),
    ("bluza zhinocha bila rozmir 42 bavovna", {"num_42"}),
    ("plattya bez rozmiru", set()),
])
def test_extract_item_sizes(text, expected_sizes):
    sizes = extract_item_sizes(text)
    for expected in expected_sizes:
        assert expected in sizes, f"В строке '{text}' ожидался размер '{expected}', получено: {sizes}"


# ─────────────────────────────────────────────────────────────
# 2. Тесты многофакторного сопоставления перевыставлений
# ─────────────────────────────────────────────────────────────
def test_relist_exact_slug():
    """Тот же слаг, но новый ID ➔ 100% совпадение."""
    old_item = {
        "item_id": "100001",
        "url": "https://shafa.ua/uk/men/polo/100001-polo-charles-tyrwhitt-bila-xl",
        "title": "Polo Charles Tyrwhitt bila XL",
        "price": "350"
    }
    new_item = {
        "item_id": "200002",
        "url": "https://shafa.ua/uk/men/polo/200002-polo-charles-tyrwhitt-bila-xl",
        "title": "Polo Charles Tyrwhitt bila XL",
        "price": "350"
    }
    matched, score, reason = is_relisted_match(old_item, new_item)
    assert matched is True
    assert score == 1.0
    assert reason == "exact_slug"


def test_relist_different_sizes_blocked():
    """Тот же бренд и модель, но разный размер (XL vs S) ➔ БЛОКИРУЕТСЯ."""
    old_item = {
        "item_id": "100001",
        "url": "https://shafa.ua/uk/men/polo/100001-polo-charles-tyrwhitt-bila-xl",
        "title": "Polo Charles Tyrwhitt bila XL",
        "price": "350"
    }
    new_item = {
        "item_id": "200002",
        "url": "https://shafa.ua/uk/men/polo/200002-polo-charles-tyrwhitt-bila-s",
        "title": "Polo Charles Tyrwhitt bila S",
        "price": "350"
    }
    matched, score, reason = is_relisted_match(old_item, new_item)
    assert matched is False
    assert reason == "different_sizes"


def test_relist_different_garment_types_blocked():
    """Один бренд, но рубашка vs худи ➔ БЛОКИРУЕТСЯ."""
    old_item = {
        "item_id": "100001",
        "url": "https://shafa.ua/uk/men/rubashki/100001-sorochka-ralph-lauren-bila-l",
        "title": "Сорочка Ralph Lauren біла L",
        "price": "500"
    }
    new_item = {
        "item_id": "200002",
        "url": "https://shafa.ua/uk/men/hudi/200002-hudi-ralph-lauren-bila-l",
        "title": "Худі Ralph Lauren біла L",
        "price": "500"
    }
    matched, score, reason = is_relisted_match(old_item, new_item)
    assert matched is False
    assert reason == "different_garment_type"


def test_relist_wildly_different_price_blocked():
    """Цена отличается в 5 раз (300 vs 1500) ➔ БЛОКИРУЕТСЯ."""
    old_item = {
        "item_id": "100001",
        "url": "https://shafa.ua/uk/men/polo/100001-polo-charles-tyrwhitt-bila-xl",
        "title": "Polo Charles Tyrwhitt bila XL",
        "price": "300"
    }
    new_item = {
        "item_id": "200002",
        "url": "https://shafa.ua/uk/men/polo/200002-polo-charles-tyrwhitt-bila-xl",
        "title": "Polo Charles Tyrwhitt bila XL",
        "price": "1500"
    }
    matched, score, reason = is_relisted_match(old_item, new_item)
    assert matched is False
    assert reason == "wildly_different_price"


def test_relist_minor_title_modification():
    """Незначительное изменение заголовка (добавили 'бавовна') ➔ успешно распознается."""
    old_item = {
        "item_id": "100001",
        "url": "https://shafa.ua/uk/men/polo/100001-futbolka-polo-charles-tyrwhitt-bila-xl",
        "title": "Футболка поло Charles Tyrwhitt біла XL",
        "price": "350"
    }
    new_item = {
        "item_id": "200002",
        "url": "https://shafa.ua/uk/men/polo/200002-futbolka-polo-charles-tyrwhitt-bila-xl-bavovna",
        "title": "Футболка поло Charles Tyrwhitt біла XL бавовна",
        "price": "340"
    }
    matched, score, reason = is_relisted_match(old_item, new_item)
    assert matched is True
    assert score >= 0.75


# ─────────────────────────────────────────────────────────────
# 3. Интеграционный тест: Аудит перепривязывает товар без ложной продажи
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("src.sync.profile_store.SYNC_PROFILES_DIR", str(tmp_path))
    return ProfileStore()


def test_audit_relinks_relisted_item_instead_of_marking_sold(store):
    username = "donor_bump"
    old_donor_id = "111111"
    new_donor_id = "222222"
    my_item_id = "999999"

    # 1. В базе товар числится как опубликованный под старым ID донора
    store.save_profile(username, {
        old_donor_id: {
            "item_id": old_donor_id,
            "url": f"https://shafa.ua/uk/men/polo/{old_donor_id}-polo-charles-tyrwhitt-bila-xl",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350",
            "status": "published",
            "donor_state": "active",
            "my_item_url": f"https://shafa.ua/uk/men/{my_item_id}-polo",
            "my_item_id": my_item_id,
            "published_at": "2026-09-01 12:00:00",
            "error": None
        }
    })

    # 2. Донор удалил старое объявление и выставил новое
    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    mock_scanner.scan_profile_items.return_value = [
        # Старого 111111 нет, есть новый 222222!
        {
            "item_id": new_donor_id,
            "url": f"https://shafa.ua/uk/men/polo/{new_donor_id}-polo-charles-tyrwhitt-bila-xl",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350"
        }
    ]
    checker.profile_scanner = mock_scanner

    # 3. Запускаем аудит
    results = checker.audit_donor_profile(username, driver=MagicMock())

    # Товар НЕ должен попасть в список проданных!
    assert results == []

    # В базе товар должен быть автоматически перепривязан на новый ID донора
    updated_data = store.load_profile(username)
    assert old_donor_id not in updated_data
    assert new_donor_id in updated_data

    relinked = updated_data[new_donor_id]
    assert relinked["status"] == "published"
    assert relinked["my_item_id"] == my_item_id
    assert relinked["donor_state"] == "active"
    assert new_donor_id in relinked["url"]


# ─────────────────────────────────────────────────────────────
# 4. Тест уникальности 1-к-1: один живой товар не может склеиться с двумя
# ─────────────────────────────────────────────────────────────
def test_audit_strict_one_to_one_relink(store):
    username = "donor_bump_unique"
    old_id_1 = "101"
    old_id_2 = "102"
    new_live_id = "201"

    # Два похожих старых товара
    store.save_profile(username, {
        old_id_1: {
            "item_id": old_id_1,
            "url": f"https://shafa.ua/uk/men/polo/{old_id_1}-polo-charles-tyrwhitt-bila-xl",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350",
            "status": "published",
            "donor_state": "active",
            "my_item_id": "901",
            "my_item_url": "https://shafa.ua/my/901"
        },
        old_id_2: {
            "item_id": old_id_2,
            "url": f"https://shafa.ua/uk/men/polo/{old_id_2}-polo-charles-tyrwhitt-bila-xl-copy",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350",
            "status": "published",
            "donor_state": "active",
            "my_item_id": "902",
            "my_item_url": "https://shafa.ua/my/902"
        }
    })

    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    # У донора остался только ОДИН живой товар
    mock_scanner.scan_profile_items.return_value = [
        {
            "item_id": new_live_id,
            "url": f"https://shafa.ua/uk/men/polo/{new_live_id}-polo-charles-tyrwhitt-bila-xl",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350"
        }
    ]
    # Кабинет пользователя
    mock_scanner.scan_target_account_listings.return_value = [
        {"item_id": "901", "url": "https://shafa.ua/my/901", "title": "Polo bila XL"},
        {"item_id": "902", "url": "https://shafa.ua/my/902", "title": "Polo bila XL copy"}
    ]
    checker.profile_scanner = mock_scanner

    results = checker.audit_donor_profile(username, driver=MagicMock())

    # Ровно 1 товар перепривязан, а второй честно помечен как ПРОДАННЫЙ
    assert len(results) == 1
    data = store.load_profile(username)
    assert new_live_id in data  # один перепривязан


# ─────────────────────────────────────────────────────────────
# 5. Дедупликация при сканировании профиля (upsert_scanned_items)
# ─────────────────────────────────────────────────────────────
def test_upsert_scanned_items_deduplication(store):
    username = "donor_scan_dedup"
    old_id = "555001"
    new_id = "555002"
    my_id = "888001"

    # Товар уже перенесен под старым ID донора
    store.save_profile(username, {
        old_id: {
            "item_id": old_id,
            "url": f"https://shafa.ua/uk/men/polo/{old_id}-polo-charles-tyrwhitt-bila-xl",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350",
            "status": "published",
            "donor_state": "active",
            "my_item_id": my_id,
            "my_item_url": f"https://shafa.ua/my/{my_id}"
        }
    })

    # Пользователь запускает сканирование донора
    # Донор удалил 555001 и выставил 555002
    scanned_items = [
        {
            "item_id": new_id,
            "url": f"https://shafa.ua/uk/men/polo/{new_id}-polo-charles-tyrwhitt-bila-xl",
            "title": "Polo Charles Tyrwhitt bila XL",
            "price": "350"
        }
    ]

    new_count, total = store.upsert_scanned_items(username, scanned_items)

    # new_count должен быть 0 (дубль НЕ добавлен в очередь pending!)
    assert new_count == 0
    assert total == 1

    # Запись должна остаться в статусе published, но с новым donor ID
    data = store.load_profile(username)
    assert old_id not in data
    assert new_id in data
    assert data[new_id]["status"] == "published"
    assert data[new_id]["my_item_id"] == my_id
