"""
爬蟲模組套件
此文件使 crawlers 資料夾成為一個 Python 套件，方便導入各個爬蟲模組
"""

# 導入基礎爬蟲類
from .base_crawler import BaseCrawler

# 導入各爬蟲實現
from .twse_crawler import TWSECrawler

# 在這裡註冊所有爬蟲，方便統一導入
crawler_registry = {
    'twse': TWSECrawler,
    # 'three_institutes': ThreeInstitutesCrawler,  # 未來可以添加
    # 'futures': FuturesCrawler,  # 未來可以添加
}

# 定義對外公開的類和函數
__all__ = [
    "BaseCrawler",
    "TWSECrawler",
    "crawler_registry"
]
