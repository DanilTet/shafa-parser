import time
import pyperclip
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

from src.models import Product
from src.config import CHROME_PROFILE_PATH
from src.utils.logger import logger

class ShafaPoster:
    def __init__(self):
        logger.info("Запуск браузера для публикации...")
        options = Options()
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.wait = WebDriverWait(self.driver, 15)

    def publish(self, product: Product, image_paths: list):
        logger.info("Переход на страницу создания объявления...")
        self.driver.get("https://shafa.ua/uk/new")

        self._upload_photos(image_paths)
        
        # 1. Базовый текст (БЕЗ ЦЕНЫ)
        self._fill_basic_text_fields(product)
        
        # 2. Основные выпадающие списки
        self._fill_category(product)
        self._fill_condition(product)
        self._fill_brand(product)
        
        # 3. Размеры и цвета
        self._fill_size(product)
        self._fill_color(product)
        
        # 4. Доп. характеристики (здесь сайт перерисовывает форму)
        self._fill_additional_characteristics(product)
        
        # 5. ЦЕНА ВВОДИТСЯ В САМОМ КОНЦЕ
        self._fill_price(product)
        
        logger.info("=== ВСЕ ДОСТУПНЫЕ ПОЛЯ ЗАПОЛНЕНЫ ===")

    def _safe_input(self, element, text):
        """Универсальная функция ввода, которая не ломает React."""
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.2)
        try:
            element.click()
        except:
            self.driver.execute_script("arguments[0].click();", element)
        time.sleep(0.2)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.BACKSPACE)
        time.sleep(0.2)
        element.send_keys(str(text))
        time.sleep(0.5)

    def _close_popup(self):
        """Жесткое закрытие ИИ-всплывашки Шафы."""
        logger.info("Ожидание и закрытие всплывающего окна ИИ...")
        time.sleep(2) 
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
            time.sleep(0.5)
            body.send_keys(Keys.ESCAPE)
        except:
            pass

    def _upload_photos(self, image_paths: list):
        if not image_paths:
            return
        logger.info("Загрузка фотографий...")
        try:
            upload_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')))
            paths_string = "\n".join(image_paths)
            upload_input.send_keys(paths_string)
            logger.info("Ожидание 10 секунд для рендера изображений сервером Шафы...")
            time.sleep(10) 
        except Exception as e:
            logger.error(f"Ошибка при загрузке фото: {e}")

    def _fill_basic_text_fields(self, product: Product):
        logger.info("Заполнение названия и описания...")
        try:
            # Название
            title_field = self.wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@name='titleUk']")))
            self._safe_input(title_field, product.title)
            logger.info("Название вставлено.")

            self._close_popup()

            # Описание
            if product.description:
                desc_field = self.wait.until(EC.visibility_of_element_located((By.TAG_NAME, "textarea")))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", desc_field)
                pyperclip.copy(product.description)
                time.sleep(0.2)
                desc_field.click()
                desc_field.send_keys(Keys.CONTROL, 'v')
                time.sleep(0.5)
                logger.info("Описание вставлено через буфер обмена.")

        except Exception as e:
            logger.error(f"Ошибка при заполнении базовых полей: {e}")

    def _fill_category(self, product: Product):
        target_categories = product.characteristics.get('категорії:', [])
        if not target_categories:
            return
        target_category = target_categories[0]
        logger.info(f"Ожидание рекомендаций для категории: {target_category}...")
        try:
            time.sleep(2)
            category_btn_xpath = f"//button[contains(., '{target_category}')]"
            category_btn = self.wait.until(EC.visibility_of_element_located((By.XPATH, category_btn_xpath)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", category_btn)
            category_btn.click()
            logger.info(f"Категория '{target_category}' успешно выбрана.")
        except:
            logger.warning(f"Категория '{target_category}' не найдена. Оберіть вручну.")

    def _fill_condition(self, product: Product):
        if not product.condition:
            return
        logger.info(f"Выбор состояния: {product.condition}...")
        try:
            xpath = f"//button[normalize-space(text())='{product.condition}']"
            condition_btn = self.wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", condition_btn)
            condition_btn.click()
            logger.info("Состояние успешно выбрано.")
        except Exception as e:
            logger.error(f"Не удалось выбрать состояние '{product.condition}': {e}")

    def _fill_brand(self, product: Product):
        if not product.brand:
            return
        logger.info(f"Выбор бренда: {product.brand}...")
        try:
            brand_xpath = "//*[text()='Бренд']/following::input[@role='combobox'][1]"
            brand_input = self.wait.until(EC.visibility_of_element_located((By.XPATH, brand_xpath)))
            self._safe_input(brand_input, product.brand)
            dropdown = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='menu']")))
            for option in dropdown.find_elements(By.XPATH, ".//div"):
                if option.text.strip().lower() == product.brand.lower():
                    option.click()
                    logger.info(f"Бренд '{product.brand}' успешно выбран.")
                    break
        except Exception as e:
            logger.error(f"Ошибка при выборе бренда: {e}")

    def _fill_size(self, product: Product):
        target_sizes = product.characteristics.get('розмір:', [])
        if not target_sizes:
            return
        target_size = target_sizes[0]
        logger.info(f"Поиск размера: {target_size}...")
        try:
            tabs_to_check = ["Міжнародний", "Європейський", "🇺🇦 Український", "Виробника"]
            size_btn_xpath = f"//button[.//p[normalize-space(text())='{target_size}']]"
            for tab_name in tabs_to_check:
                try:
                    tab_btn = self.driver.find_element(By.XPATH, f"//button[contains(., '{tab_name}')]")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab_btn)
                    tab_btn.click()
                    time.sleep(1)
                    size_btn = self.driver.find_element(By.XPATH, size_btn_xpath)
                    if size_btn.is_displayed():
                        size_btn.click()
                        logger.info(f"Размер '{target_size}' выбран (вкладка '{tab_name}').")
                        return
                except:
                    continue
        except Exception as e:
            logger.error(f"Ошибка при выборе размера: {e}")

    def _fill_color(self, product: Product):
        colors = product.characteristics.get('колір:', [])
        if not colors:
            return
        for color in colors:
            logger.info(f"Поиск цвета: {color}...")
            try:
                color_xpath = f"//button[.//span[normalize-space(text())='{color}']]"
                color_btn = self.driver.find_element(By.XPATH, color_xpath)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", color_btn)
                time.sleep(0.3)
                self.driver.execute_script("arguments[0].click();", color_btn)
                logger.info(f"Цвет '{color}' успешно выбран.")
            except Exception as e:
                logger.warning(f"Не удалось найти цвет '{color}'.")

    def _fill_additional_characteristics(self, product: Product):
        logger.info("Заполнение дополнительных характеристик...")
        ignore_keys = ["категорії:", "розмір:", "колір:", "стан"]
        
        # СЕТ-ПАМЯТЬ: Сюда записываем то, что уже заполнили
        processed_keys = set() 
        
        # Даем ИИ Шафы 3 секунды, чтобы он закончил свою авто-расстановку галочек
        time.sleep(3)
        
        try:
            labels = self.driver.find_elements(By.XPATH, "//form//section//li/div/p[1]")
            for label_el in labels:
                try:
                    full_text = label_el.text.strip()
                    if not full_text:
                        continue
                        
                    clean_key = full_text.split('(')[0].replace('\xa0', ' ').strip().lower().replace(" ", "_")
                    
                    if clean_key in ignore_keys or clean_key not in product.characteristics or clean_key in processed_keys:
                        continue
                        
                    values_to_select = product.characteristics[clean_key]
                    if not values_to_select:
                        continue
                        
                    parent_div = label_el.find_element(By.XPATH, "..")
                    success = False 
                    
                    # === 1. ОБРАБОТКА КНОПОК (Стиль, Крой, Сезон) ===
                    buttons = parent_div.find_elements(By.XPATH, ".//ul/li/button")
                    if buttons:
                        # Вычисляем длину базового (невыделенного) класса
                        btn_classes = [b.get_attribute("class") or "" for b in buttons]
                        base_class_len = min([len(c) for c in btn_classes]) if btn_classes else 0
                        
                        for btn in buttons:
                            btn_text = btn.text.strip() or btn.get_attribute("textContent").strip()
                            if btn_text in values_to_select:
                                btn_class = btn.get_attribute("class") or ""
                                
                                # Если класс длиннее базового, значит кнопка уже нажата встроенным ИИ
                                if len(btn_class) > base_class_len + 2:
                                    logger.info(f"✅ ИИ Шафы уже выбрал [{clean_key}]: {btn_text}. Пропускаем клик.")
                                else:
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                    time.sleep(0.3)
                                    self.driver.execute_script("arguments[0].click();", btn)
                                    logger.info(f"🔘 Бот выбрал [{clean_key}]: {btn_text}")
                                success = True
                                
                    # === 2. ОБРАБОТКА ПОЛЕЙ ВВОДА (Материал, Принт) ===
                    combobox = parent_div.find_elements(By.XPATH, ".//input[@role='combobox']")
                    if combobox:
                        # Проверяем, не вписал ли ИИ Шафы уже это значение (ищем текст внутри всего блока)
                        if values_to_select[0].lower() in parent_div.text.lower():
                            logger.info(f"✅ ИИ Шафы уже вписал [{clean_key}]: {values_to_select[0]}. Пропускаем ввод.")
                            success = True
                        else:
                            combo_input = combobox[0]
                            self._safe_input(combo_input, values_to_select[0])
                            time.sleep(1)
                            dropdown = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='menu']")))
                            for option in dropdown.find_elements(By.XPATH, ".//div"):
                                if option.text.strip().lower() == values_to_select[0].lower():
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                    option.click()
                                    logger.info(f"🔘 Бот вписал [{clean_key}]: {values_to_select[0]}")
                                    success = True
                                    break

                    if success:
                        processed_keys.add(clean_key)

                except Exception as inner_e:
                    logger.warning(f"Не удалось заполнить {clean_key}. Возможно, элемент перекрыт.")
                    continue
        except Exception as e:
            logger.error(f"Ошибка сканирования характеристик: {e}")

    def _fill_price(self, product: Product):
        """Ввод цены в самом конце, чтобы сайт не сбрасывал значение."""
        if not product.price:
            return
        
        logger.info("Заполнение цены (финальный этап)...")
        try:
            price_field = self.wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@name='price']")))
            self._safe_input(price_field, product.price)
            
            # Нажимаем TAB, чтобы снять фокус с поля и зафиксировать цену в React
            price_field.send_keys(Keys.TAB)
            time.sleep(0.5)
            logger.info("Цена надежно вставлена и зафиксирована.")
        except Exception as e:
            logger.error(f"Ошибка при заполнении цены: {e}")

    def close(self):
        self.driver.quit()