from src.config import SAVE_FOLDER, CROPPED_FOLDER, INFO_TXT_PATH, INFO_JSON_PATH
from src.utils.file_utils import prepare_image_folder, save_product_to_txt, save_product_to_json
from src.utils.image_utils import prepare_images_for_upload
from src.scraper.parser import ShafaParser
from src.publisher.poster import ShafaPoster
from src.utils.logger import logger

def main():
    logger.info("=== ЗАПУСК СКРИПТА ПАРСИНГА И ПУБЛИКАЦИИ ===")
    
    # 1. Подготовка директорий
    prepare_image_folder(SAVE_FOLDER)

    while True:
        url = input("Введіть посилання (URL) на річ: ").strip()  
        if url.startswith("http://") or url.startswith("https://"):
            break
        logger.error("Введен некорректный URL. Необходимо 'http://' или 'https://'.")

    # === ЭТАП 1: ПАРСИНГ ===
    parser = ShafaParser()
    try:
        logger.info("--- СТАРТ ПАРСИНГА ---")
        product_data = parser.parse_item(url)

        save_product_to_txt(product_data, INFO_TXT_PATH)
        save_product_to_json(product_data, INFO_JSON_PATH)
        
    except Exception as e:
        logger.error(f"Ошибка во время парсинга: {e}", exc_info=True)
        return  # Если парсинг упал, дальше идти нет смысла
    finally:
        parser.close()

    # === ЭТАП 2: ОБРАБОТКА ФОТО ===
    logger.info("--- СТАРТ ОБРАБОТКИ ФОТО ---")
    processed_images = prepare_images_for_upload(product_data.downloaded_images, CROPPED_FOLDER)

    # === ЭТАП 3: ПУБЛИКАЦИЯ ===
    logger.info("--- СТАРТ ПУБЛИКАЦИИ ---")
    poster = ShafaPoster()
    try:
        poster.publish(product_data, processed_images)
        
        logger.info("=== ВСЕ БАЗОВЫЕ ЭТАПЫ ВЫПОЛНЕНЫ ===")
        input("👀 Посмотри на результат в браузере. Нажми ENTER здесь в консоли, чтобы закрыть браузер и завершить работу...")
        
    except Exception as e:
        logger.error(f"Ошибка во время публикации: {e}", exc_info=True)
    finally:
        poster.close()
        logger.info("=== ЗАВЕРШЕНИЕ РАБОТЫ СКРИПТА ===")

if __name__ == "__main__":
    main()