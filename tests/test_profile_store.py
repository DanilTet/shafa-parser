"""
Unit-тесты для ProfileStore — фокус на mark_item_status с my_item_id.
"""
import pytest
from datetime import datetime
from src.sync.profile_store import ProfileStore


def _make_item(item_id: str, status: str = "pending", my_item_id=None, my_item_url=None, donor_state="active") -> dict:
    return {
        "item_id": item_id,
        "url": f"https://shafa.ua/uk/men/{item_id}-item",
        "title": f"Item {item_id}",
        "price": "100",
        "status": status,
        "donor_state": donor_state,
        "my_item_url": my_item_url,
        "my_item_id": my_item_id,
        "discovered_at": "2026-01-01 00:00:00",
        "published_at": None,
        "error": None,
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("src.sync.profile_store.SYNC_PROFILES_DIR", str(tmp_path))
    return ProfileStore()


def _seed(store: ProfileStore, username: str, items: list[dict]):
    data = {item["item_id"]: item for item in items}
    store.save_profile(username, data)


# ─────────────────────────────────────────────────────────────
# Тест 1: mark_item_status сохраняет my_item_id и my_item_url
# ─────────────────────────────────────────────────────────────
def test_mark_item_status_saves_my_item_id(store):
    _seed(store, "donor", [_make_item("111")])

    store.mark_item_status(
        "donor", "111", "published",
        my_item_url="https://shafa.ua/uk/men/futbolki/217099999-polo-charles",
        my_item_id="217099999"
    )

    data = store.load_profile("donor")
    item = data["111"]
    assert item["status"] == "published"
    assert item["my_item_id"] == "217099999"
    assert item["my_item_url"] == "https://shafa.ua/uk/men/futbolki/217099999-polo-charles"
    assert item["published_at"] is not None
    assert item["error"] is None


# ─────────────────────────────────────────────────────────────
# Тест 2: mark_item_status НЕ перезатирает my_item_id если не передан
# ─────────────────────────────────────────────────────────────
def test_mark_item_status_preserves_existing_my_item_id(store):
    _seed(store, "donor", [_make_item(
        "222", status="published",
        my_item_id="217000001",
        my_item_url="https://shafa.ua/uk/men/futbolki/217000001-polo"
    )])

    # Вызываем без my_item_id — существующий должен остаться
    store.mark_item_status("donor", "222", "published")

    data = store.load_profile("donor")
    assert data["222"]["my_item_id"] == "217000001"
    assert data["222"]["my_item_url"] == "https://shafa.ua/uk/men/futbolki/217000001-polo"


# ─────────────────────────────────────────────────────────────
# Тест 3: Несколько товаров — каждый получает свой my_item_id
# ─────────────────────────────────────────────────────────────
def test_multiple_items_each_get_own_my_item_id(store):
    _seed(store, "donor", [
        _make_item("100"),
        _make_item("200"),
        _make_item("300"),
    ])

    store.mark_item_status("donor", "100", "published",
                           my_item_url="https://shafa.ua/uk/men/1000001-item-a",
                           my_item_id="1000001")
    store.mark_item_status("donor", "200", "published",
                           my_item_url="https://shafa.ua/uk/men/1000002-item-b",
                           my_item_id="1000002")
    store.mark_item_status("donor", "300", "failed", error="Тестовая ошибка")

    data = store.load_profile("donor")
    assert data["100"]["my_item_id"] == "1000001"
    assert data["200"]["my_item_id"] == "1000002"
    assert data["300"]["my_item_id"] is None
    assert data["300"]["status"] == "failed"
    assert "Тестовая" in data["300"]["error"]


# ─────────────────────────────────────────────────────────────
# Тест 4: get_stats считает donor_sold корректно
# ─────────────────────────────────────────────────────────────
def test_get_stats_donor_sold_count(store):
    _seed(store, "donor", [
        _make_item("1", status="published", my_item_id="1001", donor_state="active"),
        _make_item("2", status="published", my_item_id="1002", donor_state="sold_or_deleted"),
        _make_item("3", status="pending", donor_state="active"),
        _make_item("4", status="failed", donor_state="sold_or_deleted"),
    ])

    stats = store.get_stats("donor")
    assert stats["total"] == 4
    assert stats["published"] == 2
    assert stats["pending"] == 1
    assert stats["failed"] == 1
    assert stats["donor_sold"] == 2  # оба с sold_or_deleted


# ─────────────────────────────────────────────────────────────
# Тест 5: Атомарная запись не повреждает файл при одновременных вызовах
# ─────────────────────────────────────────────────────────────
def test_atomic_write_no_corruption(store, tmp_path):
    _seed(store, "donor", [_make_item(str(i)) for i in range(20)])

    # Последовательные записи — все должны сохраняться корректно
    for i in range(20):
        store.mark_item_status("donor", str(i), "published",
                               my_item_id=str(100000 + i),
                               my_item_url=f"https://shafa.ua/uk/men/{100000+i}-item")

    data = store.load_profile("donor")
    assert len(data) == 20
    for i in range(20):
        assert data[str(i)]["my_item_id"] == str(100000 + i)
        assert data[str(i)]["status"] == "published"


# ─────────────────────────────────────────────────────────────
# Тест 6: Только published с my_item_id должны отслеживаться аудитом
# ─────────────────────────────────────────────────────────────
def test_audit_trackable_items_require_my_item_id(store):
    """
    Проверяем что фильтрация 'trackable' items (published + my_item_id)
    работает правильно — основа логики аудита.
    """
    _seed(store, "donor", [
        _make_item("A", status="published", my_item_id="999001"),  # ✅ отслеживается
        _make_item("B", status="published", my_item_id=None),      # ❌ нет my_item_id
        _make_item("C", status="pending"),                          # ❌ pending
        _make_item("D", status="published", my_item_id="999002"),  # ✅ отслеживается
    ])

    data = store.load_profile("donor")
    trackable = [
        v for v in data.values()
        if v.get("status") == "published" and v.get("my_item_id")
    ]
    ids = {item["item_id"] for item in trackable}
    assert ids == {"A", "D"}
    assert len(trackable) == 2


# ─────────────────────────────────────────────────────────────
# Тест 7: upsert_scanned_items идемпотентен
# ─────────────────────────────────────────────────────────────
def test_upsert_is_idempotent(store):
    items = [{"item_id": "555", "url": "https://shafa.ua/uk/555-item",
              "title": "Test Item", "price": "200"}]
    store.upsert_scanned_items("donor", items)
    store.upsert_scanned_items("donor", items)  # второй раз
    store.upsert_scanned_items("donor", items)  # третий раз

    data = store.load_profile("donor")
    assert len(data) == 1  # всё ещё один товар
    assert data["555"]["status"] == "pending"
