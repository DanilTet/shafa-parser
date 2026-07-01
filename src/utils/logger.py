import logging

def setup_logger():
    # Создаем логгер с именем нашего проекта
    logger = logging.getLogger("ShafaParser")
    logger.setLevel(logging.DEBUG)

    # Настраиваем вывод в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Задаем формат: [Время] | [Уровень] | Сообщение
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(formatter)

    # Чтобы логи не дублировались при перезапусках
    if not logger.handlers:
        logger.addHandler(console_handler)

    return logger

# Экспортируем готовый объект логгера
logger = setup_logger()