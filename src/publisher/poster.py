import time
import re
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
from src.publisher.category_matcher import (
    detect_gender_profile,
    score_category_candidate,
    get_category_synonyms,
)

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
        
        try:
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except Exception as e:
            if "DevToolsActivePort" in str(e) or "crashed" in str(e):
                logger.warning("⚠️ Обнаружен конфликт или зависший процесс Chrome. Выполняется очистка и повторный запуск...")
                import subprocess
                subprocess.run("taskkill /F /IM chrome.exe /IM chromedriver.exe", shell=True, capture_output=True)
                time.sleep(1.5)
                self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            else:
                raise

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
        new_url = None
        if auto_publish:
            new_url = self.confirm_publish()
        else:
            logger.info("Автопубликация отключена. Товар готов к ручной проверке.")
        return new_url

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

    def _close_category_modal_if_open(self):
        """Закрывает всплывающее модальное окно выбора категории, если оно открыто."""
        try:
            modals = self.driver.find_elements(
                By.XPATH,
                "//p[normalize-space(text())='Виберіть категорію' or normalize-space(text())='Выберите категорию']"
                " | //div[contains(@class, 'modal') and .//*[contains(text(), 'категор')]]"
            )
            for m in modals:
                if m.is_displayed():
                    logger.info("Закрытие активного модального окна категорий через Escape...")
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ESCAPE)
                    time.sleep(0.5)
                    break
        except Exception:
            pass

    def _fill_category(self, product: Product):
        target_categories = product.characteristics.get('категорії:', [])
        if not target_categories:
            logger.warning("Категории не указаны в характеристиках товара.")
            return

        logger.info(f"Выбор категории из списка: {target_categories}...")
        gender = detect_gender_profile(product.title, target_categories)
        logger.info(f"Определен гендерный профиль товара: '{gender}'")

        # -------------------------------------------------------------
        # ЭТАП 1: Выбор из блока «Рекомендовані категорії» (приоритет)
        # -------------------------------------------------------------
        rec_buttons = []
        rec_xpath = (
            "//p[contains(text(), 'Рекомендовані') or contains(text(), 'Рекомендованные')]"
            "/ancestor::div[contains(@class, 'lgtnl3') or .//ul]//button"
            " | //div[contains(@class, 'lgtnl3')]//button"
            " | //ul[contains(@class, 'I6ysXv')]//button"
        )

        # Ожидаем подгрузку блока рекомендаций сервером Shafa (до 4 сек)
        for _ in range(8):
            try:
                rec_buttons = self.driver.find_elements(By.XPATH, rec_xpath)
                rec_buttons = [b for b in rec_buttons if b.is_displayed()]
                if rec_buttons:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if rec_buttons:
            logger.info(f"Найдено {len(rec_buttons)} рекомендованных категорий от Shafa. Оценка релевантности...")
            candidates = []
            for btn in rec_buttons:
                try:
                    p_tags = btn.find_elements(By.TAG_NAME, "p")
                    if p_tags:
                        btn_title = p_tags[0].text.strip()
                        btn_path = p_tags[1].text.strip() if len(p_tags) > 1 else ""
                    else:
                        lines = [line.strip() for line in btn.text.split("\n") if line.strip()]
                        btn_title = lines[0] if lines else ""
                        btn_path = lines[1] if len(lines) > 1 else ""

                    score = score_category_candidate(btn_title, btn_path, target_categories, gender)
                    candidates.append((score, btn, btn_title, btn_path))
                    logger.info(f"  Кандидат: '{btn_title}' [{btn_path}] -> Оценка: {score}")
                except Exception:
                    continue

            # Сортируем по убыванию оценки
            candidates.sort(key=lambda x: x[0], reverse=True)

            if candidates and candidates[0][0] > 0:
                best_score, best_btn, best_title, best_path = candidates[0]
                logger.info(f"🎯 Выбрана лучшая рекомендация: '{best_title}' ({best_path}) с баллом {best_score}")
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", best_btn)
                    time.sleep(0.3)
                    self.driver.execute_script("arguments[0].click();", best_btn)
                    time.sleep(1.5)

                    # Защита: если вдруг открылась модалка — закрываем через Escape
                    self._close_category_modal_if_open()

                    logger.info(f"✅ Категория '{best_title}' успешно зафиксирована из рекомендаций!")
                    return
                except Exception as e_click:
                    logger.warning(f"Не удалось кликнуть по рекомендованной категории: {e_click}")

        # -------------------------------------------------------------
        # ЭТАП 2: Резервный выбор через каталог (Fallback)
        # -------------------------------------------------------------
        logger.info("ℹ️ Рекомендации не подошли или отсутствуют. Попытка навигации по общему списку категорий...")
        try:
            list_xpath = (
                "//p[contains(text(), 'Або виберіть') or contains(text(), 'Или выберите')]"
                "/ancestor::div[contains(@class, 'U_OD58') or .//ul]//button"
                " | //div[contains(@class, 'U_OD58')]//button"
                " | //ul[contains(@class, 'Y5sM3M')]//button"
            )
            list_buttons = self.driver.find_elements(By.XPATH, list_xpath)

            # Определяем корневую категорию для клика
            root_cat = target_categories[1] if len(target_categories) > 1 else target_categories[0]
            root_synonyms = get_category_synonyms(root_cat)

            target_btn = None
            for b in list_buttons:
                try:
                    b_text = b.text.strip().lower()
                    if any(syn in b_text or b_text in syn for syn in root_synonyms):
                        target_btn = b
                        break
                except Exception:
                    continue

            if target_btn:
                logger.info(f"Открытие модального окна категорий через раздел '{root_cat}'...")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_btn)
                time.sleep(0.3)
                self.driver.execute_script("arguments[0].click();", target_btn)
                time.sleep(1.2)

                # Ищем внутри открытого модального окна кнопку конечной категории
                leaf_cat = target_categories[0]
                leaf_synonyms = get_category_synonyms(leaf_cat)

                modal_btns = self.driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'modal') or .//p[contains(text(), 'Виберіть категорію') or contains(text(), 'Выберите категорию')]]//button"
                )

                leaf_clicked = False
                for mb in modal_btns:
                    try:
                        mb_text = mb.text.strip().lower()
                        if any(syn == mb_text for syn in leaf_synonyms):
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", mb)
                            time.sleep(0.2)
                            self.driver.execute_script("arguments[0].click();", mb)
                            logger.info(f"✅ В модальном окне выбрана конечная категория '{leaf_cat}'!")
                            leaf_clicked = True
                            time.sleep(1.5)
                            break
                    except Exception:
                        continue

                # Закрываем модалку если она осталась висеть
                self._close_category_modal_if_open()
                if leaf_clicked:
                    return

        except Exception as e_list:
            logger.warning(f"Ошибка резервного выбора категории через список: {e_list}")
            self._close_category_modal_if_open()

        logger.warning(f"⚠️ Категория из списка {target_categories} не выбрана автоматически. Оберіть вручну.")

    def _fill_condition(self, product: Product):
        if not product.condition:
            return
        logger.info(f"Выбор состояния: {product.condition}...")

        # Синонимы состояний на случай несовпадения локалей (UK <-> RU)
        condition_synonyms = [product.condition]
        cond_lower = product.condition.strip().lower()
        condition_map = {
            "новий": ["новий", "новый"],
            "новый": ["новий", "новый"],
            "ідеальний": ["ідеальний", "идеальный", "идеальное", "ідеальне"],
            "идеальный": ["ідеальний", "идеальный", "идеальное", "ідеальне"],
            "дуже хороший": ["дуже хороший", "очень хорошее", "очень хороший", "дуже добре"],
            "очень хорошее": ["дуже хороший", "очень хорошее", "очень хороший"],
            "хороший": ["хороший", "хорошее", "добрий"],
            "хорошее": ["хороший", "хорошее", "добрий"],
            "задовільний": ["задовільний", "удовлетворительное", "удовлетворительный"],
            "удовлетворительное": ["задовільний", "удовлетворительное", "удовлетворительный"],
        }
        if cond_lower in condition_map:
            condition_synonyms = condition_map[cond_lower]

        try:
            for cond_candidate in condition_synonyms:
                xpath = f"//button[normalize-space(text())='{cond_candidate}']"
                condition_btns = self.driver.find_elements(By.XPATH, xpath)
                for btn in condition_btns:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        time.sleep(0.2)
                        btn.click()
                        logger.info(f"Состояние '{cond_candidate}' успешно выбрано.")
                        return

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
            time.sleep(0.8)

            dropdown = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div[class*='menu']")))
            options = dropdown.find_elements(By.XPATH, ".//div")
            for option in options:
                try:
                    text = option.text.strip()
                    if text.lower() == product.brand.lower():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                        time.sleep(0.2)
                        option.click()
                        logger.info(f"Бренд '{product.brand}' успешно выбран.")
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Ошибка при выборе бренда: {e}")

    def _fill_size(self, product: Product):
        target_sizes = product.characteristics.get('розмір:', []) or product.characteristics.get('розмір', [])
        if isinstance(target_sizes, str):
            target_sizes = [target_sizes]
        if not target_sizes:
            return

        # 1. Формируем список кандидатов для каждого запрошенного размера (с учетом регистров)
        parsed_size_candidates = []
        has_range = False
        has_alpha = False
        has_kids_height = False

        for raw_size in target_sizes:
            raw_clean = str(raw_size).strip()
            candidates = []

            # Добавляем базовые формы и регистры (например: 95f, 95F, 100D, 100d)
            for s in [raw_clean, raw_clean.upper(), raw_clean.lower()]:
                if s and s not in candidates:
                    candidates.append(s)

            # Обработка 'см' (например: 110см -> 110 см, 110 см -> 110)
            if "см" in raw_clean.lower():
                without_cm = re.sub(r'(?i)\s*см', '', raw_clean).strip()
                if without_cm:
                    for s in [without_cm, without_cm.upper(), without_cm.lower(), f"{without_cm} см", f"{without_cm} СМ"]:
                        if s and s not in candidates:
                            candidates.append(s)
            elif raw_clean.isdigit():
                for s in [f"{raw_clean} см", f"{raw_clean} СМ"]:
                    if s and s not in candidates:
                        candidates.append(s)

            # Составной формат со слэшами (L / 40 / 48)
            if "/" in raw_clean:
                parts = [p.strip() for p in raw_clean.split("/")]
                for p in parts:
                    for s in [p, p.upper(), p.lower()]:
                        if s and s not in candidates:
                            candidates.append(s)
                alpha_parts = [p for p in parts if any(c.isalpha() for c in p)]
                if alpha_parts:
                    alpha_upper = [p.upper() for p in alpha_parts]
                    candidates = alpha_upper + [c for c in candidates if c not in alpha_upper]

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

        # 2. Проверяем, есть ли на странице вкладки переключения сеток (Міжнародний, Європейський, etc.)
        all_possible_tabs = [
            "За зростом",
            "Український",
            "Міжнародний",
            "Європейський",
            "За віком",
            "Довжина устілки",
            "Виробника"
        ]

        # Ищем любые отображаемые кнопки вкладок на форме
        visible_tab_elements = []
        for tab_name in all_possible_tabs:
            try:
                btns = self.driver.find_elements(By.XPATH, f"//button[contains(., '{tab_name}')]")
                for b in btns:
                    if b.is_displayed():
                        visible_tab_elements.append((tab_name, b))
                        break
            except Exception:
                pass

        try:
            # === СЦЕНАРИЙ А: НА СТРАНИЦЕ НЕТ ВКЛАДОК (Бюстгальтеры / Белье / Ремни / Аксессуары) ===
            if not visible_tab_elements:
                logger.info("ℹ️ Вкладки размерных сеток не обнаружены. Поиск в плоской сетке (белье/аксессуары)...")
                selected_count = 0
                for candidate_group in parsed_size_candidates:
                    size_selected = False
                    for candidate in candidate_group:
                        try:
                            xpath = f"//button[.//p[normalize-space(text())='{candidate}'] or normalize-space(text())='{candidate}']"
                            btns = self.driver.find_elements(By.XPATH, xpath)
                            for btn in btns:
                                if btn.is_displayed():
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                    time.sleep(0.2)
                                    self.driver.execute_script("arguments[0].click();", btn)
                                    logger.info(f"✅ Выбран размер '{candidate}' (прямой выбор без вкладок).")
                                    size_selected = True
                                    selected_count += 1
                                    break
                        except Exception:
                            pass
                        if size_selected:
                            break
                if selected_count == 0:
                    logger.warning(f"⚠️ Не удалось найти размеры {target_sizes} в плоской сетке.")
                return

            # === СЦЕНАРИЙ Б: НА СТРАНИЦЕ ЕСТЬ ВКЛАДКИ (Взрослая, детская одежда, обувь) ===
            tabs_to_check = all_possible_tabs
            if has_range:
                # Диапазонные размеры (например: 60-62, 42-44, 48-50, 52-54) есть ТОЛЬКО в Украинской сетке!
                tabs_to_check = ["Український", "Міжнародний", "Європейський", "За зростом", "За віком", "Виробника"]
            elif has_kids_height and not has_alpha:
                tabs_to_check = ["За зростом", "Український", "Міжнародний", "Європейський", "За віком", "Виробника"]
            elif has_alpha:
                tabs_to_check = ["Міжнародний", "Український", "Європейський", "За зростом", "Виробника"]

            best_tab = None
            best_buttons = []

            # Ищем вкладку, в которой поместится МАКСИМАЛЬНОЕ количество запрошенных размеров
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

    def confirm_publish(self) -> str | None:
        """
        Нажимает 'Додати річ', затем проходит всю цепочку публикации Shafa:
          1. Нажать "Додати річ"
          2. Нажать "Опублікувати без реклами" (на странице /new/ID/thanks)
          3. Нажать "Сторінка товару" (извлекаем ID из href до клика)
          4. Дождаться финального редиректа на страницу товара
        Возвращает полный URL опубликованного товара или None при ошибке.
        """
        from selenium.webdriver.support.ui import WebDriverWait as _WDW
        try:
            # --- Шаг 1: Нажимаем "Додати річ" ---
            logger.info("Подготовка к публикации, стабилизация формы...")
            time.sleep(1.5)
            confirm_btn_xpath = "//button[@class='vFhB6y vOHxES aVcdmD' and text()='Додати річ']"
            confirm_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, confirm_btn_xpath)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", confirm_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", confirm_btn)
            logger.info("✅ Кнопка 'Додати річ' нажата. Ожидание страницы подтверждения...")

            # --- Шаг 2: Нажимаем "Опублікувати без реклами" ---
            # Важно: ищем именно тег //a (а не //*, который захватывает родительские div/body!)
            # Также проверяем href на наличие '/thanks'
            no_ads_xpath = (
                "//a[contains(@href, '/thanks')] | "
                "//a[contains(normalize-space(.), 'без реклами') or contains(normalize-space(.), 'без рекламы')] | "
                "//button[contains(normalize-space(.), 'без реклами') or contains(normalize-space(.), 'без рекламы')]"
            )
            no_ads_link = _WDW(self.driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, no_ads_xpath))
            )

            # Извлекаем href и ID товара заранее (он уже есть в /new/ID/thanks)
            thanks_href = no_ads_link.get_attribute("href") or ""
            import re as _re
            extracted_id = None
            if thanks_href:
                id_match = _re.search(r'/new/(\d+)/thanks', thanks_href)
                if id_match:
                    extracted_id = id_match.group(1)
                    logger.info(f"ID нового товара определён из ссылки: #{extracted_id}")

            # Прокручиваем к ссылке (она находится под карточками тарифов)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", no_ads_link)
            time.sleep(0.8)

            logger.info("Найдена кнопка 'Опублікувати без реклами'. Нажимаем...")
            try:
                no_ads_link.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", no_ads_link)

            # Если после клика страница не сменилась (SPA не сработало), переходим по прямому URL
            time.sleep(1.5)
            if "/thanks" not in self.driver.current_url and thanks_href:
                logger.info(f"Переход на страницу благодарности по прямому адресу: {thanks_href}")
                self.driver.get(thanks_href)

            # --- Шаг 3: Нажимаем "Сторінка товару" ---
            product_page_xpath = (
                "//a[contains(@href, '/p/')] | "
                "//a[contains(normalize-space(.), 'Сторінка товару') or contains(normalize-space(.), 'Страница товара')]"
            )
            try:
                product_page_link = _WDW(self.driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, product_page_xpath))
                )

                href = product_page_link.get_attribute("href") or ""
                if not extracted_id and href:
                    p_match = _re.search(r'/p/(\d+)', href)
                    if p_match:
                        extracted_id = p_match.group(1)

                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", product_page_link)
                time.sleep(0.5)
                logger.info("Найдена ссылка 'Сторінка товару'. Переходим...")
                try:
                    product_page_link.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", product_page_link)

            except Exception as e_step3:
                logger.warning(f"Не удалось нажать 'Сторінка товару' ({e_step3}). Пробуем прямой переход...")
                # Запасной путь: если ID известен, открываем напрямую /p/ID
                if extracted_id:
                    direct_p_url = f"https://shafa.ua/uk/p/{extracted_id}"
                    logger.info(f"Прямой переход на эндпоинт товара: {direct_p_url}")
                    self.driver.get(direct_p_url)

            # --- Шаг 4: Ждём перехода, перезагружаем страницу и забираем чистую ссылку ---
            time.sleep(2)
            try:
                def _is_transitioned(d):
                    u = d.current_url
                    return ("/p/" in u) or (extracted_id and extracted_id in u) or ("/new" not in u and "/thanks" not in u)
                _WDW(self.driver, 10).until(_is_transitioned)
            except Exception:
                pass

            # Перезагружаем страницу, чтобы устранить баг фронтенда Шафы и зафиксировать финальный URL
            logger.info("🔄 Перезагрузка страницы товара для устранения бага отображения и фиксации URL...")
            try:
                self.driver.refresh()
                time.sleep(2.5)
            except Exception as e_ref:
                logger.warning(f"Не удалось выполнить refresh: {e_ref}")

            def _is_final_product_url(d):
                url = d.current_url
                if "/p/" in url or "/new" in url or "/thanks" in url:
                    return False
                if extracted_id and extracted_id in url:
                    return True
                # Fallback: любой шафа-URL не из /new и не /p/
                return "shafa.ua" in url and "/new" not in url and "/p/" not in url

            try:
                _WDW(self.driver, 15).until(_is_final_product_url)
            except Exception:
                pass

            final_url = self.driver.current_url
            logger.info(f"✅ Товар опубликован! URL: {final_url}")
            return final_url

        except Exception as e:
            logger.error(f"Ошибка в процессе подтверждения публикации: {e}")
            # Fallback: берём что есть в current_url если это не форма
            try:
                fallback_url = self.driver.current_url
                if "shafa.ua" in fallback_url and "/new" not in fallback_url:
                    logger.warning(f"⚠️ Используем fallback URL: {fallback_url}")
                    return fallback_url
            except Exception:
                pass
            return None

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


    def close(self):
        self.driver.quit()