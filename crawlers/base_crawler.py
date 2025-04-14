"""
爬蟲基礎類
功能：提供爬蟲的共同功能和介面，作為所有爬蟲模組的基礎類
"""

import time
import random
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
import pytz

# 導入資料庫訪問層
from database.db_access import db_layer

class BaseCrawler(ABC):
    """爬蟲基礎類"""
    
    def __init__(self, collection_name, db_layer_instance=None):
        """
        初始化爬蟲基礎類
        
        Args:
            collection_name: MongoDB集合名稱
            db_layer_instance: 資料庫訪問層實例，如果為None則使用默認實例
        """
        self.collection_name = collection_name
        self.db_layer = db_layer_instance or db_layer
        
        # 註冊集合（如果子類有定義索引，則使用子類的索引）
        indexes = getattr(self, 'collection_indexes', [])
        validator = getattr(self, 'collection_validator', None)
        self.db_layer.register_collection(collection_name, indexes, validator)
    
    def get_taiwan_current_time(self):
        """取得台灣目前時間"""
        return self.db_layer.get_taiwan_current_time()
    
    @abstractmethod
    def fetch_data(self):
        """
        爬取數據的實現
        
        返回值:
            dict: 爬取的數據字典，如果失敗則返回None
        """
        pass
    
    def save_to_database(self, data):
        """
        將數據保存到資料庫
        
        Args:
            data: 要保存的數據字典
            
        Returns:
            bool: 操作是否成功
        """
        if not data:
            print(f"{self.__class__.__name__}: 無數據可保存")
            return False
            
        try:
            # 檢查是否已有相同日期的資料
            if 'date' in data:
                existing = self.db_layer.find_one(
                    self.collection_name, 
                    {"date": data["date"]}
                )
                
                if existing:
                    # 更新已有資料
                    result = self.db_layer.update_one(
                        self.collection_name,
                        {"date": data["date"]},
                        {"$set": data}
                    )
                    success = result.modified_count > 0 or result.matched_count > 0
                    print(f"{self.__class__.__name__}: 資料已更新至資料庫: {data.get('date', 'unknown')}")
                    return success
                else:
                    # 新增資料
                    result = self.db_layer.insert_one(self.collection_name, data)
                    success = result.inserted_id is not None
                    print(f"{self.__class__.__name__}: 資料已新增至資料庫: {data.get('date', 'unknown')}")
                    return success
            else:
                # 無日期欄位的資料，直接插入
                result = self.db_layer.insert_one(self.collection_name, data)
                success = result.inserted_id is not None
                print(f"{self.__class__.__name__}: 資料已新增至資料庫 (無日期欄位)")
                return success
                
        except Exception as e:
            print(f"{self.__class__.__name__}: 儲存資料至資料庫時出錯: {str(e)}")
            traceback.print_exc()
            return False
    
    def format_output(self, data):
        """
        格式化輸出結果為易讀的文字格式
        
        Args:
            data: 爬取的數據字典
            
        Returns:
            str: 格式化後的文字
        """
        # 子類應該重寫此方法以提供格式化輸出
        return str(data)
    
    def check_and_fetch_data(self, max_retries=5, retry_interval_min=1, retry_interval_max=3, ignore_time_check=False):
        """
        檢查並爬取最新數據，如果數據未更新則在指定時間內重試
        
        Args:
            max_retries: 最大重試次數
            retry_interval_min: 最小重試間隔（分鐘）
            retry_interval_max: 最大重試間隔（分鐘）
            ignore_time_check: 是否忽略時間檢查（用於強制初始化）
            
        Returns:
            dict: 包含最新數據的字典，若失敗則返回None
        """
        last_data = None
        
        for attempt in range(max_retries):
            print(f"{self.__class__.__name__}: 嘗試第 {attempt + 1} 次爬取數據...")
            data = self.fetch_data()
            
            # 保存最後一次爬取的結果
            if data:
                last_data = data
                
                # 嘗試保存到資料庫
                self.save_to_database(data)
                
                # 如果設置了忽略時間檢查，直接返回數據
                if ignore_time_check:
                    print(f"{self.__class__.__name__}: 忽略時間檢查，直接返回數據")
                    return data
                
                # 檢查資料日期是否為最新
                # 在實際應用中，您可能需要更複雜的邏輯來確定資料是否為最新
                print(f"{self.__class__.__name__}: 成功獲取數據")
                return data
            
            # 使用指數退避算法計算等待時間
            if attempt < max_retries - 1:
                wait_minutes = random.uniform(retry_interval_min, retry_interval_max)
                wait_seconds = int(wait_minutes * 60)
                print(f"{self.__class__.__name__}: 等待 {wait_seconds} 秒後重試...")
                time.sleep(wait_seconds)
        
        print(f"{self.__class__.__name__}: 已達最大重試次數，返回最後一次爬取的結果")
        return last_data  # 返回最後一次爬取的結果，即使可能不是今天的
