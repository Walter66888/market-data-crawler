"""
爬蟲模組套件
此文件使 crawlers 資料夾成為一個 Python 套件，方便導入各個爬蟲模組
"""

# 讓 Python 在導入爬蟲模組時可以識別這個資料夾為一個套件

# 可以在這裡提供方便使用的導入，例如：
from .twse_crawler import TWSECrawler

# 這樣在其他檔案中可以直接使用：
# from crawlers import TWSECrawler

__all__ = ["TWSECrawler"]
