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
        Сверхбыстро сканирует все активные объявления из каталога продавца через JS DOM-инжекцию.
        """
        username = self.extract_username(url_or_username)
        if not username:
            raise ValueError(f"Не удалось определить имя пользователя из: {url_or_username}")

        logger.info(f"⚡ Запуск сверхбыстрого сканирования профиля '{username}'...")
        current_tab = driver.current_window_handle
        driver.execute_script("window.open('about:blank', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])

        all_items = []
        try:
            url = f"https://shafa.ua/uk/member/{username}"
            logger.info(f"Загрузка каталога: {url}")
            driver.get(url)
            time.sleep(2.5)

            js_extract = """
            const results = [];
            const seen = new Set();
            const links = document.querySelectorAll('a');
            
            for (const a of links) {
                const href = a.href;
                if (!href || href.includes('/member/') || href.includes('/help/') || href.includes('/about')) continue;
                
                const match = href.match(/\\/(\\d+)-([a-zA-Z0-9_-]+)/);
                if (match) {
                    const id = match[1];
                    const slug = match[2];
                    if (!seen.has(id)) {
                        seen.add(id);
                        const title = a.innerText.trim().split('\\n')[0] || slug.replace(/-/g, ' ');
                        results.push({ item_id: id, url: href, title: title, price: "" });
                    }
                }
            }
            return results;
            """

            consecutive_no_new = 0
            last_count = 0
            max_scrolls = 80

            for step in range(1, max_scrolls + 1):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.4)

                items = driver.execute_script(js_extract)
                count = len(items) if items else 0
                all_items = items if items else all_items

                if progress_callback:
                    progress_callback(count, step)

                if count > last_count:
                    consecutive_no_new = 0
                    last_count = count
                    if step % 5 == 0:
                        logger.info(f"Шаг {step}: собрано {count} товаров...")
                else:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 4:
                        break

        finally:
            try:
                driver.close()
            except:
                pass
            driver.switch_to.window(current_tab)

        logger.info(f"✅ Сканирование завершено: успешно найдено {len(all_items)} товаров продавца '{username}'.")
        return all_items

    def scan_target_account_listings(self, driver) -> list[dict]:
        """
        Считывает список объявлений (URL, слагов и названий) из личного кабинета
        (https://shafa.ua/my/clothes) для автосверки.
        """
        logger.info("Сканирование личного кабинета для автосверки...")
        target_items = []
        current_tab = driver.current_window_handle

        driver.execute_script("window.open('https://shafa.ua/my/clothes', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(3)

        try:
            js_extract = """
            const items = [];
            const seen = new Set();
            const links = document.querySelectorAll("a[href*='-']");
            
            for (const a of links) {
                const href = a.href;
                if (!href || href.includes('/dynamic-') || href.includes('/page/') || href.includes('/help')) continue;
                const match = href.match(/\\/(\\d+)-([a-zA-Z0-9_-]+)/);
                if (match) {
                    const id = match[1];
                    const slug = match[2];
                    if (!seen.has(id)) {
                        seen.add(id);
                        const title = a.innerText.trim().split('\\n')[0] || slug.replace(/-/g, ' ');
                        items.push({ item_id: id, url: href, slug: slug, title: title });
                    }
                }
            }
            return items;
            """

            consecutive_no_new = 0
            last_count = 0

            for step in range(1, 30):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)

                items = driver.execute_script(js_extract)
                count = len(items) if items else 0
                target_items = items if items else target_items

                if count > last_count:
                    consecutive_no_new = 0
                    last_count = count
                else:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
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
