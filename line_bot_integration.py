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
from dotenv import load_dotenv

# 導入資料庫訪問層
from database.db_access import db_layer

# 載入環境變數
load_dotenv()

# 創建 Blueprint 而不是 Flask 應用
line_bot_bp = Blueprint('line_bot', __name__)

# 設定 Line Bot API
line_bot_api = None
handler = None

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

# 執行初始化
initialize_line_bot()

def get_taiwan_current_time():
    """取得台灣目前時間"""
    taiwan_tz = pytz.timezone('Asia/Taipei')
    return datetime.now(taiwan_tz)

def get_latest_market_data():
    """
    獲取最新的市場資料，如果沒有當天資料，則返回最後一筆資料
    
    Returns:
        tuple: (資料字典, 是否為今天的資料)
    """
    try:
        # 確保資料庫連接存在
        if not db_layer.db_client:
            print("資料庫未連接，無法獲取市場資料")
            return None, False
        
        # 確保集合存在
        if "twse_index" not in db_layer.db.list_collection_names():
            print("twse_index 集合不存在")
            return None, False
        
        # 取得今天的日期範圍
        now = get_taiwan_current_time()
        today_date = now.strftime("%Y-%m-%d")
        
        # 先嘗試獲取今天的資料
        today_data = db_layer.find_one(
            "twse_index", 
            {"date": today_date}
        )
        
        if today_data:
            print(f"找到今天({today_date})的加權指數資料")
            return {"index_data": today_data}, True
        
        # 如果沒有今天的資料，則獲取最新的資料
        latest_data = db_layer.find_one(
            "twse_index",
            sort=[("date", -1)]  # 按日期降序排序
        )
        
        if latest_data:
            print(f"找到最新的加權指數資料，日期為: {latest_data.get('date', 'unknown')}")
            return {"index_data": latest_data}, False
        
        # 如果集合中沒有任何資料
        print("找不到任何加權指數資料")
        return None, False
        
    except Exception as e:
        print(f"獲取市場資料時出錯: {str(e)}")
        traceback.print_exc()
        return None, False

def format_market_data_message(market_data, is_today_data=False):
    """
    格式化市場資料為易讀的文字訊息
    
    Args:
        market_data: 市場資料字典
        is_today_data: 是否為今天的資料
        
    Returns:
        str: 格式化後的文字訊息
    """
    if not market_data or not market_data.get("index_data"):
        return "無法取得市場資料"
    
    index_data = market_data["index_data"]
    
    # 檢查必要欄位是否存在
    required_fields = ["trading_value", "change", "chinese_date", "index", "transactions", "date"]
    for field in required_fields:
        if field not in index_data:
            return f"市場資料缺少必要欄位: {field}"
    
    try:
        # 將成交金額轉換為億元單位
        trading_value = float(index_data["trading_value"].replace(',', ''))
        trading_value_billion = trading_value / 100000000  # 轉換為億元
        
        change = float(index_data["change"].replace(',', ''))
        change_symbol = "▲" if change > 0 else "▼" if change < 0 else "-"
        
        # 格式化日期
        date_parts = index_data["chinese_date"].split('/')
        formatted_date = f"{date_parts[0]}年{date_parts[1]}月{date_parts[2]}日"
        
        # 判斷是否為今天的資料
        data_date = index_data["date"]
        today_date = get_taiwan_current_time().strftime("%Y-%m-%d")
        date_notice = ""
        
        if not is_today_data:
            # 明確告知用戶這不是今天的資料
            date_notice = f"\n⚠️ 注意：這是 {data_date} 的歷史資料，尚未更新今日資料"
        
        message = (
            f"📊 盤後籌碼資訊 {formatted_date}\n"
            f"------------------------\n"
            f"📈 加權指數：{index_data['index']} {change_symbol} {abs(change)}\n"
            f"💰 成交金額：{trading_value_billion:.2f} 億元\n"
            f"🔢 成交筆數：{index_data['transactions']}\n"
            f"------------------------"
            f"{date_notice}"
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

def handle_message(event):
    """處理用戶訊息"""
    text = event.message.text.strip()
    
    if text.lower() in ['盤後', '盤後資訊', '盤後籌碼', '今日盤後', '加權指數']:
        # 提供盤後資訊
        market_data, is_today_data = get_latest_market_data()
        
        if not market_data:
            # 如果無法獲取任何市場資料
            message = (
                "目前無法取得盤後資料，請稍後再試。\n"
                "系統將在每日收盤後自動更新資料。"
            )
        else:
            # 即使不是最新資料，也會顯示最後一筆可用的資料
            message = format_market_data_message(market_data, is_today_data)
        
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
        market_data, is_today_data = get_latest_market_data()
        if not market_data:
            print("無法獲取市場數據，取消推送")
            return False
            
        # 格式化訊息
        message = format_market_data_message(market_data, is_today_data)
        
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
    if db_layer.db_client:
        try:
            db_layer.db_client.server_info()
            db_connected = True
        except:
            db_connected = False
    
    # 檢查最新市場資料
    latest_data = None
    is_today_data = False
    
    if db_connected:
        try:
            market_data, is_today_data = get_latest_market_data()
            if market_data and market_data.get("index_data"):
                latest_data = {
                    "date": market_data["index_data"].get("date", "unknown"),
                    "index": market_data["index_data"].get("index", "unknown"),
                    "change": market_data["index_data"].get("change", "unknown"),
                    "is_today_data": is_today_data
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
        market_data, is_today_data = get_latest_market_data()
        
        if not market_data:
            return jsonify({
                "status": "error",
                "message": "無法獲取市場資料"
            })
        
        formatted_message = format_market_data_message(market_data, is_today_data)
        
        # 移除 _id 欄位，因為它不能被 JSON 序列化
        if market_data and "index_data" in market_data and "_id" in market_data["index_data"]:
            market_data["index_data"]["_id"] = str(market_data["index_data"]["_id"])
        
        return jsonify({
            "status": "success",
            "formatted_message": formatted_message,
            "raw_data": market_data,
            "is_today_data": is_today_data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        })
