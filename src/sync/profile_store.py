import os
import json
import re
from datetime import datetime
from src.config import SYNC_PROFILES_DIR
from src.utils.logger import logger
from src.sync.matching_utils import is_relisted_match, normalize_slug, normalize_title

class ProfileStore:
    def __init__(self):
        os.makedirs(SYNC_PROFILES_DIR, exist_ok=True)

    def _clean_username(self, username_or_url: str) -> str:
        """Извлекает и нормализует имя пользователя из URL или строки."""
        raw = username_or_url.strip()
        # Если передан URL: https://shafa.ua/uk/member/daniltet07/clothes -> daniltet07
        match = re.search(r'/member/([^/?#]+)', raw)
        if match:
            return match.group(1).lower()
        # Убираем лишние слэши и спецсимволы
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '', raw).lower()
        return clean

    def get_profile_path(self, username_or_url: str) -> str:
        username = self._clean_username(username_or_url)
        return os.path.join(SYNC_PROFILES_DIR, f"{username}.json")

    def get_saved_profiles(self) -> list[str]:
        """Возвращает список всех сохраненных профилей в базе."""
        if not os.path.exists(SYNC_PROFILES_DIR):
            return []
        profiles = []
        for fname in os.listdir(SYNC_PROFILES_DIR):
            if fname.endswith(".json"):
                profiles.append(fname[:-5])
        return sorted(profiles)

    def load_profile(self, username_or_url: str) -> dict[str, dict]:
        """Загружает базу товаров для указанного профиля."""
        filepath = self.get_profile_path(username_or_url)
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения базы профиля {filepath}: {e}")
            return {}

    def save_profile(self, username_or_url: str, data: dict):
        """Атомарно сохраняет базу товаров на диск."""
        filepath = self.get_profile_path(username_or_url)
        temp_filepath = filepath + ".tmp"
        try:
            with open(temp_filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Атомарная замена файла
            if os.path.exists(filepath):
                os.remove(filepath)
            os.rename(temp_filepath, filepath)
        except Exception as e:
            logger.error(f"Ошибка сохранения базы профиля {filepath}: {e}")
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except:
                    pass

    def upsert_scanned_items(self, username_or_url: str, scanned_items: list[dict]) -> tuple[int, int]:
        """
        Добавляет новые отсканированные товары в базу.
        Возвращает (количество_новых_товаров, общее_количество).
        """
        username = self._clean_username(username_or_url)
        profile_data = self.load_profile(username)
        new_count = 0
        relinked_count = 0

        # Собираем ID всех отсканированных товаров
        scanned_ids = {str(item.get("item_id")) for item in scanned_items if item.get("item_id")}

        # Находим уже перенесенные товары, чей старый донорский ID отсутствует в текущем каталоге
        disappeared_published = {
            old_id: entry for old_id, entry in profile_data.items()
            if entry.get("status") == "published" and old_id not in scanned_ids
        }

        for item in scanned_items:
            item_id = str(item.get("item_id"))
            if not item_id:
                continue

            if item_id not in profile_data:
                # Проверяем, не является ли этот "новый" товар перевыставленной версией
                # одного из ранее перенесенных товаров, чей старый ID пропал
                matched_old_id = None
                for old_id, old_entry in list(disappeared_published.items()):
                    is_match, score, reason = is_relisted_match(old_entry, item)
                    if is_match:
                        matched_old_id = old_id
                        break

                if matched_old_id:
                    # Это перевыставление! Переносим связку на новый ID без создания дубля в очереди
                    relinked_entry = profile_data.pop(matched_old_id)
                    relinked_entry["item_id"] = item_id
                    relinked_entry["url"] = item.get("url", relinked_entry.get("url", ""))
                    if item.get("title") and item["title"].lower() not in ("резерв", "продано", "бронь"):
                        relinked_entry["title"] = item["title"]
                    if item.get("price"):
                        relinked_entry["price"] = str(item["price"])
                    relinked_entry["donor_state"] = "active"
                    profile_data[item_id] = relinked_entry
                    del disappeared_published[matched_old_id]
                    relinked_count += 1
                    logger.info(
                        f"🔄 При сканировании обнаружено перевыставление: донор обновил #{matched_old_id} ➔ #{item_id}. "
                        f"Связка сохранена без дублирования ({item.get('url')})"
                    )
                else:
                    # Настоящий новый товар донора
                    profile_data[item_id] = {
                        "item_id": item_id,
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                        "price": str(item.get("price", "")),
                        "status": "pending",  # pending | published | skipped | failed
                        "donor_state": "active",  # active | sold_or_deleted
                        "my_item_url": None,
                        "my_item_id": None,
                        "discovered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "published_at": None,
                        "error": None
                    }
                    new_count += 1
            else:
                # Обновляем актуальную ссылку/цену/название, сохраняя существующий статус
                profile_data[item_id]["url"] = item.get("url", profile_data[item_id]["url"])
                if item.get("title"):
                    profile_data[item_id]["title"] = item["title"]
                if item.get("price"):
                    profile_data[item_id]["price"] = str(item["price"])
                profile_data[item_id]["donor_state"] = "active"

        self.save_profile(username, profile_data)
        msg = f"Профиль '{username}': добавлено новых: {new_count}"
        if relinked_count > 0:
            msg += f", перепривязано перевыставленных: {relinked_count}"
        msg += f", всего в базе: {len(profile_data)}"
        logger.info(msg)
        return new_count, len(profile_data)

    def mark_item_status(self, username_or_url: str, item_id: str, status: str, error: str = None, my_item_url: str = None, my_item_id: str = None):
        """Обновляет статус конкретного товара и опционально привязывает ссылку на опубликованный товар."""
        username = self._clean_username(username_or_url)
        item_id = str(item_id)
        profile_data = self.load_profile(username)

        if item_id in profile_data:
            profile_data[item_id]["status"] = status
            if status == "published":
                profile_data[item_id]["published_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                profile_data[item_id]["error"] = None
                if my_item_url:
                    profile_data[item_id]["my_item_url"] = my_item_url
                if my_item_id:
                    profile_data[item_id]["my_item_id"] = my_item_id
            elif status == "failed":
                profile_data[item_id]["error"] = str(error) if error else "Неизвестная ошибка"
            elif status == "skipped":
                profile_data[item_id]["error"] = str(error) if error else "Пропущено"

            self.save_profile(username, profile_data)

    def update_item_mapping(self, username_or_url: str, item_id: str, my_item_url: str, my_item_id: str = None):
        """Привязывает ссылку и ID товара в личном кабинете к товару донора."""
        username = self._clean_username(username_or_url)
        item_id = str(item_id)
        profile_data = self.load_profile(username)

        if item_id in profile_data:
            profile_data[item_id]["my_item_url"] = my_item_url
            if my_item_id:
                profile_data[item_id]["my_item_id"] = str(my_item_id)
            self.save_profile(username, profile_data)

    def mark_donor_sold(self, username_or_url: str, item_id: str):
        """Помечает товар донора как проданный или удаленный."""
        username = self._clean_username(username_or_url)
        item_id = str(item_id)
        profile_data = self.load_profile(username)

        if item_id in profile_data:
            profile_data[item_id]["donor_state"] = "sold_or_deleted"
            self.save_profile(username, profile_data)

    def mark_donor_active(self, username_or_url: str, item_id: str):
        """Помечает товар донора как активный."""
        username = self._clean_username(username_or_url)
        item_id = str(item_id)
        profile_data = self.load_profile(username)

        if item_id in profile_data:
            profile_data[item_id]["donor_state"] = "active"
            self.save_profile(username, profile_data)

    def relink_donor_item(self, username_or_url: str, old_id: str, new_item_data: dict):
        """Перепривязывает товар к новому ID и ссылке донора (при перевыставлении продавцом)."""
        username = self._clean_username(username_or_url)
        old_id = str(old_id)
        new_id = str(new_item_data.get("item_id"))
        profile_data = self.load_profile(username)

        if old_id in profile_data:
            entry = profile_data.pop(old_id)
            entry["item_id"] = new_id
            entry["url"] = new_item_data.get("url", entry.get("url", ""))
            new_title = new_item_data.get("title", "")
            if new_title and new_title.lower() not in ("резерв", "продано", "бронь"):
                entry["title"] = new_title
            entry["donor_state"] = "active"
            profile_data[new_id] = entry
            self.save_profile(username, profile_data)
            logger.info(f"🔄 Товар профиля '{username}' перепривязан со старого ID #{old_id} на новый актуальный ID #{new_id} ({entry['url']})")

    def get_items_by_status(self, username_or_url: str, status: str = "pending", limit: int = None) -> list[dict]:
        """Возвращает список товаров с указанным статусом."""
        username = self._clean_username(username_or_url)
        profile_data = self.load_profile(username)
        items = [item for item in profile_data.values() if item.get("status") == status]
        if limit and limit > 0:
            return items[:limit]
        return items

    def get_stats(self, username_or_url: str) -> dict:
        """Возвращает статистику по статусам товаров в профиле."""
        username = self._clean_username(username_or_url)
        profile_data = self.load_profile(username)
        
        stats = {
            "total": len(profile_data),
            "pending": 0,
            "published": 0,
            "skipped": 0,
            "failed": 0,
            "donor_sold": 0
        }
        for item in profile_data.values():
            s = item.get("status", "pending")
            if s in stats:
                stats[s] += 1
            else:
                stats["pending"] += 1
                
            if item.get("donor_state") == "sold_or_deleted":
                stats["donor_sold"] += 1
        return stats

    def _normalize_title(self, title: str) -> str:
        """Нормализует заголовок для сравнения."""
        return normalize_title(title)

    def _normalize_slug(self, url_or_slug: str) -> str:
        """Извлекает и нормализует слаг из URL товара."""
        return normalize_slug(url_or_slug)

    def reconcile_listings(self, username_or_url: str, target_listings: list[dict]) -> int:
        """
        Сверяет товары источника с уже опубликованными на целевом аккаунте по слагам URL и названиям.
        Помечает найденные товары как 'published' и сохраняет ссылку на объявление пользователя.
        """
        username = self._clean_username(username_or_url)
        profile_data = self.load_profile(username)
        if not profile_data or not target_listings:
            return 0

        # Индексируем объявления с целевого аккаунта
        target_map_by_slug = {}
        target_map_by_title = {}
        
        for item in target_listings:
            slug = item.get("slug") or item.get("url", "")
            norm_slug = self._normalize_slug(slug)
            if norm_slug and len(norm_slug) > 3:
                target_map_by_slug[norm_slug] = item

            title = item.get("title", "")
            norm_title = self._normalize_title(title)
            if norm_title and len(norm_title) > 3:
                target_map_by_title[norm_title] = item

        matched_count = 0
        for item_id, item in profile_data.items():
            source_slug = self._normalize_slug(item.get("url", ""))
            source_title = self._normalize_title(item.get("title", ""))

            matched_target_item = None
            if source_slug and source_slug in target_map_by_slug:
                matched_target_item = target_map_by_slug[source_slug]
            elif source_title and source_title in target_map_by_title:
                matched_target_item = target_map_by_title[source_title]
            else:
                for target_slug, target_item in target_map_by_slug.items():
                    if len(target_slug) > 10 and (target_slug in source_slug or source_slug in target_slug):
                        matched_target_item = target_item
                        break

            if matched_target_item:
                is_new_match = item.get("status") != "published" or not item.get("my_item_url")
                item["status"] = "published"
                if not item.get("published_at"):
                    item["published_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (автосверка)"
                item["my_item_url"] = matched_target_item.get("url")
                item["my_item_id"] = str(matched_target_item.get("item_id", ""))
                item["error"] = None
                if is_new_match:
                    matched_count += 1

        if matched_count > 0:
            self.save_profile(username, profile_data)
            logger.info(f"Автосверка для '{username}': сопоставлено и привязано товаров: {matched_count} шт.")

        return matched_count
