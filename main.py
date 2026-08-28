import threading
import logging
import time
import re
import os
import tkinter.messagebox as messagebox
import customtkinter as ctk

from selenium.webdriver.common.by import By
from src.config import SAVE_FOLDER, CROPPED_FOLDER, INFO_TXT_PATH, INFO_JSON_PATH
from src.utils.file_utils import prepare_image_folder, save_product_to_txt, save_product_to_json
from src.utils.image_utils import prepare_images_for_upload
from src.scraper.parser import ShafaParser
from src.scraper.profile_scanner import ProfileScanner
from src.sync.profile_store import ProfileStore
from src.publisher.poster import ShafaPoster
from src.utils.display_utils import prevent_sleep, allow_sleep
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
        self.title("Shafa.ua Автоматизация & Синхронизация Профилей")
        self.geometry("900x750")
        
        # Модули синхронизации
        self.profile_store = ProfileStore()
        self.profile_scanner = ProfileScanner()

        # Настройка главной сетки
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # Переменные управления
        self.is_running = False
        self.should_stop = False

        # --- ВКЛАДКИ ПРИЛОЖЕНИЯ ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, padx=10, pady=(5, 5), sticky="nsew")
        
        self.tab_manual = self.tabview.add("📋 Парсинг по ссылкам")
        self.tab_sync = self.tabview.add("🔄 Синхронизация профилей")

        # Инициализация интерфейса обеих вкладок
        self._setup_manual_tab()
        self._setup_sync_tab()

        # --- ОБЩИЙ БЛОК ЛОГОВ ---
        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.log_frame.grid_columnconfigure(0, weight=1)

        self.log_label = ctk.CTkLabel(self.log_frame, text="Логи работы в реальном времени:")
        self.log_label.grid(row=0, column=0, padx=10, pady=(5, 0), sticky="w")
        
        self.log_textbox = ctk.CTkTextbox(self.log_frame, height=140, state="disabled")
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="nsew")

        # Настройка логгера
        self.setup_logging()

    def setup_logging(self):
        handler = TextboxHandler(self.log_textbox)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # =========================================================================
    # ВКЛАДКА 1: ПОШТУЧНЫЙ ПАРСИНГ ПО ССЫЛКАМ
    # =========================================================================
    def _setup_manual_tab(self):
        tab = self.tab_manual
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Поле ввода ссылок
        self.input_frame = ctk.CTkFrame(tab)
        self.input_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.input_frame.grid_rowconfigure(1, weight=1)

        self.url_label = ctk.CTkLabel(self.input_frame, text="Список ссылок на товары (каждая с новой строки):")
        self.url_label.grid(row=0, column=0, padx=10, pady=(5, 0), sticky="w")
        
        self.url_textbox = ctk.CTkTextbox(self.input_frame, height=100)
        self.url_textbox.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="nsew")

        # Настройки
        self.settings_frame = ctk.CTkFrame(tab)
        self.settings_frame.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        self.settings_frame.grid_columnconfigure((0, 1), weight=1)
        
        self.deactivate_var = ctk.BooleanVar(value=False)
        self.deactivate_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Деактивировать оригинал", variable=self.deactivate_var)
        self.deactivate_checkbox.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
        
        self.autopublish_var = ctk.BooleanVar(value=False)
        self.autopublish_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Опубликовывать автоматически", variable=self.autopublish_var)
        self.autopublish_checkbox.grid(row=0, column=1, padx=10, pady=(8, 2), sticky="w")
        
        self.deactivate_desc = ctk.CTkLabel(self.settings_frame, text="Скрывает исходный товар после успешного копирования", text_color="gray", font=("Arial", 10))
        self.deactivate_desc.grid(row=1, column=0, padx=10, pady=(0, 4), sticky="w")
        
        self.autopublish_desc = ctk.CTkLabel(self.settings_frame, text="ВКЛ: сразу публикует. ВЫКЛ: сохраняет как Черновик", text_color="gray", font=("Arial", 10))
        self.autopublish_desc.grid(row=1, column=1, padx=10, pady=(0, 4), sticky="w")

        self.secondary_monitor_var = ctk.BooleanVar(value=True)
        self.secondary_monitor_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Запускать на 2-м мониторе", variable=self.secondary_monitor_var)
        self.secondary_monitor_checkbox.grid(row=2, column=0, padx=10, pady=(4, 2), sticky="w")

        self.hidden_mode_var = ctk.BooleanVar(value=False)
        self.hidden_mode_checkbox = ctk.CTkCheckBox(self.settings_frame, text="Скрытый режим (показ в конце)", variable=self.hidden_mode_var)
        self.hidden_mode_checkbox.grid(row=2, column=1, padx=10, pady=(4, 2), sticky="w")

        self.secondary_monitor_desc = ctk.CTkLabel(self.settings_frame, text="Перемещает Chrome на второй экран (если подключен)", text_color="gray", font=("Arial", 10))
        self.secondary_monitor_desc.grid(row=3, column=0, padx=10, pady=(0, 8), sticky="w")

        self.hidden_mode_desc = ctk.CTkLabel(self.settings_frame, text="Работает без окна и разворачивает браузер в финале", text_color="gray", font=("Arial", 10))
        self.hidden_mode_desc.grid(row=3, column=1, padx=10, pady=(0, 8), sticky="w")

        # Панель управления конвейером
        self.control_frame = ctk.CTkFrame(tab)
        self.control_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")

        self.start_button = ctk.CTkButton(
            self.control_frame, text="Запустить конвейер", command=self.start_pipeline,
            fg_color="#2eb82e", hover_color="#208020", text_color="white"
        )
        self.start_button.pack(side="left", padx=10, pady=8)

        self.stop_button = ctk.CTkButton(
            self.control_frame, text="Закончить выставляние", command=self.stop_pipeline,
            fg_color="#d32f2f", hover_color="#c2185b", text_color="white",
            state="disabled"
        )
        self.stop_button.pack(side="left", padx=10, pady=8)

        # Статистика и Прогресс Бар
        self.stats_frame = ctk.CTkFrame(tab)
        self.stats_frame.grid(row=3, column=0, padx=5, pady=5, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.stats_frame)
        self.progress_bar.pack(fill="x", padx=10, pady=(8, 4))
        self.progress_bar.set(0)

        self.stats_label = ctk.CTkLabel(self.stats_frame, text="Всего: 0/0 | Успешно: 0 | Ошибок: 0 | Среднее время: 0 сек.")
        self.stats_label.pack(side="left", padx=10, pady=4)

    # =========================================================================
    # ВКЛАДКА 2: СИНХРОНИЗАЦИЯ ПРОФИЛЕЙ
    # =========================================================================
    def _setup_sync_tab(self):
        tab = self.tab_sync
        tab.grid_columnconfigure(0, weight=1)

        # 1. Блок выбора и сканирования источника
        self.source_frame = ctk.CTkFrame(tab)
        self.source_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.source_frame.grid_columnconfigure(1, weight=1)

        self.sync_url_label = ctk.CTkLabel(self.source_frame, text="Профиль-источник:")
        self.sync_url_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        self.sync_url_entry = ctk.CTkEntry(
            self.source_frame,
            placeholder_text="https://shafa.ua/member/username или просто имя продавца"
        )
        self.sync_url_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Сохраненные профили
        saved_profiles = self.profile_store.get_saved_profiles()
        self.sync_saved_combo = ctk.CTkComboBox(
            self.source_frame,
            values=saved_profiles if saved_profiles else ["(Нет сохраненных)"],
            command=self.on_saved_profile_selected,
            width=160
        )
        self.sync_saved_combo.grid(row=0, column=2, padx=5, pady=5)

        self.sync_scan_button = ctk.CTkButton(
            self.source_frame, text="🔍 Сканировать", command=self.start_profile_scan,
            fg_color="#1f77b4", hover_color="#145a86", text_color="white", width=120
        )
        self.sync_scan_button.grid(row=0, column=3, padx=10, pady=5)

        self.sync_scan_hidden_var = ctk.BooleanVar(value=True)
        self.sync_scan_hidden_cb = ctk.CTkCheckBox(
            self.source_frame, text="Скрытое сканирование (быстрее и без окон)",
            variable=self.sync_scan_hidden_var
        )
        self.sync_scan_hidden_cb.grid(row=1, column=1, columnspan=2, padx=5, pady=(0, 5), sticky="w")

        # 2. Информационные карточки статистики профиля
        self.profile_stats_frame = ctk.CTkFrame(tab)
        self.profile_stats_frame.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        self.profile_stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_total_card = ctk.CTkLabel(self.profile_stats_frame, text="Всего в каталоге: 0", font=("Arial", 12, "bold"))
        self.stat_total_card.grid(row=0, column=0, padx=5, pady=8)

        self.stat_pending_card = ctk.CTkLabel(self.profile_stats_frame, text="Ожидают переноса: 0", font=("Arial", 12, "bold"), text_color="#e6b800")
        self.stat_pending_card.grid(row=0, column=1, padx=5, pady=8)

        self.stat_published_card = ctk.CTkLabel(self.profile_stats_frame, text="Уже перенесено: 0", font=("Arial", 12, "bold"), text_color="#2eb82e")
        self.stat_published_card.grid(row=0, column=2, padx=5, pady=8)

        self.stat_failed_card = ctk.CTkLabel(self.profile_stats_frame, text="Ошибок/Пропущено: 0", font=("Arial", 12, "bold"), text_color="#d32f2f")
        self.stat_failed_card.grid(row=0, column=3, padx=5, pady=8)

        # 3. Настройки переноса и автосверки
        self.sync_settings_frame = ctk.CTkFrame(tab)
        self.sync_settings_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        self.sync_settings_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # Порция переноса
        self.batch_size_label = ctk.CTkLabel(self.sync_settings_frame, text="Размер порции:")
        self.batch_size_label.grid(row=0, column=0, padx=10, pady=(6, 2), sticky="w")
        
        self.batch_size_combo = ctk.CTkComboBox(
            self.sync_settings_frame,
            values=["Все оставшиеся", "10 товаров", "20 товаров", "50 товаров"],
            width=150
        )
        self.batch_size_combo.set("Все оставшиеся")
        self.batch_size_combo.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="w")

        # Кнопка автосверки
        self.reconcile_button = ctk.CTkButton(
            self.sync_settings_frame, text="✨ Сверить с моим аккаунтом",
            command=self.start_reconciliation,
            fg_color="#8e44ad", hover_color="#6c3483", text_color="white"
        )
        self.reconcile_button.grid(row=1, column=1, padx=10, pady=(0, 6), sticky="w")

        # Чекбоксы синхронизации
        self.sync_autopublish_var = ctk.BooleanVar(value=False)
        self.sync_autopublish_cb = ctk.CTkCheckBox(self.sync_settings_frame, text="Опубликовывать сразу", variable=self.sync_autopublish_var)
        self.sync_autopublish_cb.grid(row=0, column=2, padx=10, pady=(6, 2), sticky="w")

        self.sync_hidden_var = ctk.BooleanVar(value=False)
        self.sync_hidden_cb = ctk.CTkCheckBox(self.sync_settings_frame, text="Скрытый режим", variable=self.sync_hidden_var)
        self.sync_hidden_cb.grid(row=1, column=2, padx=10, pady=(0, 6), sticky="w")

        # 4. Панель управления миграцией
        self.sync_control_frame = ctk.CTkFrame(tab)
        self.sync_control_frame.grid(row=3, column=0, padx=5, pady=5, sticky="ew")

        self.sync_start_button = ctk.CTkButton(
            self.sync_control_frame, text="🚀 Начать перенос товаров", command=self.start_profile_migration,
            fg_color="#2eb82e", hover_color="#208020", text_color="white", width=200
        )
        self.sync_start_button.pack(side="left", padx=10, pady=8)

        self.sync_stop_button = ctk.CTkButton(
            self.sync_control_frame, text="Закончить выставляние", command=self.stop_pipeline,
            fg_color="#d32f2f", hover_color="#c2185b", text_color="white",
            state="disabled"
        )
        self.sync_stop_button.pack(side="left", padx=10, pady=8)

        # Прогресс миграции
        self.sync_progress_frame = ctk.CTkFrame(tab)
        self.sync_progress_frame.grid(row=4, column=0, padx=5, pady=5, sticky="ew")

        self.sync_progress_bar = ctk.CTkProgressBar(self.sync_progress_frame)
        self.sync_progress_bar.pack(fill="x", padx=10, pady=(8, 4))
        self.sync_progress_bar.set(0)

        self.sync_status_label = ctk.CTkLabel(self.sync_progress_frame, text="Готов к работе. Выберите профиль и нажмите 'Сканировать'.")
        self.sync_status_label.pack(side="left", padx=10, pady=4)

    # =========================================================================
    # ОБРАБОТЧИКИ СОБЫТИЙ СИНХРОНИЗАЦИИ ПРОФИЛЕЙ
    # =========================================================================
    def on_saved_profile_selected(self, choice):
        if choice and choice != "(Нет сохраненных)":
            self.sync_url_entry.delete(0, "end")
            self.sync_url_entry.insert(0, choice)
            self.update_profile_stats_display(choice)

    def update_profile_stats_display(self, username_or_url: str):
        username = ProfileScanner.extract_username(username_or_url)
        stats = self.profile_store.get_stats(username)
        
        self.stat_total_card.configure(text=f"Всего в каталоге: {stats['total']}")
        self.stat_pending_card.configure(text=f"Ожидают переноса: {stats['pending']}")
        self.stat_published_card.configure(text=f"Уже перенесено: {stats['published']}")
        self.stat_failed_card.configure(text=f"Ошибок/Пропущено: {stats['failed'] + stats['skipped']}")

    def refresh_saved_profiles_dropdown(self):
        saved = self.profile_store.get_saved_profiles()
        values = saved if saved else ["(Нет сохраненных)"]
        self.sync_saved_combo.configure(values=values)

    def start_profile_scan(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Конвейер уже выполняется!")
            return

        raw_input = self.sync_url_entry.get().strip()
        if not raw_input:
            messagebox.showwarning("Ошибка", "Введите ссылку на профиль продавца или его логин!")
            return

        self.is_running = True
        self.sync_scan_button.configure(state="disabled")
        self.sync_status_label.configure(text="🔍 Сканирование каталога продавца...")
        
        threading.Thread(target=self._run_profile_scan_thread, args=(raw_input,), daemon=True).start()

    def _run_profile_scan_thread(self, raw_input: str):
        poster = None
        prevent_sleep()
        try:
            username = ProfileScanner.extract_username(raw_input)
            logger.info(f"Запуск сканирования профиля '{username}'...")
            
            use_secondary = self.secondary_monitor_var.get()
            hidden = self.sync_scan_hidden_var.get()
            
            poster = ShafaPoster(use_secondary_monitor=use_secondary, hidden_mode=hidden)
            scanned = self.profile_scanner.scan_profile_items(
                username,
                driver=poster.driver,
                progress_callback=lambda count, step: self.after(0, lambda: self.sync_status_label.configure(
                    text=f"🔍 Сканирование '{username}': найдено {count} объявлений..."
                ))
            )

            new_cnt, total_cnt = self.profile_store.upsert_scanned_items(username, scanned)
            logger.info(f"✅ Сканирование завершено: {total_cnt} товаров найдено ({new_cnt} новых добавлено в очередь).")

            self.after(0, lambda u=username: self.update_profile_stats_display(u))
            self.after(0, self.refresh_saved_profiles_dropdown)
            self.after(0, lambda: self.sync_status_label.configure(
                text=f"✅ Сканирование '{username}' завершено: всего {total_cnt} шт. (новых {new_cnt} шт.)"
            ))

        except Exception as e:
            logger.error(f"Ошибка при сканировании профиля: {e}", exc_info=True)
            self.after(0, lambda: self.sync_status_label.configure(text=f"❌ Ошибка сканирования: {e}"))
        finally:
            if poster:
                poster.close()
            allow_sleep()
            self.is_running = False
            self.after(0, lambda: self.sync_scan_button.configure(state="normal"))

    def start_reconciliation(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Конвейер уже выполняется!")
            return

        raw_input = self.sync_url_entry.get().strip()
        if not raw_input:
            messagebox.showwarning("Ошибка", "Сначала выберите или отсканируйте профиль!")
            return

        username = ProfileScanner.extract_username(raw_input)
        self.is_running = True
        self.reconcile_button.configure(state="disabled")
        self.sync_status_label.configure(text="✨ Сверка с вашим личным кабинетом...")

        threading.Thread(target=self._run_reconciliation_thread, args=(username,), daemon=True).start()

    def _run_reconciliation_thread(self, username: str):
        poster = None
        try:
            poster = ShafaPoster(use_secondary_monitor=False, hidden_mode=True)
            if not poster.is_authorized():
                poster.reveal_window()
                user_agreed = self.request_login_dialog()
                if not user_agreed or not poster.is_authorized():
                    logger.error("Авторизация не подтверждена. Сверка отменена.")
                    return

            target_items = self.profile_scanner.scan_target_account_listings(poster.driver)
            matched = self.profile_store.reconcile_listings(username, target_items)

            logger.info(f"✨ Автосверка завершена! Автоматически помечено как опубликованные: {matched} шт.")
            self.after(0, lambda u=username: self.update_profile_stats_display(u))
            self.after(0, lambda: self.sync_status_label.configure(
                text=f"✨ Сверка завершена: распознано {matched} ранее выставленных товаров."
            ))
        except Exception as e:
            logger.error(f"Ошибка при сверке аккаунтов: {e}", exc_info=True)
        finally:
            if poster:
                poster.close()
            self.is_running = False
            self.after(0, lambda: self.reconcile_button.configure(state="normal"))

    def start_profile_migration(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Конвейер уже выполняется!")
            return

        raw_input = self.sync_url_entry.get().strip()
        if not raw_input:
            messagebox.showwarning("Ошибка", "Сначала укажите профиль-источник!")
            return

        username = ProfileScanner.extract_username(raw_input)
        stats = self.profile_store.get_stats(username)
        if stats["pending"] == 0:
            messagebox.showinfo("Инфо", f"В профиле '{username}' нет товаров со статусом 'Ожидают переноса'!")
            return

        # Парсим размер порции
        batch_choice = self.batch_size_combo.get()
        batch_limit = None
        if "10" in batch_choice: batch_limit = 10
        elif "20" in batch_choice: batch_limit = 20
        elif "50" in batch_choice: batch_limit = 50

        self.is_running = True
        self.should_stop = False
        self.sync_start_button.configure(state="disabled")
        self.sync_stop_button.configure(state="normal")
        self.start_button.configure(state="disabled")

        threading.Thread(
            target=self._run_migration_thread,
            args=(
                username,
                batch_limit,
                self.deactivate_var.get(),
                self.sync_autopublish_var.get(),
                self.secondary_monitor_var.get(),
                self.sync_hidden_var.get()
            ),
            daemon=True
        ).start()

    def _run_migration_thread(self, username, batch_limit, deactivate_flag, autopublish_flag, use_secondary_flag, hidden_flag):
        logger.info(f"=== ЗАПУСК МИГРАЦИИ ПРОФИЛЯ '{username}' ===")
        prevent_sleep()
        prepare_image_folder(SAVE_FOLDER)

        pending_items = self.profile_store.get_items_by_status(username, status="pending", limit=batch_limit)
        total = len(pending_items)
        processed = 0
        success = 0
        failed = 0

        poster = None
        parser = None
        try:
            poster = ShafaPoster(use_secondary_monitor=use_secondary_flag, hidden_mode=hidden_flag)
            parser = ShafaParser()

            # Проверка логина
            if not poster.is_authorized():
                if hidden_flag:
                    poster.reveal_window(use_secondary_monitor=use_secondary_flag)
                user_agreed = self.request_login_dialog()
                if not user_agreed or not poster.is_authorized():
                    logger.error("Авторизация не подтверждена. Миграция остановлена.")
                    return

            for item in pending_items:
                if self.should_stop:
                    logger.info(f"Миграция профиля '{username}' мягко остановлена пользователем.")
                    break

                item_id = item["item_id"]
                url = item["url"]
                logger.info(f"\n--- ПЕРЕНОС ТОВАРА #{item_id}: {url} ---")
                self.after(0, lambda t=item.get('title', item_id): self.sync_status_label.configure(
                    text=f"⏳ Выставление ({processed + 1}/{total}): {t[:50]}..."
                ))

                try:
                    product_data = parser.parse_item(url, fallback_driver=poster.driver)
                    processed_images = prepare_images_for_upload(product_data.downloaded_images, CROPPED_FOLDER)
                    poster.publish(product_data, processed_images, deactivate_flag, autopublish_flag)

                    # Атомарная фиксация статуса в базе
                    self.profile_store.mark_item_status(username, item_id, "published")
                    success += 1
                    processed += 1
                    logger.info(f"✅ Товар #{item_id} успешно перенесен!")

                except Exception as e:
                    logger.error(f"❌ Ошибка переноса товара #{item_id}: {e}", exc_info=True)
                    self.profile_store.mark_item_status(username, item_id, "failed", error=str(e))
                    failed += 1
                    processed += 1

                self.after(0, lambda u=username: self.update_profile_stats_display(u))
                self.after(0, lambda p=processed, t=total: self.sync_progress_bar.set(p / t if t > 0 else 0))

            if poster and hidden_flag and not autopublish_flag:
                poster.reveal_window(use_secondary_monitor=use_secondary_flag)

            logger.info(f"\n=== МИГРАЦИЯ ПРОФИЛЯ '{username}' ЗАВЕРШЕНА (Успешно: {success}, Ошибок: {failed}) ===")
            self.after(0, lambda: self.sync_status_label.configure(
                text=f"✅ Готово! Успешно перенесено: {success}, Ошибок: {failed}"
            ))

        except Exception as e:
            logger.error(f"Критическая ошибка миграции: {e}", exc_info=True)
        finally:
            if parser:
                parser.close()
            allow_sleep()
            self.is_running = False
            self.after(0, lambda: self.sync_start_button.configure(state="normal"))
            self.after(0, lambda: self.sync_stop_button.configure(state="disabled", text="Закончить выставляние"))
            self.after(0, lambda: self.start_button.configure(state="normal"))

    # =========================================================================
    # ОБЩИЕ МЕТОДЫ И ПОШТУЧНЫЙ КОНВЕЙЕР
    # =========================================================================
    def update_stats_display(self, processed, total, success, failed, avg_time):
        self.stats_label.configure(text=f"Всего: {processed}/{total} | Успешно: {success} | Ошибок: {failed} | Среднее время: {avg_time} сек.")
        self.progress_bar.set(processed / total if total > 0 else 0)

    def request_login_dialog(self) -> bool:
        login_event = threading.Event()
        result = {"agreed": False}

        def on_continue():
            result["agreed"] = True
            login_event.set()
            dialog.destroy()

        def on_cancel():
            result["agreed"] = False
            login_event.set()
            dialog.destroy()

        def show_dialog():
            nonlocal dialog
            dialog = ctk.CTkToplevel(self)
            dialog.title("Требуется вход на Shafa.ua")
            dialog.geometry("460x220")
            dialog.resizable(False, False)
            dialog.attributes("-topmost", True)
            dialog.grab_set()

            label = ctk.CTkLabel(
                dialog,
                text="⚠️ Вы не авторизованы на Shafa.ua!\n\n"
                     "В открывшемся окне браузера войдите в свой аккаунт.\n"
                     "После успешного входа нажмите кнопку 'Я вошел, продолжить'.",
                font=("Arial", 13),
                wraplength=420,
                justify="center"
            )
            label.pack(pady=(20, 15), padx=20)

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=10)

            btn_ok = ctk.CTkButton(btn_frame, text="✅ Я вошел, продолжить", command=on_continue, fg_color="#2eb82e", hover_color="#208020")
            btn_ok.pack(side="left", padx=10)

            btn_stop = ctk.CTkButton(btn_frame, text="❌ Отмена", command=on_cancel, fg_color="#d32f2f", hover_color="#c2185b")
            btn_stop.pack(side="left", padx=10)

        dialog = None
        self.after(0, show_dialog)
        login_event.wait()
        return result["agreed"]

    def start_pipeline(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Конвейер уже запущен!")
            return
            
        urls_raw = self.url_textbox.get("1.0", "end").strip()
        if not urls_raw:
            messagebox.showwarning("Ошибка", "Список ссылок пуст!")
            return
            
        urls = [line.strip() for line in urls_raw.split("\n") if line.strip() and line.strip().startswith("http")]
        if not urls:
            messagebox.showwarning("Ошибка", "Не найдено валидных ссылок (должны начинаться с http)!")
            return
            
        self.is_running = True
        self.should_stop = False
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.sync_start_button.configure(state="disabled")
        
        self.progress_bar.set(0)
        self.stats_label.configure(text=f"Всего: 0/{len(urls)} | Успешно: 0 | Ошибок: 0 | Среднее время: 0 сек.")
        
        threading.Thread(target=self.run_pipeline, args=(urls,), daemon=True).start()

    def stop_pipeline(self):
        if not self.is_running:
            return
        self.should_stop = True
        self.stop_button.configure(text="⏳ Завершаем текущий товар...", state="disabled")
        self.sync_stop_button.configure(text="⏳ Завершаем текущий товар...", state="disabled")
        logger.info("Получен сигнал остановки: конвейер завершит текущий товар и сохранит прогресс.")

    def run_pipeline(self, urls):
        logger.info("=== ЗАПУСК ПОТОКА АВТОМАТИЗАЦИИ ===")
        prevent_sleep()
        prepare_image_folder(SAVE_FOLDER)
        
        deactivate_flag = self.deactivate_var.get()
        autopublish_flag = self.autopublish_var.get()
        use_secondary_flag = self.secondary_monitor_var.get()
        hidden_flag = self.hidden_mode_var.get()
        
        total = len(urls)
        processed = 0
        success = 0
        failed = 0
        total_time = 0
        
        poster = None
        parser = None
        try:
            poster = ShafaPoster(use_secondary_monitor=use_secondary_flag, hidden_mode=hidden_flag)
            parser = ShafaParser()

            # Проверка логина
            if not poster.is_authorized():
                if hidden_flag:
                    poster.reveal_window(use_secondary_monitor=use_secondary_flag)
                user_agreed = self.request_login_dialog()
                if not user_agreed or not poster.is_authorized():
                    logger.error("Авторизация не подтверждена. Конвейер остановлен.")
                    return
            
            for url in urls:
                if self.should_stop:
                    logger.info("Конвейер остановлен пользователем.")
                    break
                    
                logger.info(f"\n--- ОБРАБОТКА ТОВАРА: {url} ---")
                start_time = time.perf_counter()
                
                product_data = None
                try:
                    product_data = parser.parse_item(url, fallback_driver=poster.driver)
                    save_product_to_txt(product_data, INFO_TXT_PATH)
                    save_product_to_json(product_data, INFO_JSON_PATH)
                except Exception as e:
                    logger.error(f"Ошибка сбора данных товара {url}: {e}", exc_info=True)
                    failed += 1
                    processed += 1
                    avg_time = round(total_time / processed, 2) if processed > 0 else 0
                    self.after(0, lambda p=processed, s=success, f=failed, a=avg_time: self.update_stats_display(p, total, s, f, a))
                    continue

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

            if poster and hidden_flag and not autopublish_flag:
                poster.reveal_window(use_secondary_monitor=use_secondary_flag)
            
        except Exception as e:
            logger.error(f"Критическая ошибка конвейера: {e}", exc_info=True)
        finally:
            if parser:
                parser.close()
            allow_sleep()
            self.is_running = False
            self.after(0, lambda: self.start_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="disabled", text="Закончить выставляние"))
            self.after(0, lambda: self.sync_start_button.configure(state="normal"))

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = ShafaApp()
    app.mainloop()