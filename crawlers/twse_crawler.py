"""
台灣證交所加權指數爬蟲
功能：爬取台灣證交所的加權指數資料
資料來源：https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html
"""

import pandas as pd
from datetime import datetime
import re
from bs4 import BeautifulSoup
import time
import random
from pymongo import MongoClient
import os
from dotenv import load_dotenv

# 導入工具函數
from utils import (
    get_taiwan_current_time, fetch_with_retry, retry_operation,
    exponential_backoff
)

# 載入環境變數
load_dotenv()

class TWSECrawler:
    def __init__(self, db_client=None):
        """
        初始化爬蟲類別
        
        Args:
            db_client: MongoDB客戶端實例，如果為None則嘗試創建新連接
        """
        self.url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.twse.com.tw/",
        }
        
        # 設置資料庫連接
        if db_client is None:
            mongodb_uri = os.getenv("MONGODB_URI")
            if mongodb_uri:
                self.db_client = MongoClient(mongodb_uri)
                self.db = self.db_client["market_data"]
                self.collection = self.db["twse_index"]
            else:
                print("警告：未提供MongoDB連接字串，資料將不會被儲存。")
                self.db_client = None
                self.db = None
                self.collection = None
        else:
            self.db_client = db_client
            self.db = self.db_client["market_data"]
            self.collection = self.db["twse_index"]
    
    def _convert_chinese_date_to_iso(self, date_str):
        """
        將中文日期格式(如：113/04/01)轉換為ISO標準格式(YYYY-MM-DD)
        
        Args:
            date_str: 中文日期字串
            
        Returns:
            ISO格式日期字串
        """
        # 處理民國年
        match = re.match(r'(\d+)/(\d+)/(\d+)', date_str)
        if match:
            year = int(match.group(1)) + 1911  # 民國年份加1911轉為西元年
            month = match.group(2).zfill(2)    # 補零
            day = match.group(3).zfill(2)      # 補零
            return f"{year}-{month}-{day}"
        return None
    
    def fetch_index_data(self):
        """
        爬取證交所加權指數資料
        
        Returns:
            dict: 包含最新加權指數資料的字典，若失敗則返回None
        """
        try:
            # 使用重試機制進行HTTP請求
            response = fetch_with_retry(
                url=self.url, 
                headers=self.headers,
                timeout=30
            )
            
            # 解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 解析表格資料
            table = soup.find('table')
            if not table:
                print("找不到資料表格")
                return None
                
            # 使用pandas解析表格
            dfs = pd.read_html(str(table))
            if not dfs:
                print("無法解析表格數據")
                return None
                
            df = dfs[0]
            
            # 取得最新一筆資料（最後一行）
            latest_data = df.iloc[-1].to_dict()
            
            # 轉換日期格式
            iso_date = self._convert_chinese_date_to_iso(latest_data['日期'])
            
            # 整理資料結構
            result = {
                "date": iso_date,
                "chinese_date": latest_data['日期'],
                "trading_value": latest_data['成交金額'],
                "trading_volume": latest_data['成交股數'],
                "transactions": latest_data['成交筆數'],
                "index": latest_data['發行量加權股價指數'],
                "change": latest_data['漲跌點數'],
                "fetched_at": get_taiwan_current_time().isoformat()
            }
            
            # 儲存到資料庫
            if self.collection:
                self._save_to_database(result)
            
            return result
            
        except Exception as e:
            print(f"爬取加權指數資料時發生錯誤: {str(e)}")
            return None
    
    def _save_to_database(self, data):
        """
        將數據保存到資料庫
        
        Args:
            data: 要保存的數據字典
        """
        try:
            # 檢查是否已有相同日期的資料
            existing = self.collection.find_one({"date": data["date"]})
            if existing:
                self.collection.update_one(
                    {"date": data["date"]},
                    {"$set": data}
                )
                print(f"資料已更新至資料庫: {data['date']}")
            else:
                self.collection.insert_one(data)
                print(f"資料已新增至資料庫: {data['date']}")
        except Exception as e:
            print(f"儲存資料至資料庫時出錯: {str(e)}")
    
    def format_output(self, data):
        """
        格式化輸出結果為易讀的文字格式
        
        Args:
            data: 指數資料字典
            
        Returns:
            str: 格式化後的文字
        """
        if not data:
            return "無法取得加權指數資料"
        
        # 將成交金額轉換為億元單位
        trading_value = float(data["trading_value"].replace(',', ''))
        trading_value_billion = trading_value / 100000000  # 轉換為億元
        
        # 計算漲跌符號
        change = float(data['change'])
        change_symbol = "▲" if change > 0 else "▼" if change < 0 else "-"
        
        # 格式化輸出
        formatted_output = (
            f"📊 大盤資訊 {data['chinese_date']}\n"
            f"加權指數：{data['index']} {change_symbol} {abs(change)}\n"
            f"成交金額：{trading_value_billion:.2f} 億元\n"
            f"成交筆數：{data['transactions']}\n"
        )
        
        return formatted_output
    
    def check_and_fetch_data(self, max_retries=10, retry_interval_min=1, retry_interval_max=3, ignore_time_check=False):
        """
        檢查並爬取最新數據，如果數據未更新則在指定時間內重試
        
        Args:
            max_retries: 最大重試次數
            retry_interval_min: 最小重試間隔（分鐘）
            retry_interval_max: 最大重試間隔（分鐘）
            ignore_time_check: 是否忽略時間檢查（用於強制初始化）
            
        Returns:
            dict: 包含最新加權指數資料的字典，若失敗則返回None
        """
        for attempt in range(max_retries):
            print(f"嘗試第 {attempt + 1} 次爬取加權指數...")
            data = self.fetch_index_data()
            
            # 檢查爬取的資料是否是今天的
            # 注意：假日或是盤後未更新時，最新數據可能不是今天的
            if data:
                # 如果設置了忽略時間檢查，直接返回數據
                if ignore_time_check:
                    return data
                    
                taiwan_now = get_taiwan_current_time()
                today_date = taiwan_now.strftime("%Y-%m-%d")
                
                # 如果爬取的資料是最新的（當日數據或最後交易日數據）
                # 這裡簡化判斷，實際上可能需要比較複雜的邏輯確定是否為最新數據
                return data
            
            # 使用指數退避算法計算等待時間
            if attempt < max_retries - 1:
                wait_minutes = random.uniform(retry_interval_min, retry_interval_max)
                wait_seconds = int(wait_minutes * 60)
                print(f"資料可能尚未更新，等待 {wait_seconds} 秒後重試...")
                time.sleep(wait_seconds)
        
        print("已達最大重試次數，返回最後一次爬取的結果")
        return data  # 返回最後一次爬取的結果，即使可能不是今天的

def main():
    """主程式"""
    crawler = TWSECrawler()
    data = crawler.check_and_fetch_data()
    if data:
        output = crawler.format_output(data)
        print(output)
        # 這裡可以加入發送到Line Bot的邏輯
    else:
        print("無法取得加權指數資料")

if __name__ == "__main__":
    main()
