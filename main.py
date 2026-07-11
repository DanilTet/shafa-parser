import threading
import logging
import time
import re
import json
import os
import tkinter.messagebox as messagebox
import customtkinter as ctk

from selenium.webdriver.common.by import By
from src.config import SAVE_FOLDER, CROPPED_FOLDER, INFO_TXT_PATH, INFO_JSON_PATH
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
        self.grid_rowconfigure(6, weight=1)

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
        


        # Панель управления конвейером
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

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
        self.stats_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.stats_frame)
        self.progress_bar.pack(fill="x", padx=10, pady=(10, 5))
        self.progress_bar.set(0)

        self.stats_label = ctk.CTkLabel(self.stats_frame, text="Всего: 0/0 | Успешно: 0 | Ошибок: 0 | Среднее время: 0 сек.")
        self.stats_label.pack(side="left", padx=10, pady=5)

        # Логи
        self.log_label = ctk.CTkLabel(self, text="Логи работы:")
        self.log_label.grid(row=5, column=0, padx=10, pady=(5, 0), sticky="w")
        
        self.log_textbox = ctk.CTkTextbox(self, height=180, state="disabled")
        self.log_textbox.grid(row=6, column=0, padx=10, pady=(0, 10), sticky="nsew")

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

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = ShafaApp()
    app.mainloop()