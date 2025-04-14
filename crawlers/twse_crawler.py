"""
台灣證交所加權指數爬蟲
功能：爬取台灣證交所的加權指數資料
資料來源：https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json
"""

import re
import traceback
from datetime import datetime
import pytz
import requests
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

class TWSECrawler:
    """台灣證交所加權指數爬蟲類"""
    
    def __init__(self, db_client=None):
        """
        初始化爬蟲類別
        
        Args:
            db_client: MongoDB客戶端實例，如果為None則嘗試創建新連接
        """
        # 設置資料來源URL和請求標頭
        self.base_url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.twse.com.tw/",
        }
        
        # 設置資料庫連接
        self.db_client = db_client
        if db_client:
            self.db = db_client["market_data"]
            # 確保集合存在
            if "twse_index" not in self.db.list_collection_names():
                self.db.create_collection("twse_index")
            self.collection = self.db["twse_index"]
        else:
            self.db = None
            self.collection = None
    
    def _convert_chinese_date_to_iso(self, date_str):
        """
        將中文日期格式(如：113/04/01)轉換為ISO標準格式(YYYY-MM-DD)
        
        Args:
            date_str: 中文日期字串
            
        Returns:
            ISO格式日期字串或None
        """
        # 處理民國年
        match = re.match(r'(\d+)/(\d+)/(\d+)', date_str)
        if match:
            year = int(match.group(1)) + 1911  # 民國年份加1911轉為西元年
            month = match.group(2).zfill(2)    # 補零
            day = match.group(3).zfill(2)      # 補零
            return f"{year}-{month}-{day}"
        return None
    
    def get_taiwan_current_time(self):
        """取得台灣目前時間"""
        taiwan_tz = pytz.timezone('Asia/Taipei')
        return datetime.now(taiwan_tz)
    
    def fetch_index_data(self):
        """
        爬取證交所加權指數資料 (使用 JSON API)
        
        Returns:
            dict: 包含最新加權指數資料的字典，若失敗則返回None
        """
        try:
            now = self.get_taiwan_current_time()
            date_str = now.strftime("%Y%m%d")
            
            # 使用 JSON API
            url = f"{self.base_url}?response=json&date={date_str}"
            print(f"請求 URL: {url}")
            
            # 發送請求
            print("發送請求到台灣證交所...")
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            # 解析 JSON 響應
            data = response.json()
            
            # 輸出響應狀態和部分數據以便調試
            print(f"響應狀態: {data.get('stat')}")
            print(f"響應標題: {data.get('title')}")
            
            # 檢查響應狀態
            if data.get('stat') != 'OK':
                print(f"API 返回錯誤狀態: {data.get('stat')}")
                print(f"完整響應: {data}")
                return None
            
            # 檢查數據欄位
            if 'fields' not in data or 'data' not in data or not data['data']:
                print("API 返回的數據結構不完整或為空")
                print(f"完整響應: {data}")
                return None
            
            # 獲取欄位名稱和對應的索引
            fields = data['fields']
            print(f"數據欄位: {fields}")
            
            # 確保有必要的欄位
            required_fields = ['日期', '成交金額', '成交股數', '成交筆數', '發行量加權股價指數', '漲跌點數']
            for field in required_fields:
                if field not in fields:
                    print(f"缺少必要欄位: {field}")
                    return None
            
            # 獲取各欄位的索引
            date_index = fields.index('日期')
            trading_value_index = fields.index('成交金額')
            trading_volume_index = fields.index('成交股數')
            transactions_index = fields.index('成交筆數')
            index_index = fields.index('發行量加權股價指數')
            change_index = fields.index('漲跌點數')
            
            # 獲取最新一筆資料（最後一行）
            latest_row = data['data'][-1]
            print(f"最新資料行: {latest_row}")
            
            # 轉換日期格式
            iso_date = self._convert_chinese_date_to_iso(latest_row[date_index])
            if not iso_date:
                print(f"無法轉換日期格式: {latest_row[date_index]}")
                return None
            
            # 整理資料結構
            result = {
                "date": iso_date,
                "chinese_date": latest_row[date_index],
                "trading_value": latest_row[trading_value_index],
                "trading_volume": latest_row[trading_volume_index],
                "transactions": latest_row[transactions_index],
                "index": latest_row[index_index],
                "change": latest_row[change_index],
                "fetched_at": self.get_taiwan_current_time().isoformat()
            }
            
            print(f"整理後的數據: {result}")
            
            # 儲存到資料庫
            if self.collection:
                success = self._save_to_database(result)
                print(f"數據保存結果: {'成功' if success else '失敗'}")
            
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
        
        try:
            # 處理可能存在的逗號
            trading_value_str = data["trading_value"].replace(',', '')
            # 將成交金額轉換為億元單位
            trading_value = float(trading_value_str)
            trading_value_billion = trading_value / 100000000  # 轉換為億元
            
            # 計算漲跌符號
            change_str = data['change'].replace(',', '')
            change = float(change_str)
            change_symbol = "▲" if change > 0 else "▼" if change < 0 else "-"
            
            # 格式化輸出
            formatted_output = (
                f"📊 大盤資訊 {data['chinese_date']}\n"
                f"加權指數：{data['index']} {change_symbol} {abs(change)}\n"
                f"成交金額：{trading_value_billion:.2f} 億元\n"
                f"成交筆數：{data['transactions']}\n"
            )
            
            return formatted_output
        except Exception as e:
            print(f"格式化輸出時出錯: {str(e)}")
            traceback.print_exc()
            return "格式化輸出資料時出錯"
    
    def check_and_fetch_data(self, max_retries=5, retry_interval_min=1, retry_interval_max=3, ignore_time_check=False):
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
        import time
        import random
        
        last_data = None
        
        for attempt in range(max_retries):
            print(f"嘗試第 {attempt + 1} 次爬取加權指數...")
            data = self.fetch_index_data()
            
            # 保存最後一次爬取的結果
            if data:
                last_data = data
                
                # 如果設置了忽略時間檢查，直接返回數據
                if ignore_time_check:
                    print("忽略時間檢查，直接返回數據")
                    return data
                
                # 檢查資料日期是否為最新
                # 在實際應用中，您可能需要更複雜的邏輯來確定資料是否為最新
                print(f"成功獲取數據，日期為: {data['date']}")
                return data
            
            # 使用簡單退避算法計算等待時間
            if attempt < max_retries - 1:
                wait_minutes = random.uniform(retry_interval_min, retry_interval_max)
                wait_seconds = int(wait_minutes * 60)
                print(f"等待 {wait_seconds} 秒後重試...")
                time.sleep(wait_seconds)
        
        print("已達最大重試次數，返回最後一次爬取的結果")
        return last_data  # 返回最後一次爬取的結果，即使可能不是今天的
    
    def get_historical_data(self, year, month):
        """
        獲取歷史數據
        
        Args:
            year: 年份（西元年）
            month: 月份 (1-12)
            
        Returns:
            list: 該月份的加權指數資料列表，若失敗則返回None
        """
        try:
            # 轉換為民國年
            tw_year = year - 1911
            
            # 格式化月份
            month_str = str(month).zfill(2)
            date_str = f"{tw_year}{month_str}01"  # 使用每月的第一天
            
            # 使用 JSON API
            url = f"{self.base_url}?response=json&date={year}{month_str}01"
            print(f"請求歷史數據 URL: {url}")
            
            # 發送請求
            print(f"發送請求獲取 {year}年{month}月 數據...")
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            # 解析 JSON 響應
            data = response.json()
            
            # 檢查響應狀態
            if data.get('stat') != 'OK':
                print(f"API 返回錯誤狀態: {data.get('stat')}")
                return None
            
            # 檢查數據欄位
            if 'fields' not in data or 'data' not in data or not data['data']:
                print("API 返回的數據結構不完整或為空")
                return None
            
            # 獲取欄位名稱和對應的索引
            fields = data['fields']
            
            # 確保有必要的欄位
            required_fields = ['日期', '成交金額', '成交股數', '成交筆數', '發行量加權股價指數', '漲跌點數']
            for field in required_fields:
                if field not in fields:
                    print(f"缺少必要欄位: {field}")
                    return None
            
            # 獲取各欄位的索引
            date_index = fields.index('日期')
            trading_value_index = fields.index('成交金額')
            trading_volume_index = fields.index('成交股數')
            transactions_index = fields.index('成交筆數')
            index_index = fields.index('發行量加權股價指數')
            change_index = fields.index('漲跌點數')
            
            # 處理所有數據行
            results = []
            for row in data['data']:
                # 轉換日期格式
                iso_date = self._convert_chinese_date_to_iso(row[date_index])
                if not iso_date:
                    print(f"無法轉換日期格式: {row[date_index]}")
                    continue
                
                # 整理資料結構
                result = {
                    "date": iso_date,
                    "chinese_date": row[date_index],
                    "trading_value": row[trading_value_index],
                    "trading_volume": row[trading_volume_index],
                    "transactions": row[transactions_index],
                    "index": row[index_index],
                    "change": row[change_index],
                    "fetched_at": self.get_taiwan_current_time().isoformat()
                }
                
                results.append(result)
                
                # 儲存到資料庫
                if self.collection:
                    self._save_to_database(result)
            
            print(f"成功獲取 {year}年{month}月 數據，共 {len(results)} 筆")
            return results
            
        except Exception as e:
            print(f"獲取歷史數據時發生錯誤: {str(e)}")
            traceback.print_exc()
            return None

def main():
    """主程式"""
    try:
        # 初始化爬蟲
        crawler = TWSECrawler()
        
        # 爬取最新數據
        print("開始爬取加權指數最新數據...")
        data = crawler.fetch_index_data()
        
        if data:
            print("成功爬取到最新數據：")
            print(f"- 日期：{data.get('date', 'N/A')}")
            print(f"- 指數：{data.get('index', 'N/A')}")
            print(f"- 漲跌：{data.get('change', 'N/A')}")
            
            # 格式化輸出
            output = crawler.format_output(data)
            print("格式化輸出：")
            print(output)
        else:
            print("無法取得最新加權指數資料，嘗試獲取本月歷史數據...")
            
            # 如果無法獲取最新數據，嘗試獲取本月的歷史數據
            now = crawler.get_taiwan_current_time()
            year = now.year
            month = now.month
            
            historical_data = crawler.get_historical_data(year, month)
            
            if historical_data and len(historical_data) > 0:
                print(f"成功獲取 {year}年{month}月 歷史數據，共 {len(historical_data)} 筆")
                print("最新一筆歷史數據：")
                latest = historical_data[-1]
                print(f"- 日期：{latest.get('date', 'N/A')}")
                print(f"- 指數：{latest.get('index', 'N/A')}")
                print(f"- 漲跌：{latest.get('change', 'N/A')}")
                
                # 格式化輸出
                output = crawler.format_output(latest)
                print("格式化輸出：")
                print(output)
            else:
                print("無法獲取任何加權指數資料")
            
    except Exception as e:
        print(f"執行主程式時發生錯誤: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
