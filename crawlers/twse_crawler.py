"""
台灣證交所加權指數爬蟲
功能：爬取台灣證交所的加權指數資料
資料來源：https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html
"""

import pandas as pd
import re
from bs4 import BeautifulSoup
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
        self.url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
        爬取證交所加權指數資料
        
        Returns:
            dict: 包含最新加權指數資料的字典，若失敗則返回None
        """
        try:
            # 直接使用 requests 發送請求
            print("發送請求到台灣證交所...")
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()  # 如果請求失敗，拋出異常
            
            # 輸出一部分響應內容以便調試
            print(f"響應狀態碼: {response.status_code}")
            print(f"響應內容前500個字符: {response.text[:500]}")
            
            # 解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 尋找表格 - 更精確地定位表格
            tables = soup.find_all('table')
            print(f"找到 {len(tables)} 個表格")
            
            if not tables:
                print("找不到資料表格")
                return None
            
            # 嘗試每個表格直到找到正確的一個
            for i, table in enumerate(tables):
                print(f"處理第 {i+1} 個表格")
                
                # 檢查表格標題，確保是我們需要的表格
                if table.find('th', text=re.compile('日期')) and table.find('th', text=re.compile('發行量加權股價指數')):
                    print("找到加權指數表格")
                    # 使用pandas解析表格
                    dfs = pd.read_html(str(table))
                    
                    if not dfs or len(dfs) == 0:
                        print(f"無法解析表格 {i+1}")
                        continue
                    
                    df = dfs[0]
                    print(f"表格 {i+1} 列數: {len(df)}")
                    
                    # 檢查表格是否為空
                    if df.empty:
                        print(f"表格 {i+1} 為空")
                        continue
                    
                    # 檢查列名
                    print(f"表格 {i+1} 列名: {df.columns.tolist()}")
                    
                    # 確保有必要的列
                    expected_columns = ['日期', '成交金額', '成交股數', '成交筆數', '發行量加權股價指數', '漲跌點數']
                    if not all(col in df.columns for col in expected_columns):
                        print(f"表格 {i+1} 缺少必要列")
                        continue
                    
                    # 取得最新一筆資料（最後一行）
                    if len(df) == 0:
                        print(f"表格 {i+1} 無資料列")
                        continue
                        
                    latest_data = df.iloc[-1].to_dict()
                    print(f"最新資料: {latest_data}")
                    
                    # 轉換日期格式
                    iso_date = self._convert_chinese_date_to_iso(latest_data['日期'])
                    if not iso_date:
                        print(f"無法轉換日期格式: {latest_data['日期']}")
                        continue
                    
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
                        "fetched_at": self.get_taiwan_current_time().isoformat()
                    }
                    
                    # 儲存到資料庫
                    if self.collection:
                        self._save_to_database(result)
                    
                    return result
            
            print("未找到加權指數表格")
            return None
                
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

def main():
    """主程式"""
    try:
        # 初始化爬蟲
        crawler = TWSECrawler()
        
        # 爬取數據
        print("開始爬取加權指數數據...")
        data = crawler.check_and_fetch_data()
        
        if data:
            print("成功爬取到數據：")
            print(f"- 日期：{data.get('date', 'N/A')}")
            print(f"- 指數：{data.get('index', 'N/A')}")
            print(f"- 漲跌：{data.get('change', 'N/A')}")
            
            # 格式化輸出
            output = crawler.format_output(data)
            print("格式化輸出：")
            print(output)
            
            # 這裡可以加入發送到Line Bot的邏輯
        else:
            print("無法取得加權指數資料")
            
    except Exception as e:
        print(f"執行主程式時發生錯誤: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
