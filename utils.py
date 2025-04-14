"""
工具函數模組
包含系統共用的工具函數，如重試機制、日期處理等
"""

import time
import random
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
from bs4 import BeautifulSoup
import re
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import traceback

# 載入環境變數
load_dotenv()

# 連接 MongoDB - 使用全局變數避免重複連接
db_client = None
db = None

# 初始化資料庫連接
def initialize_db_connection():
    """初始化資料庫連接"""
    global db_client, db
    
    mongodb_uri = os.getenv("MONGODB_URI")
    if mongodb_uri:
        try:
            db_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            # 測試連接是否成功
            db_client.server_info()
            db = db_client["market_data"]
            print("MongoDB 連接成功 (utils)")
            return True
        except Exception as e:
            print(f"MongoDB 連接失敗 (utils): {str(e)}")
            db_client = None
            db = None
            return False
    else:
        print("警告：未提供MongoDB連接字串 (utils)")
        db_client = None
        db = None
        return False

# 嘗試初始化資料庫連接
initialize_db_connection()

def get_taiwan_current_time():
    """取得台灣目前時間"""
    taiwan_tz = pytz.timezone('Asia/Taipei')
    return datetime.now(taiwan_tz)

def exponential_backoff(attempt, base=1, cap=60, jitter=True):
    """
    計算指數退避等待時間
    
    Args:
        attempt: 當前重試次數
        base: 基礎等待時間（秒）
        cap: 最大等待時間（秒）
        jitter: 是否添加隨機波動
        
    Returns:
        float: 計算後的等待時間（秒）
    """
    wait = min(cap, base * (2 ** attempt))
    if jitter:
        # 增加±10%的隨機波動
        wait = wait * random.uniform(0.9, 1.1)
    return wait

def retry_operation(operation_func, max_retries=5, **kwargs):
    """
    通用重試機制
    
    Args:
        operation_func: 要執行的函數
        max_retries: 最大重試次數
        **kwargs: 傳遞給operation_func的參數
        
    Returns:
        函數operation_func的返回值
        
    Raises:
        Exception: 如果所有重試都失敗，則拋出最後一個異常
    """
    last_exception = None
    for attempt in range(max_retries):
        try:
            return operation_func(**kwargs)
        except Exception as e:
            last_exception = e
            wait_time = exponential_backoff(attempt)
            print(f"操作失敗: {str(e)}，等待 {wait_time:.2f} 秒後重試...")
            time.sleep(wait_time)
    
    # 所有重試失敗後，拋出最後捕獲的異常
    raise last_exception

def fetch_with_retry(url, headers=None, timeout=30, max_retries=5):
    """
    帶有重試機制的HTTP請求函數
    
    Args:
        url: 請求的URL
        headers: 請求標頭
        timeout: 請求超時時間（秒）
        max_retries: 最大重試次數
        
    Returns:
        requests.Response: 請求回應
        
    Raises:
        Exception: 如果所有重試都失敗，則拋出異常
    """
    def _fetch():
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response
    
    return retry_operation(_fetch, max_retries=max_retries)

def fetch_taiwan_holidays(year=None):
    """
    從台灣證交所網站獲取指定年份的休市日期
    
    Args:
        year: 年份，如果為None則獲取當前年份
        
    Returns:
        list: 休市日期列表，格式為 ["YYYY-MM-DD", ...]
    """
    if year is None:
        year = get_taiwan_current_time().year
    
    # 證交所民國年和西元年轉換
    # 要處理兩種情況：
    # 1. URL使用民國年（需要西元年-1911）
    # 2. 頁面顯示也是民國年，需要轉回西元年顯示
    tw_year = year - 1911
    
    # 構建請求URL - 注意證交所使用民國年
    url = f"https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=html&queryYear={tw_year}"
    
    try:
        response = fetch_with_retry(url)
        
        # 解析HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 尋找包含休市日期的表格
        table = soup.find('table')
        if not table:
            print("找不到休市日期表格")
            return []
            
        # 使用pandas解析表格
        dfs = pd.read_html(str(table))
        if not dfs:
            print("無法解析表格數據")
            return []
            
        df = dfs[0]
        
        # 提取日期列
        date_column = df.columns[0]  # 假設第一列是日期
        holidays = []
        
        # 將民國年日期轉換為西元年日期
        for date_str in df[date_column]:
            # 跳過非日期值
            if not isinstance(date_str, str) or not re.match(r'\d{3}/\d{2}/\d{2}', date_str):
                continue
                
            # 將民國年日期轉換為西元年日期
            match = re.match(r'(\d+)/(\d+)/(\d+)', date_str)
            if match:
                year = int(match.group(1)) + 1911  # 民國年份加1911轉為西元年
                month = match.group(2).zfill(2)    # 補零
                day = match.group(3).zfill(2)      # 補零
                holidays.append(f"{year}-{month}-{day}")
        
        return holidays
    
    except Exception as e:
        print(f"獲取台灣休市日期時出錯: {str(e)}")
        traceback.print_exc()
        return []

def update_holiday_database():
    """
    更新假日資料庫
    獲取當年和下一年的休市日期並存入資料庫
    
    Returns:
        bool: 操作是否成功
    """
    global db_client, db
    
    # 如果資料庫連接不存在，嘗試重新連接
    if not db_client:
        if not initialize_db_connection():
            print("資料庫未連接，無法更新假日資訊")
            return False
    
    current_year = get_taiwan_current_time().year
    next_year = current_year + 1
    
    try:
        # 獲取當年和下一年的休市日期
        current_year_holidays = fetch_taiwan_holidays(current_year)
        next_year_holidays = fetch_taiwan_holidays(next_year)
        
        # 如果獲取失敗，不進行更新
        if not current_year_holidays and not next_year_holidays:
            print("無法獲取休市日期，跳過更新")
            return False
        
        # 合併假日列表
        all_holidays = current_year_holidays + next_year_holidays
        
        # 如果還是沒有數據，則返回失敗
        if not all_holidays:
            print("合併後的假日列表為空，跳過更新")
            return False
        
        # 確保集合存在
        if "market_holidays" not in db.list_collection_names():
            db.create_collection("market_holidays")
        
        # 更新資料庫
        for holiday in all_holidays:
            # 檢查是否已存在
            existing = db.market_holidays.find_one({"date": holiday})
            if not existing:
                db.market_holidays.insert_one({
                    "date": holiday,
                    "created_at": get_taiwan_current_time().isoformat()
                })
                print(f"已添加休市日: {holiday}")
        
        print(f"休市日資料更新完成，共 {len(all_holidays)} 天")
        return True
    
    except Exception as e:
        print(f"更新休市日資料時出錯: {str(e)}")
        traceback.print_exc()
        return False

def is_holiday(date=None):
    """
    檢查指定日期是否為休市日
    
    Args:
        date: 日期字串 (YYYY-MM-DD) 或 datetime 物件，如果為None則檢查今天
        
    Returns:
        bool: 是否為休市日
    """
    global db_client, db
    
    # 如果資料庫連接不存在，嘗試重新連接
    if not db_client:
        if not initialize_db_connection():
            print("資料庫未連接，無法檢查假日")
            # 如果無法檢查，保守地假設不是假日
            return False
    
    if date is None:
        date = get_taiwan_current_time().strftime("%Y-%m-%d")
    elif isinstance(date, datetime):
        date = date.strftime("%Y-%m-%d")
    
    try:
        # 從資料庫查詢
        holiday = db.market_holidays.find_one({"date": date})
        return holiday is not None
    except Exception as e:
        print(f"檢查假日時出錯: {str(e)}")
        # 如果查詢出錯，保守地假設不是假日
        return False

def check_trading_day(date=None):
    """
    檢查指定日期是否為交易日
    
    Args:
        date: 日期物件，如果為None則檢查今天
        
    Returns:
        bool: 是否為交易日
    """
    if date is None:
        date = get_taiwan_current_time()
    
    # 週末不是交易日
    if date.weekday() >= 5:  # 5是星期六，6是星期日
        return False
    
    # 檢查是否為休市日
    if is_holiday(date):
        return False
    
    return True

def get_latest_trading_day(date=None):
    """
    獲取指定日期或之前的最近交易日
    
    Args:
        date: 日期物件，如果為None則使用今天
        
    Returns:
        datetime: 最近的交易日
    """
    if date is None:
        date = get_taiwan_current_time()
    
    # 向前找，直到找到交易日
    check_date = date
    max_days_back = 10  # 防止無限循環
    days_checked = 0
    
    while days_checked < max_days_back:
        if check_trading_day(check_date):
            return check_date
        check_date = check_date - timedelta(days=1)
        days_checked += 1
    
    # 如果找不到，返回原始日期
    return date

def check_if_already_crawled_today():
    """
    檢查今天是否已經成功爬取過數據
    
    Returns:
        bool: 是否已經爬取
    """
    global db_client, db
    
    # 如果資料庫連接不存在，嘗試重新連接
    if not db_client:
        if not initialize_db_connection():
            print("資料庫未連接，無法檢查是否已爬取")
            return False
    
    try:
        # 獲取今天的日期範圍
        now = get_taiwan_current_time()
        today_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
        
        # 確保集合存在
        if "twse_index" not in db.list_collection_names():
            return False
        
        # 檢查今天是否已經有爬取記錄
        result = db.twse_index.find_one({
            "fetched_at": {"$gte": today_start.isoformat()}
        })
        
        return result is not None
    except Exception as e:
        print(f"檢查今天是否已爬取時出錯: {str(e)}")
        return False

def should_crawl_on_startup():
    """
    檢查啟動時是否需要執行爬蟲
    用於在系統重啟後檢查是否有錯過的爬取任務
    
    Returns:
        bool: 是否需要執行爬蟲
    """
    now = get_taiwan_current_time()
    
    # 只在交易日且當天14:50以後檢查
    if not check_trading_day(now):
        return False
        
    if now.hour < 14 or (now.hour == 14 and now.minute < 50):
        return False
    
    # 檢查今天是否已經爬取過
    if check_if_already_crawled_today():
        return False
    
    # 只在18:00前執行
    if now.hour >= 18:
        return False
    
    return True
