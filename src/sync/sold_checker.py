import difflib
import time
import re
from datetime import datetime
from src.sync.profile_store import ProfileStore
from src.scraper.profile_scanner import ProfileScanner
from src.utils.logger import logger
from src.sync.matching_utils import (
    GARMENT_TYPES,
    STOP_WORDS,
    detect_garment_type,
    extract_item_sizes,
    check_price_proximity,
    normalize_slug,
    normalize_title,
    is_relisted_match
)


class SoldChecker:
    def __init__(self, profile_store: ProfileStore = None, profile_scanner: ProfileScanner = None):
        self.profile_store = profile_store or ProfileStore()
        self.profile_scanner = profile_scanner or ProfileScanner()

    def find_relisted_donor_item(self, tracked_item: dict, live_donor_items: list[dict], claimed_ids: set = None) -> dict | None:
        """
        Проверяет, не перевыставил ли донор этот товар под новым ID/ссылкой.
        Использует многофакторный каскад (категория, размер, цена, слаг, заголовок).
        Выбирает наилучшего подходящего кандидата и гарантирует 1-к-1 сопоставление.
        """
        claimed = claimed_ids or set()
        best_match = None
        best_score = 0.0

        for live_item in live_donor_items:
            live_id = str(live_item.get("item_id", ""))
            if not live_id or live_id in claimed:
                continue

            matched, score, reason = is_relisted_match(tracked_item, live_item)
            if matched and score > best_score:
                best_score = score
                best_match = live_item

        return best_match

    def audit_donor_profile(self, donor_username: str, driver, progress_callback=None) -> list[dict]:
        """
        Выполняет полный аудит одного донора:
        1. Загружает локальную базу перенесенных товаров.
        2. Сканирует витрину донора, чтобы узнать, какие товары активны сейчас.
        3. Находит товары, которые числились как 'published', но исчезли из каталога донора.
        4. Сканирует личный кабинет пользователя (/my/clothes).
        5. Сопоставляет исчезнувшие товары с объявлениями в личном кабинете пользователя.
        6. Возвращает список проданных у донора товаров с привязанными ссылками на товары пользователя.
        """
        username = self.profile_store._clean_username(donor_username)
        profile_data = self.profile_store.load_profile(username)
        
        if not profile_data:
            logger.warning(f"База профиля '{username}' пуста или не найдена.")
            return []

        # Находим все товары, которые мы когда-либо переносили (status == 'published')
        tracked_items = [item for item in profile_data.values() if item.get("status") == "published"]
        if not tracked_items:
            logger.info(f"В профиле '{username}' нет перенесенных (published) товаров для проверки.")
            return []

        if progress_callback:
            progress_callback(f"Сканирование каталога донора '{username}'...", 0.1)

        # Сканируем актуальный каталог донора
        live_donor_items = self.profile_scanner.scan_profile_items(username, driver)
        live_donor_ids = {str(item.get("item_id")) for item in live_donor_items if item.get("item_id")}

        # ЗАЩИТА: Если каталог донора не загрузился (0 товаров)
        if len(live_donor_ids) == 0 and len(tracked_items) > 0:
            logger.error(f"❌ Каталог донора '{username}' не загрузился (найдено 0 товаров на сайте). Проверьте интернет/страницу. Аудит безопасно остановлен.")
            if progress_callback:
                progress_callback("Ошибка: страница донора не загрузилась. Аудит отменен.", 1.0)
            return []

        if len(live_donor_ids) < len(tracked_items) * 0.15 and len(tracked_items) > 30:
            logger.error(f"⚠️ Каталог донора '{username}' загрузился не полностью ({len(live_donor_ids)} из {len(tracked_items)}). Аудит отменен для безопасности.")
            if progress_callback:
                progress_callback("Ошибка: каталог загружен не полностью. Повторите попытку.", 1.0)
            return []

        logger.info(f"Донор '{username}': активных товаров на сайте: {len(live_donor_ids)}, в нашей базе перенесено: {len(tracked_items)}")

        # Выявляем пропавшие у донора позиции с автоматической проверкой перевыставлений (1-к-1)
        missing_donor_items = []
        relisted_count = 0
        claimed_relisted_ids = set()

        for item in tracked_items:
            item_id = str(item.get("item_id"))
            if item_id not in live_donor_ids:
                relisted_item = self.find_relisted_donor_item(item, live_donor_items, claimed_ids=claimed_relisted_ids)
                if relisted_item:
                    relisted_count += 1
                    relisted_id = str(relisted_item.get("item_id"))
                    claimed_relisted_ids.add(relisted_id)
                    logger.info(f"🔄 Товар #{item_id} перевыставлен донором под новым ID #{relisted_id} ({relisted_item['url']}). Товар активен!")
                    self.profile_store.relink_donor_item(username, item_id, relisted_item)
                else:
                    missing_donor_items.append(item)
                    self.profile_store.mark_donor_sold(username, item_id)
            else:
                self.profile_store.mark_donor_active(username, item_id)

        if relisted_count > 0:
            logger.info(f"✨ Распознано и автоматически обновлено перевыставленных донором товаров: {relisted_count} шт.")

        if not missing_donor_items:
            logger.info(f"🎉 У донора '{username}' все перенесенные товары ({len(tracked_items)} шт.) по-прежнему активны (включая {relisted_count} перевыставленных)!")
            if progress_callback:
                progress_callback(f"Все товары донора '{username}' активны (перевыставлено: {relisted_count}). Проданных не найдено.", 1.0)
            return []

        logger.info(f"⚠️ Обнаружено {len(missing_donor_items)} товаров донора, которые проданы или удалены!")

        if progress_callback:
            progress_callback(f"Найдено {len(missing_donor_items)} пропавших у донора. Сканирование вашего кабинета...", 0.5)

        # Сканируем личный кабинет пользователя
        user_listings = self.profile_scanner.scan_target_account_listings(driver)
        logger.info(f"Личный кабинет пользователя: обнаружено {len(user_listings)} активных объявлений.")

        # ЗАЩИТА: Если кабинет не загрузился (0 объявлений), но есть пропавшие товары —
        # это почти наверняка сбой загрузки страницы, а не реально пустой кабинет.
        # Останавливаем аудит, чтобы не создавать ложные результаты "не найден у вас".
        if len(user_listings) == 0 and len(missing_donor_items) > 0:
            logger.error(
                f"❌ Личный кабинет вернул 0 объявлений при {len(missing_donor_items)} пропавших товарах донора. "
                f"Возможно, страница /my/clothes не загрузилась или требует входа. "
                f"Аудит безопасно остановлен — повторите попытку."
            )
            if progress_callback:
                progress_callback(
                    "Ошибка: кабинет вернул 0 объявлений. Проверьте авторизацию и повторите аудит.", 1.0
                )
            return []

        if progress_callback:
            progress_callback("Сопоставление объявлений...", 0.8)

        # Сопоставляем пропавшие товары донора с товарами пользователя
        results = self.match_missing_items(username, missing_donor_items, user_listings)

        if progress_callback:
            progress_callback(f"Аудит завершен: {len(results)} проданных позиций требуют внимания.", 1.0)

        return results

    def audit_all_saved_profiles(self, driver, progress_callback=None) -> list[dict]:
        """Проводит аудит всех сохраненных профилей доноров."""
        saved_profiles = self.profile_store.get_saved_profiles()
        if not saved_profiles:
            logger.warning("Нет сохраненных профилей для аудита.")
            return []

        all_results = []
        total_profiles = len(saved_profiles)

        for idx, username in enumerate(saved_profiles, 1):
            if progress_callback:
                progress_callback(f"Проверка профиля {idx}/{total_profiles}: '{username}'...", (idx - 1) / total_profiles)
            
            res = self.audit_donor_profile(username, driver)
            all_results.extend(res)

        if progress_callback:
            progress_callback(f"Аудит всех профилей завершен! Всего найдено {len(all_results)} проданных позиций.", 1.0)

        return all_results

    def match_missing_items(self, donor_username: str, missing_items: list[dict], user_listings: list[dict]) -> list[dict]:
        """
        Сопоставляет пропавшие товары донора с активными объявлениями пользователя
        по сохраненному URL, слагам и названиям (включая нечеткий поиск).
        """
        user_by_id = {str(item.get("item_id")): item for item in user_listings if item.get("item_id")}
        user_by_slug = {}
        user_by_title = {}

        for item in user_listings:
            slug = item.get("slug") or item.get("url", "")
            norm_slug = self.profile_store._normalize_slug(slug)
            if norm_slug and len(norm_slug) > 3:
                user_by_slug[norm_slug] = item

            title = item.get("title", "")
            norm_title = self.profile_store._normalize_title(title)
            if norm_title and len(norm_title) > 3:
                user_by_title[norm_title] = item

        results = []

        for missing in missing_items:
            donor_id = str(missing.get("item_id"))
            donor_title = missing.get("title", "")
            donor_url = missing.get("url", "")
            donor_price = missing.get("price", "")

            matched_user_item = None
            match_type = "unknown"

            d_type = detect_garment_type(donor_url + " " + donor_title)

            # 1. Проверяем уже сохраненный my_item_id / my_item_url с валидацией категории
            saved_my_id = str(missing.get("my_item_id")) if missing.get("my_item_id") else None
            if saved_my_id and saved_my_id in user_by_id:
                cached_item = user_by_id[saved_my_id]
                u_type = detect_garment_type(cached_item.get("url", "") + " " + cached_item.get("title", ""))
                if not (d_type and u_type and d_type != u_type):
                    matched_user_item = cached_item
                    match_type = "cached_id"

            # 2. Проверяем по точному слагу
            if not matched_user_item:
                d_slug = self.profile_store._normalize_slug(donor_url)
                if d_slug and d_slug in user_by_slug:
                    matched_user_item = user_by_slug[d_slug]
                    match_type = "exact_slug"

            # 3. Проверяем по частичному совпадению слага
            if not matched_user_item and d_slug and len(d_slug) > 10:
                for u_slug, u_item in user_by_slug.items():
                    u_type = detect_garment_type(u_item.get("url", "") + " " + u_item.get("title", ""))
                    if d_type and u_type and d_type != u_type:
                        continue
                    if d_slug in u_slug or u_slug in d_slug:
                        matched_user_item = u_item
                        match_type = "substring_slug"
                        break

            # 4. Проверяем по пересечению характерных слов из слага URL (Латиница: Marks Spencer, Tommy Hilfiger и т.д.)
            if not matched_user_item and donor_url:
                d_slug_raw = re.search(r'/\d+-([a-zA-Z0-9_-]+)', donor_url)
                d_slug_str = d_slug_raw.group(1) if d_slug_raw else donor_url
                d_slug_words = set(re.findall(r'[a-zA-Z0-9]{3,}', d_slug_str.lower())) - STOP_WORDS
                
                best_slug_score = 0.0
                best_slug_item = None
                
                for u_item in user_listings:
                    u_type = detect_garment_type(u_item.get("url", "") + " " + u_item.get("title", ""))
                    if d_type and u_type and d_type != u_type:
                        continue

                    u_slug_str = u_item.get("slug") or u_item.get("url", "")
                    u_slug_words = set(re.findall(r'[a-zA-Z0-9]{3,}', u_slug_str.lower())) - STOP_WORDS
                    if d_slug_words and u_slug_words:
                        common = d_slug_words & u_slug_words
                        if len(common) >= 2:
                            score = len(common) / min(len(d_slug_words), len(u_slug_words))
                            if score > best_slug_score:
                                best_slug_score = score
                                best_slug_item = u_item
                                
                if best_slug_score >= 0.70 and best_slug_item:
                    matched_user_item = best_slug_item
                    match_type = f"slug_words ({int(best_slug_score * 100)}%)"

            # 5. Проверяем по точному названию
            if not matched_user_item:
                d_title = self.profile_store._normalize_title(donor_title)
                if d_title and d_title in user_by_title:
                    u_item = user_by_title[d_title]
                    u_type = detect_garment_type(u_item.get("url", "") + " " + u_item.get("title", ""))
                    if not (d_type and u_type and d_type != u_type):
                        matched_user_item = u_item
                        match_type = "exact_title"

            # 6. Проверяем по нечеткому совпадению заголовка и пересечению слов (Fuzzy & Token matching)
            if not matched_user_item and donor_title:
                d_words = set(re.findall(r'[a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]{3,}', donor_title.lower())) - STOP_WORDS
                d_title_norm = self.profile_store._normalize_title(donor_title)
                
                best_score = 0.0
                best_item = None
                
                for u_item in user_listings:
                    u_type = detect_garment_type(u_item.get("url", "") + " " + u_item.get("title", ""))
                    if d_type and u_type and d_type != u_type:
                        continue

                    u_title_raw = u_item.get("title", "")
                    if not u_title_raw:
                        continue
                    
                    u_words = set(re.findall(r'[a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]{3,}', u_title_raw.lower())) - STOP_WORDS
                    u_title_norm = self.profile_store._normalize_title(u_title_raw)
                    
                    # 1) Схожесть последовательности символов
                    char_ratio = difflib.SequenceMatcher(None, d_title_norm, u_title_norm).ratio()
                    
                    # 2) Пересечение слов (Jaccard / Token overlap)
                    if d_words and u_words:
                        common_words = d_words & u_words
                        token_ratio = len(common_words) / max(len(d_words), len(u_words))
                        donor_coverage = len(common_words) / len(d_words)
                    else:
                        token_ratio = 0.0
                        donor_coverage = 0.0
                        
                    score = max(char_ratio, token_ratio * 0.9, donor_coverage * 0.85)
                    if score > best_score:
                        best_score = score
                        best_item = u_item
                
                if best_score >= 0.70 and best_item:
                    matched_user_item = best_item
                    match_type = f"fuzzy_title ({int(best_score * 100)}%)"

            # Если сопоставление найдено в личном кабинете
            if matched_user_item:
                my_url = matched_user_item.get("url", "")
                my_id = str(matched_user_item.get("item_id", ""))
                my_title = matched_user_item.get("title", "")

                # Сохраняем связку в базу донора для быстрого доступа
                self.profile_store.update_item_mapping(donor_username, donor_id, my_url, my_id)

                results.append({
                    "donor_username": donor_username,
                    "donor_item_id": donor_id,
                    "donor_title": donor_title,
                    "donor_url": donor_url,
                    "donor_price": donor_price,
                    "my_item_id": my_id,
                    "my_item_title": my_title,
                    "my_item_url": my_url,
                    "is_active_on_my_account": True,
                    "match_type": match_type
                })
            else:
                # Если в личном кабинете товар не найден (возможно, уже удален пользователем ранее)
                cached_url = missing.get("my_item_url")
                results.append({
                    "donor_username": donor_username,
                    "donor_item_id": donor_id,
                    "donor_title": donor_title,
                    "donor_url": donor_url,
                    "donor_price": donor_price,
                    "my_item_id": missing.get("my_item_id", ""),
                    "my_item_title": donor_title,
                    "my_item_url": cached_url if cached_url else "",
                    "is_active_on_my_account": False,
                    "match_type": "not_in_cabinet"
                })

        return results
