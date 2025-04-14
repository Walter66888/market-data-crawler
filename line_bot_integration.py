"""
Line Bot 整合
功能：將爬取的盤後籌碼資料發送到 Line Bot，提供每日推送和用戶查詢功能
"""

import os
import json
import traceback
from datetime import datetime, timedelta
import pytz
from flask import request, abort, Blueprint, jsonify
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

# 創建 Blueprint 而不是 Flask 應用
line_bot_bp = Blueprint('line_bot', __name__)

# 設定 Line Bot API
line_bot_api = None
handler = None

# MongoDB 連接
mongodb_uri = os.environ.get("MONGODB_URI")
db_client = None
db = None

# 初始化 Line Bot API
def initialize_line_bot():
    """初始化 Line Bot API"""
    global line_bot_api, handler
    
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    secret = os.environ.get('LINE_CHANNEL_SECRET')
    
    if token and secret:
        try:
            line_bot_api = LineBotApi(token)
            handler = WebhookHandler(secret)
            return True
        except Exception as e:
            print(f"初始化 Line Bot API 時出錯: {str(e)}")
            return False
    else:
        print("未設定 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_CHANNEL_SECRET 環境變數")
        return False

# 初始化資料庫連接
def initialize_db():
    """初始化資料庫連接"""
    global db_client, db
    
    mongodb_uri = os.environ.get("MONGODB_URI")
    if mongodb_uri:
        try:
            db_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            # 測試連接是否成功
            db_client.server_info()
            db = db_client["market_data"]
            print("MongoDB 連接成功 (line_bot)")
            return True
        except Exception as e:
            print(f"MongoDB 連接失敗 (line_bot): {str(e)}")
            db_client = None
            db = None
            return False
    else:
        print("警告：未提供MongoDB連接字串 (line_bot)")
        db_client = None
        db = None
        return False

# 執行初始化
initialize_line_bot()
initialize_db()

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
    global db_client, db
    
    # 如果資料庫連接不存在，嘗試重新連接
    if not db_client:
        if not initialize_db():
            print("資料庫未連接，無法獲取市場資料")
            return None
    
    try:
        # 確保集合存在
        if "twse_index" not in db.list_collection_names():
            print("twse_index 集合不存在，無法獲取資料")
            return None
        
        # 取得最新的加權指數資料
        latest_index = db.twse_index.find_one(
            sort=[("date", -1)]  # 按日期降序排序
        )
        
        # 如果沒有找到數據，返回 None
        if not latest_index:
            print("找不到任何加權指數資料")
            return None
        
        # 調試輸出
        print(f"獲取到最新市場資料，日期: {latest_index.get('date', 'unknown')}")
        
        # 這裡可以加入其他資料來源的查詢
        # 例如: 三大法人、期貨資料等
        
        return {
            "index_data": latest_index,
            # 可以添加其他資料
        }
    except Exception as e:
        print(f"獲取市場資料時出錯: {str(e)}")
        traceback.print_exc()
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
    
    # 檢查必要欄位是否存在
    required_fields = ["trading_value", "change", "chinese_date", "index", "transactions"]
    for field in required_fields:
        if field not in index_data:
            return f"市場資料缺少必要欄位: {field}"
    
    try:
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
    except Exception as e:
        print(f"格式化市場資料時出錯: {str(e)}")
        traceback.print_exc()
        return f"格式化市場資料時出錯: {str(e)}"

@line_bot_bp.route("/callback", methods=['POST'])
def callback():
    """Line Bot 回調函數"""
    # 檢查 Line Bot API 是否已初始化
    if not line_bot_api or not handler:
        print("Line Bot API 未初始化，重新初始化...")
        if not initialize_line_bot():
            return jsonify({"status": "error", "message": "Line Bot API 初始化失敗"})
    
    # 獲取 X-Line-Signature 標頭值
    signature = request.headers.get('X-Line-Signature', '')
    if not signature:
        print("缺少 X-Line-Signature 標頭")
        abort(400)

    # 獲取請求主體
    body = request.get_data(as_text=True)
    print("Request body:", body)  # 使用 print 代替 app.logger

    # 處理 webhook
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Check your channel access token/channel secret.")
        abort(400)
    except Exception as e:
        print(f"處理 webhook 時出錯: {str(e)}")
        traceback.print_exc()
        abort(500)

    return 'OK'

@line_bot_bp.route("/callback-test", methods=['GET'])
def callback_test():
    """測試 Line Bot 回調端點"""
    return jsonify({
        "status": "success",
        "message": "Line Bot 回調端點正常",
        "line_bot_initialized": bool(line_bot_api and handler)
    })

def handle_message_wrapper(event):
    """處理用戶訊息的包裝函數，用於捕獲異常"""
    try:
        handle_message(event)
    except Exception as e:
        print(f"處理訊息時出錯: {str(e)}")
        traceback.print_exc()
        
        # 嘗試發送錯誤訊息
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="處理您的訊息時出現問題，請稍後再試。")
            )
        except Exception as e2:
            print(f"發送錯誤訊息時出錯: {str(e2)}")

# 使用包裝函數註冊處理器
if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def wrapped_handle_message(event):
        handle_message_wrapper(event)

def handle_message(event):
    """處理用戶訊息"""
    text = event.message.text.strip()
    
    if text.lower() in ['盤後', '盤後資訊', '盤後籌碼', '今日盤後', '加權指數']:
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
    # 檢查 Line Bot API 是否已初始化
    if not line_bot_api:
        print("Line Bot API 未初始化，重新初始化...")
        if not initialize_line_bot():
            print("Line Bot API 初始化失敗，無法發送推送通知")
            return False
    
    try:
        # 獲取推送目標的 user ID 或群組 ID
        target_id = os.environ.get('LINE_PUSH_TARGET')
        if not target_id:
            print("未設定推送目標 ID")
            return False
        
        # 獲取最新市場數據
        market_data = get_latest_market_data()
        if not market_data:
            print("無法獲取市場數據，取消推送")
            return False
            
        # 格式化訊息
        message = format_market_data_message(market_data)
        
        # 發送推送通知
        line_bot_api.push_message(
            target_id,
            TextSendMessage(text=message)
        )
        
        print(f"成功發送每日推送通知至 {target_id}")
        return True
    except Exception as e:
        print(f"發送推送通知時出錯: {str(e)}")
        traceback.print_exc()
        return False

@line_bot_bp.route("/push-notification", methods=['POST'])
def trigger_push_notification():
    """
    手動觸發推送通知的 API 端點
    注意：應設置適當的認證以防止未授權訪問
    """
    # 簡單的 API 金鑰認證
    api_key = request.headers.get('X-API-KEY')
    if api_key != os.environ.get('API_KEY'):
        abort(403)  # 拒絕未授權的訪問
    
    success = send_daily_push_notification()
    return jsonify({
        "status": "success" if success else "error",
        "message": "推送通知已觸發" if success else "觸發推送通知失敗"
    })

@line_bot_bp.route("/test", methods=['GET'])
def test_line_bot():
    """測試 Line Bot 整合是否正常加載"""
    # 檢查資料庫連接
    db_connected = False
    if db_client:
        try:
            db_client.server_info()
            db_connected = True
        except:
            db_connected = False
    
    # 檢查最新市場資料
    latest_data = None
    if db_connected:
        try:
            market_data = get_latest_market_data()
            if market_data and market_data.get("index_data"):
                latest_data = {
                    "date": market_data["index_data"].get("date", "unknown"),
                    "index": market_data["index_data"].get("index", "unknown"),
                    "change": market_data["index_data"].get("change", "unknown")
                }
        except:
            latest_data = None
    
    return jsonify({
        "status": "success",
        "message": "Line Bot 整合模組運行正常",
        "line_bot_initialized": bool(line_bot_api and handler),
        "database_connected": db_connected,
        "latest_data": latest_data
    })

@line_bot_bp.route("/manual-get-market-data", methods=['GET'])
def manual_get_market_data():
    """手動測試獲取市場資料的 API 端點"""
    try:
        market_data = get_latest_market_data()
        
        if not market_data:
            return jsonify({
                "status": "error",
                "message": "無法獲取市場資料"
            })
        
        formatted_message = format_market_data_message(market_data)
        
        # 移除 _id 欄位，因為它不能被 JSON 序列化
        if market_data and "index_data" in market_data and "_id" in market_data["index_data"]:
            market_data["index_data"]["_id"] = str(market_data["index_data"]["_id"])
        
        return jsonify({
            "status": "success",
            "formatted_message": formatted_message,
            "raw_data": market_data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        })
