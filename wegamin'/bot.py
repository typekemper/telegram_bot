import telebot
import os
import tempfile
from io import BytesIO
import sqlite3
from openai import OpenAI
import requests
import logging

# Замените 'YOUR_BOT_TOKEN' на токен вашего бота
bot = telebot.TeleBot('6772194248:AAEnBnmvXi3i92hPD8-EU3QtuEQmODZw4V0')

chat_history = {}
last_processed_message = {}

# Функция для создания таблицы api_keys
def create_api_key_table():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS api_keys
                      (chat_id INTEGER PRIMARY KEY, key TEXT)''')
    conn.commit()
    conn.close()

def save_api_key(message):
    api_key = message.text
    chat_id = message.chat.id

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Сохраняем новый API-ключ в базе данных
    cursor.execute('INSERT OR REPLACE INTO api_keys (chat_id, key) VALUES (?, ?)', (chat_id, api_key))
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, 'API-ключ успешно сохранен!')
    start_bot(message)

def delete_api_key(message):
    chat_id = message.chat.id

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Удаляем API-ключ из базы данных
    cursor.execute('DELETE FROM api_keys WHERE chat_id = ?', (chat_id,))
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, 'API-ключ успешно удален!')
    start_message(message)

def get_api_key(chat_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT key FROM api_keys WHERE chat_id = ?', (chat_id,))
    result = cursor.fetchone()
    conn.close()

    if result is not None:
        return result[0]
    else:
        return None

def start_bot(message):
    # Создаем клавиатуру с кнопками
    keyboard = telebot.types.ReplyKeyboardMarkup(row_width=2)
    button1 = telebot.types.KeyboardButton('Аудио в текст')
    button2 = telebot.types.KeyboardButton('Текст в аудио')
    button3 = telebot.types.KeyboardButton('Создание изображений')
    button4 = telebot.types.KeyboardButton('gpt4-omni')
    button5 = telebot.types.KeyboardButton('Удалить токен')
    keyboard.add(button1, button2, button3, button4, button5)

    bot.send_message(message.chat.id, 'Выберите одну из опций:', reply_markup=keyboard)

@bot.message_handler(commands=['start'])
def start_message(message):
    create_api_key_table()
    api_key = get_api_key(message.chat.id)

    if api_key is None:
        bot.send_message(message.chat.id, 'Привет! Пожалуйста, введите API-ключ от OpenAI:')
        bot.register_next_step_handler(message, save_api_key)
    else:
        start_bot(message)

def audio_to_text(message):
    if message.message_id in last_processed_message:
        return
    last_processed_message[message.chat.id] = message.message_id

    if not message.audio:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте аудиофайл.")
        return

    api_key = get_api_key(message.chat.id)
    if not api_key:
        bot.send_message(message.chat.id, 'API-ключ не найден. Пожалуйста, введите API-ключ.')
        bot.register_next_step_handler(message, save_api_key)
        return

    client = OpenAI(api_key=api_key)

    # Получаем файл аудио от пользователя
    audio_file_info = bot.get_file(message.audio.file_id)
    audio_file_path = f"https://api.telegram.org/file/bot{bot.token}/{audio_file_info.file_path}"
    audio_content = requests.get(audio_file_path).content

    # Сохраняем аудио контент во временный файл
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_audio_file:
        temp_audio_path = temp_audio_file.name
        temp_audio_file.write(audio_content)

    # Отправляем запрос на транскрибацию аудио в текст
    try:
        with open(temp_audio_path, 'rb') as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
            # Проверяем, что получен ответ и извлекаем текст
            if hasattr(response, 'text'):
                text = response.text
            else:
                text = "Не удалось получить транскрипцию."

        # Отправляем транскрибированный текст пользователю
        bot.send_message(message.chat.id, text)

    except Exception as e:
        logging.exception(e)
        bot.send_message(message.chat.id, f"Произошла ошибка при транскрибации аудио: {str(e)}")

    # Удаляем временный файл после использования
    os.remove(temp_audio_path)

def text_to_audio(message):
    if message.message_id in last_processed_message:
        return
    last_processed_message[message.chat.id] = message.message_id
    text = message.text

    api_key = get_api_key(message.chat.id)
    if not api_key:
        bot.send_message(message.chat.id, 'API-ключ не найден. Пожалуйста, введите API-ключ.')
        bot.register_next_step_handler(message, save_api_key)
        return

    client = OpenAI(api_key=api_key)

    try:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice="nova",
            input=text,
            response_format="mp3"
        )
        # Получаем бинарные данные аудио
        audio_data = response.content
        # Сохраняем аудио в памяти
        audio_stream = BytesIO(audio_data)
        audio_stream.name = 'output.mp3'  # Telegram требует, чтобы объект BytesIO имел атрибут 'name'

        # Отправляем аудио файл пользователю
        bot.send_audio(message.chat.id, audio_stream)
    except Exception as e:
        logging.exception(e)
        bot.send_message(message.chat.id, f"Произошла ошибка при генерации аудио: {str(e)}")

def image_generation(message):
    if message.message_id in last_processed_message:
        return

    last_processed_message[message.chat.id] = message.message_id

    prompt = message.text
    if not prompt:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте текстовое описание для создания изображения.")
        return

    api_key = get_api_key(message.chat.id)
    if not api_key:
        bot.send_message(message.chat.id, 'API-ключ не найден. Пожалуйста, введите API-ключ.')
        bot.register_next_step_handler(message, save_api_key)
        return

    client = OpenAI(api_key=api_key)

    try:
        # Отправляем запрос на генерацию изображения
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )

        # Получаем URL сгенерированного изображения
        image_url = response.data[0].url

        # Отправляем изображение пользователю
        bot.send_photo(message.chat.id, image_url)

    except Exception as e:
        logging.exception(e)
        bot.send_message(message.chat.id, f"Произошла ошибка при генерации изображения: {str(e)}")

def gpt4_vision(message):
    if message.message_id in last_processed_message:
        return
    last_processed_message[message.chat.id] = message.message_id

    user_message = message.text if message.text else ""
    user_id = message.from_user.id

    # Получаем историю сообщений для данного пользователя или создаем новую
    if user_id not in chat_history:
        chat_history[user_id] = [{"role": "system", "content": "You are a helpful assistant that can understand images."}]

    # Добавляем текущее сообщение пользователя в историю
    chat_history[user_id].append({"role": "user", "content": user_message})

    # Проверяем наличие изображений в сообщении
    if message.photo:
        for photo in message.photo:
            file_info = bot.get_file(photo.file_id)
            image_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
            chat_history[user_id].append({"type": "image_url", "image_url": {"url": image_url}})

    api_key = get_api_key(message.chat.id)
    if not api_key:
        bot.send_message(message.chat.id, 'API-ключ не найден. Пожалуйста, введите API-ключ.')
        bot.register_next_step_handler(message, save_api_key)
        return

    client = OpenAI(api_key=api_key)

    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=chat_history[user_id]
        )

        if completion.choices:
            assistant_response = completion.choices[0].message.content
        else:
            assistant_response = "No response generated."

        # Добавляем ответ ассистента в историю сообщений
        chat_history[user_id].append({"role": "assistant", "content": assistant_response})

        # Отправляем ответ пользователю
        bot.send_message(message.chat.id, assistant_response)
    except Exception as e:
        logging.exception(e)
        bot.send_message(message.chat.id, f"Произошла ошибка при генерации ответа: {str(e)}")

COMMANDS = ['Аудио в текст', 'Текст в аудио', 'Создание изображений', 'gpt4-omni', 'Удалить токен']

# Обработчик всех текстовых сообщений для продолжения диалога и команд
@bot.message_handler(func=lambda message: True)
def handle_text_message(message):
    if message.text in COMMANDS:
        if message.text == 'Аудио в текст':
            bot.send_message(message.chat.id, 'Пришлите аудио для преобразования в текст')
            bot.register_next_step_handler(message, audio_to_text)
        elif message.text == 'Текст в аудио':
            bot.send_message(message.chat.id, 'Пришлите текст для преобразования в аудио')
            bot.register_next_step_handler(message, text_to_audio)
        elif message.text == 'Создание изображений':
            bot.send_message(message.chat.id, 'Пришлите текстовое описание для создания изображения')
            bot.register_next_step_handler(message, image_generation)
        elif message.text == 'gpt4-omni':
            bot.send_message(message.chat.id, 'Напишите сообщение для разговора с GPT-4 omni')
            bot.register_next_step_handler(message, gpt4_vision)
        elif message.text == 'Удалить токен':
            delete_api_key(message)
    else:
        # Если сообщение не совпадает с командами, продолжаем диалог
        gpt4_vision(message)

# Запускаем бота
bot.polling()
