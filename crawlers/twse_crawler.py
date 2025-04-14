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
import traceback
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
                try:
                    self.db_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
                    # 測試連接是否成功
                    self.db_client.server_info()
                    self.db = self.db_client["market_data"]
                    # 確保集合存在
                    if "twse_index" not in self.db.list_collection_names():
                        self.db.create_collection("twse_index")
                    self.collection = self.db["twse_index"]
                    print("MongoDB 連接成功 (twse_crawler)")
                except Exception as e:
                    print(f"MongoDB 連接失敗 (twse_crawler): {str(e)}")
                    self.db_client = None
                    self.db = None
                    self.collection = None
            else:
                print("警告：未提供MongoDB連接字串，資料將不會被儲存。")
                self.db_client = None
                self.db = None
                self.collection = None
        else:
            try:
                # 測試提供的連接是否有效
                db_client.server_info()
                self.db_client = db_client
                self.db = self.db_client["market_data"]
                # 確保集合存在
                if "twse_index" not in self.db.list_collection_names():
                    self.db.create_collection("twse_index")
                self.collection = self.db["twse_index"]
            except Exception as e:
                print(f"使用提供的 MongoDB 連接時出錯: {str(e)}")
                self.db_client = None
                self.db = None
                self.collection = None
    
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
            if not dfs or len(dfs) == 0:
                print("無法解析表格數據")
                return None
                
            df = dfs[0]
            
            # 檢查表格是否為空
            if df.empty:
                print("表格為空")
                return None
            
            # 檢查表格結構
            expected_columns = ['日期', '成交金額', '成交股數', '成交筆數', '發行量加權股價指數', '漲跌點數']
            for col in expected_columns:
                if col not in df.columns:
                    print(f"表格缺少預期欄位: {col}")
                    print(f"實際欄位: {df.columns.tolist()}")
                    return None
            
            # 取得最新一筆資料（最後一行）
            if len(df) == 0:
                print("表格無資料列")
                return None
                
            latest_data = df.iloc[-1].to_dict()
            
            # 轉換日期格式
            iso_date = self._convert_chinese_date_to_iso(latest_data['日期'])
            if not iso_date:
                print(f"無法轉換日期格式: {latest_data['日期']}")
                return None
            
            # 檢查數據格式
            for key, value in latest_data.items():
                if pd.isna(value):
                    print(f"欄位 {key} 的值為 NaN")
                    latest_data[key] = "0"  # 替換 NaN 為 "0"
            
            # 整理資料結構
            result = {
                "date": iso_date,
                "chinese_date": latest_data['日期'],
                "trading_value": str(latest_data['成交金額']),
                "trading_volume": str(latest_data['成交股數']),
                "transactions": str(latest_data['成交筆數']),
                "index": str(latest_data['發行量加權股價指數']),
                "change": str(latest_data['漲跌點數']),
                "fetched_at": get_taiwan_current_time().isoformat()
            }
            
            # 儲存到資料庫
            if self.collection:
                success = self._save_to_database(result)
                if not success:
                    print("儲存資料到資料庫失敗")
            
            return result
            
        except Exception as e:
            print(f"爬取加權指數資料時發生錯誤: {str(e)}")
            traceback.print_exc()
            return None
    
    def _save_to_database(self, data):
        """
        將數據保存到資料庫
        
        Args:
            data: 要保存的數據字典
            
        Returns:
            bool: 操作是否成功
        """
        if not self.collection:
            print("資料庫集合未初始化，無法保存數據")
            return False
            
        try:
            # 檢查是否已有相同日期的資料
            existing = self.collection.find_one({"date": data["date"]})
            if existing:
                # 更新已有資料
                result = self.collection.update_one(
                    {"date": data["date"]},
                    {"$set": data}
                )
                success = result.modified_count > 0 or result.matched_count > 0
                print(f"資料已更新至資料庫: {data['date']}")
                return success
            else:
                # 新增資料
                result = self.collection.insert_one(data)
                success = result.inserted_id is not None
                print(f"資料已新增至資料庫: {data['date']}")
                return success
        except Exception as e:
            print(f"儲存資料至資料庫時出錯: {str(e)}")
            traceback.print_exc()
            return False
