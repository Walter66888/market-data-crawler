"""
主應用程式
功能：整合所有爬蟲模組，處理定時任務和資料整合
"""

import os
import time
import random
import threading
import schedule
from datetime import datetime
import pytz
from dotenv import load_dotenv
from flask import Flask, request, jsonify, abort

# 導入爬蟲註冊表
from crawlers import crawler_registry

# 導入 Line Bot 模組和工具函數
from line_bot_integration import send_daily_push_notification, line_bot_bp
from utils import (
    get_taiwan_current_time, check_trading_day, update_holiday_database,
    should_crawl_on_startup, check_if_already_crawled_today
)

# 導入資料庫訪問層
from database.db_access import db_layer

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# 註冊 Line Bot Blueprint
app.register_blueprint(line_bot_bp)

def crawl_all_data():
    """爬取所有數據"""
    print(f"開始爬取所有數據 - {get_taiwan_current_time().isoformat()}")
    
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
    
    # 使用爬蟲註冊表動態爬取所有數據
    for crawler_name, crawler_class in crawler_registry.items():
        try:
            print(f"開始爬取 {crawler_name} 數據...")
            crawler = crawler_class()
            data = crawler.check_and_fetch_data()
            if data:
                all_data[crawler_name] = data
                data_updated = True
        except Exception as e:
            print(f"爬取 {crawler_name} 數據時出錯: {str(e)}")
    
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
    
    data_updated = False
    all_data = {}
    
    # 使用爬蟲註冊表動態爬取所有數據
    for crawler_name, crawler_class in crawler_registry.items():
        try:
            print(f"強制爬取 {crawler_name} 數據...")
            crawler = crawler_class()
            data = crawler.check_and_fetch_data(ignore_time_check=True)
            if data:
                all_data[crawler_name] = data
                data_updated = True
        except Exception as e:
            print(f"強制爬取 {crawler_name} 數據時出錯: {str(e)}")
    
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
    try:
        # 檢查資料庫連接狀態
        if not db_layer.db_client:
            return False
            
        # 檢查重要集合是否存在且有數據
        collections = db_layer.db.list_collection_names()
        has_holidays = "market_holidays" in collections and db_layer.count_documents("market_holidays") > 0
        has_index_data = "twse_index" in collections and db_layer.count_documents("twse_index") > 0
        
        return has_holidays and has_index_data
    except Exception as e:
        print(f"檢查資料庫初始化狀態時出錯: {str(e)}")
        return False

def initialize_system():
    """系統初始化函數"""
    print("正在初始化系統...")
    
    # 檢查資料庫是否已初始化
    is_initialized = check_database_initialized()
    
    if not is_initialized:
        print("系統尚未初始化，開始執行自動初始化...")
        try:
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
    db_status = "已連接" if db_layer.db_client else "未連接"
    return f"盤後籌碼爬蟲服務正在運行。資料庫狀態：{db_status}"

@app.route("/health")
def health_check():
    """健康檢查"""
    try:
        # 檢查資料庫連接
        db_connected = False
        if db_layer.db_client:
            try:
                # 嘗試執行一個簡單的資料庫操作
                db_layer.db_client.server_info()
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
            "database_initialized": db_initialized,
            "registered_crawlers": list(crawler_registry.keys())
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
        # 可以指定特定爬蟲
        crawler_name = request.args.get('crawler')
        
        if crawler_name:
            if crawler_name in crawler_registry:
                # 執行特定爬蟲
                print(f"手動觸發爬蟲: {crawler_name}")
                crawler = crawler_registry[crawler_name]()
                data = crawler.check_and_fetch_data()
                success = data is not None
                
                return jsonify({
                    "status": "success" if success else "no_update",
                    "crawler": crawler_name,
                    "message": f"爬蟲 {crawler_name} 已執行" + ("且數據已更新" if success else "但無新數據")
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": f"未知的爬蟲: {crawler_name}",
                    "available_crawlers": list(crawler_registry.keys())
                })
        else:
            # 執行所有爬蟲
            success = crawl_all_data()
            return jsonify({
                "status": "success" if success else "no_update",
                "message": "所有爬蟲已執行" + ("且數據已更新" if success else "但無新數據")
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
        if not db_layer.db_client:
            return jsonify({"status": "error", "message": "未連接到資料庫"})
        
        # 測試連接是否成功
        db_layer.db_client.server_info()
        
        # 獲取數據庫列表
        dbs = db_layer.db_client.list_database_names()
        
        # 檢查初始化狀態
        is_initialized = check_database_initialized()
        
        # 獲取集合列表
        collections = db_layer.db.list_collection_names() if "market_data" in dbs else []
            
        # 獲取各集合的文檔數量
        collection_counts = {}
        for collection in collections:
            collection_counts[collection] = db_layer.count_documents(collection)
        
        return jsonify({
            "status": "success", 
            "databases": dbs,
            "initialized": is_initialized,
            "collections": collections,
            "collection_counts": collection_counts
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
            },
            "registered_crawlers": list(crawler_registry.keys())
        }
        
        # 檢查資料庫連接
        if db_layer.db_client:
            try:
                db_layer.db_client.server_info()
                info["database"] = {
                    "status": "connected",
                    "databases": db_layer.db_client.list_collection_names() if hasattr(db_layer.db_client, 'list_collection_names') else []
                }
                
                collections = db_layer.db.list_collection_names() if hasattr(db_layer.db, 'list_collection_names') else []
                info["database"]["collections"] = collections
                
                # 獲取各集合的文檔數量
                info["database"]["collection_counts"] = {}
                info["database"]["latest_docs"] = {}
                
                for collection in collections:
                    count = db_layer.count_documents(collection)
                    info["database"]["collection_counts"][collection] = count
                    
                    # 如果有文檔，獲取最新的一條記錄
                    if count > 0:
                        latest_doc = db_layer.find_one(collection, {}, sort=[("_id", -1)])
                        if latest_doc and "_id" in latest_doc:
                            latest_doc["_id"] = str(latest_doc["_id"])
                        info["database"]["latest_docs"][collection] = latest_doc
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

@app.route("/list-crawlers")
def list_crawlers():
    """列出所有已註冊的爬蟲"""
    registered_crawlers = {}
    
    for name, crawler_class in crawler_registry.items():
        crawler_info = {
            "name": name,
            "class": crawler_class.__name__,
            "collection": getattr(crawler_class, 'collection_name', None) or name,
            "description": crawler_class.__doc__ or "無描述"
        }
        registered_crawlers[name] = crawler_info
    
    return jsonify({
        "status": "success",
        "crawlers": registered_crawlers
    })

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

@app.route("/test-crawler-simple", methods=['GET'])
def test_crawler_simple():
    """简单测试爬虫，无需API密钥"""
    try:
        # 初始化爬虫
        from crawlers.twse_crawler import TWSECrawler
        crawler = TWSECrawler(db_client)
        
        # 直接爬取数据
        print("开始测试爬虫...")
        data = crawler.fetch_index_data()
        
        if data:
            result = {
                "status": "success",
                "message": "成功爬取数据",
                "data": data
            }
        else:
            result = {
                "status": "error",
                "message": "无法爬取数据"
            }
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        })
