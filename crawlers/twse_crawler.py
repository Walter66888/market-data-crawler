"""
台灣證交所加權指數爬蟲
功能：爬取台灣證交所的加權指數資料
資料來源：https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html
"""

import pandas as pd
import re
from bs4 import BeautifulSoup
import traceback
from dotenv import load_dotenv

# 導入爬蟲基礎類
from crawlers.base_crawler import BaseCrawler

# 導入工具函數
from utils import fetch_with_retry

# 載入環境變數
load_dotenv()

class TWSECrawler(BaseCrawler):
    """台灣證交所加權指數爬蟲類"""
    
    # 定義集合索引
    collection_indexes = [
        ('date', 1),  # 按日期建立索引
        ('fetched_at', -1)  # 按抓取時間建立索引
    ]
    
    def __init__(self, db_layer_instance=None):
        """
        初始化爬蟲類別
        
        Args:
            db_layer_instance: 資料庫訪問層實例，如果為None則使用默認實例
        """
        # 調用父類初始化，指定集合名稱
        super().__init__("twse_index", db_layer_instance)
        
        # 設置資料來源URL和請求標頭
        self.url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.twse.com.tw/",
        }
    
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
    
    def fetch_data(self):
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
                "fetched_at": self.get_taiwan_current_time().isoformat()
            }
            
            return result
            
        except Exception as e:
            print(f"爬取加權指數資料時發生錯誤: {str(e)}")
            traceback.print_exc()
            return None
    
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
