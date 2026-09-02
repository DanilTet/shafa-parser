"""
Unit-тесты для confirm_publish() в poster.py.
Тестируют логику навигации без реального браузера — через Mock-объекты.
"""
import re
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from selenium.common.exceptions import TimeoutException


# ─────────────────────────────────────────────────────────────
# Вспомогательная функция: создаёт mock-постер с нужным driver
# ─────────────────────────────────────────────────────────────
def _make_poster_with_mock_driver(url_sequence: list[str]):
    """
    Создаёт экземпляр ShafaPoster с полностью замоканным driver.
    url_sequence — список URL которые будет возвращать driver.current_url
    при последовательных вызовах.
    """
    # Патчим ChromeDriverManager и webdriver.Chrome чтобы не открывать браузер
    with patch("src.publisher.poster.ChromeDriverManager"), \
         patch("src.publisher.poster.webdriver.Chrome") as mock_chrome_cls:

        mock_driver = MagicMock()
        mock_chrome_cls.return_value = mock_driver

        # Очередь URL
        url_iter = iter(url_sequence)
        type(mock_driver).current_url = PropertyMock(side_effect=lambda: next(url_iter, url_sequence[-1]))

        from src.publisher.poster import ShafaPoster
        poster = ShafaPoster.__new__(ShafaPoster)
        poster.driver = mock_driver
        poster.hidden_mode = True
        poster.use_secondary_monitor = False
        from selenium.webdriver.support.ui import WebDriverWait
        poster.wait = WebDriverWait(mock_driver, 15)
        poster._initial_tab_consumed = True
        return poster, mock_driver


# ─────────────────────────────────────────────────────────────
# Тест 1: Извлечение my_item_id из URL
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url,expected_id", [
    ("https://shafa.ua/uk/men/futbolki/217094977-polo-charles-tyrwhitt", "217094977"),
    ("https://shafa.ua/uk/women/sukni/200000001-suknya-zhinocha-elegantna", "200000001"),
    ("https://shafa.ua/uk/men/rubashki/rubashki/999999999-sorochka-bila", "999999999"),
    ("https://shafa.ua/uk/new", None),       # форма — ID нет
    ("https://shafa.ua/uk/p/217094977", None),  # промежуточный /p/ — нет слага
    (None, None),
    ("", None),
])
def test_extract_item_id_from_url(url, expected_id):
    """Проверяем regex-извлечение ID из финального URL товара."""
    result = None
    if url:
        m = re.search(r'/(\d+)-[a-zA-Z0-9_-]+', url)
        result = m.group(1) if m else None
    assert result == expected_id, f"URL '{url}': ожидался ID '{expected_id}', получен '{result}'"


# ─────────────────────────────────────────────────────────────
# Тест 2: Извлечение ID из href /uk/p/ID (Сторінка товару)
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("href,expected_id", [
    ("/uk/p/217094977", "217094977"),
    ("https://shafa.ua/uk/p/200000001", "200000001"),
    ("/uk/new/217094977/thanks", None),   # thanks — не /p/
    ("", None),
])
def test_extract_id_from_p_href(href, expected_id):
    """Проверяем regex извлечения ID из href ссылки 'Сторінка товару'."""
    m = re.search(r'/p/(\d+)', href)
    result = m.group(1) if m else None
    assert result == expected_id


# ─────────────────────────────────────────────────────────────
# Тест 3: _is_final_product_url — логика проверки финального URL
# ─────────────────────────────────────────────────────────────
def _make_url_checker(extracted_id: str):
    """Возвращает ту же lambda что используется в confirm_publish."""
    def _is_final(d):
        url = d.current_url
        if "/p/" in url or "/new" in url:
            return False
        if extracted_id and extracted_id in url:
            return True
        return "shafa.ua" in url and "/new" not in url and "/p/" not in url
    return _is_final


@pytest.mark.parametrize("url,extracted_id,expected", [
    ("https://shafa.ua/uk/men/futbolki/217094977-polo", "217094977", True),   # финальный
    ("https://shafa.ua/uk/p/217094977", "217094977", False),                   # промежуточный /p/
    ("https://shafa.ua/uk/new/217094977/thanks", "217094977", False),          # страница thanks
    ("https://shafa.ua/uk/new", None, False),                                  # форма
    ("https://shafa.ua/uk/men/futbolki/217094977-polo", None, True),           # без extracted_id — fallback
    ("https://google.com", "217094977", False),                                # не shafa
])
def test_is_final_product_url(url, extracted_id, expected):
    mock_driver = MagicMock()
    type(mock_driver).current_url = PropertyMock(return_value=url)
    checker = _make_url_checker(extracted_id)
    assert checker(mock_driver) == expected, f"URL '{url}', id={extracted_id}: ожидалось {expected}"


# ─────────────────────────────────────────────────────────────
# Тест 4: confirm_publish — fallback при ошибке (возвращает URL из кабинета)
# ─────────────────────────────────────────────────────────────
def test_confirm_publish_returns_none_on_full_failure():
    """Если driver бросает исключение на каждом шаге — возвращаем None."""
    with patch("src.publisher.poster.ChromeDriverManager"), \
         patch("src.publisher.poster.webdriver.Chrome"):
        from src.publisher.poster import ShafaPoster
        poster = ShafaPoster.__new__(ShafaPoster)

        mock_driver = MagicMock()
        mock_driver.current_url = "https://shafa.ua/uk/new"  # остались на форме
        mock_driver.execute_script.side_effect = Exception("Network error")

        poster.driver = mock_driver
        poster.hidden_mode = True

        from selenium.webdriver.support.ui import WebDriverWait
        poster.wait = MagicMock()
        poster.wait.until.side_effect = TimeoutException("Timeout")

        result = poster.confirm_publish()
        # Кабинет /new → fallback не должен вернуть этот URL
        assert result is None


# ─────────────────────────────────────────────────────────────
# Тест 5: confirm_publish — fallback возвращает URL если не /new
# ─────────────────────────────────────────────────────────────
def test_confirm_publish_fallback_returns_non_new_url():
    """Если что-то пошло не так, но URL уже не /new — возвращаем fallback."""
    with patch("src.publisher.poster.ChromeDriverManager"), \
         patch("src.publisher.poster.webdriver.Chrome"):
        from src.publisher.poster import ShafaPoster
        poster = ShafaPoster.__new__(ShafaPoster)

        mock_driver = MagicMock()
        # Допустим кнопка "Додати річ" не нашлась, но страница уже сменилась
        type(mock_driver).current_url = PropertyMock(
            return_value="https://shafa.ua/uk/men/futbolki/217094977-polo-charles"
        )
        poster.driver = mock_driver
        poster.hidden_mode = True

        from selenium.webdriver.support.ui import WebDriverWait
        poster.wait = MagicMock()
        poster.wait.until.side_effect = TimeoutException("Timeout")

        result = poster.confirm_publish()
        assert result == "https://shafa.ua/uk/men/futbolki/217094977-polo-charles"
