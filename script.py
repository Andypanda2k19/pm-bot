import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import logging
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from aiogram.enums import ParseMode
import os
import random

# Настройки
load_dotenv()
TOKEN = "8125187062:AAFGe_HFNxM3oTMwWuQYIwvem2ILEkcUj3o"
ADMIN_CHAT_ID = "665509096"

# Искомые коэффициенты (любой из этих)
TARGET_ODDS = {2.57, 1.83, 2.21}

# Соответствие классов элементов типам ставок
MARKET_TYPES = {
    "lv_market_results": "1-X-2",
    "lv_market-doubleChance": "Двойной шанс",
    "lv_market-overUnder": "Тотал",
    "lv_market-handicap": "Фора"
}

# Инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_market_name(element):
    """Определяем тип ставки по классам родительских элементов"""
    try:
        # Ищем родительский элемент с классом рынка
        market_element = element.find_element(By.XPATH, "./ancestor::div[contains(@class, 'lv_event_market')]")
        for class_name, market_name in MARKET_TYPES.items():
            if class_name in market_element.get_attribute("class"):
                return market_name
        return "Неизвестный тип"
    except:
        return "Неизвестный тип"


async def check_odds(match_element):
    """Проверяем коэффициенты и возвращаем найденные с типами ставок"""
    found_odds = []
    try:
        # Проверяем все коэффициенты в матче
        all_odds_elements = match_element.find_elements(By.CSS_SELECTOR, ".lv_stake_odd")

        for odd_element in all_odds_elements:
            try:
                odd_text = odd_element.text
                if not odd_text:
                    continue

                num = float(odd_text)
                if num in TARGET_ODDS:
                    market_type = await get_market_name(odd_element)
                    found_odds.append({
                        "value": num,
                        "type": market_type,
                        "element": odd_element
                    })
            except ValueError:
                continue

    except Exception as e:
        logger.warning(f"Ошибка проверки коэффициентов: {e}")

    return found_odds


async def parse_shadow_dom():
    """Парсинг данных из Shadow DOM"""
    driver = None
    try:
        # Настройка Chrome
        chrome_options = Options()
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"--user-data-dir=/tmp/chrome_profile_{random.randint(1,10000)}")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # Инициализация драйвера
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        logger.info("Открываю страницу PM.BY...")
        driver.get("https://pm.by/ru/sport/live/football/flt-IntcIjFcIjp7fX0i-sub")

        # Ожидание загрузки Shadow DOM
        wait = WebDriverWait(driver, 20)
        shadow_host = wait.until(
            EC.presence_of_element_located((By.TAG_NAME, "sport-latino-view"))
        )

        # Получаем Shadow Root
        shadow_root = driver.execute_script(
            "return arguments[0].shadowRoot", shadow_host
        )

        if not shadow_root:
            logger.error("Не удалось получить Shadow Root")
            return None

        # Поиск всех матчей
        matches = []
        match_blocks = shadow_root.find_elements(By.CSS_SELECTOR, ".lv_event_row")

        for match in match_blocks:
            try:
                teams = match.find_element(By.CSS_SELECTOR, ".lv_teams").text
                time_elem = match.find_element(By.CSS_SELECTOR, ".lv_event_time")
                time = time_elem.get_attribute("title") or time_elem.text

                # Получаем текущий счет
                try:
                    score = match.find_element(By.CSS_SELECTOR, ".dg_live_score").text
                except:
                    score = "Счет неизвестен"

                # Проверяем коэффициенты
                found_odds = await check_odds(match)

                matches.append({
                    "teams": teams,
                    "time": time,
                    "score": score,
                    "found_odds": found_odds,
                    "has_target_odds": len(found_odds) > 0
                })

            except Exception as e:
                logger.warning(f"Ошибка обработки матча: {e}")
                continue

        return matches

    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None
    finally:
        if driver:
            driver.quit()


async def monitor_matches():
    """Мониторинг матчей каждые 30 секунд"""
    while True:
        try:
            logger.info("Начинаю проверку матчей...")
            matches = await parse_shadow_dom()

            if matches:
                target_matches = [m for m in matches if m['has_target_odds']]

                if target_matches:
                    message = "🎯 Найдены матчи с нужными коэффициентами:\n\n"
                    for match in target_matches:
                        message += (
                            f"⚽ <b>{match['teams']}</b>\n"
                            f"⏰ <b>Время:</b> {match['time']}\n"
                        )

                        # Группируем коэффициенты по типам ставок
                        odds_by_type = {}
                        for odd in match['found_odds']:
                            if odd['type'] not in odds_by_type:
                                odds_by_type[odd['type']] = []
                            odds_by_type[odd['type']].append(str(odd['value']))

                        # Добавляем информацию о коэффициентах
                        for market_type, odds in odds_by_type.items():
                            message += f"💰 <b>{market_type}:</b> {', '.join(odds)}\n"

                        message += "\n"

                    await bot.send_message(ADMIN_CHAT_ID, message, parse_mode="HTML")
                else:
                    logger.info("Матчи с нужными коэффициентами не найдены")
            else:
                logger.warning("Не удалось получить данные о матчах")

            await asyncio.sleep(120)

        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(120)


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🤖 <b>Бот для мониторинга коэффициентов PM.BY</b>\n\n"
        "Идет постоянная проверка матчей на коэффициенты: 2.57, 1.83 или 2.21\n\n",
        parse_mode="HTML"
    )


@dp.message(Command("check"))
async def manual_check(message: types.Message):
    msg = await message.answer("🔄 Проверяю матчи вручную...")
    matches = await parse_shadow_dom()

    if not matches:
        await msg.edit_text("❌ Не удалось получить данные о матчах")
        return

    target_matches = [m for m in matches if m['has_target_odds']]
    if not target_matches:
        await msg.edit_text("ℹ️ Матчи с нужными коэффициентами не найдены")
        return

    message = "🔍 <b>Найдены матчи с нужными коэффициентами:</b>\n\n"
    for match in target_matches[:5]:  # Ограничиваем 5 матчами
        message += (
            f"⚽ <b>{match['teams']}</b>\n"
            f"⏰ <b>Время:</b> {match['time']}\n"
            f"🔢 <b>Счет:</b> {match['score']}\n"
        )

        # Группируем коэффициенты по типам
        odds_by_type = {}
        for odd in match['found_odds']:
            if odd['type'] not in odds_by_type:
                odds_by_type[odd['type']] = []
            odds_by_type[odd['type']].append(str(odd['value']))

        for market_type, odds in odds_by_type.items():
            message += f"💰 <b>{market_type}:</b> {', '.join(odds)}\n"

        message += "\n"

    await msg.edit_text(message, parse_mode="HTML")


async def main():
    # Запускаем мониторинг в фоне
    asyncio.create_task(monitor_matches())

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
