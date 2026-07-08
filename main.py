import threading
import logging
import customtkinter as ctk

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
        # Ensure thread safety for tkinter
        self.textbox.after(0, append)

class ShafaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Shafa.ua Автопубликация")
        self.geometry("800x600")
        
        # Настройка сетки
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # URLs
        self.url_label = ctk.CTkLabel(self, text="Список ссылок (каждая с новой строки):")
        self.url_label.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")
        
        self.url_textbox = ctk.CTkTextbox(self, height=150)
        self.url_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        # Настройки
        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        
        self.deactivate_var = ctk.BooleanVar(value=False)
        self.deactivate_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Деактивировать оригинальный товар", variable=self.deactivate_var)
        self.deactivate_checkbox.pack(side="left", padx=10, pady=10)

        self.autopublish_var = ctk.BooleanVar(value=False)
        self.autopublish_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Опубликовывать автоматически", variable=self.autopublish_var)
        self.autopublish_checkbox.pack(side="left", padx=10, pady=10)

        # Кнопка старта
        self.start_button = ctk.CTkButton(self.settings_frame, text="Запустить конвейер", command=self.start_pipeline)
        self.start_button.pack(side="right", padx=10, pady=10)

        # Логи
        self.log_label = ctk.CTkLabel(self, text="Логи работы:")
        self.log_label.grid(row=3, column=0, padx=10, pady=(0, 0), sticky="w")
        
        self.log_textbox = ctk.CTkTextbox(self, height=200, state="disabled")
        self.log_textbox.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # Настройка логгера для GUI
        self.setup_logging()

    def setup_logging(self):
        handler = TextboxHandler(self.log_textbox)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    def start_pipeline(self):
        urls_text = self.url_textbox.get("1.0", "end").strip()
        if not urls_text:
            logger.error("Список ссылок пуст!")
            return
            
        urls = [u.strip() for u in urls_text.split('\n') if u.strip().startswith('http')]
        if not urls:
            logger.error("Не найдено корректных ссылок. (Должны начинаться с http/https)")
            return
            
        deactivate_flag = self.deactivate_var.get()
        autopublish_flag = self.autopublish_var.get()
        
        self.start_button.configure(state="disabled")
        logger.info(f"Запуск потока для {len(urls)} ссылок...")
        
        thread = threading.Thread(target=self.run_pipeline, args=(urls, deactivate_flag, autopublish_flag), daemon=True)
        thread.start()

    def run_pipeline(self, urls, deactivate_flag, autopublish_flag):
        logger.info("=== ЗАПУСК КОНВЕЙЕРА ПУБЛИКАЦИИ ===")
        prepare_image_folder(SAVE_FOLDER)

        # 1 браузер для всех публикаций (останется открытым)
        poster = None
        try:
            poster = ShafaPoster()
            
            for index, url in enumerate(urls, 1):
                logger.info(f"\n--- ОБРАБОТКА ТОВАРА {index}/{len(urls)} ---")
                
                # Отдельный парсер для каждого товара (чтобы не копить мусор)
                parser = ShafaParser()
                try:
                    logger.info("--- СТАРТ ПАРСИНГА ---")
                    product_data = parser.parse_item(url)
                    save_product_to_txt(product_data, INFO_TXT_PATH)
                    save_product_to_json(product_data, INFO_JSON_PATH)
                except Exception as e:
                    logger.error(f"Ошибка во время парсинга {url}: {e}", exc_info=True)
                    continue
                finally:
                    parser.close()
                
                logger.info("--- СТАРТ ОБРАБОТКИ ФОТО ---")
                processed_images = prepare_images_for_upload(product_data.downloaded_images, CROPPED_FOLDER)

                logger.info("--- СТАРТ ПУБЛИКАЦИИ ---")
                try:
                    poster.publish(product_data, processed_images, deactivate_flag, autopublish_flag)
                except Exception as e:
                    logger.error(f"Ошибка во время публикации {url}: {e}", exc_info=True)

            logger.info("\n=== КОНВЕЙЕР УСПЕШНО ЗАВЕРШИЛ РАБОТУ ===")
            if not autopublish_flag:
                logger.info("Вкладки в браузере готовы к вашей ручной проверке.")
            
        except Exception as e:
            logger.error(f"Критическая ошибка конвейера: {e}", exc_info=True)
        finally:
            def enable_btn():
                self.start_button.configure(state="normal")
            self.after(0, enable_btn)
            # Внимание: poster НЕ закрываем, чтобы пользователь мог прокликать "Опубликовать"
            # poster.close()

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = ShafaApp()
    app.mainloop()