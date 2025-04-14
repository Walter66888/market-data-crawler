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
from line_bot_integration import send_daily_push_notification, line_bot_bp
from utils import (
    get_taiwan_current_time, check_trading_day, update_holiday_database,
    should_crawl_on_startup, check_if_already_crawled_today
)

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# 註冊 Line Bot Blueprint
app.register_blueprint(line_bot_bp)

# 設置資料庫連接
mongodb_uri = os.getenv("MONGODB_URI")
if mongodb_uri:
    try:
        db_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        # 測試連接是否成功
        db_client.server_info()
        db = db_client["market_data"]
        print("MongoDB 連接成功")
    except Exception as e:
        print(f"MongoDB 連接失敗: {str(e)}")
        db_client = None
        db = None
else:
    print("警告：未提供MongoDB連接字串")
    db_client = None
    db = None

def crawl_all_data():
    """爬取所有數據"""
    print(f"開始爬取所有數據 - {get_taiwan_current_time().isoformat()}")
    
    # 檢查資料庫連接
    if not db_client:
        print("資料庫未連接，無法爬取數據")
        return False
    
    # 檢查是否為交易日
    if not check_trading_day():
        print("今天不是交易日，跳過爬取")
        return False
    
    # 檢查是否在工作時間內 (在強制初始化時跳過此檢查)
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

# 添加一個無視時間檢查的強制爬蟲函數，用於初始化
def force_crawl_data():
    """強制爬取資料，用於初始化"""
    print(f"強制爬取初始數據 - {get_taiwan_current_time().isoformat()}")
    
    # 檢查資料庫連接
    if not db_client:
        print("資料庫未連接，無法爬取數據")
        return False
    
    data_updated = False
    all_data = {}
    
    # 爬取加權指數資料
    try:
        twse_crawler = TWSECrawler(db_client)
        index_data = twse_crawler.check_and_fetch_data(ignore_time_check=True)
        if index_data:
            all_data["index_data"] = index_data
            data_updated = True
    except Exception as e:
        print(f"強制爬取加權指數資料時出錯: {str(e)}")
    
    # 這裡可以加入其他爬蟲模組的強制爬取
    
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
        try:
            schedule.run_pending()
            time.sleep(60)  # 每分鐘檢查一次
        except Exception as e:
            print(f"排程執行時發生錯誤: {str(e)}")
            time.sleep(60)  # 發生錯誤時等待一分鐘後繼續

def check_and_crawl_if_needed():
    """檢查是否需要執行爬蟲任務"""
    now = get_taiwan_current_time()
    
    # 如果現在是交易日，且時間在14:50到18:00之間，且今天還沒有成功爬取數據
    if (check_trading_day() and 
        ((now.hour == 14 and now.minute >= 50) or (now.hour > 14 and now.hour < 18)) and
        not check_if_already_crawled_today()):
        
        return crawl_all_data()
    
    return False

def check_database_initialized():
    """檢查資料庫是否已初始化"""
    if not db_client:
        return False
    
    try:
        # 檢查是否存在 market_data 資料庫
        databases = db_client.list_database_names()
        
        # 檢查重要集合是否存在且有數據
        has_holidays = False
        has_index_data = False
        
        if "market_data" in databases:
            has_holidays = db.market_holidays.count_documents({}) > 0
            has_index_data = db.twse_index.count_documents({}) > 0
        
        return has_holidays and has_index_data
    except Exception as e:
        print(f"檢查資料庫初始化狀態時出錯: {str(e)}")
        return False

def initialize_system():
    """系統初始化函數"""
    print("正在初始化系統...")
    
    # 檢查資料庫連接
    if not db_client:
        print("資料庫未連接，無法初始化系統")
        return False
    
    # 檢查資料庫是否已初始化
    is_initialized = check_database_initialized()
    
    if not is_initialized:
        print("系統尚未初始化，開始執行自動初始化...")
        try:
            # 確保資料庫中有所需的集合
            if "market_holidays" not in db.list_collection_names():
                db.create_collection("market_holidays")
            if "twse_index" not in db.list_collection_names():
                db.create_collection("twse_index")
            
            # 初始化假日資料庫
            print("正在初始化假日資料...")
            update_success = update_holiday_database()
            if not update_success:
                print("假日資料初始化失敗")
                
            # 強制爬取初始數據
            print("正在爬取初始數據...")
            crawl_success = force_crawl_data()
            if not crawl_success:
                print("初始數據爬取失敗")
            
            print("系統初始化完成")
            return update_success and crawl_success
        except Exception as e:
            print(f"系統初始化過程中出錯: {str(e)}")
            return False
    else:
        print("系統已初始化，檢查是否需要更新...")
        
        # 檢查是否需要在啟動時執行爬蟲
        if should_crawl_on_startup():
            print("系統重新啟動，檢測到需要執行爬蟲任務...")
            threading.Thread(target=crawl_all_data).start()
        
        return True

@app.route("/")
def home():
    """首頁"""
    # 檢查資料庫連接狀態
    db_status = "已連接" if db_client else "未連接"
    return f"盤後籌碼爬蟲服務正在運行。資料庫狀態：{db_status}"

@app.route("/health")
def health_check():
    """健康檢查"""
    try:
        # 檢查資料庫連接
        db_connected = False
        if db_client:
            try:
                # 嘗試執行一個簡單的資料庫操作
                db_client.server_info()
                db_connected = True
            except Exception as e:
                db_connected = False
        
        # 檢查資料庫初始化狀態
        db_initialized = check_database_initialized() if db_connected else False
        
        return jsonify({
            "status": "healthy" if db_connected else "unhealthy", 
            "time": get_taiwan_current_time().isoformat(),
            "is_trading_day": check_trading_day(),
            "already_crawled_today": check_if_already_crawled_today() if db_connected else False,
            "database_connected": db_connected,
            "database_initialized": db_initialized
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "time": get_taiwan_current_time().isoformat()
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
    
    try:
        # 檢查資料庫連接
        if not db_client:
            return jsonify({
                "status": "error",
                "message": "資料庫未連接，無法執行爬蟲"
            })
        
        success = crawl_all_data()
        return jsonify({
            "status": "success" if success else "no_update",
            "message": "爬蟲已執行" + ("且數據已更新" if success else "但無新數據")
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"執行爬蟲時出錯: {str(e)}"
        })

@app.route("/force-initialize", methods=['POST'])
def force_initialize():
    """
    強制初始化系統的 API 端點
    """
    # 簡單的 API 金鑰認證
    api_key = request.headers.get('X-API-KEY')
    if api_key != os.environ.get('API_KEY'):
        abort(403)  # 拒絕未授權的訪問
    
    try:
        # 檢查資料庫連接
        if not db_client:
            return jsonify({
                "status": "error",
                "message": "資料庫未連接，無法初始化系統"
            })
        
        # 確保資料庫中有所需的集合
        if "market_holidays" not in db.list_collection_names():
            db.create_collection("market_holidays")
        if "twse_index" not in db.list_collection_names():
            db.create_collection("twse_index")
        
        # 更新假日資料
        update_success = update_holiday_database()
        
        # 強制爬取數據
        crawl_success = force_crawl_data()
        
        return jsonify({
            "status": "success",
            "update_holidays": update_success,
            "crawl_data": crawl_success,
            "message": "系統已強制初始化"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"初始化過程中出錯: {str(e)}"
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
    
    try:
        # 檢查資料庫連接
        if not db_client:
            return jsonify({
                "status": "error",
                "message": "資料庫未連接，無法更新假日資料"
            })
        
        success = update_holiday_database()
        return jsonify({
            "status": "success" if success else "error",
            "message": "假日資料已更新" if success else "更新假日資料失敗"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"更新假日資料時出錯: {str(e)}"
        })

@app.route("/test-db")
def test_db():
    """
    測試資料庫連接的 API 端點
    """
    try:
        if not db_client:
            return jsonify({"status": "error", "message": "未連接到資料庫"})
        
        # 測試連接是否成功
        db_client.server_info()
        
        # 獲取數據庫列表
        dbs = db_client.list_database_names()
        
        # 檢查初始化狀態
        is_initialized = check_database_initialized()
        
        # 獲取集合列表
        collections = []
        if "market_data" in dbs:
            collections = db.list_collection_names()
            
            # 獲取各集合的文檔數量
            collection_counts = {}
            for collection in collections:
                collection_counts[collection] = db[collection].count_documents({})
        
        return jsonify({
            "status": "success", 
            "databases": dbs,
            "initialized": is_initialized,
            "collections": collections,
            "collection_counts": collection_counts if 'collection_counts' in locals() else {}
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/check-line-bot")
def check_line_bot():
    """
    檢查 Line Bot 設置是否正確
    """
    try:
        token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
        secret = os.environ.get('LINE_CHANNEL_SECRET')
        target = os.environ.get('LINE_PUSH_TARGET')
        
        if not token or not secret:
            return jsonify({
                "status": "warning", 
                "message": "Line Bot 認證設置不完整",
                "token_set": bool(token),
                "secret_set": bool(secret),
                "target_set": bool(target)
            })
            
        return jsonify({
            "status": "success", 
            "message": "Line Bot 設置正確",
            "token_set": bool(token),
            "secret_set": bool(secret),
            "target_set": bool(target)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/debug-info")
def debug_info():
    """
    提供詳細的偵錯資訊
    """
    try:
        info = {
            "time": get_taiwan_current_time().isoformat(),
            "is_trading_day": check_trading_day(),
            "env_vars": {
                "mongodb_uri_set": bool(os.getenv("MONGODB_URI")),
                "api_key_set": bool(os.getenv("API_KEY")),
                "line_token_set": bool(os.getenv("LINE_CHANNEL_ACCESS_TOKEN")),
                "line_secret_set": bool(os.getenv("LINE_CHANNEL_SECRET")),
                "line_target_set": bool(os.getenv("LINE_PUSH_TARGET"))
            }
        }
        
        # 檢查資料庫連接
        if db_client:
            try:
                db_client.server_info()
                info["database"] = {
                    "status": "connected",
                    "databases": db_client.list_database_names()
                }
                
                if "market_data" in info["database"]["databases"]:
                    info["database"]["collections"] = db.list_collection_names()
                    
                    # 獲取各集合的文檔數量
                    info["database"]["collection_counts"] = {}
                    for collection in info["database"]["collections"]:
                        info["database"]["collection_counts"][collection] = db[collection].count_documents({})
                        
                        # 如果有文檔，獲取最新的一條記錄
                        if db[collection].count_documents({}) > 0:
                            latest_doc = db[collection].find_one(sort=[("_id", -1)])
                            if latest_doc and "_id" in latest_doc:
                                latest_doc["_id"] = str(latest_doc["_id"])
                            info["database"]["latest_docs"] = {collection: latest_doc}
            except Exception as e:
                info["database"] = {
                    "status": "error",
                    "message": str(e)
                }
        else:
            info["database"] = {
                "status": "not_connected"
            }
        
        return jsonify(info)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    # 在啟動時進行系統初始化
    init_success = initialize_system()
    print(f"系統初始化{'成功' if init_success else '失敗'}")
    
    # 在背景執行排程任務
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # 啟動 Flask 應用
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
