"""
資料庫訪問層
功能：提供統一的資料庫訪問介面，自動處理集合創建與管理
"""

import os
import traceback
from datetime import datetime
import pytz
from pymongo import MongoClient
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

class DatabaseAccessLayer:
    """資料庫訪問抽象層"""
    
    _instance = None  # 單例模式
    
    @classmethod
    def get_instance(cls):
        """獲取單例實例"""
        if cls._instance is None:
            cls._instance = DatabaseAccessLayer()
        return cls._instance
    
    def __init__(self):
        """初始化資料庫連接"""
        self.db_client = None
        self.db = None
        self.initialize_connection()
        
        # 集合元數據註冊表
        self.collection_metadata = {}
    
    def initialize_connection(self):
        """初始化資料庫連接"""
        mongodb_uri = os.getenv("MONGODB_URI")
        if mongodb_uri:
            try:
                self.db_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
                # 測試連接是否成功
                self.db_client.server_info()
                self.db = self.db_client["market_data"]
                print("MongoDB 連接成功 (DatabaseAccessLayer)")
                return True
            except Exception as e:
                print(f"MongoDB 連接失敗 (DatabaseAccessLayer): {str(e)}")
                self.db_client = None
                self.db = None
                return False
        else:
            print("警告：未提供MongoDB連接字串 (DatabaseAccessLayer)")
            return False
    
    def register_collection(self, collection_name, indexes=None, validator=None):
        """
        註冊集合元數據
        
        Args:
            collection_name: 集合名稱
            indexes: 索引定義列表，例如 [('date', 1), ('symbol', 1)]
            validator: 資料驗證規則(MongoDB Schema Validation)
        """
        self.collection_metadata[collection_name] = {
            'indexes': indexes or [],
            'validator': validator
        }
        
        # 立即檢查並創建集合
        self.ensure_collection_exists(collection_name)
        
        return collection_name
    
    def ensure_collection_exists(self, collection_name):
        """確保集合存在，如果不存在則創建"""
        if not self.db_client:
            if not self.initialize_connection():
                print(f"無法創建集合 {collection_name}：資料庫未連接")
                return False
        
        try:
            # 檢查集合是否存在
            if collection_name not in self.db.list_collection_names():
                # 獲取集合元數據
                metadata = self.collection_metadata.get(collection_name, {})
                
                # 創建集合
                self.db.create_collection(collection_name)
                print(f"已創建集合: {collection_name}")
                
                # 創建索引
                for index_def in metadata.get('indexes', []):
                    if isinstance(index_def, tuple):
                        self.db[collection_name].create_index(index_def[0])
                    else:
                        self.db[collection_name].create_index(index_def)
                
                # 添加驗證器
                validator = metadata.get('validator')
                if validator:
                    self.db.command({
                        'collMod': collection_name,
                        'validator': validator
                    })
            
            return True
        except Exception as e:
            print(f"確保集合 {collection_name} 存在時出錯: {str(e)}")
            traceback.print_exc()
            return False
    
    def get_collection(self, collection_name):
        """獲取集合，如果不存在則自動創建"""
        self.ensure_collection_exists(collection_name)
        return self.db[collection_name]
    
    def find_one(self, collection_name, query=None, *args, **kwargs):
        """查詢單個文檔"""
        collection = self.get_collection(collection_name)
        return collection.find_one(query or {}, *args, **kwargs)
    
    def find(self, collection_name, query=None, *args, **kwargs):
        """查詢多個文檔"""
        collection = self.get_collection(collection_name)
        return collection.find(query or {}, *args, **kwargs)
    
    def insert_one(self, collection_name, document):
        """插入單個文檔"""
        collection = self.get_collection(collection_name)
        return collection.insert_one(document)
    
    def update_one(self, collection_name, query, update, *args, **kwargs):
        """更新單個文檔"""
        collection = self.get_collection(collection_name)
        return collection.update_one(query, update, *args, **kwargs)
    
    def delete_one(self, collection_name, query):
        """刪除單個文檔"""
        collection = self.get_collection(collection_name)
        return collection.delete_one(query)
    
    def count_documents(self, collection_name, query=None):
        """計數文檔數量"""
        collection = self.get_collection(collection_name)
        return collection.count_documents(query or {})
    
    def get_taiwan_current_time(self):
        """取得台灣目前時間"""
        taiwan_tz = pytz.timezone('Asia/Taipei')
        return datetime.now(taiwan_tz)

# 創建一個全局實例
db_layer = DatabaseAccessLayer.get_instance()
