import os
import time
import shutil
from PIL import Image
from src.utils.logger import logger

def prepare_images_for_upload(input_paths: list, output_folder: str) -> list:
    """Обрезает 10 пикселей снизу у каждой картинки и сохраняет в уникальную подпапку.
    
    Использует уникальные подпапки для каждого товара, предотвращая ошибку блокировки
    файлов Windows ([WinError 32]), когда предыдущие открытые вкладки Chrome удерживают фото.
    """
    logger.info("Подготовка фотографий для обхода антифрод-системы...")
    
    os.makedirs(output_folder, exist_ok=True)

    # 1. Безопасная очистка старых временных подпапок (с подавлением ошибок блокировки открытыми вкладками)
    try:
        for entry in os.scandir(output_folder):
            try:
                if entry.is_dir():
                    shutil.rmtree(entry.path, ignore_errors=True)
                elif entry.is_file():
                    try:
                        os.unlink(entry.path)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

    # 2. Создаем уникальную подпапку под текущий товар
    batch_id = int(time.time() * 1000)
    item_folder = os.path.abspath(os.path.join(output_folder, f"item_{batch_id}"))
    os.makedirs(item_folder, exist_ok=True)

    processed_paths = []
    for path in input_paths:
        if not os.path.exists(path):
            continue
            
        try:
            filename = os.path.basename(path)
            save_path = os.path.join(item_folder, filename)
            
            with Image.open(path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                width, height = img.size
                
                # Отрезаем 10 пикселей снизу
                new_height = max(1, height - 10)
                cropped = img.crop((0, 0, width, new_height))
                cropped.save(save_path, "JPEG", quality=95, progressive=False)
                
            processed_paths.append(save_path)
            
        except Exception as e:
            logger.error(f"Не удалось обработать фото {path}: {e}")
            
    logger.info(f"Успешно обработано фотографий: {len(processed_paths)}")
    return processed_paths