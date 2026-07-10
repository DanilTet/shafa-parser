import os

# Определяем корень проекта (поднимаемся на уровень выше папки src)
# __file__ указывает на сам config.py
# os.path.dirname берет папку, в которой лежит файл
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Папка для сохранения фото (теперь внутри проекта: parser-shafa/data/img)
SAVE_FOLDER = os.path.join(BASE_DIR, "data", "img")

# Пути к файлам результатов (сохраняем их тоже в папку data, чтобы не мусорить в корне)
INFO_TXT_PATH = os.path.join(BASE_DIR, "data", "thing-info.txt")
INFO_JSON_PATH = os.path.join(BASE_DIR, "data", "thing-info.json")

# Папка для обрезанных (уникализированных) фото
CROPPED_FOLDER = os.path.join(BASE_DIR, "data", "img_cropped")

# Профиль Chrome теперь будет храниться внутри проекта: parser-shafa/data/chrome_profile
CHROME_PROFILE_PATH = os.path.join(BASE_DIR, "data", "chrome_profile")

# Локальная база объявлений профиля
MY_LISTINGS_PATH = os.path.join(BASE_DIR, "data", "my_listings.json")