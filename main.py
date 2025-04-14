"""
主應用程式
功能：整合所有爬蟲模組，處理定時任務和資料整合
"""

import os
import time
import random
import threading
import schedule
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from pymongo import MongoClient
from flask import Flask, request, jsonify, abort

# 導入爬蟲模組 - 從 crawlers 包中導入
from crawlers.twse_crawler import TWSECrawler
# 後續可以添加其他爬蟲:
# from crawlers.other_crawler import OtherCrawler

# 導入 Line Bot 模組和工具函數
from line_bot_integration import send_daily_push_notification
from utils import (
    get_taiwan_current_time, check_trading_day, update_holiday_database,
    should_crawl_on_startup, check_if_already_crawled_today
)

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# 設置資料庫連接
mongodb_uri = os.getenv("MONGODB_URI")
if mongodb_uri:
    db_client = MongoClient(mongodb_uri)
    db = db_client["market_data"]
else:
    print("警告：未提供MongoDB連接字串")
    db_client = None
    db = None

def crawl_all_data():
    """爬取所有數據"""
    print(f"開始爬取所有數據 - {get_taiwan_current_time().isoformat()}")
    
    # 檢查是否為交易日
    if not check_trading_day():
        print("今天不是交易日，跳過爬取")
        return False
    
    # 檢查是否在工作時間內
    now = get_taiwan_current_time()
    if now.hour < 14 or (now.hour == 14 and now.minute < 50):
        print("尚未到達盤後資料時間（14:50後），跳過爬取")
        return False
    
    # 隨機等待1-3分鐘
    wait_minutes = random.uniform(1, 3)
    wait_seconds = int(wait_minutes * 60)
    print(f"隨機等待 {wait_seconds} 秒...")
    time.sleep(wait_seconds)
    
    data_updated = False
    all_data = {}
    
    # 爬取加權指數資料
    try:
        twse_crawler = TWSECrawler(db_client)
        index_data = twse_crawler.check_and_fetch_data()
        if index_data:
            all_data["index_data"] = index_data
            data_updated = True
    except Exception as e:
        print(f"爬取加權指數資料時出錯: {str(e)}")
    
    # 這裡可以加入其他爬蟲模組的調用
    # 例如：
    # try:
    #     other_crawler = OtherCrawler(db_client)
    #     other_data = other_crawler.check_and_fetch_data()
    #     if other_data:
    #         all_data["other_data"] = other_data
    #         data_updated = True
    # except Exception as e:
    #     print(f"爬取其他資料時出錯: {str(e)}")
    
    # 如果有數據更新，則發送 Line 通知
    if data_updated:
        try:
            send_daily_push_notification()
            print("已發送每日 Line 推送通知")
        except Exception as e:
            print(f"發送 Line 通知時出錯: {str(e)}")
    
    return data_updated

def run_scheduler():
    """執行排程任務"""
    # 設定每日下午2:50執行爬蟲任務
    schedule.every().day.at("14:50").do(crawl_all_data)
    
    # 設定每小時檢查一次
    # 這是為了防止排程錯過2:50的執行時間
    schedule.every().hour.do(check_and_crawl_if_needed)
    
    # 設定每週一更新假日資料庫
    schedule.every().monday.do(update_holiday_database)
    
    # 持續運行排程
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分鐘檢查一次

def check_and_crawl_if_needed():
    """檢查是否需要執行爬蟲任務"""
    now = get_taiwan_current_time()
    
    # 如果現在是交易日，且時間在14:50到18:00之間，且今天還沒有成功爬取數據
    if (check_trading_day() and 
        ((now.hour == 14 and now.minute >= 50) or (now.hour > 14 and now.hour < 18)) and
        not check_if_already_crawled_today()):
        
        return crawl_all_data()
    
    return False

def initialize_system():
    """系統初始化函數"""
    print("正在初始化系統...")
    
    # 確保市場假日資料已更新
    try:
        update_holiday_database()
    except Exception as e:
        print(f"更新假日資料時出錯: {str(e)}")
    
    # 檢查是否需要在啟動時執行爬蟲
    if should_crawl_on_startup():
        print("系統重新啟動，檢測到需要執行爬蟲任務...")
        threading.Thread(target=crawl_all_data).start()
    
    print("系統初始化完成")

@app.route("/")
def home():
    """首頁"""
    return "盤後籌碼爬蟲服務正在運行"

@app.route("/health")
def health_check():
    """健康檢查"""
    return jsonify({
        "status": "healthy", 
        "time": get_taiwan_current_time().isoformat(),
        "is_trading_day": check_trading_day(),
        "already_crawled_today": check_if_already_crawled_today()
    })

@app.route("/manual-crawl", methods=['POST'])
def manual_crawl():
    """
    手動觸發爬蟲的 API 端點
    注意：應設置適當的認證以防止未授權訪問
    """
    # 簡單的 API 金鑰認證
    api_key = request.headers.get('X-API-KEY')
    if api_key != os.environ.get('API_KEY'):
        abort(403)  # 拒絕未授權的訪問
    
    success = crawl_all_data()
    return jsonify({
        "status": "success" if success else "no_update",
        "message": "爬蟲已執行" + ("且數據已更新" if success else "但無新數據")
    })

@app.route("/update-holidays", methods=['POST'])
def trigger_update_holidays():
    """
    手動觸發更新假日資料的 API 端點
    """
    # 簡單的 API 金鑰認證
    api_key = request.headers.get('X-API-KEY')
    if api_key != os.environ.get('API_KEY'):
        abort(403)  # 拒絕未授權的訪問
    
    success = update_holiday_database()
    return jsonify({
        "status": "success" if success else "error",
        "message": "假日資料已更新" if success else "更新假日資料失敗"
    })

if __name__ == "__main__":
    # 在啟動時進行系統初始化
    initialize_system()
    
    # 在背景執行排程任務
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # 啟動 Flask 應用
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
