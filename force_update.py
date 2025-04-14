"""
強制更新腳本
功能：強制獲取最近幾個月的歷史資料，確保資料庫中有可用的加權指數數據
"""

import os
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from dotenv import load_dotenv

# 導入爬蟲模組
from crawlers.twse_crawler import TWSECrawler

# 載入環境變數
load_dotenv()

def get_taiwan_current_time():
    """取得台灣目前時間"""
    taiwan_tz = pytz.timezone('Asia/Taipei')
    return datetime.now(taiwan_tz)

def fetch_recent_months(months=3):
    """
    獲取最近幾個月的歷史資料
    
    Args:
        months: 要獲取的月份數
    
    Returns:
        bool: 操作是否成功
    """
    # 連接MongoDB
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        print("錯誤：未設定MONGODB_URI環境變數")
        return False
    
    try:
        # 建立連接
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        
        # 初始化爬蟲
        crawler = TWSECrawler(client)
        
        # 獲取當前時間
        now = get_taiwan_current_time()
        
        # 爬取當前月份和之前幾個月的資料
        success = False
        for i in range(months):
            # 計算目標月份
            target_month = now.month - i
            target_year = now.year
            
            # 處理月份小於1的情況
            if target_month <= 0:
                target_month += 12
                target_year -= 1
            
            print(f"獲取 {target_year}年{target_month}月 的歷史資料...")
            
            # 爬取該月資料
            month_data = crawler.get_historical_data(target_year, target_month)
            
            if month_data and len(month_data) > 0:
                print(f"成功獲取 {target_year}年{target_month}月 資料，共 {len(month_data)} 筆")
                success = True
            else:
                print(f"無法獲取 {target_year}年{target_month}月 資料")
        
        # 嘗試再次爬取最新數據
        latest_data = crawler.fetch_index_data()
        if latest_data:
            print("成功爬取最新資料：")
            print(f"- 日期：{latest_data.get('date', 'N/A')}")
            print(f"- 指數：{latest_data.get('index', 'N/A')}")
            success = True
        
        return success
        
    except Exception as e:
        print(f"獲取歷史資料時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("開始強制更新歷史資料...")
    success = fetch_recent_months(3)  # 獲取最近3個月的資料
    print(f"強制更新{'成功' if success else '失敗'}")
