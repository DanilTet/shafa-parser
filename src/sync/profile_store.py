import os
import json
import re
from datetime import datetime
from src.config import SYNC_PROFILES_DIR
from src.utils.logger import logger

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

        for item in scanned_items:
            item_id = str(item.get("item_id"))
            if not item_id:
                continue

            if item_id not in profile_data:
                profile_data[item_id] = {
                    "item_id": item_id,
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "price": str(item.get("price", "")),
                    "status": "pending",  # pending | published | skipped | failed
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

        self.save_profile(username, profile_data)
        logger.info(f"Профиль '{username}': добавлено новых товаров: {new_count}, всего в базе: {len(profile_data)}")
        return new_count, len(profile_data)

    def mark_item_status(self, username_or_url: str, item_id: str, status: str, error: str = None):
        """Обновляет статус конкретного товара."""
        username = self._clean_username(username_or_url)
        item_id = str(item_id)
        profile_data = self.load_profile(username)

        if item_id in profile_data:
            profile_data[item_id]["status"] = status
            if status == "published":
                profile_data[item_id]["published_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                profile_data[item_id]["error"] = None
            elif status == "failed":
                profile_data[item_id]["error"] = str(error) if error else "Неизвестная ошибка"
            elif status == "skipped":
                profile_data[item_id]["error"] = str(error) if error else "Пропущено"

            self.save_profile(username, profile_data)

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
            "failed": 0
        }
        for item in profile_data.values():
            s = item.get("status", "pending")
            if s in stats:
                stats[s] += 1
            else:
                stats["pending"] += 1
        return stats

    def _normalize_title(self, title: str) -> str:
        """Нормализует заголовок для сравнения."""
        cleaned = re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]', '', str(title).lower())
        return cleaned

    def _normalize_slug(self, url_or_slug: str) -> str:
        """Извлекает и нормализует слаг из URL товара."""
        m = re.search(r'/\d+-([a-zA-Z0-9_-]+)', str(url_or_slug))
        slug = m.group(1) if m else str(url_or_slug)
        return re.sub(r'[^a-z0-9]', '', slug.lower())

    def reconcile_listings(self, username_or_url: str, target_listings: list[dict]) -> int:
        """
        Сверяет товары источника с уже опубликованными на целевом аккаунте по слагам URL и названиям.
        Помечает найденные товары как 'published'.
        """
        username = self._clean_username(username_or_url)
        profile_data = self.load_profile(username)
        if not profile_data or not target_listings:
            return 0

        # Собираем нормализованные слаги и заголовки с целевого аккаунта
        target_slugs = set()
        target_titles = set()
        for item in target_listings:
            slug = item.get("slug") or item.get("url", "")
            norm_slug = self._normalize_slug(slug)
            if norm_slug and len(norm_slug) > 3:
                target_slugs.add(norm_slug)

            title = item.get("title", "")
            norm_title = self._normalize_title(title)
            if norm_title and len(norm_title) > 3:
                target_titles.add(norm_title)

        matched_count = 0
        for item_id, item in profile_data.items():
            if item.get("status") == "pending":
                source_slug = self._normalize_slug(item.get("url", ""))
                source_title = self._normalize_title(item.get("title", ""))

                is_match = False
                if source_slug and source_slug in target_slugs:
                    is_match = True
                elif source_title and source_title in target_titles:
                    is_match = True
                elif any(len(s) > 10 and (s in source_slug or source_slug in s) for s in target_slugs):
                    is_match = True

                if is_match:
                    item["status"] = "published"
                    item["published_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (автосверка)"
                    item["error"] = None
                    matched_count += 1

        if matched_count > 0:
            self.save_profile(username, profile_data)
            logger.info(f"Автосверка для '{username}': автоматически помечено как перенесенные: {matched_count} шт.")

        return matched_count
