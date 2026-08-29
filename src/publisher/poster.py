import time
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
from src.utils.display_utils import get_secondary_monitor

class ShafaPoster:
    def __init__(self, use_secondary_monitor: bool = True, hidden_mode: bool = False):
        self.hidden_mode = hidden_mode
        self.use_secondary_monitor = use_secondary_monitor
        logger.info("Запуск браузера для публикации...")
        options = Options()
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        
        target_monitor = None
        if hidden_mode:
            logger.info("🫥 Скрытый режим: браузер запущен в фоне (без отображения на экране).")
            options.add_argument("--window-position=-10000,-10000")
            options.add_argument("--window-size=1280,900")
        elif use_secondary_monitor:
            target_monitor = get_secondary_monitor()
            if target_monitor:
                logger.info(f"🖥️ Обнаружен второй монитор (x={target_monitor['x']}, y={target_monitor['y']}). Открываем браузер на дополнительном экране!")
                options.add_argument(f"--window-position={target_monitor['x']},{target_monitor['y']}")
                options.add_argument(f"--window-size={target_monitor['width']},{target_monitor['height']}")
                options.add_argument("--start-maximized")
            else:
                options.add_argument("--start-maximized")
        else:
            options.add_argument("--start-maximized")
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        if hidden_mode:
            try:
                self.driver.set_window_position(-10000, -10000)
            except Exception:
                pass
        elif target_monitor:
            try:
                self.driver.set_window_position(target_monitor['x'], target_monitor['y'])
                self.driver.maximize_window()
            except Exception:
                pass
        else:
            self.driver.maximize_window()

        self.wait = WebDriverWait(self.driver, 15)
        self._initial_tab_consumed = False

    def reveal_window(self, use_secondary_monitor: bool = True):
        """Мгновенно перемещает и разворачивает скрытый браузер на целевой монитор."""
        logger.info("🪄 Раскрытие окна браузера на экране для проверки объявлений...")
        try:
            target_monitor = None
            if use_secondary_monitor:
                target_monitor = get_secondary_monitor()

            if target_monitor:
                self.driver.set_window_position(target_monitor['x'], target_monitor['y'])
            else:
                self.driver.set_window_position(0, 0)
                
            self.driver.maximize_window()
            
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
                
            logger.info("✅ Браузер успешно отображен на экране!")
        except Exception as e:
            logger.error(f"Не удалось развернуть окно браузера: {e}")

    def is_authorized(self) -> bool:
        """Проверяет, авторизован ли пользователь на Shafa.ua."""
        try:
            logger.info("Проверка статуса авторизации на Shafa.ua...")
            self.driver.get("https://shafa.ua/uk/new")
            time.sleep(2)
            current_url = self.driver.current_url.lower()

            # Если произошел редирект на страницу входа
            if "login" in current_url or "signup" in current_url or "auth" in current_url:
                logger.warning("Сессия отсутствует или истекла (редирект на страницу входа).")
                return False

            # Проверяем, есть ли на странице элементы формы создания объявления или профиля
            form_elements = self.driver.find_elements(
                By.XPATH,
                "//input[@name='titleUk'] | //input[@type='file'] | //a[contains(@href, '/member/')] | //a[contains(@href, '/my/')]"
            )
            if form_elements:
                logger.info("✅ Авторизация подтверждена!")
                return True

            # Дополнительная проверка на наличие кнопки входа
            login_buttons = self.driver.find_elements(
                By.XPATH,
                "//a[contains(@href, '/login')] | //button[contains(., 'Увійти')] | //button[contains(., 'Вхід')]"
            )
            if login_buttons:
                logger.warning("Найдена кнопка входа: пользователь не авторизован.")
                return False

            if "/new" in current_url:
                logger.info("✅ Авторизация подтверждена!")
                return True

            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке авторизации: {e}")
            return False

    def publish(self, product: Product, image_paths: list, deactivate_original: bool = False, auto_publish: bool = False):
        if not self._initial_tab_consumed:
            logger.info("Использование текущей вкладки для создания объявления...")
            if "/new" not in self.driver.current_url.lower():
                self.driver.get("https://shafa.ua/uk/new")
            self._initial_tab_consumed = True
        else:
            logger.info("Открытие новой вкладки для создания следующего объявления...")
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
        """Универсальный и надежный ввод текста напрямую в React-компонент без использования буфера обмена ОС."""
        try:
            js_script = """
            const el = arguments[0];
            const val = arguments[1];
            el.scrollIntoView({block: 'center'});
            
            const isTextarea = el.tagName.toLowerCase() === 'textarea';
            const proto = isTextarea ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            
            nativeSetter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """
            self.driver.execute_script(js_script, element, str(text))
            time.sleep(0.3)
        except Exception:
            try:
                element.clear()
                element.send_keys(str(text))
            except Exception:
                pass

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

    def _wait_for_photos_uploaded(self, expected_count: int, timeout: int = 45):
        """Динамически ожидает полной загрузки и рендера всех фото сервером Шафы."""
        logger.info(f"Ожидание полной обработки всех {expected_count} фото сервером Шафы...")
        start_time = time.time()
        
        js_check = """
        const spinners = document.querySelectorAll(
            "[class*='spinner'], [class*='loading'], [class*='loader'], [class*='progress'], [role='progressbar']"
        );
        const visibleSpinners = Array.from(spinners).filter(s => s.offsetParent !== null);
        
        return {
            has_spinners: visibleSpinners.length > 0
        };
        """
        
        time.sleep(3)
        while time.time() - start_time < timeout:
            try:
                res = self.driver.execute_script(js_check)
                has_spinners = res.get("has_spinners", False) if isinstance(res, dict) else False
                
                if not has_spinners and (time.time() - start_time >= 4):
                    logger.info("✅ Все фотографии успешно загружены и обработаны сервером!")
                    time.sleep(1.5)
                    return True
            except Exception:
                pass
            time.sleep(1)
            
        logger.warning("Таймаут ожидания рендера фото. Продолжаем заполнение...")
        return False

    def _upload_photos(self, image_paths: list):
        if not image_paths:
            return
            
        logger.info(f"Загрузка {len(image_paths)} фотографий...")
        try:
            upload_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')))
            
            for i, path in enumerate(image_paths, 1):
                upload_input.send_keys(path)
                logger.info(f"Фото {i}/{len(image_paths)} отправлено.")
                time.sleep(1.2)
                
            self._wait_for_photos_uploaded(len(image_paths))
            
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
                self._safe_input(desc_field, product.description)
                logger.info("Описание вставлено.")

        except Exception as e:
            logger.error(f"Ошибка при заполнении базовых полей: {e}")

    def _fill_category(self, product: Product):
        target_categories = product.characteristics.get('категорії:', [])
        if not target_categories:
            logger.warning("Категории не указаны в характеристиках товара.")
            return

        logger.info(f"Выбор категории из списка: {target_categories}...")
        time.sleep(2)  # Даем Shafa время подгрузить блок рекомендаций

        for cat_name in target_categories:
            try:
                # Ищем кнопку категории среди рекомендаций и по общему списку
                xpath_candidates = [
                    f"//button[.//p[normalize-space(text())='{cat_name}'] or .//span[normalize-space(text())='{cat_name}'] or normalize-space(text())='{cat_name}']",
                    f"//button[contains(., '{cat_name}')]",
                ]
                for xpath in xpath_candidates:
                    buttons = self.driver.find_elements(By.XPATH, xpath)
                    for btn in buttons:
                        if btn.is_displayed():
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                            time.sleep(0.3)
                            self.driver.execute_script("arguments[0].click();", btn)
                            logger.info(f"✅ Категория '{cat_name}' успешно выбрана!")
                            time.sleep(1.5)  # Ожидание рендера зависимых разделов (размеры, цвета, свойства)
                            return
            except Exception as e:
                logger.warning(f"Попытка выбора категории '{cat_name}' не удалась: {e}")

        logger.warning(f"Категория из списка {target_categories} не найдена автоматически. Оберіть вручну.")

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

        # 1. Формируем список кандидатов для каждого запрошенного размера
        parsed_size_candidates = []
        has_range = False
        has_alpha = False
        has_kids_height = False

        for raw_size in target_sizes:
            raw_clean = str(raw_size).strip()
            candidates = [raw_clean]

            # Убираем 'см' (например: 110 см -> 110)
            if "см" in raw_clean.lower():
                without_cm = re.sub(r'(?i)\s*см', '', raw_clean).strip()
                if without_cm and without_cm not in candidates:
                    candidates.append(without_cm)

            # Составной формат со слэшами (L / 40 / 48)
            if "/" in raw_clean:
                parts = [p.strip() for p in raw_clean.split("/")]
                for p in parts:
                    if p not in candidates:
                        candidates.append(p)
                alpha_parts = [p for p in parts if any(c.isalpha() for c in p)]
                if alpha_parts:
                    candidates = alpha_parts + [c for c in candidates if c not in alpha_parts]

            # Проверяем специфику размеров
            for c in candidates:
                if "-" in c and any(ch.isdigit() for ch in c):
                    has_range = True
                if any(ch.isalpha() for ch in c):
                    has_alpha = True
                if c.isdigit() and 50 <= int(c) <= 176:
                    has_kids_height = True

            parsed_size_candidates.append(candidates)

        logger.info(f"Подбор размерной сетки для: {parsed_size_candidates}")

        # 2. Динамический приоритет вкладок (Шафа ТРЕБУЕТ выбор всех размеров в ОДНОЙ сетке!)
        tabs_to_check = [
            "За зростом",
            "Український",
            "Міжнародний",
            "Європейський",
            "За віком",
            "Довжина устілки",
            "Виробника"
        ]

        if has_range:
            # Диапазонные размеры (например: 60-62, 42-44, 48-50, 52-54) есть ТОЛЬКО в Украинской сетке!
            tabs_to_check = ["Український", "Міжнародний", "Європейський", "За зростом", "За віком", "Виробника"]
        elif has_kids_height and not has_alpha:
            tabs_to_check = ["За зростом", "Український", "Міжнародний", "Європейський", "За віком", "Виробника"]
        elif has_alpha:
            tabs_to_check = ["Міжнародний", "Український", "Європейський", "За зростом", "Виробника"]

        best_tab = None
        best_buttons = []

        try:
            # 3. Ищем вкладку, в которой поместится МАКСИМАЛЬНОЕ количество запрошенных размеров
            for tab_name in tabs_to_check:
                try:
                    tab_btns = self.driver.find_elements(By.XPATH, f"//button[contains(., '{tab_name}')]")
                    found_tab_el = None
                    for tb in tab_btns:
                        if tb.is_displayed():
                            found_tab_el = tb
                            break

                    if not found_tab_el:
                        continue

                    # Переключаемся на вкладку
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", found_tab_el)
                    self.driver.execute_script("arguments[0].click();", found_tab_el)
                    time.sleep(0.3)

                    # Ищем кнопки для каждого кандидата внутри этой вкладки
                    current_tab_matching_btns = []
                    for candidate_group in parsed_size_candidates:
                        btn_found_for_group = None
                        for candidate in candidate_group:
                            xpath = f"//button[.//p[normalize-space(text())='{candidate}'] or normalize-space(text())='{candidate}']"
                            btns = self.driver.find_elements(By.XPATH, xpath)
                            for btn in btns:
                                if btn.is_displayed():
                                    btn_found_for_group = (btn, candidate)
                                    break
                            if btn_found_for_group:
                                break
                        if btn_found_for_group:
                            current_tab_matching_btns.append(btn_found_for_group)

                    # Если все размеры (или больше, чем в других вкладках) найдены в этой сетке
                    if len(current_tab_matching_btns) > len(best_buttons):
                        best_tab = (tab_name, found_tab_el)
                        best_buttons = current_tab_matching_btns

                    if len(best_buttons) == len(parsed_size_candidates):
                        # 100% совпадение всех размеров в одной вкладке!
                        break
                except Exception:
                    continue

            # 4. Выбираем все найденные размеры в единой лучшей сетке
            if best_tab and best_buttons:
                tab_name, tab_el = best_tab
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab_el)
                self.driver.execute_script("arguments[0].click();", tab_el)
                time.sleep(0.3)

                for btn, candidate_name in best_buttons:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(0.2)
                    self.driver.execute_script("arguments[0].click();", btn)
                    logger.info(f"✅ Выбран размер '{candidate_name}' (единая сетка '{tab_name}').")
            else:
                logger.warning(f"⚠️ Не удалось подобрать единую размерную сетку для: {target_sizes}")

        except Exception as e:
            logger.error(f"Ошибка при выборе размеров {target_sizes}: {e}")

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
            logger.info("Подготовка к публикации и стабилизация формы...")
            time.sleep(1.5)  # Буфер для полной фиксации всех медиаданных в React state
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