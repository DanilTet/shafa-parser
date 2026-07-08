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
        
        # Запуск во весь экран
        options.add_argument("--start-maximized")
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.driver.maximize_window()
        self.wait = WebDriverWait(self.driver, 15)

    def publish(self, product: Product, image_paths: list, deactivate_original: bool = False, auto_publish: bool = False):
        logger.info("Открытие новой вкладки и переход на страницу создания объявления...")
        self.driver.execute_script("window.open('https://shafa.ua/uk/new', '_blank');")
        self.driver.switch_to.window(self.driver.window_handles[-1])

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
        
        # 4. Доп. характеристики
        self._fill_additional_characteristics(product)
        
        # 5. КЛЮЧЕВЫЕ СЛОВА
        self._fill_keywords(product)
        
        # 6. ЦЕНА ВВОДИТСЯ В САМОМ КОНЦЕ
        self._fill_price(product)
        
        logger.info("=== ВСЕ ДОСТУПНЫЕ ПОЛЯ ЗАПОЛНЕНЫ ===")

        # 7. ДЕАКТИВАЦИЯ СТАРОГО ОБЪЯВЛЕНИЯ
        if deactivate_original:
            logger.info("Запуск процесса деактивации старого товара...")
            self.deactivate_original(product.original_url)

        # Нажатие на кнопку подтверждения публикации
        if auto_publish:
            self.confirm_publish()
        else:
            logger.info("Автопубликация отключена. Товар готов к ручной проверке.")

    def _safe_input(self, element, text):
        """Универсальная функция ввода, которая использует буфер обмена для защиты от багов React."""
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
        
        pyperclip.copy(str(text))
        time.sleep(0.1)
        element.send_keys(Keys.CONTROL, "v")
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
            if len(image_paths) > 1:
                image_paths = [image_paths[-1]] + image_paths[:-1]

            upload_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')))
            
            for i, path in enumerate(image_paths, 1):
                upload_input.send_keys(path)
                logger.info(f"Фото {i}/{len(image_paths)} отправлено на server.")
                time.sleep(1.5) 
                
            logger.info("Ожидание рендера всех изображений сервером Шафы...")
            time.sleep(5) 
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке фото: {e}")

    def _fill_basic_text_fields(self, product: Product):
        logger.info("Заполнение названия и описания...")
        try:
            title_field = self.wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@name='titleUk']")))
            self._safe_input(title_field, product.title)
            logger.info("Название вставлено.")

            self._close_popup()

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
            
        for raw_size in target_sizes:
            target_size = raw_size
            
            # --- БЛОК АДАПТАЦИИ СТАРЫХ РАЗМЕРОВ ---
            if "/" in raw_size:
                parts = [p.strip() for p in raw_size.split("/")]
                for part in parts:
                    if any(c.isalpha() for c in part):
                        target_size = part
                        break
                else:
                    target_size = parts[1] if len(parts) >= 3 else parts[0]
                logger.info(f"Обнаружен старый формат '{raw_size}'. Выделен: '{target_size}'")

            logger.info(f"Поиск размера: {target_size}...")
            try:
                tabs_to_check = ["Міжнародний", "Європейський", "🇺🇦 Український", "Виробника"]
                size_btn_xpath = f"//button[.//p[normalize-space(text())='{target_size}']]"
                size_found = False
                
                for tab_name in tabs_to_check:
                    try:
                        tab_btn = self.driver.find_element(By.XPATH, f"//button[contains(., '{tab_name}')]")
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab_btn)
                        tab_btn.click()
                        time.sleep(0.5)
                        
                        size_btn = self.driver.find_element(By.XPATH, size_btn_xpath)
                        if size_btn.is_displayed():
                            # Жёсткий клик через JS, чтобы Selenium не симулировал промах
                            self.driver.execute_script("arguments[0].click();", size_btn)
                            logger.info(f"Размер '{target_size}' выбран (вкладка '{tab_name}').")
                            size_found = True
                            break 
                    except:
                        continue
                        
                if not size_found:
                    logger.warning(f"Размер '{target_size}' не найден ни в одной вкладке.")
            except Exception as e:
                logger.error(f"Ошибка при выборе размера '{target_size}': {e}")

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
        processed_keys = set() 
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
                    
                    # === 1. ОБРАБОТКА КНОПОК ===
                    buttons = parent_div.find_elements(By.XPATH, ".//ul/li/button")
                    if buttons:
                        btn_classes = [b.get_attribute("class") or "" for b in buttons]
                        base_class_len = min([len(c) for c in btn_classes]) if btn_classes else 0
                        
                        for btn in buttons:
                            btn_text = btn.text.strip() or btn.get_attribute("textContent").strip()
                            if btn_text in values_to_select:
                                btn_class = btn.get_attribute("class") or ""
                                if len(btn_class) > base_class_len + 2:
                                    logger.info(f"✅ ИИ Шафы уже выбрал [{clean_key}]: {btn_text}. Пропускаем.")
                                else:
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                    time.sleep(0.3)
                                    self.driver.execute_script("arguments[0].click();", btn)
                                    logger.info(f"🔘 Бот выбрал [{clean_key}]: {btn_text}")
                                success = True
                                
                    # === 2. ОБРАБОТКА ПОЛЕЙ ВВОДА (Материал, Принт и т.д.) ===
                    combobox = parent_div.find_elements(By.XPATH, ".//input[@role='combobox']")
                    if combobox:
                        combo_input = combobox[0]
                        
                        # 2.1 Очистка ошибочных тегов, которые ИИ Шафы мог подставить сам
                        existing_valid_tags = set()
                        try:
                            # Ищем элементы тегов (в них есть <span> с текстом и <div> с <svg> для удаления)
                            existing_tags = parent_div.find_elements(By.XPATH, ".//div[span and .//*[local-name()='svg']]")
                            for tag_el in existing_tags:
                                try:
                                    tag_text = tag_el.find_element(By.TAG_NAME, "span").text.strip()
                                    if tag_text:
                                        # Если этого тега нет в оригинальных характеристиках товара — удаляем
                                        if not any(tag_text.lower() == v.lower() for v in values_to_select):
                                            logger.info(f"🗑️ Удаление ошибочного тега от ИИ: '{tag_text}' в поле [{clean_key}]")
                                            remove_btn = tag_el.find_element(By.XPATH, ".//*[local-name()='svg']/..")
                                            self.driver.execute_script("arguments[0].click();", remove_btn)
                                            time.sleep(0.3)
                                        else:
                                            existing_valid_tags.add(tag_text.lower())
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.warning(f"Ошибка при фильтрации тегов ИИ: {e}")

                        # 2.2 Ввод новых тегов
                        # Цикл по ВСЕМ материалам из списка JSON
                        for val in values_to_select:
                            if val.lower() in existing_valid_tags or val.lower() in parent_div.text.lower():
                                logger.info(f"✅ ИИ Шафы уже вписал [{clean_key}]: {val}. Пропускаем.")
                                success = True
                                continue
                                
                            try:
                                combo_input.click()
                            except:
                                self.driver.execute_script("arguments[0].click();", combo_input)
                            
                            combo_input.send_keys(val)
                            time.sleep(1)
                            
                            try:
                                dropdown = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='menu']")))
                                for option in dropdown.find_elements(By.XPATH, ".//div"):
                                    if option.text.strip().lower() == val.lower():
                                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                                        option.click()
                                        logger.info(f"🔘 Бот вписал [{clean_key}]: {val}")
                                        success = True
                                        break
                            except Exception:
                                logger.warning(f"Dropdown для '{val}' не появился. Пробуем Enter.")
                                combo_input.send_keys(Keys.ENTER)
                                
                            time.sleep(0.5)

                    if success:
                        processed_keys.add(clean_key)

                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Ошибка сканирования характеристик: {e}")

    def _fill_price(self, product: Product):
        if not product.price:
            return
        logger.info("Заполнение цены (финальный этап)...")
        try:
            price_field = self.wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@name='price']")))
            self._safe_input(price_field, product.price)
            price_field.send_keys(Keys.TAB)
            time.sleep(0.5)
            logger.info("Цена надежно вставлена.")
        except Exception as e:
            logger.error(f"Ошибка при заполнении цены: {e}")

    def _fill_keywords(self, product: Product):
        logger.info("Генерация и заполнение ключевых слов...")
        keywords = []
        first_word = product.title.split()[0] if product.title else ""
        if first_word: keywords.append(first_word)
        if product.brand: keywords.append(product.brand)
        if first_word and product.brand: keywords.append(f"{first_word} {product.brand}")
        keywords = list(dict.fromkeys(keywords))

        if not keywords: return

        try:
            # 🟢 ИДЕАЛЬНЫЙ XPATH: Ищем по тексту плейсхолдера, который лежит прямо рядом с input
            keyword_xpath = "//div[text()='Введіть ключові слова']/following-sibling::div//input"
            
            # Срабатывает моментально!
            keyword_input = self.wait.until(EC.presence_of_element_located((By.XPATH, keyword_xpath)))

            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", keyword_input)
            time.sleep(0.5)

            for key in keywords:
                logger.info(f"Ввод ключевого слова: {key}...")
                try:
                    keyword_input.click()
                except:
                    self.driver.execute_script("arguments[0].click();", keyword_input)
                
                keyword_input.send_keys(key)
                time.sleep(1)

                try:
                    dropdown = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='menu']")))
                    options = dropdown.find_elements(By.XPATH, ".//div")
                    selected = False
                    for option in options:
                        if option.text.strip().lower() == key.lower():
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                            option.click()
                            logger.info(f"✅ Выбрано ключевое слово: {option.text.strip()}")
                            selected = True
                            break
                    if not selected:
                        keyword_input.send_keys(Keys.ENTER)
                except Exception:
                    keyword_input.send_keys(Keys.ENTER)
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка при заполнении ключевых слов: {e}")

    def deactivate_original(self, original_url: str):
        if not original_url:
            logger.warning("Нет ссылки на оригинальный товар. Пропуск деактивации.")
            return

        current_tab = self.driver.current_window_handle
        logger.info(f"Переход на старое объявление для деактивации: {original_url}")
        self.driver.execute_script("window.open(arguments[0], '_blank');", original_url)
        self.driver.switch_to.window(self.driver.window_handles[-1])
        time.sleep(3)

        try:
            deactivate_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Деактивувати')]")))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", deactivate_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", deactivate_btn)
            logger.info("✅ Оригинальное объявление успешно деактивировано!")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Не удалось деактивировать товар: {e}")
        finally:
            try:
                self.driver.close()
            except:
                pass
            self.driver.switch_to.window(current_tab)

    def confirm_publish(self):
        """Нажатие на кнопку подтверждения публикации."""
        try:
            confirm_btn_xpath = "//button[@class='vFhB6y vOHxES aVcdmD' and text()='Додати річ']"
            confirm_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, confirm_btn_xpath)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", confirm_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", confirm_btn)
            logger.info("Кнопка подтверждения публикации успешно нажата.")
        except Exception as e:
            logger.error(f"Не удалось нажать кнопку подтверждения: {e}")

    def close(self):
        self.driver.quit()