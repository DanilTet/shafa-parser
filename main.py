import threading
import logging
import time
import tkinter.messagebox as messagebox
import customtkinter as ctk

from src.config import SAVE_FOLDER, CROPPED_FOLDER, INFO_TXT_PATH, INFO_JSON_PATH
from src.utils.file_utils import prepare_image_folder, save_product_to_txt, save_product_to_json
from src.utils.image_utils import prepare_images_for_upload
from src.scraper.parser import ShafaParser
from src.publisher.poster import ShafaPoster
from src.utils.logger import logger
from src.utils.state_manager import (
    load_state, save_state, init_state, update_item_status, clear_state
)

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
        self.grid_rowconfigure(5, weight=1)

        # Переменные управления
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.is_running = False

        # URLs
        self.url_label = ctk.CTkLabel(self, text="Список ссылок (каждая с новой строки):")
        self.url_label.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")
        
        self.url_textbox = ctk.CTkTextbox(self, height=120)
        self.url_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        # Настройки
        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        
        self.deactivate_var = ctk.BooleanVar(value=False)
        self.deactivate_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Деактивировать оригинал", variable=self.deactivate_var)
        self.deactivate_checkbox.pack(side="left", padx=10, pady=10)

        self.autopublish_var = ctk.BooleanVar(value=False)
        self.autopublish_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Опубликовывать автоматически", variable=self.autopublish_var)
        self.autopublish_checkbox.pack(side="left", padx=10, pady=10)

        # Панель управления конвейером
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

        self.start_button = ctk.CTkButton(
            self.control_frame, text="Запустить конвейер", command=self.start_pipeline,
            fg_color="#2eb82e", hover_color="#208020", text_color="white",
            disabled_fg_color="#3a3a3a", text_color_disabled="#7a7a7a"
        )
        self.start_button.pack(side="left", padx=10, pady=10)

        self.pause_button = ctk.CTkButton(
            self.control_frame, text="Пауза", command=self.toggle_pause, state="disabled",
            fg_color="#ff9800", hover_color="#e68a00", text_color="white",
            disabled_fg_color="#3a3a3a", text_color_disabled="#7a7a7a"
        )
        self.pause_button.pack(side="left", padx=10, pady=10)

        self.stop_button = ctk.CTkButton(
            self.control_frame, text="Стоп", command=self.stop_pipeline, state="disabled",
            fg_color="#f44336", hover_color="#d32f2f", text_color="white",
            disabled_fg_color="#3a3a3a", text_color_disabled="#7a7a7a"
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

        # Проверка предыдущего состояния при запуске
        self.after(500, self.check_previous_state)

    def setup_logging(self):
        handler = TextboxHandler(self.log_textbox)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    def check_previous_state(self):
        state = load_state()
        if not state:
            return
        
        # 1. Проверяем товары в режиме ожидания ручной публикации
        manual_items = [i for i in state["urls"] if i["status"] == "filled_awaiting_manual"]
        if manual_items:
            ans = messagebox.askyesno(
                "Подтверждение ручной публикации",
                f"Обнаружено {len(manual_items)} товаров, подготовленных к ручной публикации в прошлый раз.\n\n"
                "Вы успели опубликовать их вручную? (Да - пометить как успешные, Нет - вернуть в очередь)"
            )
            if ans:
                for item in manual_items:
                    update_item_status(item["url"], "success", item.get("time_spent", 0))
            else:
                for item in manual_items:
                    update_item_status(item["url"], "pending", 0)
            state = load_state()

        # 2. Проверяем оставшиеся необработанные ссылки
        pending_or_failed = [i for i in state["urls"] if i["status"] in ("pending", "failed")]
        if pending_or_failed:
            ans = messagebox.askyesno(
                "Незавершенный сеанс",
                f"Обнаружен незавершенный сеанс ({len(pending_or_failed)} необработанных/упавших ссылок).\n"
                "Продолжить прошлую сессию? (Да - продолжить, Нет - сбросить и начать заново)"
            )
            if ans:
                self.url_textbox.delete("1.0", "end")
                urls = [i["url"] for i in state["urls"] if i["status"] in ("pending", "failed")]
                self.url_textbox.insert("1.0", "\n".join(urls))
                self.update_stats_display(state)
            else:
                clear_state()

    def update_stats_display(self, state):
        urls = state["urls"]
        total = len(urls)
        processed = state["stats"]["total_processed"]
        success = state["stats"]["total_success"]
        failed = state["stats"]["total_failed"]
        avg_time = state["stats"]["avg_time_per_item"]
        
        self.stats_label.configure(
            text=f"Всего: {processed}/{total} | Успешно: {success} | Ошибок: {failed} | Среднее время: {avg_time} сек."
        )
        if total > 0:
            self.progress_bar.set(processed / total)

    def start_pipeline(self):
        urls_text = self.url_textbox.get("1.0", "end").strip()
        if not urls_text:
            logger.error("Список ссылок пуст!")
            return
            
        urls = [u.strip() for u in urls_text.split('\n') if u.strip().startswith('http')]
        if not urls:
            logger.error("Не найдено корректных ссылок.")
            return

        # Инициализируем БД
        state = load_state()
        if not state or set(u["url"] for u in state["urls"]) != set(urls):
            state = init_state(urls)
        
        self.update_stats_display(state)

        # Сброс флагов управления
        self.pause_event.set()  # Запущен
        self.stop_event.clear() # Не остановлен
        self.is_running = True

        # Управление кнопками
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="Пауза")
        self.stop_button.configure(state="normal")
        
        logger.info(f"Запуск конвейера для {len(urls)} товаров...")
        thread = threading.Thread(target=self.run_pipeline, daemon=True)
        thread.start()

    def toggle_pause(self):
        if not self.is_running:
            return
        
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.configure(text="Продолжить", fg_color="#2196f3", hover_color="#1976d2")
            logger.info("⏸️ Конвейер поставлен на паузу. Бот остановится перед следующим шагом.")
        else:
            self.pause_event.set()
            self.pause_button.configure(text="Пауза", fg_color="#ff9800", hover_color="#e68a00")
            logger.info("▶️ Конвейер возобновлен.")

    def stop_pipeline(self):
        if not self.is_running:
            return
        
        logger.info("🛑 Запрос на остановку конвейера. Завершаем текущий шаг...")
        self.stop_event.set()
        self.pause_event.set() # Разблокируем поток, если он был на паузе
        self.stop_button.configure(state="disabled")
        self.pause_button.configure(state="disabled")

    def run_pipeline(self):
        logger.info("=== ЗАПУСК ПОТОКА АВТОМАТИЗАЦИИ ===")
        prepare_image_folder(SAVE_FOLDER)
        
        deactivate_flag = self.deactivate_var.get()
        autopublish_flag = self.autopublish_var.get()
        
        poster = None
        try:
            poster = ShafaPoster()
            
            while True:
                # 1. Проверяем паузу
                self.pause_event.wait()
                
                # 2. Проверяем остановку
                if self.stop_event.is_set():
                    break
                
                # 3. Берем следующую незавершенную ссылку
                state = load_state()
                pending_items = [i for i in state["urls"] if i["status"] in ("pending", "failed")]
                if not pending_items:
                    break
                    
                target_item = pending_items[0]
                url = target_item["url"]
                
                logger.info(f"\n--- ОБРАБОТКА ТОВАРА: {url} ---")
                start_time = time.perf_counter()
                
                # Обновляем статус на processing
                update_item_status(url, "processing")
                
                # Парсинг
                parser = ShafaParser()
                product_data = None
                try:
                    product_data = parser.parse_item(url)
                    save_product_to_txt(product_data, INFO_TXT_PATH)
                    save_product_to_json(product_data, INFO_JSON_PATH)
                except Exception as e:
                    logger.error(f"Ошибка парсинга товара {url}: {e}", exc_info=True)
                    state = update_item_status(url, "failed", error=str(e))
                    self.after(0, lambda s=state: self.update_stats_display(s))
                    continue
                finally:
                    parser.close()

                # Проверка паузы и стопа перед публикацией
                self.pause_event.wait()
                if self.stop_event.is_set():
                    # Сбрасываем в pending, чтобы обработать в следующий раз
                    state = update_item_status(url, "pending")
                    self.after(0, lambda s=state: self.update_stats_display(s))
                    break

                # Обработка фото и публикация
                try:
                    processed_images = prepare_images_for_upload(product_data.downloaded_images, CROPPED_FOLDER)
                    
                    poster.publish(product_data, processed_images, deactivate_flag, autopublish_flag)
                    
                    time_spent = round(time.perf_counter() - start_time, 2)
                    
                    # Записываем правильный финальный статус в зависимости от флага автопубликации
                    final_status = "success" if autopublish_flag else "filled_awaiting_manual"
                    state = update_item_status(url, final_status, time_spent=time_spent)
                    
                    logger.info(f"Товар {url} успешно обработан за {time_spent} сек. Статус: {final_status}")
                    self.after(0, lambda s=state: self.update_stats_display(s))
                    
                except Exception as e:
                    logger.error(f"Ошибка публикации товара {url}: {e}", exc_info=True)
                    state = update_item_status(url, "failed", error=str(e))
                    self.after(0, lambda s=state: self.update_stats_display(s))

            logger.info("\n=== КОНВЕЙЕР ОСТАНОВЛЕН ИЛИ УСПЕШНО ЗАВЕРШЕН ===")
            
        except Exception as e:
            logger.error(f"Критическая ошибка конвейера: {e}", exc_info=True)
        finally:
            self.is_running = False
            # Возвращаем кнопки в исходное состояние
            def reset_buttons():
                self.start_button.configure(state="normal")
                self.pause_button.configure(state="disabled", text="Пауза", fg_color="#ff9800", hover_color="#e68a00")
                self.stop_button.configure(state="disabled")
            self.after(0, reset_buttons)

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = ShafaApp()
    app.mainloop()