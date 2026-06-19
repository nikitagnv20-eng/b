"""
Бот для автопересылки объявлений с revolution-estate.bg в Telegram.

Что делает:
1. Заходит на страницу со списком объявлений (под наем, София).
2. Находит новые объявления (которые ещё не отправляли).
3. Заходит на страницу каждого объявления и вытаскивает: цену, район,
   этаж, площадь, изложение, отопление, телефон, фото.
4. Просит Claude API написать текст объявления в стиле вашего примера.
5. Отправляет готовый пост (текст + фото) вам в Telegram.

Настройка — см. README.md в этой же папке.
"""

import os
import json
import re
import time
import requests
from bs4 import BeautifulSoup

# ---------------- НАСТРОЙКИ ----------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8837144583:AAEScqV_UUtDtvObQ6syDWRxHud5eft6mFA")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")          # см. README, как узнать
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # ключ с console.anthropic.com

BASE_URL = "https://revolution-estate.bg"
LISTING_URL_TEMPLATE = BASE_URL + "/imoti-pod-naem/sofia?page={page}"
MAX_PAGES_PER_RUN = 3          # сколько страниц списка проверять за один запуск
SENT_FILE = "sent_listings.json"  # тут хранится история уже отправленных объявлений

# Пример, под стиль которого Claude будет оформлять текст
EXAMPLE_POST = """🏡✨ ТОП ОФЕРТА! ДВУСТАЕН АПАРТАМЕНТ ПОД НАЕМ В ЛОЗЕНЕЦ ✨🏡

🔥 Търсите уютен и просторен дом в един от най-предпочитаните квартали на София? Това предложение е за Вас!

📍 ж.к. Лозенец
💶 Наем: 770 € / месец
🏢 Етаж: 3 от 6
📐 Площ: 76 кв.м
☀️ Изложение: Изток
⚡ Отопление: Електричество
🛏️ Двустаен апартамент

📞0897881482"""

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ListingBot/1.0)"}

# ---------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------

def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent(sent_set):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_set), f, ensure_ascii=False, indent=2)


def get_listing_links(page):
    """Собирает ссылки на отдельные объявления со страницы списка."""
    url = LISTING_URL_TEMPLATE.format(page=page)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for a in soup.select("a[href*='/imot/']"):
        href = a.get("href")
        if href and "/imot/" in href:
            full = href if href.startswith("http") else BASE_URL + href
            links.add(full.split("?")[0])
    return list(links)


def extract_field(soup, label):
    """Ищет жирную подпись типа 'Етаж' и возвращает значение рядом с ней."""
    el = soup.find(string=re.compile(rf"^\s*{re.escape(label)}\s*$"))
    if not el:
        return None
    parent = el.find_parent()
    sib = parent.find_next_sibling() if parent else None
    if sib:
        return sib.get_text(strip=True)
    if parent and parent.next_sibling:
        return str(parent.next_sibling).strip()
    return None


def parse_listing(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    price_match = re.search(r"(\d[\d\s]*)\s*€", soup.get_text())
    price = (price_match.group(1).strip() + " €") if price_match else ""

    fields = {}
    for label in ["Регион", "Вид имот", "Етаж", "Площ", "Стаи", "Спални", "Бани", "Изложение", "Отопление"]:
        fields[label] = extract_field(soup, label)

    phone_el = soup.find("a", href=re.compile(r"^tel:"))
    phone = phone_el.get_text(strip=True) if phone_el else ""

    images = []
    for img in soup.select("img[src*='/images/estate/']"):
        src = img.get("src")
        if src and "placeholder" not in src and src not in images:
            images.append(src if src.startswith("http") else BASE_URL + src)

    return {
        "url": url,
        "title": title,
        "price": price,
        "fields": fields,
        "phone": phone,
        "images": images[:8],
    }


def generate_post_text(listing):
    prompt = f"""Ти си копирайтър на агенция за недвижими имоти. Напиши обява в социална мрежа \
на български език, СТРОГО следвайки стила, дължината, емоджитата и структурата на този пример:

ПРИМЕР:
{EXAMPLE_POST}

Данни за новия имот (използвай само това, не измисляй нищо):
Заглавие: {listing['title']}
Цена: {listing['price']}
Регион: {listing['fields'].get('Регион')}
Вид имот: {listing['fields'].get('Вид имот')}
Етаж: {listing['fields'].get('Етаж')}
Площ: {listing['fields'].get('Площ')}
Изложение: {listing['fields'].get('Изложение')}
Отопление: {listing['fields'].get('Отопление')}
Телефон: {listing['phone']}

Върни само текста на готовата обява, без обяснения."""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    ).strip()


def send_to_telegram(text, images):
    if not images:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=30,
        )
        return

    if len(images) == 1:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "photo": images[0], "caption": text},
            timeout=30,
        )
        return

    media = []
    for i, img_url in enumerate(images[:10]):
        item = {"type": "photo", "media": img_url}
        if i == 0:
            item["caption"] = text
        media.append(item)

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup",
        data={"chat_id": CHAT_ID, "media": json.dumps(media)},
        timeout=30,
    )


# ---------------- ОСНОВНОЙ ЗАПУСК ----------------

def main():
    if not CHAT_ID or not ANTHROPIC_API_KEY:
        print("Заполните переменные окружения TELEGRAM_CHAT_ID и ANTHROPIC_API_KEY перед запуском (см. README.md).")
        return

    sent = load_sent()
    new_links = []
    for page in range(1, MAX_PAGES_PER_RUN + 1):
        try:
            links = get_listing_links(page)
        except Exception as e:
            print(f"Ошибка на странице {page}: {e}")
            break
        if not links:
            break
        new_links.extend([l for l in links if l not in sent])

    print(f"Найдено новых объявлений: {len(new_links)}")

    for url in new_links:
        try:
            listing = parse_listing(url)
            text = generate_post_text(listing)
            send_to_telegram(text, listing["images"])
            sent.add(url)
            save_sent(sent)
            print(f"Отправлено: {url}")
            time.sleep(3)
        except Exception as e:
            print(f"Ошибка при обработке {url}: {e}")


if __name__ == "__main__":
    main()
