import traceback
import requests

def test_twse_api():
    """測試台灣證交所 API"""
    try:
        # 使用 JSON API
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.twse.com.tw/",
        }
        
        print(f"發送請求到: {url}")
        response = requests.get(url, headers=headers, timeout=30)
        
        print(f"響應狀態碼: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"API 響應狀態: {data.get('stat')}")
            print(f"API 響應標題: {data.get('title')}")
            
            if 'fields' in data and 'data' in data:
                print(f"欄位: {data['fields']}")
                print(f"數據行數: {len(data['data'])}")
                if data['data']:
                    print(f"最新一行: {data['data'][-1]}")
            else:
                print("無法找到有效數據欄位")
                print(f"完整響應: {data}")
        else:
            print(f"API 請求失敗: {response.text[:500]}")
        
    except Exception as e:
        print(f"測試 API 時出錯: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    test_twse_api()
