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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройки
load_dotenv()
TOKEN = "8125187062:AAFGe_HFNxM3oTMwWuQYIwvem2ILEkcUj3o"
ADMIN_CHAT_ID = "-4917303136"
GROUP_CHAT_ID = "-1002605832321"

# Искомые коэффициенты
TARGET_ODDS = {2.57, 1.83, 2.21}

# Типы ставок
MARKET_TYPES = {
    "lv_market_results": "1-X-2",
    "lv_market-doubleChance": "Двойной шанс",
    "lv_market-overUnder": "Тотал",
    "lv_market-handicap": "Фора",
    "lv_market-bothTeamsToScore": "Обе забьют",
    "lv_market-correctScore": "Точный счет"
}

# Ключевые слова для киберфутбола
CYBER_FOOTBALL_KEYWORDS = ["fifa", "кибер", "cyber", "esports", "e-sports", "виртуальный", "virtual", "EA", "volta"]

# Инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Хранилище сообщений
bet_messages = {}

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def is_cyber_football(teams_text):
    """Проверяет, является ли матч киберфутболом"""
    if not teams_text:
        return False
    teams_lower = teams_text.lower()
    return any(keyword in teams_lower for keyword in CYBER_FOOTBALL_KEYWORDS)


async def get_market_name(element):
    """Определяет тип ставки по классам элементов"""
    try:
        market_element = element.find_element(By.XPATH, "./ancestor::div[contains(@class, 'lv_event_market')]")
        for class_name, market_name in MARKET_TYPES.items():
            if class_name in market_element.get_attribute("class"):
                return market_name
        return "Неизвестный тип"
    except:
        return "Неизвестный тип"


async def check_odds(match_element):
    """Проверяет коэффициенты в матче"""
    found_odds = []
    try:
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
    """Парсит данные из Shadow DOM"""
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"--user-data-dir=/tmp/chrome_profile_{random.randint(1, 10000)}")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        logger.info("Открываю страницу PM.BY...")
        driver.get("https://pm.by/ru/sport/live/football/flt-IntcIjFcIjp7fX0i-sub")

        wait = WebDriverWait(driver, 20)
        shadow_host = wait.until(EC.presence_of_element_located((By.TAG_NAME, "sport-latino-view")))
        shadow_root = driver.execute_script("return arguments[0].shadowRoot", shadow_host)

        if not shadow_root:
            logger.error("Не удалось получить Shadow Root")
            return None

        matches = []
        match_blocks = shadow_root.find_elements(By.CSS_SELECTOR, ".lv_event_row")

        for match in match_blocks:
            try:
                teams = match.find_element(By.CSS_SELECTOR, ".lv_teams").text
                if await is_cyber_football(teams):
                    logger.info(f"Пропускаем киберфутбол: {teams}")
                    continue

                time_elem = match.find_element(By.CSS_SELECTOR, ".lv_event_time")
                time = time_elem.get_attribute("title") or time_elem.text

                try:
                    score = match.find_element(By.CSS_SELECTOR, ".dg_live_score").text
                except:
                    score = "Счет неизвестен"

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


async def send_bet_to_chats(match_info, found_odds):
    """Отправляет ставку в оба чата"""
    try:
        # Формируем текст сообщения
        message_text = (
            f"----------------------------------\n"
            f"⚽ <b>{match_info['teams']}</b>\n"
            f"⏰ Время: {match_info['time']}\n"
            f"🔢 Счет: {match_info['score']}\n\n"
            f"💰 <b>Найдены коэффициенты:</b>\n"
        )

        # Добавляем коэффициенты
        odds_by_type = {}
        for odd in found_odds:
            if odd['type'] not in odds_by_type:
                odds_by_type[odd['type']] = []
            odds_by_type[odd['type']].append(str(odd['value']))

        for market_type, odds in odds_by_type.items():
            message_text += f"• {market_type}: {', '.join(odds)}\n"

        # Клавиатура для группового чата
        group_keyboard = InlineKeyboardBuilder()
        group_keyboard.row(
            InlineKeyboardButton(text="🔄 В процессе", callback_data="empty")

        )

        # Клавиатура для админов
        admin_keyboard = InlineKeyboardBuilder()
        bet_id = str(hash(f"{match_info['teams']}_{match_info['time']}"))[:10]
        admin_keyboard.row(
            InlineKeyboardButton(text="✅ Подтвердить выигрыш",
                                 callback_data=f"set_result:win:{bet_id}"),
            InlineKeyboardButton(text="❌ Подтвердить проигрыш",
                                 callback_data=f"set_result:lose:{bet_id}"),
        )

        # Отправляем в групповой чат
        group_message = await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message_text,
            parse_mode="HTML",
            reply_markup=group_keyboard.as_markup()
        )

        # Отправляем в чат админов
        admin_message = await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📢 АДМИН | {message_text}",
            parse_mode="HTML",
            reply_markup=admin_keyboard.as_markup()
        )

        # Сохраняем ID сообщений
        bet_messages[bet_id] = {
            "teams": match_info['teams'],
            "group_message_id": group_message.message_id,
            "admin_message_id": admin_message.message_id,
            "text": message_text
        }

    except Exception as e:
        logger.error(f"Ошибка отправки ставки: {e}")


async def update_bet_status(teams, status):
    """Обновляет статус ставки в групповом чате"""
    try:
        if teams not in bet_messages:
            return False

        message_info = bet_messages[teams]
        status_text = {
            "win": "✅ Ставка ВЫИГРАЛА",
            "lose": "❌ Ставка ПРОИГРАЛА",
            "pending": "🔄 Ожидание результата"
        }.get(status, "🔄 Статус неизвестен")

        # Обновляем сообщение в группе
        await bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=message_info["group_message_id"],
            text=f"{status_text}\n\n{message_info['text']}",
            parse_mode="HTML"
        )

        # Обновляем сообщение у админов
        await bot.edit_message_text(
            chat_id=ADMIN_CHAT_ID,
            message_id=message_info["admin_message_id"],
            text=f"📢 АДМИН | {status_text}\n\n{message_info['text']}",
            parse_mode="HTML"
        )

        return True
    except Exception as e:
        logger.error(f"Ошибка обновления статуса: {e}")
        return False


async def monitor_matches():
    """Мониторинг матчей"""
    while True:
        try:
            logger.info("Проверяю матчи...")
            matches = await parse_shadow_dom()

            if matches:
                target_matches = [m for m in matches if m['has_target_odds']]
                if target_matches:
                    for match in target_matches:
                        if match['teams'] not in bet_messages:
                            await send_bet_to_chats(match, match['found_odds'])
                else:
                    logger.info("Подходящих матчей не найдено")
            else:
                logger.warning("Не удалось получить данные о матчах")

            await asyncio.sleep(120)
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(120)


@dp.callback_query(lambda c: c.data.startswith("set_result:"))
async def handle_admin_callback(callback: types.CallbackQuery):
    try:
        _, action, bet_id = callback.data.split(":", 2)

        if bet_id not in bet_messages:
            await callback.answer("Ставка не найдена")
            return

        message_info = bet_messages[bet_id]
        status_text = {
            "win": "✅ Ставка ВЫИГРАЛА",
            "lose": "❌ Ставка ПРОИГРАЛА",
            "pending": "🔄 Ожидание результата"
        }.get(action, "🔄 Статус неизвестен")

        # Обновляем сообщение в группе
        await bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=message_info["group_message_id"],
            text=f"{status_text}\n\n{message_info['text']}",
            parse_mode="HTML"
        )

        # Обновляем сообщение у админов
        await bot.edit_message_text(
            chat_id=ADMIN_CHAT_ID,
            message_id=message_info["admin_message_id"],
            text=f"📢 АДМИН | {status_text}\n\n{message_info['text']}",
            parse_mode="HTML"
        )

        await callback.answer(f"Статус обновлен: {action}")
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await callback.answer("Произошла ошибка")


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🤖 <b>Бот для мониторинга коэффициентов</b>\n\n"
        "Автоматически проверяет матчи на наличие нужных коэффициентов.\n"
        "Киберфутбол (FIFA) не учитывается.\n\n"
        "Используйте /check для ручной проверки.",
        parse_mode="HTML"
    )


@dp.message(Command("check"))
async def manual_check(message: types.Message):
    msg = await message.answer("🔄 Проверяю матчи...")
    matches = await parse_shadow_dom()

    if not matches:
        await msg.edit_text("❌ Не удалось получить данные")
        return

    target_matches = [m for m in matches if m['has_target_odds']]
    if not target_matches:
        await msg.edit_text("ℹ️ Подходящих матчей не найдено")
        return

    await msg.edit_text("🔍 Найдены подходящие матчи. Отправляю в чаты...")
    for match in target_matches[:3]:  # Ограничиваем 3 матчами
        await send_bet_to_chats(match, match['found_odds'])
        await asyncio.sleep(1)


async def main():
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())