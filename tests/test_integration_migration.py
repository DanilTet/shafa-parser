"""
Интеграционные тесты — полный цикл scan → publish → audit без реального браузера.
"""
import pytest
from unittest.mock import MagicMock
from src.sync.profile_store import ProfileStore
from src.sync.sold_checker import SoldChecker


def _make_item_dict(donor_id: str, my_item_id: str, my_item_url: str, donor_state="active") -> dict:
    return {
        "item_id": donor_id,
        "url": f"https://shafa.ua/uk/men/{donor_id}-donor-item",
        "title": f"Donor Item {donor_id}",
        "price": "350",
        "status": "published",
        "donor_state": donor_state,
        "my_item_url": my_item_url,
        "my_item_id": my_item_id,
        "discovered_at": "2026-01-01 00:00:00",
        "published_at": "2026-01-02 10:00:00",
        "error": None,
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("src.sync.profile_store.SYNC_PROFILES_DIR", str(tmp_path))
    return ProfileStore()


# ─────────────────────────────────────────────────────────────
# Тест 1: Полный цикл scan → publish → audit (донор продал товар)
# ─────────────────────────────────────────────────────────────
def test_full_cycle_donor_sold_item_found(store):
    """
    1. Сканируем донора → pending
    2. Публикуем → published + my_item_id
    3. Аудит: донор продал → алгоритм находит наш товар
    """
    username = "testdonor"
    donor_id = "100500"
    my_id = "217099999"
    my_url = f"https://shafa.ua/uk/men/futbolki/{my_id}-polo-charles-tyrwhitt-bila"

    # Шаг 1: скан
    store.upsert_scanned_items(username, [{
        "item_id": donor_id,
        "url": f"https://shafa.ua/uk/men/polo/{donor_id}-polo-charles-tyrwhitt",
        "title": "Polo Charles Tyrwhitt bila XXL",
        "price": "350",
    }])
    assert store.load_profile(username)[donor_id]["status"] == "pending"

    # Шаг 2: публикация
    store.mark_item_status(username, donor_id, "published",
                           my_item_url=my_url, my_item_id=my_id)
    data = store.load_profile(username)
    assert data[donor_id]["status"] == "published"
    assert data[donor_id]["my_item_id"] == my_id

    # Шаг 3: аудит — донор продал именно наш товар (но другие у него ещё есть)
    # Имитируем: у донора 10 других активных товаров, но нашего поло среди них нет
    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    other_live_items = [
        {"item_id": str(i), "url": f"https://shafa.ua/uk/men/{i}-other-item",
         "title": f"Other Item {i}", "slug": f"{i}-other-item"}
        for i in range(100001, 100011)  # 10 других товаров, НЕ включая donor_id
    ]
    mock_scanner.scan_profile_items.return_value = other_live_items
    mock_scanner.scan_target_account_listings.return_value = [
        {"item_id": my_id, "url": my_url,
         "title": "Polo Charles Tyrwhitt bila",
         "slug": "polo-charles-tyrwhitt-bila"}
    ]
    checker.profile_scanner = mock_scanner

    results = checker.audit_donor_profile(username, driver=MagicMock())


    assert len(results) == 1
    r = results[0]
    assert r["donor_item_id"] == donor_id
    assert r["my_item_id"] == my_id
    assert r["is_active_on_my_account"] is True


# ─────────────────────────────────────────────────────────────
# Тест 2: Аудит — донор активен → кабинет не сканируется
# ─────────────────────────────────────────────────────────────
def test_audit_skips_cabinet_when_all_donor_items_active(store):
    username = "testdonor2"
    donor_id = "200200"
    my_id = "217000001"

    store.save_profile(username, {
        donor_id: _make_item_dict(
            donor_id, my_id,
            f"https://shafa.ua/uk/men/{my_id}-item"
        )
    })

    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    # Донор активен — товар есть в live
    mock_scanner.scan_profile_items.return_value = [
        {"item_id": donor_id, "url": f"https://shafa.ua/uk/men/{donor_id}-donor-item",
         "title": "Donor Item", "slug": f"{donor_id}-donor-item"}
    ]
    checker.profile_scanner = mock_scanner

    results = checker.audit_donor_profile(username, driver=MagicMock())

    # Кабинет НЕ должен был сканироваться
    mock_scanner.scan_target_account_listings.assert_not_called()
    assert results == []


# ─────────────────────────────────────────────────────────────
# Тест 3: Защита — кабинет вернул 0 → аудит безопасно останавливается
# ─────────────────────────────────────────────────────────────
def test_audit_aborts_on_empty_cabinet(store):
    username = "testdonor3"

    # 5 published товаров (меньше 30 — защита по порогу не блокирует)
    items = {}
    for i in range(5):
        items[str(i)] = _make_item_dict(
            str(i), str(1000 + i),
            f"https://shafa.ua/uk/men/{1000+i}-item"
        )
    store.save_profile(username, items)

    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    mock_scanner.scan_profile_items.return_value = []  # донор пустой
    mock_scanner.scan_target_account_listings.return_value = []  # кабинет тоже 0
    checker.profile_scanner = mock_scanner

    results = checker.audit_donor_profile(username, driver=MagicMock())
    # Защита кабинета (Путь 1) должна вернуть []
    assert results == []


# ─────────────────────────────────────────────────────────────
# Тест 4: Защита — каталог донора вернул 0 при 35+ tracked → стоп
# ─────────────────────────────────────────────────────────────
def test_audit_aborts_on_empty_donor_catalog_with_many_tracked(store):
    """
    Защита срабатывает: 0 live items при 35 tracked items → аудит остановлен.
    """
    username = "testdonor4"
    items = {}
    for i in range(35):
        items[str(i)] = _make_item_dict(str(i), str(1000 + i),
                                        f"https://shafa.ua/uk/men/{1000+i}-item")
    store.save_profile(username, items)

    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    mock_scanner.scan_profile_items.return_value = []  # 0 live
    checker.profile_scanner = mock_scanner

    results = checker.audit_donor_profile(username, driver=MagicMock())
    # Защита донора: 0 < 35 * 0.15 = 5.25 → стоп
    assert results == []
    # Кабинет не должен был сканироваться
    mock_scanner.scan_target_account_listings.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Тест 5: mark_item_status + аудит — pending товары не проверяются
# ─────────────────────────────────────────────────────────────
def test_pending_items_not_checked_in_audit(store):
    username = "testdonor5"
    store.upsert_scanned_items(username, [
        {"item_id": "777", "url": "https://shafa.ua/uk/men/777-item",
         "title": "Not Published Yet", "price": "100"}
    ])
    # Статус pending — не трогаем

    checker = SoldChecker(profile_store=store)
    mock_scanner = MagicMock()
    mock_scanner.scan_profile_items.return_value = []
    checker.profile_scanner = mock_scanner

    results = checker.audit_donor_profile(username, driver=MagicMock())
    # Нет published товаров → аудит сразу возвращает []
    assert results == []
    mock_scanner.scan_profile_items.assert_not_called()  # даже скан донора не запускался
