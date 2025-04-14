"""
Line Bot 整合
功能：將爬取的盤後籌碼資料發送到 Line Bot，提供每日推送和用戶查詢功能
"""

import os
import json
from datetime import datetime, timedelta
import pytz
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, ButtonComponent, URIAction,
    QuickReply, QuickReplyButton, MessageAction
)
from pymongo import MongoClient
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# 設定 Line Bot API
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

# 連接 MongoDB
mongodb_uri = os.environ.get("MONGODB_URI")
client = MongoClient(mongodb_uri)
db = client["market_data"]

def _get_taiwan_current_time():
    """取得台灣目前時間"""
    taiwan_tz = pytz.timezone('Asia/Taipei')
    return datetime.now(taiwan_tz)

def get_latest_market_data():
    """
    獲取最新的市場資料
    
    Returns:
        dict: 包含各類市場資料的字典
    """
    try:
        # 取得最新的加權指數資料
        latest_index = db.twse_index.find_one(
            sort=[("date", -1)]  # 按日期降序排序
        )
        
        # 這裡可以加入其他資料來源的查詢
        # 例如: 三大法人、期貨資料等
        
        return {
            "index_data": latest_index,
            # 可以添加其他資料
        }
    except Exception as e:
        print(f"獲取市場資料時出錯: {str(e)}")
        return None

def format_market_data_message(market_data):
    """
    格式化市場資料為易讀的文字訊息
    
    Args:
        market_data: 市場資料字典
        
    Returns:
        str: 格式化後的文字訊息
    """
    if not market_data or not market_data.get("index_data"):
        return "無法取得市場資料"
    
    index_data = market_data["index_data"]
    
    # 將成交金額轉換為億元單位
    trading_value = float(index_data["trading_value"].replace(',', ''))
    trading_value_billion = trading_value / 100000000  # 轉換為億元
    
    change = float(index_data["change"])
    change_symbol = "▲" if change > 0 else "▼" if change < 0 else "-"
    
    # 格式化日期
    date_parts = index_data["chinese_date"].split('/')
    formatted_date = f"{date_parts[0]}年{date_parts[1]}月{date_parts[2]}日"
    
    message = (
        f"📊 盤後籌碼資訊 {formatted_date}\n"
        f"------------------------\n"
        f"📈 加權指數：{index_data['index']} {change_symbol} {abs(change)}\n"
        f"💰 成交金額：{trading_value_billion:.2f} 億元\n"
        f"🔢 成交筆數：{index_data['transactions']}\n"
        f"------------------------\n"
        # 這裡可以加入其他資料
    )
    
    return message

@app.route("/callback", methods=['POST'])
def callback():
    """Line Bot 回調函數"""
    # 獲取 X-Line-Signature 標頭值
    signature = request.headers['X-Line-Signature']

    # 獲取請求主體
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 處理 webhook
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理用戶訊息"""
    text = event.message.text
    
    if text.strip().lower() in ['盤後', '盤後資訊', '盤後籌碼', '今日盤後', '加權指數']:
        # 提供盤後資訊
        market_data = get_latest_market_data()
        message = format_market_data_message(market_data)
        
        # 添加快速回覆按鈕
        quick_reply = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="加權指數", text="加權指數")),
            # 可以添加其他快速回覆按鈕
        ])
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message, quick_reply=quick_reply)
        )
    else:
        # 處理其他類型的消息
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=(
                "您好！我是盤後籌碼小幫手。\n"
                "您可以輸入以下關鍵字查詢資訊：\n"
                "- 盤後\n"
                "- 加權指數\n"
                # 可以添加其他命令
            ))
        )

def send_daily_push_notification():
    """
    發送每日推送通知
    此函數應由排程任務呼叫
    """
    try:
        # 獲取推送目標的 user ID 或群組 ID
        target_id = os.environ.get('LINE_PUSH_TARGET')
        if not target_id:
            print("未設定推送目標 ID")
            return
        
        # 獲取最新市場數據
        market_data = get_latest_market_data()
        if not market_data:
            print("無法獲取市場數據，取消推送")
            return
            
        # 格式化訊息
        message = format_market_data_message(market_data)
        
        # 發送推送通知
        line_bot_api.push_message(
            target_id,
            TextSendMessage(text=message)
        )
        
        print(f"成功發送每日推送通知至 {target_id}")
    except Exception as e:
        print(f"發送推送通知時出錯: {str(e)}")

@app.route("/push-notification", methods=['POST'])
def trigger_push_notification():
    """
    手動觸發推送通知的 API 端點
    注意：應設置適當的認證以防止未授權訪問
    """
    # 簡單的 API 金鑰認證
    api_key = request.headers.get('X-API-KEY')
    if api_key != os.environ.get('API_KEY'):
        abort(403)  # 拒絕未授權的訪問
    
    send_daily_push_notification()
    return {"status": "success", "message": "推送通知已觸發"}

@app.route("/test-db")
def test_db():
    """
    測試資料庫連接的 API 端點
    """
    try:
        dbs = client.list_database_names()
        return {"status": "success", "databases": dbs}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    # 本地測試
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
