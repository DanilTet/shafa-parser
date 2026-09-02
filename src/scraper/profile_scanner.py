import re
import time
from src.utils.logger import logger

class ProfileScanner:
    def __init__(self):
        pass

    @staticmethod
    def extract_username(url_or_username: str) -> str:
        """Извлекает username продавца из URL или сырой строки."""
        raw = url_or_username.strip()
        match = re.search(r'/member/([^/?#]+)', raw)
        if match:
            return match.group(1).lower()
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '', raw).lower()
        return clean

    def scan_profile_items(self, url_or_username: str, driver, progress_callback=None) -> list[dict]:
        """
        Сверхбыстро сканирует все 100% активных объявлений из каталога продавца.
        """
        username = self.extract_username(url_or_username)
        if not username:
            raise ValueError(f"Не удалось определить имя пользователя из: {url_or_username}")

        logger.info(f"⚡ Запуск полного сканирования профиля '{username}'...")
        current_tab = driver.current_window_handle
        driver.execute_script("window.open('about:blank', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])

        all_items = []
        try:
            url = f"https://shafa.ua/uk/member/{username}"
            logger.info(f"Загрузка каталога: {url}")
            driver.get(url)
            time.sleep(3)

            # Определяем целевое количество товаров из шапки профиля
            expected_total = 0
            try:
                js_get_total = r"""
                const m = document.body.innerText.match(/(?:Мої товари|Товари|товари)\s*(\d+)/i);
                return m ? parseInt(m[1]) : 0;
                """
                expected_total = driver.execute_script(js_get_total) or 0
                if expected_total:
                    logger.info(f"Целевое количество объявлений в профиле '{username}': {expected_total} шт.")
            except Exception:
                pass

            js_extract = r"""
            const results = [];
            const seen = new Set();
            const links = document.querySelectorAll('a');
            
            for (const a of links) {
                const href = a.href;
                if (!href || href.includes('/member/') || href.includes('/help/') || href.includes('/about')) continue;
                
                const match = href.match(/\/(\d+)-([a-zA-Z0-9_-]+)/);
                if (match) {
                    const id = match[1];
                    const slug = match[2];
                    if (!seen.has(id)) {
                        seen.add(id);
                        const title = a.innerText.trim().split('\n')[0] || slug.replace(/-/g, ' ');
                        results.push({ item_id: id, url: href, slug: slug, title: title, price: "" });
                    }
                }
            }
            return results;
            """

            # Ожидаем появления первых товаров на странице (до 15 секунд)
            for _ in range(15):
                items = driver.execute_script(js_extract)
                if items and len(items) > 0:
                    all_items = items
                    last_count = len(items)
                    break
                time.sleep(1.0)

            consecutive_no_new = 0
            max_scrolls = 300

            for step in range(1, max_scrolls + 1):
                # Прокручиваем страницу вниз
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.7)

                items = driver.execute_script(js_extract)
                count = len(items) if items else 0
                all_items = items if items else all_items

                if progress_callback:
                    progress_callback(count, step)

                if count > last_count:
                    consecutive_no_new = 0
                    last_count = count
                    if step % 5 == 0 or count == expected_total:
                        logger.info(f"Шаг {step}: собрано {count}/{expected_total or '?'} товаров...")
                elif count > 0:
                    consecutive_no_new += 1
                    # Если собрали все 100% ожидаемых товаров
                    if expected_total and count >= expected_total:
                        logger.info(f"🎉 Собрано 100% объявлений ({count}/{expected_total})!")
                        break
                    # Если 8 прокруток подряд нет новых данных — каталог точно закончился
                    if consecutive_no_new >= 8:
                        break
                else:
                    # Если товары еще не появились, продолжаем ждать
                    time.sleep(0.5)

        finally:
            try:
                driver.close()
            except:
                pass
            driver.switch_to.window(current_tab)

        logger.info(f"✅ Полное сканирование завершено: успешно найдено {len(all_items)} товаров продавца '{username}'.")
        return all_items

    def scan_target_account_listings(self, driver) -> list[dict]:
        """
        Считывает список объявлений (URL, слагов и названий) из личного кабинета
        (https://shafa.ua/my/clothes) для автосверки.

        Улучшения:
        - Активное ожидание появления первого товара (до 20 сек) вместо слепого sleep(3)
        - Проверка редиректа на страницу входа
        - Повторная попытка прокрутки если страница ещё грузится
        """
        logger.info("Сканирование личного кабинета для автосверки...")
        target_items = []
        current_tab = driver.current_window_handle

        driver.execute_script("window.open('https://shafa.ua/my/clothes', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])

        try:
            js_extract = r"""
            const items = [];
            const seen = new Set();
            const links = document.querySelectorAll("a[href*='-']");
            
            for (const a of links) {
                const href = a.href;
                if (!href || href.includes('/dynamic-') || href.includes('/page/') || href.includes('/help') || href.includes('/member/')) continue;
                const match = href.match(/\/(\d+)-([a-zA-Z0-9_-]+)/);
                if (match) {
                    const id = match[1];
                    const slug = match[2];
                    if (!seen.has(id)) {
                        seen.add(id);
                        
                        let title = '';
                        try {
                            const lines = a.innerText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                            for (const line of lines) {
                                if (!line.match(/^\d+[\s]*(?:грн|uah|\$|€)/i) && 
                                    !line.match(/^(?:активно|неактивно|опубліковано|чернетка|деактивовано|резерв|промо|заповнено)/i) && 
                                    !line.match(/заповнено/i) &&
                                    !line.match(/^\d+%/i) &&
                                    line.length > title.length) {
                                    title = line;
                                }
                            }
                        } catch(e) {}
                        if (!title) {
                            title = slug.replace(/-/g, ' ');
                        }
                        items.push({ item_id: id, url: href, slug: slug, title: title });
                    }
                }
            }
            return items;
            """

            # --- Шаг 1: Ждём загрузки страницы и проверяем авторизацию ---
            # Активное ожидание появления первого товара (до 20 секунд)
            logger.info("Ожидание загрузки страницы /my/clothes...")
            loaded = False
            for wait_step in range(20):
                time.sleep(1.0)

                # Проверяем, не произошёл ли редирект на страницу входа
                current_url = driver.current_url.lower()
                if "login" in current_url or "signup" in current_url or "auth" in current_url:
                    logger.error("❌ Страница /my/clothes перенаправила на форму входа — пользователь не авторизован.")
                    return []

                items = driver.execute_script(js_extract)
                count = len(items) if items else 0
                if count > 0:
                    target_items = items
                    logger.info(f"✅ Страница загружена: найдено {count} объявлений (за {wait_step + 1} сек)")
                    loaded = True
                    break

                if wait_step % 5 == 4:
                    logger.info(f"⏳ Ожидание загрузки /my/clothes... ({wait_step + 1}/20 сек)")

            if not loaded:
                logger.warning("⚠️ Страница /my/clothes не показала товаров за 20 секунд. Возможно, кабинет пуст или страница не загрузилась.")
                # Возвращаем пустой список — защита в sold_checker остановит аудит
                return []

            # --- Шаг 2: Прокручиваем страницу, подбирая все товары ---
            consecutive_no_new = 0
            last_count = len(target_items)

            for step in range(1, 100):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.6)

                items = driver.execute_script(js_extract)
                count = len(items) if items else 0
                if items:
                    target_items = items

                if count > last_count:
                    consecutive_no_new = 0
                    last_count = count
                    if step % 10 == 0:
                        logger.info(f"Прокрутка {step}: собрано {count} объявлений...")
                else:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 6:
                        break

            logger.info(f"Личный кабинет: обнаружено {len(target_items)} активных объявлений для сверки.")
        except Exception as e:
            logger.error(f"Ошибка при сканировании личного кабинета: {e}")
        finally:
            try:
                driver.close()
            except:
                pass
            driver.switch_to.window(current_tab)

        return target_items

