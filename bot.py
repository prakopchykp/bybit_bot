from flask import Flask, request, render_template_string
import threading
import time
import requests
from pybit.unified_trading import WebSocket, HTTP
import os

app = Flask(__name__)

# --- ГЛОБАЛЬНЫЕ НАСТРОЙКИ ---
config = {
    "TOKEN": "8713291809:AAHX9C5ubNKuRPPorXtAqSsBRk5MJYqP5pQ",
    "CHAT_ID": "5225617529",
    "THRESHOLD": 3.0,
    "TIME_FRAME": 300,
    "COOLDOWN_TIME": 600,
    "DIRECTION": "BOTH",
    "IS_RUNNING": True  # Статус работы бота
}

history = {}
last_signal_time = {}

# --- HTML ИНТЕРФЕЙС ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Bybit Bot Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; margin: 20px; background: #f4f4f4; color: #333; }
        .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 400px; margin: auto; }
        h2 { color: #007bff; text-align: center; }
        label { display: block; margin-top: 15px; font-weight: bold; font-size: 0.9em; }
        input, select { width: 100%; padding: 12px; margin-top: 5px; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; }
        .btn-save { width: 100%; padding: 15px; background: #28a745; color: white; border: none; border-radius: 8px; cursor: pointer; margin-top: 20px; font-weight: bold; }
        .btn-toggle { width: 100%; padding: 15px; color: white; border: none; border-radius: 8px; cursor: pointer; margin-top: 10px; font-weight: bold; }
        .run { background: #dc3545; } /* Кнопка Стоп */
        .stop { background: #007bff; } /* Кнопка Пуск */
        .status-badge { text-align: center; padding: 10px; border-radius: 5px; margin-bottom: 20px; font-weight: bold; }
        .online { background: #e2f9e1; color: #1e7e34; }
        .offline { background: #f9e2e2; color: #a71d2a; }
    </style>
</head>
<body>
    <div class="card">
        <div class="status-badge {% if config.IS_RUNNING %}online{% else %}offline{% endif %}">
            СТАТУС: {% if config.IS_RUNNING %}РАБОТАЕТ{% else %}ОСТАНОВЛЕН{% endif %}
        </div>
        
        <form method="POST">
            <button type="submit" name="action" value="toggle" class="btn-toggle {% if config.IS_RUNNING %}run{% else %}stop{% endif %}">
                {% if config.IS_RUNNING %}ОСТАНОВИТЬ БОТА{% else %}ЗАПУСТИТЬ БОТА{% endif %}
            </button>
            <hr style="margin: 20px 0; border: 0; border-top: 1px solid #eee;">
            
            <label>Порог изменения (%)</label>
            <input type="number" step="0.1" name="THRESHOLD" value="{{config.THRESHOLD}}">
            
            <label>Окно анализа (сек)</label>
            <input type="number" name="TIME_FRAME" value="{{config.TIME_FRAME}}">
            
            <label>Заморозка монеты (сек)</label>
            <input type="number" name="COOLDOWN_TIME" value="{{config.COOLDOWN_TIME}}">
            
            <label>Направление</label>
            <select name="DIRECTION">
                <option value="BOTH" {% if config.DIRECTION == 'BOTH' %}selected{% endif %}>BOTH (Рост и Падение)</option>
                <option value="LONG" {% if config.DIRECTION == 'LONG' %}selected{% endif %}>LONG (Только рост)</option>
                <option value="SHORT" {% if config.DIRECTION == 'SHORT' %}selected{% endif %}>SHORT (Только падение)</option>
            </select>
            <button type="submit" name="action" value="save" class="btn-save">СОХРАНИТЬ НАСТРОЙКИ</button>
        </form>
    </div>
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'toggle':
            config['IS_RUNNING'] = not config['IS_RUNNING']
        elif action == 'save':
            config['THRESHOLD'] = float(request.form['THRESHOLD'])
            config['TIME_FRAME'] = int(request.form['TIME_FRAME'])
            config['COOLDOWN_TIME'] = int(request.form['COOLDOWN_TIME'])
            config['DIRECTION'] = request.form['DIRECTION']
        print(f"Изменение: {config}")
    return render_template_string(HTML_TEMPLATE, config=config)

# --- ЛОГИКА БОТА ---
def send_to_tg(text):
    url = f"https://api.telegram.org/bot{config['TOKEN']}/sendMessage"
    data = {"chat_id": config['CHAT_ID'], "text": text, "parse_mode": "HTML"}
    try: requests.post(url, data=data)
    except: pass

def handle_message(message):
    # Если бот "выключен" кнопкой — просто выходим
    if not config['IS_RUNNING']:
        return

    data = message.get("data", {})
    symbol = data.get("symbol")
    if "lastPrice" in data:
        curr_price = float(data.get("lastPrice"))
        now = time.time()
        
        if symbol in last_signal_time and (now - last_signal_time[symbol] < config['COOLDOWN_TIME']):
            return

        if symbol not in history: history[symbol] = []
        history[symbol].append((curr_price, now))
        history[symbol] = [p for p in history[symbol] if p[1] > (now - config['TIME_FRAME'])]
        
        if len(history[symbol]) > 1:
            oldest_price = history[symbol][0][0]
            change = ((curr_price - oldest_price) / oldest_price) * 100
            
            sig = False
            if config['DIRECTION'] == "BOTH" and abs(change) >= config['THRESHOLD']: sig = True
            elif config['DIRECTION'] == "LONG" and change >= config['THRESHOLD']: sig = True
            elif config['DIRECTION'] == "SHORT" and change <= -config['THRESHOLD']: sig = True

            if sig:
                last_signal_time[symbol] = now
                history[symbol] = []
                emoji = "🚀 ЛОНГ" if change > 0 else "📉 ШОРТ"
                tv_url = f"https://www.tradingview.com/chart/?symbol=BYBIT:{symbol}.p"
                msg = (f"{emoji} <b>{symbol}</b>\n"
                       f"Изменение: <b>{change:.2f}%</b> за {config['TIME_FRAME']//60} мин\n"
                       f"Цена: <code>{curr_price}</code>\n\n"
                       f"📊 <a href='{tv_url}'>Открыть на TradingView</a>")
                send_to_tg(msg)

def run_bot():
    session = HTTP(testnet=False)
    info = session.get_instruments_info(category="linear")
    symbols = [item['symbol'] for item in info['result']['list'] if item['symbol'].endswith('USDT')]
    ws = WebSocket(testnet=False, channel_type="linear")
    for i in range(0, len(symbols), 10):
        for s in symbols[i:i+10]:
            ws.ticker_stream(symbol=s, callback=handle_message)
    while True: time.sleep(1)

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)