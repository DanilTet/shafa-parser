import os

# Определяем корень проекта (поднимаемся на уровень выше папки src)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Папка данных
DATA_DIR = os.path.join(BASE_DIR, "data")

# Папка для сохранения фото
SAVE_FOLDER = os.path.join(DATA_DIR, "img")

# Пути к файлам результатов
INFO_TXT_PATH = os.path.join(DATA_DIR, "thing-info.txt")
INFO_JSON_PATH = os.path.join(DATA_DIR, "thing-info.json")

# Папка для обрезанных (уникализированных) фото
CROPPED_FOLDER = os.path.join(DATA_DIR, "img_cropped")

# Профиль Chrome
CHROME_PROFILE_PATH = os.path.join(DATA_DIR, "chrome_profile")

# Папка для реестров синхронизации профилей
SYNC_PROFILES_DIR = os.path.join(DATA_DIR, "sync_profiles")