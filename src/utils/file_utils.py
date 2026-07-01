import os
import shutil
import json
from src.models import Product

def prepare_image_folder(folder_path: str):
    """Удаляет старую папку с картинками и создает чистую."""
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)
    os.makedirs(folder_path, exist_ok=True)

def save_product_to_txt(product: Product, file_path: str):
    """Сохраняет текстовую версию для проверки (как в старом коде)."""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(product.title + "\n")
        if product.description:
            f.write(product.description + "\n")
        f.write(product.price + "\n")
        if product.condition:
            f.write(product.condition + "\n")
        else:
            f.write("Стан: немає даних\n")

def save_product_to_json(product: Product, file_path: str):
    """Сохраняет структурированные данные товара в JSON."""
    product_dict = {
        "title": product.title,
        "description": product.description,
        "price": product.price,
        "condition": product.condition,
        "brand": product.brand
    }
    # Добавляем динамические характеристики, если они есть
    if product.characteristics:
        product_dict.update(product.characteristics)

    with open(file_path, "w", encoding="utf-8") as f_json:
        json.dump(product_dict, f_json, ensure_ascii=False, indent=4)