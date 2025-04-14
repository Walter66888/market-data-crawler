# 爬蟲模組說明

此資料夾包含所有用於爬取不同來源盤後籌碼資料的爬蟲模組。

## 模組列表

1. `twse_crawler.py` - 台灣證交所加權指數爬蟲
   - 資料來源: https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=html
   - 功能: 爬取加權指數、成交金額、成交筆數等數據

## 如何新增爬蟲模組

當需要新增一個爬蟲模組時，請按照以下步驟:

1. 創建一個新的 Python 檔案，命名遵循 `{來源}_crawler.py` 格式
2. 實現一個爬蟲類，參考 `TWSECrawler` 的結構
3. 確保實現以下基本方法:
   - `fetch_xxx_data()` - 爬取數據
   - `format_output()` - 格式化輸出
   - `check_and_fetch_data()` - 檢查並爬取最新數據

4. 在 `__init__.py` 中匯出新的爬蟲類
5. 在 `main.py` 中導入並整合新的爬蟲

## 爬蟲模組基本架構

```python
class NewCrawler:
    def __init__(self, db_client=None):
        # 初始化，設置資料來源和資料庫連接
        pass
        
    def fetch_xxx_data(self):
        # 爬取特定數據
        pass
        
    def format_output(self, data):
        # 格式化輸出結果
        pass
        
    def check_and_fetch_data(self, max_retries=10, retry_interval_min=1, retry_interval_max=3):
        # 檢查並爬取最新數據，實現重試機制
        pass
```

## 注意事項

- 爬蟲間隔不宜過短，避免對目標網站造成過大負擔
- 必須處理可能的網路異常和解析錯誤
- 爬取的數據應保持一致的結構，方便後續整合
- 程式碼中使用繁體中文註解，提高可讀性
