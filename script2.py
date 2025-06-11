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
import time
import traceback
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import StaleElementReferenceException
import hashlib
from logging.handlers import RotatingFileHandler
import uuid


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



handler = RotatingFileHandler("bot.log", maxBytes=5_000_000, backupCount=3)

def clean_tmp_older_than(minutes=30):
    now = time.time()
    tmp_dir = "/tmp"
    for filename in os.listdir(tmp_dir):
        filepath = os.path.join(tmp_dir, filename)
        if os.path.isfile(filepath):
            if now - os.path.getmtime(filepath) > minutes * 60:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

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

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-application-cache")
    chrome_options.add_argument("--disk-cache-size=0")
    chrome_options.add_argument(f"--user-data-dir=/tmp/chrome-data-{uuid.uuid4()}")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def wait_for_element(driver, by, selector, timeout=20, poll_frequency=0.5, logger=None):
    """
    Универсальная функция ожидания элемента с логами.

    :param driver: Selenium WebDriver
    :param by: Метод поиска (By.CSS_SELECTOR, By.XPATH и т.п.)
    :param selector: Строка селектора
    :param timeout: Максимальное время ожидания в секундах
    :param poll_frequency: Частота проверки в секундах
    :param logger: Логгер, если есть
    :return: WebElement или None если не найден
    """
    start_time = time.time()
    while True:
        try:
            element = driver.find_element(by, selector)
            if logger:
                elapsed = time.time() - start_time
                logger.info(f"Элемент найден: {selector} через {elapsed:.1f} секунд")
            return element
        except Exception:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                if logger:
                    logger.error(f"Не удалось найти элемент: {selector} за {timeout} секунд")
                return None
            time.sleep(poll_frequency)

# Пример использования в твоём коде

async def parse_match_page(driver, event_url):
    logger.info(">>> Начало parse_match_page")
    result_template = {
        "teams": "",
        "score": "",
        "time": "",
        "found_odds": [],
        "has_target_odds": False,
        "event_url": event_url
    }

    wait = WebDriverWait(driver, 10)
    try:
        shadow_host = wait.until(EC.presence_of_element_located((By.TAG_NAME, "sport-latino-view")))
    except TimeoutException:
        logger.error("Элемент sport-latino-view не найден после ожидания")

    def get_shadow_element(driver, shadow_host, selector):
        return driver.execute_script(
            '''
            if (arguments[0].shadowRoot) {
                return arguments[0].shadowRoot.querySelector(arguments[1]);
            }
            return null;
            ''',
            shadow_host, selector
        )

    def get_shadow_elements(driver, shadow_host, selector):
        return driver.execute_script(
            '''
            if (arguments[0].shadowRoot) {
                return Array.from(arguments[0].shadowRoot.querySelectorAll(arguments[1]));
            }
            return [];
            ''',
            shadow_host, selector
        )

    try:
        driver.save_screenshot("debug_event_page.png")

        home_team_elem = get_shadow_element(driver, shadow_host, ".lv_team-home .lv_team_name_text")
        if not home_team_elem:
            raise Exception("Домашняя команда не найдена")
        home_team = home_team_elem.text

        away_team_elem = get_shadow_element(driver, shadow_host, ".lv_team-away .lv_team_name_text")
        if not away_team_elem:
            raise Exception("Гостевая команда не найдена")
        away_team = away_team_elem.text

        logger.info(f"Проверка команд: '{home_team}' vs '{away_team}'")


        time_info_elem = get_shadow_element(driver, shadow_host, ".lv_timer")
        time_info = time_info_elem.text if time_info_elem else ""

        # Если scores и markets тоже внутри Shadow DOM, их нужно доставать аналогично
        score_elements = get_shadow_elements(driver, shadow_host, 'div.lv_live_scores span.lv_score')

        if len(score_elements) >= 2:
            home_score = score_elements[0].text  # первый счёт (например, 3)
            away_score = score_elements[1].text  # второй счёт (например, 0)
            score = f"{home_score}:{away_score}"
            print("Счёт:", score)
        else:
            print("Не удалось найти элементы счёта")


        logger.info(f"Матч: {home_team} vs {away_team}, Счёт: {score}, Время: {time_info}")

        all_odds = []

        markets = get_shadow_elements(driver, shadow_host, 'div.lv_market')
        print(f"Найдено рынков: {len(markets)}")

        for i, market in enumerate(markets):
            try:

                # Получаем заголовок обычным методом
                try:
                    header_el = market.find_element(By.CSS_SELECTOR, 'span.lv_header_text')
                    header = header_el.text.strip()
                except:
                    continue

                if "Тотал" not in header:
                    continue

                # Получаем ставки обычным методом
                stakes = market.find_elements(By.CSS_SELECTOR, 'button.lv_marketStake')

                for stake in stakes:
                    try:
                        stake_holder = stake.find_element(By.CSS_SELECTOR, 'span.lv_stake_holder')
                        odd_factor_el = stake.find_element(By.CSS_SELECTOR, 'span.lv_stake_factor')

                        stake_text = stake_holder.text.strip()
                        odd_value = float(odd_factor_el.text.strip())


                        if odd_value in TARGET_ODDS:
                            odd_type = "Больше" if "Больше" in stake_text else "Меньше"
                            detail = f"{header} {stake_text}"
                            all_odds.append({
                                "value": odd_value,
                                "type": f"Тотал {odd_type}",
                                "detail": detail
                            })
                    except Exception as e:
                        print(f"Ошибка обработки ставки: {e}")
                        continue

            except Exception as e:
                print(f"Ошибка обработки рынка: {e}")
                continue

        print("Найденные кэфы:")
        for odd in all_odds:
            print(f"{odd['type']}: {odd['value']} ({odd['detail']})")
        if len(all_odds) > 0:
            await send_bet_to_chats(
                {
                    "teams": f"{home_team} - {away_team}",
                    "score": score,
                    "time": time_info,
                    "found_odds": all_odds,
                    "has_target_odds": True,
                    "event_url": event_url
                },
                all_odds
            )
        return {
            "teams": f"{home_team} - {away_team}",
            "score": score,
            "time": time_info,
            "found_odds": all_odds,
            "has_target_odds": len(all_odds) > 0,
            "event_url": event_url
        }

    except Exception:
        logger.error(f"Критическая ошибка в parse_match_page: {traceback.format_exc()}")
        return result_template





async def parse_shadow_dom(driver):
    BASE_URL = "https://pm.by/ru/sport/live/football/flt-IntcIjFcIjp7fX0i-sub"
    logger.info(f"Открытие страницы: {BASE_URL}")
    driver.get(BASE_URL)

    # Ждем загрузки shadow root
    shadow_host = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "sport-latino-view"))
    )

    # Получаем список матчей один раз, потом будем обновлять в цикле
    shadow_root = driver.execute_script("return arguments[0].shadowRoot", shadow_host)

    # Получаем изначальный список матчей
    match_blocks = shadow_root.find_elements(By.CSS_SELECTOR, ".lv_event_row")
    logger.info(f"Найдено матчей: {len(match_blocks)}")

    all_matches = []

    for i in range(len(match_blocks)):
        try:
            # Каждый раз обновляем shadow host и корень (потому что после перехода DOM меняется)
            shadow_host = driver.find_element(By.TAG_NAME, "sport-latino-view")
            shadow_root = driver.execute_script("return arguments[0].shadowRoot", shadow_host)

            # Обновляем список матчей
            match_blocks = shadow_root.find_elements(By.CSS_SELECTOR, ".lv_event_row")

            # Проверяем, что индекс i не выходит за границы
            if i >= len(match_blocks):
                logger.warning(f"[{i}] Индекс превышает количество матчей после обновления списка. Пропускаем.")
                continue

            match_element = match_blocks[i]

            match_link = driver.execute_script(
                "return arguments[0].querySelector('.lv_event_info.lv__pointer')", match_element
            )
            if not match_link:
                logger.warning(f"[{i}] Ссылка на матч не найдена.")
                continue

            
            driver.execute_script("arguments[0].click();", match_link)

            WebDriverWait(driver, 10).until(lambda d: "/event-details/" in d.current_url)
            match_url = driver.current_url
            if ")" in match_url.lower() or "(" in match_url.lower():
                logger.info(f"[{i}] Пропуск киберфутбола: {match_url}")
                i += 1
                driver.get(BASE_URL)
                WebDriverWait(driver, 10).until(lambda d: d.current_url == BASE_URL)
                WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
                time.sleep(0.5)
                continue

            logger.info(f"[{i + 1}] Перешли по клику: {match_url}")
            time.sleep(1)

            match_data = await parse_match_page(driver, match_url)
            if match_data:
                all_matches.append(match_data)

        except StaleElementReferenceException:
            logger.warning(f"[{i}] Устаревший элемент. Пропускаем.")
            continue
        except Exception as e:
            logger.error(f"[{i}] Ошибка при переходе: {traceback.format_exc()}")
        finally:
            driver.get(BASE_URL)
            WebDriverWait(driver, 10).until(lambda d: d.current_url == BASE_URL)
            WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(0.5)

    driver.quit()
    return all_matches






async def send_bet_to_chats22(match_info, found_odds):
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
        print(f"Ошибка отправки ставки: {e}")

async def send_bet_to_chats(match_info, found_odds):
    """Отправляет ставку в оба чата"""
    try:
        print(f"🔔 send_bet_to_chats вызван для: {match_info['teams']}")

        if not found_odds:
            print("⚠️ found_odds пустой!")
            return

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

        for odd in found_odds:
            message_text += f"• {odd['detail']}: {odd['value']}\n"

        # Генерируем стабильный bet_id через md5
        bet_id = hashlib.md5(f"{match_info['teams']}_{match_info['time']}".encode()).hexdigest()[:10]
        print(f"📌 bet_id: {bet_id} | Уже существует? {'Да' if bet_id in bet_messages else 'Нет'}")

        # Клавиатура для группового чата
        group_keyboard = InlineKeyboardBuilder()
        group_keyboard.row(
            InlineKeyboardButton(text="📌 Ссылка на событие", url=match_info['event_url'])
        )


        # Отправляем в групповой чат
        try:
            group_message = await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message_text,
                parse_mode="HTML",
                reply_markup=group_keyboard.as_markup()
            )
            print("✅ Успешно отправлено в GROUP_CHAT")
        except Exception as e:
            print(f"❌ Ошибка отправки в GROUP_CHAT: {e}")
            return


    except Exception as e:
        print(f"❌ Общая ошибка в send_bet_to_chats: {e}")



async def monitor_matches():
    """Мониторинг матчей"""
    DELAY_BETWEEN_MSGS = 10  # сек между ставками

    while True:
        try:
            logger.info("Проверяю матчи...")
            matches = await parse_shadow_dom(driver=setup_driver())

            if matches:
                for match in matches:
                    if match['has_target_odds']:
                        bet_id = str(hash(f"{match['teams']}_{match['time']}"))[:10]
                        if bet_id not in bet_messages:
                            await send_bet_to_chats(match, match['found_odds'])
                            await asyncio.sleep(DELAY_BETWEEN_MSGS)
                    else:
                        logger.info(f"Нет нужного коэф. для: {match['teams']}, ищу другой...")

            else:
                logger.warning("Не удалось получить данные о матчах")

            await asyncio.sleep(30)  # интервал между полными циклами
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(60)


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
        print(f"Ошибка обработки callback: {e}")
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
    matches = await parse_shadow_dom(driver=setup_driver())

    if not matches:
        await msg.edit_text("❌ Не удалось получить данные")
        return

    target_matches = [m for m in matches if m['has_target_odds']]
    if not target_matches:
        await msg.edit_text("ℹ️ Подходящих матчей не найдено")
        return

    await msg.edit_text("🔍 Найдены подходящие матчи. Отправляю в чаты...")
    for match in target_matches[:3]:
        bet_id = str(hash(f"{match['teams']}_{match['time']}"))[:10]
        if bet_id not in bet_messages:
            await send_bet_to_chats(match, match['found_odds'])


async def main():
    asyncio.create_task(monitor_matches())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
