import os
import shutil
from PIL import Image
from src.utils.logger import logger

def prepare_images_for_upload(input_paths: list, output_folder: str) -> list:
    """Обрезает 10 пикселей снизу у каждой картинки и сохраняет в новую папку."""
    logger.info("Подготовка фотографий для обхода антифрод-системы...")
    
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    processed_paths = []
    for path in input_paths:
        if not os.path.exists(path):
            continue
            
        try:
            filename = os.path.basename(path)
            img = Image.open(path)
            width, height = img.size
            
            # Отрезаем 10 пикселей снизу
            cropped = img.crop((0, 0, width, height - 10))
            
            save_path = os.path.join(output_folder, filename)
            cropped.save(save_path, "JPEG", quality=95)
            processed_paths.append(save_path)
            
        except Exception as e:
            logger.error(f"Не удалось обработать фото {path}: {e}")
            
    logger.info(f"Успешно обработано фотографий: {len(processed_paths)}")
    return processed_paths