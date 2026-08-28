import os
import re
import json
import time
import requests

from src.models import Product
from src.config import SAVE_FOLDER
from src.utils.logger import logger

class ShafaParser:
    """Быстрый парсер карточек товаров Shafa.ua.
    
    1. Основной режим: прямой HTTP-запрос + разбор JSON-состояния Apollo State (0.3-1 сек).
    2. Резервный режим (Fallback): сбор во вкладке уже открытого браузера (fallback_driver).
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def parse_item(self, url: str, fallback_driver=None) -> Product:
        logger.info(f"Сбор данных товара: {url}")
        try:
            return self._parse_via_http(url)
        except Exception as e:
            logger.warning(f"Прямой парсинг через HTTP не удался ({e}).")
            if fallback_driver:
                logger.info("Запуск резервного сбора через вкладку браузера...")
                return self._parse_via_browser(url, fallback_driver)
            else:
                raise

    def _parse_via_http(self, url: str) -> Product:
        resp = self.session.get(url, timeout=12)
        if resp.status_code != 200:
            raise Exception(f"HTTP-статус {resp.status_code}")

        match = re.search(r'window\.__APOLLO_STATE__\s*=\s*({.*?});', resp.text, re.DOTALL)
        if not match:
            raise Exception("Не найден __APOLLO_STATE__ в HTML-коде")

        apollo = json.loads(match.group(1))
        
        # Находим объект ProductDetails
        prod_key = next((k for k in apollo if k.startswith("ProductDetails:")), None)
        if not prod_key:
            raise Exception("ProductDetails не найден в состоянии Apollo")

        prod = apollo[prod_key]
        title = prod.get("name") or prod.get("title") or ""
        description = prod.get("description") or ""
        price = str(prod.get("price") or "")

        # 1. Бренд
        brand_ref = prod.get("brand", {}).get("__ref") if isinstance(prod.get("brand"), dict) else None
        brand = apollo.get(brand_ref, {}).get("name") if brand_ref else ""

        # 2. Состояние
        cond_ref = prod.get("condition", {}).get("__ref") if isinstance(prod.get("condition"), dict) else None
        condition = apollo.get(cond_ref, {}).get("name") if cond_ref else ""

        # 3. Фотографии
        photo_urls = []
        for p in prod.get("photos", []):
            p_ref = p.get("__ref")
            if p_ref and p_ref in apollo:
                p_obj = apollo[p_ref]
                img_url = p_obj.get("originalUrl") or p_obj.get("url") or p_obj.get("thumbnailUrl")
                if img_url:
                    photo_urls.append(img_url)

        # 4. Характеристики
        characteristics = {}

        # Категория
        categories_list = []
        # 1. Проверяем category -> RootCatalog:X (содержит точное имя категории)
        cat_ref = prod.get("category", {}).get("__ref") if isinstance(prod.get("category"), dict) else None
        if cat_ref and cat_ref in apollo:
            cat_obj = apollo[cat_ref]
            if cat_obj.get("name"):
                categories_list.append(cat_obj["name"])
            for b in cat_obj.get("breadcrumbs", []):
                b_ref = b.get("__ref")
                if b_ref and b_ref in apollo and apollo[b_ref].get("name"):
                    b_name = apollo[b_ref]["name"]
                    if b_name not in categories_list:
                        categories_list.append(b_name)

        # 2. Если не нашли, проверяем catalog -> Catalog:X
        if not categories_list:
            catalog_ref = prod.get("catalog", {}).get("__ref") if isinstance(prod.get("catalog"), dict) else None
            if catalog_ref and catalog_ref in apollo:
                cat_id = apollo[catalog_ref].get("id")
                if cat_id:
                    for root_prefix in (f"RootCatalog:{cat_id}", f"CatalogType:{cat_id}"):
                        if root_prefix in apollo and apollo[root_prefix].get("name"):
                            categories_list.append(apollo[root_prefix]["name"])
                            break

        if categories_list:
            characteristics["категорії:"] = categories_list

        # Размеры
        sizes = []
        for s in prod.get("sizes", []):
            s_ref = s.get("__ref")
            if s_ref and s_ref in apollo:
                s_name = apollo[s_ref].get("name")
                if s_name:
                    sizes.append(s_name)
        if sizes:
            characteristics["розмір:"] = sizes

        # Цвета
        colors = []
        for c in prod.get("colors", []):
            c_ref = c.get("__ref")
            if c_ref and c_ref in apollo:
                c_name = apollo[c_ref].get("name")
                if c_name:
                    colors.append(c_name)
        if colors:
            characteristics["колір:"] = colors

        # Дополнительные свойства (материал, фасон, крой, сезон и т.д.)
        for char in prod.get("characteristics", []):
            c_title = char.get("title", "").strip().lower().replace(" ", "_")
            c_vals = []
            for choice in char.get("choices", []):
                ch_ref = choice.get("__ref")
                if ch_ref and ch_ref in apollo:
                    val_name = apollo[ch_ref].get("title") or apollo[ch_ref].get("name")
                    if val_name:
                        c_vals.append(val_name)
            if c_title and c_vals:
                characteristics[c_title] = c_vals

        # Скачивание фотографий
        downloaded_images = self._download_images_by_urls(photo_urls)

        logger.info(f"Товар '{title}' успешно собран (фото: {len(downloaded_images)}).")
        return Product(
            title=title,
            price=price,
            description=description,
            condition=condition,
            brand=brand,
            original_url=url,
            characteristics=characteristics,
            downloaded_images=downloaded_images
        )

    def _download_images_by_urls(self, urls: list) -> list:
        os.makedirs(SAVE_FOLDER, exist_ok=True)
        local_paths = []
        for i, photo_url in enumerate(urls, 1):
            try:
                r = self.session.get(photo_url, timeout=10)
                if r.status_code == 200:
                    file_path = os.path.join(SAVE_FOLDER, f"photo_{i}.jpg")
                    with open(file_path, "wb") as f:
                        f.write(r.content)
                    local_paths.append(file_path)
            except Exception as e:
                logger.error(f"Не удалось скачать фото #{i} ({photo_url}): {e}")
        return local_paths

    def _parse_via_browser(self, url: str, driver) -> Product:
        """Резервный метод сбора во временной вкладке уже открытого браузера."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        current_tab = driver.current_window_handle
        driver.execute_script("window.open(arguments[0], '_blank');", url)
        driver.switch_to.window(driver.window_handles[-1])
        wait = WebDriverWait(driver, 10)

        try:
            # Название
            title_el = wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
            title = title_el.text.strip()

            # Описание
            try:
                read_more = driver.find_element(By.XPATH, "//button[contains(text(), 'читати далі')]")
                driver.execute_script("arguments[0].click();", read_more)
                time.sleep(0.3)
            except:
                pass
            
            try:
                desc_el = driver.find_element(By.CSS_SELECTOR, "p[class='xWgNd3']")
                description = desc_el.text.strip()
            except:
                description = ""

            # Цена
            try:
                price_el = driver.find_element(By.CSS_SELECTOR, "p[class='azxZhr']")
                price = price_el.text.strip().split()[0]
            except:
                price = ""

            # Состояние
            try:
                cond_el = driver.find_element(By.CSS_SELECTOR, "p[class='GEL2FC']")
                condition = cond_el.text.strip()
            except:
                condition = ""

            # Бренд
            try:
                brand_el = driver.find_element(By.CSS_SELECTOR, "a[href*='/brands/']")
                brand = brand_el.text.strip()
            except:
                brand = ""

            # Характеристики
            characteristics = {}
            try:
                blocks = driver.find_elements(By.XPATH, '//li[@class="KWwYZP"]')
                for b in blocks:
                    k = b.find_element(By.TAG_NAME, "p").text.strip().lower().replace(" ", "_")
                    v = [li.text.strip() for li in b.find_elements(By.TAG_NAME, "li") if li.text.strip()]
                    if v:
                        characteristics[k] = v
            except:
                pass

            # Фото через галерею
            downloaded_images = []
            try:
                main_photo = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "img[class='RugQy_']")))
                main_photo.click()
                time.sleep(0.5)

                idx = 1
                downloaded_urls = set()
                while True:
                    try:
                        cur_photo = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "img.ril-image-current")))
                        src = cur_photo.get_attribute("src")
                        if src and src not in downloaded_urls:
                            r = self.session.get(src, timeout=10)
                            fp = os.path.join(SAVE_FOLDER, f"photo_{idx}.jpg")
                            with open(fp, "wb") as f:
                                f.write(r.content)
                            downloaded_urls.add(src)
                            downloaded_images.append(fp)
                            idx += 1
                        else:
                            break
                        next_btn = driver.find_element(By.CSS_SELECTOR, "button.ril-next-button")
                        next_btn.click()
                        time.sleep(0.3)
                    except:
                        break
            except:
                pass

            return Product(
                title=title,
                price=price,
                description=description,
                condition=condition,
                brand=brand,
                original_url=url,
                characteristics=characteristics,
                downloaded_images=downloaded_images
            )
        finally:
            try:
                driver.close()
            except:
                pass
            driver.switch_to.window(current_tab)

    def close(self):
        """Закрытие ресурсов парсера."""
        try:
            self.session.close()
        except:
            pass