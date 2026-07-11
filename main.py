import threading
import logging
import time
import re
import json
import os
import tkinter.messagebox as messagebox
import customtkinter as ctk

from selenium.webdriver.common.by import By
from src.config import SAVE_FOLDER, CROPPED_FOLDER, INFO_TXT_PATH, INFO_JSON_PATH, MY_LISTINGS_PATH
from src.utils.file_utils import prepare_image_folder, save_product_to_txt, save_product_to_json
from src.utils.image_utils import prepare_images_for_upload
from src.scraper.parser import ShafaParser
from src.publisher.poster import ShafaPoster
from src.utils.logger import logger

class TextboxHandler(logging.Handler):
    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.textbox.configure(state="normal")
            self.textbox.insert("end", msg + "\n")
            self.textbox.see("end")
            self.textbox.configure(state="disabled")
        self.textbox.after(0, append)

class ShafaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Shafa.ua Автопубликация с контролем состояния")
        self.geometry("850x650")
        
        # Настройка сетки
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(7, weight=1)

        # Переменные управления
        self.is_running = False
        self.should_stop = False

        # Контейнер для ввода
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.input_frame.grid_rowconfigure(1, weight=1)

        # Список ссылок
        self.url_label = ctk.CTkLabel(self.input_frame, text="Список ссылок (каждая с новой строки):")
        self.url_label.grid(row=0, column=0, padx=10, pady=(5, 0), sticky="w")
        self.url_textbox = ctk.CTkTextbox(self.input_frame, height=120)
        self.url_textbox.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="nsew")
        
        # Настройки
        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        self.settings_frame.grid_columnconfigure((0, 1), weight=1)
        
        # Ряд 0: Чекбоксы 1
        self.deactivate_var = ctk.BooleanVar(value=False)
        self.deactivate_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Деактивировать оригинал", variable=self.deactivate_var)
        self.deactivate_checkbox.grid(row=0, column=0, padx=10, pady=(10, 2), sticky="w")
        
        self.autopublish_var = ctk.BooleanVar(value=False)
        self.autopublish_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Опубликовывать автоматически", variable=self.autopublish_var)
        self.autopublish_checkbox.grid(row=0, column=1, padx=10, pady=(10, 2), sticky="w")
        
        # Ряд 1: Описания для Чекбоксов 1
        self.deactivate_desc = ctk.CTkLabel(self.settings_frame, text="Скрывает исходный товар после успешного копирования", text_color="gray", font=("Arial", 10))
        self.deactivate_desc.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")
        
        self.autopublish_desc = ctk.CTkLabel(self.settings_frame, text="ВКЛ: сразу публикует на сайт. ВЫКЛ: сохраняет как Черновик", text_color="gray", font=("Arial", 10))
        self.autopublish_desc.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="w")
        
        # Ряд 2: Чекбокс 2
        self.skip_duplicates_var = ctk.BooleanVar(value=True)
        self.skip_duplicates_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Исключать мои дубликаты", variable=self.skip_duplicates_var)
        self.skip_duplicates_checkbox.grid(row=2, column=0, padx=10, pady=(10, 2), sticky="w")
        
        # Ряд 3: Описание для Чекбокса 2
        self.skip_duplicates_desc = ctk.CTkLabel(self.settings_frame, text="Сверяет названия товаров с локальной базой и пропускает уже выложенные", text_color="gray", font=("Arial", 10))
        self.skip_duplicates_desc.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="w")

        # База данных объявлений
        self.db_frame = ctk.CTkFrame(self)
        self.db_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        
        self.db_label = ctk.CTkLabel(self.db_frame, text="Загрузка локальной базы...")
        self.db_label.pack(side="left", padx=10, pady=10)
        
        self.sync_button = ctk.CTkButton(
            self.db_frame, text="Актуализировать базу", command=self.start_sync_database,
            fg_color="#2196f3", hover_color="#1976d2", text_color="white"
        )
        self.sync_button.pack(side="right", padx=10, pady=10)

        # Панель управления конвейером
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")

        self.start_button = ctk.CTkButton(
            self.control_frame, text="Запустить конвейер", command=self.start_pipeline,
            fg_color="#2eb82e", hover_color="#208020", text_color="white",
            text_color_disabled="#7a7a7a"
        )
        self.start_button.pack(side="left", padx=10, pady=10)

        self.stop_button = ctk.CTkButton(
            self.control_frame, text="Закончить выставляние", command=self.stop_pipeline,
            fg_color="#d32f2f", hover_color="#c2185b", text_color="white",
            state="disabled"
        )
        self.stop_button.pack(side="left", padx=10, pady=10)

        # Статистика и Прогресс Бар
        self.stats_frame = ctk.CTkFrame(self)
        self.stats_frame.grid(row=5, column=0, padx=10, pady=5, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.stats_frame)
        self.progress_bar.pack(fill="x", padx=10, pady=(10, 5))
        self.progress_bar.set(0)

        self.stats_label = ctk.CTkLabel(self.stats_frame, text="Всего: 0/0 | Успешно: 0 | Ошибок: 0 | Среднее время: 0 сек.")
        self.stats_label.pack(side="left", padx=10, pady=5)

        # Логи
        self.log_label = ctk.CTkLabel(self, text="Логи работы:")
        self.log_label.grid(row=6, column=0, padx=10, pady=(5, 0), sticky="w")
        
        self.log_textbox = ctk.CTkTextbox(self, height=180, state="disabled")
        self.log_textbox.grid(row=7, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # Инициализация информации о базе данных
        self.load_local_db_info()

        # Настройка логгера
        self.setup_logging()

    def setup_logging(self):
        handler = TextboxHandler(self.log_textbox)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    def update_stats_display(self, processed, total, success, failed, avg_time):
        self.stats_label.configure(
            text=f"Всего: {processed}/{total} | Успешно: {success} | Ошибок: {failed} | Среднее время: {avg_time} сек."
        )
        if total > 0:
            self.progress_bar.set(processed / total)



    def load_local_db_info(self):
        if os.path.exists(MY_LISTINGS_PATH):
            try:
                with open(MY_LISTINGS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                count = len(data)
                self.db_label.configure(text=f"Локальная база профиля: {count} товаров.")
            except Exception as e:
                self.db_label.configure(text="Локальная база профиля: ошибка чтения.")
        else:
            self.db_label.configure(text="Локальная база профиля: отсутствует (сканируйте профиль).")

    def start_sync_database(self):
        if self.is_running:
            logger.error("Невозможно обновить базу во время работы конвейера!")
            return
            
        self.is_running = True
        self.sync_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        
        logger.info("Запуск процесса актуализации базы данных вашего профиля...")
        thread = threading.Thread(target=self.run_sync_database, daemon=True)
        thread.start()

    def run_sync_database(self):
        poster = None
        try:
            poster = ShafaPoster()
            own_titles = self.get_own_product_titles(poster.driver)
            
            # Сохранение в файл
            with open(MY_LISTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(list(own_titles), f, ensure_ascii=False, indent=4)
                
            logger.info(f"База данных успешно обновлена! Сохранено {len(own_titles)} товаров.")
            self.after(0, self.load_local_db_info)
        except Exception as e:
            logger.error(f"Ошибка при обновлении базы данных: {e}", exc_info=True)
        finally:
            if poster:
                poster.close()
            self.is_running = False
            self.after(0, lambda: self.sync_button.configure(state="normal"))
            self.after(0, lambda: self.start_button.configure(state="normal"))

    def get_own_product_titles(self, driver):
        driver.get("https://shafa.ua/")
        time.sleep(3)
        
        username = None
        links = driver.find_elements(By.TAG_NAME, "a")
        for a in links:
            href = a.get_attribute("href")
            if href and "/member/" in href:
                parts = href.split("/member/")
                if len(parts) > 1:
                    possible_user = parts[1].split("/")[0].split("?")[0]
                    if possible_user not in ["signup", "login", "clothes"]:
                        username = possible_user
                        break
                        
        if not username:
            driver.get("https://shafa.ua/my/clothes")
            time.sleep(3)
            current_url = driver.current_url
            if "/member/" in current_url:
                parts = current_url.split("/member/")
                username = parts[1].split("/")[0]
                
        if not username:
            logger.warning("Не удалось автоматически определить ваш никнейм на Shafa. Проверка дубликатов отключена.")
            return set()
            
        logger.info(f"Определен ваш никнейм Shafa: {username}. Сбор ваших текущих объявлений...")
        
        profile_url = f"https://shafa.ua/member/{username}"
        driver.get(profile_url)
        time.sleep(3)
        
        titles = set()
        last_count = 0
        consecutive_same = 0
        
        while consecutive_same < 3:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            links = driver.find_elements(By.TAG_NAME, "a")
            current_titles = set()
            for a in links:
                href = a.get_attribute("href")
                text = a.text.strip()
                if href and re.search(r'/\d+-[^/]+$', href) and not any(p in href for p in ["/member/", "/my/", "/dynamic-collections/"]):
                    if text:
                        current_titles.add(text.lower())
                        
            if len(current_titles) == last_count:
                consecutive_same += 1
            else:
                consecutive_same = 0
                last_count = len(current_titles)
                
            if len(current_titles) > 1000:
                break
                
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href")
            text = a.text.strip()
            if href and re.search(r'/\d+-[^/]+$', href) and not any(p in href for p in ["/member/", "/my/", "/dynamic-collections/"]):
                if text:
                    titles.add(text.lower())
                    
        logger.info(f"Собрано ваших объявлений: {len(titles)}")
        return titles

    def stop_pipeline(self):
        if self.is_running:
            logger.info("Запрошена остановка конвейера. Завершаем работу после текущего товара...")
            self.should_stop = True
            self.stop_button.configure(state="disabled")

    def start_pipeline(self):
        urls_text = self.url_textbox.get("1.0", "end").strip()
        if not urls_text:
            logger.error("Список ссылок пуст!")
            return
            
        urls = [u.strip() for u in urls_text.split('\n') if u.strip().startswith('http')]
        if not urls:
            logger.error("Не найдено корректных ссылок.")
            return

        self.update_stats_display(0, len(urls), 0, 0, 0)
        self.is_running = True
        self.should_stop = False
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.sync_button.configure(state="disabled")
        
        logger.info(f"Запуск конвейера для {len(urls)} товаров...")
        thread = threading.Thread(target=self.run_pipeline, args=(urls,), daemon=True)
        thread.start()

    def run_pipeline(self, urls):
        logger.info("=== ЗАПУСК ПОТОКА АВТОМАТИЗАЦИИ ===")
        prepare_image_folder(SAVE_FOLDER)
        
        deactivate_flag = self.deactivate_var.get()
        autopublish_flag = self.autopublish_var.get()
        
        total = len(urls)
        processed = 0
        success = 0
        failed = 0
        total_time = 0
        
        poster = None
        try:
            poster = ShafaPoster()
            
            for url in urls:
                if self.should_stop:
                    logger.info("Конвейер остановлен пользователем.")
                    break
                    
                logger.info(f"\n--- ОБРАБОТКА ТОВАРА: {url} ---")
                start_time = time.perf_counter()
                
                parser = ShafaParser()
                product_data = None
                try:
                    product_data = parser.parse_item(url)
                    save_product_to_txt(product_data, INFO_TXT_PATH)
                    save_product_to_json(product_data, INFO_JSON_PATH)
                except Exception as e:
                    logger.error(f"Ошибка парсинга товара {url}: {e}", exc_info=True)
                    failed += 1
                    processed += 1
                    avg_time = round(total_time / processed, 2) if processed > 0 else 0
                    self.after(0, lambda p=processed, s=success, f=failed, a=avg_time: self.update_stats_display(p, total, s, f, a))
                    continue
                finally:
                    parser.close()

                try:
                    processed_images = prepare_images_for_upload(product_data.downloaded_images, CROPPED_FOLDER)
                    poster.publish(product_data, processed_images, deactivate_flag, autopublish_flag)
                    
                    time_spent = round(time.perf_counter() - start_time, 2)
                    total_time += time_spent
                    success += 1
                    processed += 1
                    
                    # Синхронизация с локальной базой данных при поштучной успешной публикации
                    try:
                        if os.path.exists(MY_LISTINGS_PATH):
                            with open(MY_LISTINGS_PATH, "r", encoding="utf-8") as f:
                                db_titles = set(json.load(f))
                        else:
                            db_titles = set()
                        db_titles.add(product_data.title.lower())
                        with open(MY_LISTINGS_PATH, "w", encoding="utf-8") as f:
                            json.dump(list(db_titles), f, ensure_ascii=False, indent=4)
                        self.after(0, self.load_local_db_info)
                    except:
                        pass
                    
                    logger.info(f"Товар {url} успешно обработан за {time_spent} сек.")
                    avg_time = round(total_time / processed, 2) if processed > 0 else 0
                    self.after(0, lambda p=processed, s=success, f=failed, a=avg_time: self.update_stats_display(p, total, s, f, a))
                    
                except Exception as e:
                    logger.error(f"Ошибка публикации товара {url}: {e}", exc_info=True)
                    failed += 1
                    processed += 1
                    avg_time = round(total_time / processed, 2) if processed > 0 else 0
                    self.after(0, lambda p=processed, s=success, f=failed, a=avg_time: self.update_stats_display(p, total, s, f, a))

            logger.info("\n=== КОНВЕЙЕР УСПЕШНО ЗАВЕРШЕН ===")
            
        except Exception as e:
            logger.error(f"Критическая ошибка конвейера: {e}", exc_info=True)
        finally:
            self.is_running = False
            self.after(0, lambda: self.start_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="disabled"))
            self.after(0, lambda: self.sync_button.configure(state="normal"))

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = ShafaApp()
    app.mainloop()