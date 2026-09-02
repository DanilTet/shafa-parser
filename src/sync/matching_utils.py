"""
Вспомогательные алгоритмы нормализации, распознавания категорий,
размеров и многофакторного сопоставления перевыставленных товаров (Relisting Protection).
"""
import re
import difflib

GARMENT_TYPES = {
    "hudi": {"hudi", "hoodie", "худі", "толстовка"},
    "svitshot": {"svitshot", "sweatshirt", "світшот"},
    "sorochka": {"sorochka", "rubashka", "shirt", "сорочка", "рубашка"},
    "futbolka": {"futbolka", "tshirt", "tee", "футболка"},
    "polo": {"polo", "поло"},
    "mayka": {"mayka", "tank", "майка"},
    "dzhinsi": {"dzhinsi", "jeans", "джинси", "джинсы"},
    "shtani": {"shtani", "bryuki", "pants", "trousers", "chinos", "штани", "брюки", "чиноси"},
    "shorti": {"shorti", "shorts", "шорти", "шорты"},
    "svetr": {"svetr", "sweater", "джемпер", "dzhemper", "пуловер", "pulover", "светр", "свитер", "kofta", "кофта"},
    "kurtka": {"kurtka", "jacket", "куртка", "вітровка", "vitrovka", "пуховик"},
    "bluza": {"bluza", "blouse", "блуза", "блузка"},
    "suknya": {"suknya", "plattia", "dress", "сукня", "плаття", "платье"},
    "spidnitsya": {"spidnitsya", "skirt", "спідниця", "юбка"},
    "krosivki": {"krosivki", "sneakers", "кросівки", "кроссовки", "кеди", "kedi"},
    "tufli": {"tufli", "shoes", "туфлі", "туфли", "черевики", "chereviki", "ботинки"},
    "remin": {"remin", "belt", "ремінь", "ремень", "пояс", "poyas"}
}

STOP_WORDS = {
    # Пол и аудитория
    "cholovichiy", "cholovicha", "choloviche", "cholovichi", "cholovik", "cholovikam", "choloviki",
    "zhinochiy", "zhinocha", "zhinoche", "zhinochi", "zhinka", "zhinkam", "zhinki",
    "uniseks", "unisex", "dityachiy", "dityacha", "dityache",
    # Описательные характеристики
    "rozmir", "size", "stan", "idealniy", "horoshiy", "noviy", "vintage", "vintazh", "original",
    "dlya", "vid", "bez", "kolir", "tsina", "super", "top", "brend", "brendu", "napis", "napisom",
    "print", "printom", "komir", "zamok", "gudziki",
    # Рукава и фасоны
    "dovgiy", "korotkiy", "rukav", "rukavom", "dovgim", "korotkim", "rukava",
    # Материалы
    "bavovna", "bavovnyaniy", "bavovnyana", "koton", "cotton", "poliester", "viskoza", "viscoza",
    "elastan", "lyon", "vovna", "akril", "shkira", "zamsha", "pure", "100",
    # Цвета
    "chorna", "chorniy", "chorne", "chorni", "bila", "biliy", "bile", "bili",
    "sira", "siriy", "sire", "siri", "sinya", "siniy", "sinye", "sini",
    "chervona", "chervoniy", "zelena", "zeleniy", "zhovta", "zhovtiy",
    "bezheva", "bezheviy", "korichneva", "korichneviy", "rozheva", "rozheviy",
    "blakitna", "blakitniy", "haki", "kamuflyazh",
    # Технические служебные слова Шафы
    "zapovneno", "zapovnena", "rezerv", "prodano", "bron"
}

LETTER_SIZES = {
    "xxxs": "xxxs", "xxs": "xxs", "xs": "xs", "s": "s", "m": "m", "l": "l",
    "xl": "xl", "xxl": "xxl", "2xl": "xxl", "xxxl": "xxxl", "3xl": "xxxl",
    "4xl": "xxxxl", "5xl": "xxxxxl"
}


def detect_garment_type(text: str) -> str | None:
    """Определяет категорию одежды по ссылке или названию."""
    if not text:
        return None
    lower = text.lower()
    for gtype, keywords in GARMENT_TYPES.items():
        for kw in keywords:
            if kw in lower:
                return gtype
    return None


def extract_item_sizes(text: str) -> set[str]:
    """Извлекает нормализованные размеры (международные, джинсовые, числовые) из текста."""
    if not text:
        return set()
    s = text.lower()
    found = set()

    # 1. Буквенные размеры (отдельные токены)
    tokens = re.split(r'[^a-z0-9]', s)
    for t in tokens:
        if t in LETTER_SIZES:
            found.add(LETTER_SIZES[t])

    # 2. Джинсовые W-размеры (например: w30, w32, 30w, 32w, 30w30l)
    w_matches = re.findall(r'(?:w(\d{2})|(\d{2})w)', s)
    for m in w_matches:
        val = m[0] or m[1]
        if 24 <= int(val) <= 46:
            found.add(f"w{val}")

    # 3. Числовые размеры после 'розмір'/'size'/etc
    num_matches = re.findall(r'(?:розмір|rozmir|size|р\.?)\s*[:\-]?\s*(\d{2})\b', s)
    for n in num_matches:
        if 32 <= int(n) <= 64:
            found.add(f"num_{n}")

    return found


def check_price_proximity(p1_str, p2_str, max_ratio: float = 0.35) -> bool:
    """
    Проверяет, не отличается ли цена слишком сильно (по умолчанию не более 35%).
    Если цена не указана у одного из товаров — не блокирует.
    """
    if not p1_str or not p2_str:
        return True
    try:
        p1 = float(re.sub(r'[^\d.]', '', str(p1_str)))
        p2 = float(re.sub(r'[^\d.]', '', str(p2_str)))
        if p1 <= 0 or p2 <= 0:
            return True
        diff = abs(p1 - p2) / max(p1, p2)
        return diff <= max_ratio
    except Exception:
        return True


def normalize_slug(url_or_slug: str) -> str:
    """Извлекает и нормализует слаг из URL товара (удаляет ID и спецсимволы)."""
    m = re.search(r'/\d+-([a-zA-Z0-9_-]+)', str(url_or_slug))
    slug = m.group(1) if m else str(url_or_slug)
    return re.sub(r'[^a-z0-9]', '', slug.lower())


def normalize_title(title: str) -> str:
    """Нормализует заголовок для сравнения."""
    return re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]', '', str(title).lower())


def is_relisted_match(item_a: dict, item_b: dict) -> tuple[bool, float, str]:
    """
    Многофакторная проверка: является ли item_b перевыставленной версией item_a.
    Возвращает (is_match: bool, score: float, reason: str).
    """
    url_a = item_a.get("url", "")
    title_a = item_a.get("title", "")
    text_a = f"{url_a} {title_a}"

    url_b = item_b.get("url", "")
    title_b = item_b.get("title", "")
    text_b = f"{url_b} {title_b}"

    # 1. Проверка категории одежды
    type_a = detect_garment_type(text_a)
    type_b = detect_garment_type(text_b)
    if type_a and type_b and type_a != type_b:
        return False, 0.0, "different_garment_type"

    # 2. Проверка размеров (если оба указали размеры и они не пересекаются — это разные товары)
    sizes_a = extract_item_sizes(text_a)
    sizes_b = extract_item_sizes(text_b)
    if sizes_a and sizes_b and not (sizes_a & sizes_b):
        return False, 0.0, "different_sizes"

    # 3. Проверка близости цены
    price_a = item_a.get("price")
    price_b = item_b.get("price")
    if not check_price_proximity(price_a, price_b, max_ratio=0.35):
        return False, 0.0, "wildly_different_price"

    # 4. Точное совпадение нормализованного слага
    slug_a_norm = normalize_slug(url_a)
    slug_b_norm = normalize_slug(url_b)
    if slug_a_norm and slug_b_norm and slug_a_norm == slug_b_norm:
        return True, 1.0, "exact_slug"

    # 5. Точное совпадение нормализованного названия
    title_a_norm = normalize_title(title_a)
    title_b_norm = normalize_title(title_b)
    if title_a_norm and title_b_norm and title_a_norm == title_b_norm:
        return True, 1.0, "exact_title"

    # 6. Пересечение значимых слов в слаге (бренды, модели)
    m_a = re.search(r'/\d+-([a-zA-Z0-9_-]+)', url_a)
    slug_a_raw = m_a.group(1) if m_a else url_a
    words_slug_a = set(re.findall(r'[a-zA-Z0-9]{3,}', slug_a_raw.lower())) - STOP_WORDS

    m_b = re.search(r'/\d+-([a-zA-Z0-9_-]+)', url_b)
    slug_b_raw = m_b.group(1) if m_b else url_b
    words_slug_b = set(re.findall(r'[a-zA-Z0-9]{3,}', slug_b_raw.lower())) - STOP_WORDS

    if words_slug_a and words_slug_b:
        common_slug = words_slug_a & words_slug_b
        if len(common_slug) >= 2:
            score = len(common_slug) / min(len(words_slug_a), len(words_slug_b))
            if score >= 0.75:
                return True, score, f"slug_overlap_{int(score*100)}"

    # 7. Нечеткое совпадение названий (Fuzzy SequenceMatcher)
    if title_a_norm and title_b_norm and len(title_a_norm) > 8 and len(title_b_norm) > 8:
        ratio = difflib.SequenceMatcher(None, title_a_norm, title_b_norm).ratio()
        if ratio >= 0.82:
            return True, ratio, f"fuzzy_title_{int(ratio*100)}"

    # 8. Пересечение слов в названии (кириллица + латиница)
    words_title_a = set(re.findall(r'[a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]{3,}', title_a.lower())) - STOP_WORDS
    words_title_b = set(re.findall(r'[a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]{3,}', title_b.lower())) - STOP_WORDS
    if words_title_a and words_title_b:
        common_title = words_title_a & words_title_b
        if len(common_title) >= 2:
            score = len(common_title) / min(len(words_title_a), len(words_title_b))
            if score >= 0.80:
                return True, score, f"title_words_{int(score*100)}"

    return False, 0.0, "no_match"
