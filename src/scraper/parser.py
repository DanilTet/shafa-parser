import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.models import Product
from src.config import SAVE_FOLDER
from src.utils.logger import logger

class ShafaParser:
    def __init__(self):
        logger.info("Инициализация браузера Chrome (Selenium)...")
        options = Options()
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        options.add_argument("--start-maximized")
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.driver.maximize_window()
        self.wait = WebDriverWait(self.driver, 10)
        logger.info("Браузер успешно запущен.")

    def parse_item(self, url: str) -> Product:
        logger.info(f"Переход по ссылке: {url}")
        self.driver.get(url)

        logger.info("Поиск основной фотографии товара...")
        main_photo = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "img[class='RugQy_']")))
        main_photo.click()
        logger.info("Фотография успешно открыта в режиме галереи.")

        logger.info("Извлечение названия товара...")
        title_element = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
        title = title_element.text.strip()
        logger.info(f"Найдено название: '{title}'")

        logger.info("Извлечение описания...")
        try:
            read_more_xpath = "//button[contains(text(), 'читати далі')]"
            read_more_btn = self.driver.find_element(By.XPATH, read_more_xpath)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", read_more_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", read_more_btn)
            logger.info("🔘 Нажата кнопка 'читати далі', текст раскрыт полностью.")
            time.sleep(1) 
        except Exception:
            pass

        try:
            description_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "p[class='xWgNd3']")))
            description = description_element.text.strip()
            logger.info("Описание успешно найдено.")
        except Exception:
            description = None
            logger.warning("Описание не найдено на странице.")

        logger.info("Извлечение цены...")
        price_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "p[class='azxZhr']")))
        price_text = price_element.text.strip()
        price = price_text.split()[0]
        logger.info(f"Найдена цена: {price}")

        logger.info("Извлечение состояния товара...")
        try:
            condition_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "p[class='GEL2FC']")))
            condition = condition_element.text.strip()
            logger.info(f"Состояние: {condition}")
        except Exception:
            condition = None
            logger.warning("Состояние не указано.")

        logger.info("Извлечение бренда...")
        try:
            brand_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/brands/']")))
            brand = brand_element.text.strip()
            logger.info(f"Бренд: {brand}")
        except Exception:
            brand = None
            logger.info("Бренд не указан.")

        logger.info("Сбор дополнительных характеристик...")
        characteristics = {}
        try:
            characteristics_blocks = self.driver.find_elements(By.XPATH, '//li[@class="KWwYZP"]')
            for block in characteristics_blocks:
                key_element = block.find_element(By.TAG_NAME, "p")
                key = key_element.text.strip().lower().replace(" ", "_")

                values = [li.text.strip() for li in block.find_elements(By.TAG_NAME, "li") if li.text.strip()]
                if values:
                    characteristics[key] = values
            logger.info(f"Найдено характеристик: {len(characteristics)}")
        except Exception:
            logger.warning("Дополнительные характеристики не найдены.")

        downloaded_images = self._download_gallery_images()

        logger.info("Сбор данных со страницы успешно завершен!")
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

    def _download_gallery_images(self) -> list:
        logger.info("Запуск процесса скачивания фотографий из галереи...")
        index = 1
        downloaded_urls = set()
        local_paths = []

        while True:
            try:
                full_photo = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "img.ril-image-current")))
                photo_url = full_photo.get_attribute("src")

                if photo_url not in downloaded_urls:
                    logger.info(f"Скачивание фото #{index}...")
                    r = requests.get(photo_url)
                    file_path = os.path.join(SAVE_FOLDER, f"photo_{index}.jpg")
                    with open(file_path, "wb") as f:
                        f.write(r.content)
                    
                    logger.info(f"Фото #{index} сохранено: {file_path}")
                    downloaded_urls.add(photo_url)
                    local_paths.append(file_path)
                    index += 1
                else:
                    logger.info("Обнаружен дубликат URL фото. Галерея закончилась.")
                    break

                next_btn = self.driver.find_element(By.CSS_SELECTOR, "button.ril-next-button.ril__navButtons.ril__navButtonNext")
                next_btn.click()
                time.sleep(0.5)

            except Exception:
                logger.info("Больше доступных фотографий нет. Перелистывание завершено.")
                break
                
        logger.info(f"Всего скачано фотографий: {len(local_paths)}")
        return local_paths

    def close(self):
        logger.info("Закрытие сессии браузера...")
        self.driver.quit()
        logger.info("Браузер закрыт.")