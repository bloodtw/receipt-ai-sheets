#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 智慧刷卡簽單 & 收據辨識整理工具 (Python CLI 自動化版)
- 自動透過 Gemini 多模態視覺 API 辨識簽單收據
- 擷取日期、時間、商店名稱、品項明細、數量、金額 (折扣負數)、幣別
- 自動換算當日即時台幣匯率 (TWD)
- 互動詢問儲存目標 Google 試算表檔案與工作表分頁
"""

import os
import sys
import json
import base64
import glob
import urllib.request
from datetime import datetime

# 檢查是否安裝必要套件
try:
    import requests
except ImportError:
    requests = None

# 常見幣別基準匯率 (如連網失敗時之備援)
DEFAULT_EXCHANGE_RATES = {
    "USD": 32.5,
    "JPY": 0.21,
    "EUR": 35.2,
    "CNY": 4.5,
    "HKD": 4.15,
    "KRW": 0.024,
    "GBP": 41.5,
    "TWD": 1.0
}


def get_realtime_exchange_rates():
    """獲取當日即時外匯匯率"""
    rates = dict(DEFAULT_EXCHANGE_RATES)
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            if "rates" in data and "TWD" in data["rates"]:
                usd_to_twd = data["rates"]["TWD"]
                for curr, rate_to_usd in data["rates"].items():
                    if rate_to_usd > 0:
                        rates[curr] = usd_to_twd / rate_to_usd
                rates["TWD"] = 1.0
                print(f"[*] 成功更新今日最新外匯匯率 (USD/TWD: {usd_to_twd:.2f})")
                return rates
    except Exception as e:
        print(f"[!] 無法獲取線上即時匯率，採用基準預設匯率: {e}")
    return rates


def convert_to_twd(amount, currency, rates):
    """換算台幣金額"""
    if not amount:
        return 0.0
    curr = (currency or "TWD").upper()
    if curr in ["TWD", "NTD", "NT$"]:
        return round(float(amount), 2)
    rate = rates.get(curr, rates.get("USD", 32.5))
    return round(float(amount) * rate, 2)


def analyze_receipt_image(image_path, api_key, model="gemini-3.1-flash-lite"):
    """使用 Gemini 多模態 API 辨識簽單內容"""
    print(f"\n[+] 正在分析收據圖片: {os.path.basename(image_path)} ...")

    # 讀取圖片檔案並轉成 base64
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    b64_data = base64.b64encode(img_bytes).decode("utf-8")

    # 判斷 MIME Type
    ext = os.path.splitext(image_path)[1].lower()
    mime_type = "image/jpeg"
    if ext in [".png"]:
        mime_type = "image/png"
    elif ext in [".webp"]:
        mime_type = "image/webp"
    elif ext in [".pdf"]:
        mime_type = "application/pdf"

    prompt = """你是一個專業的發票與信用卡簽單分析專家。請對圖片進行光學字元辨識 (OCR)，並嚴格依據 JSON Schema 回傳結構化資訊：
1. 提取商店名稱，同時包含原始名稱 (merchant_original) 與繁體中文名稱 (merchant_zh)。
2. 提取交易日期 (date: YYYY-MM-DD) 與交易時間 (time: HH:MM)。
3. 提取總金額 (amount: 數字) 與幣別 (currency: 如 TWD, USD, JPY 等)。
4. 提取分類 (category: 餐飲/交通/住宿/購物/日常開銷/其他)。
5. 提取商品明細列表 (lineItems):
   - 商品原始名稱 (name_original)
   - 商品繁體中文名稱 (name_zh)
   - 數量 (quantity，預設 1)
   - 價格/金額 (price: 若為折扣、優惠、折價券，金額請務必為負數，例如 -50)
6. 輸出一個符合格式的物件陣列 []。"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": b64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "merchant_original": {"type": "STRING"},
                        "merchant_zh": {"type": "STRING"},
                        "amount": {"type": "NUMBER"},
                        "date": {"type": "STRING"},
                        "time": {"type": "STRING"},
                        "currency": {"type": "STRING"},
                        "category": {"type": "STRING"},
                        "lineItems": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "name_original": {"type": "STRING"},
                                    "name_zh": {"type": "STRING"},
                                    "quantity": {"type": "NUMBER"},
                                    "price": {"type": "NUMBER"}
                                },
                                "required": ["name_original", "name_zh", "quantity", "price"]
                            }
                        }
                    },
                    "required": ["merchant_original", "merchant_zh", "amount", "date", "currency", "category"]
                }
            }
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            text = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "[]")
            return json.loads(text)
    except Exception as e:
        print(f"[!] 呼叫 Gemini API 發生錯誤: {e}")
        return []


def ask_user_target_sheet(gas_webhook_url=None):
    """
    互動詢問使用者：「要存在那一個檔案及那一個工作表」
    """
    print("\n" + "=" * 55)
    print("   📊 Google 試算表儲存設定詢問")
    print("=" * 55)

    spreadsheet_id = input("\n請輸入 Google 試算表檔案 ID 或完整網址:\n> ").strip()
    # 擷取 ID
    if "/spreadsheets/d/" in spreadsheet_id:
        spreadsheet_id = spreadsheet_id.split("/spreadsheets/d/")[1].split("/")[0]

    # 如果有 GAS Webhook URL，自動讀取該試算表的工作表清單
    existing_sheets = []
    if gas_webhook_url:
        try:
            query_url = f"{gas_webhook_url}?action=getSheets&spreadsheetId={spreadsheet_id}"
            req = urllib.request.Request(query_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("success"):
                    existing_sheets = data.get("sheets", [])
                    print(f"[*] 成功讀取試算表「{data.get('spreadsheetName', spreadsheet_id)}」現有分頁")
        except Exception:
            pass

    print("\n請問要儲存到哪一個工作表 (分頁)？")
    if existing_sheets:
        for idx, sname in enumerate(existing_sheets, 1):
            print(f"  [{idx}] {sname}")
        print(f"  [{len(existing_sheets)+1}] ＋ 新增自訂工作表分頁")
        choice = input(f"請輸入選項 (1~{len(existing_sheets)+1}) 或直接輸入分頁名稱: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(existing_sheets):
            target_worksheet = existing_sheets[int(choice) - 1]
        elif choice.isdigit() and int(choice) == len(existing_sheets) + 1:
            target_worksheet = input("請輸入新工作表名稱 (例如 2026年11月支出): ").strip()
        else:
            target_worksheet = choice or "工作表1"
    else:
        now_month = datetime.now().strftime("%Y-%m 簽單明細")
        print(f"建議分頁名稱：[1] 工作表1  [2] {now_month}")
        target_worksheet = input("請輸入目標工作表名稱 (直接按 Enter 預設為 工作表1): ").strip()
        if not target_worksheet or target_worksheet == "1":
            target_worksheet = "工作表1"
        elif target_worksheet == "2":
            target_worksheet = now_month

    print(f"\n[✓] 目標設定完成！檔案 ID: {spreadsheet_id} | 工作表: {target_worksheet}\n")
    return spreadsheet_id, target_worksheet


def main():
    print("=" * 60)
    print("   AI 智慧刷卡簽單 & 收據自動辨識轉存系統 (Google 試算表連動)")
    print("=" * 60)

    # 1. 取得 API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        api_key = input("請輸入您的 Gemini API Key (或先設定 GEMINI_API_KEY 環境變數): ").strip()
        if not api_key:
            print("[!] 未提供 API Key，程式終止。")
            sys.exit(1)

    # 2. 獲取即時匯率
    rates = get_realtime_exchange_rates()

    # 3. 指定圖片路徑或搜尋資料夾
    image_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if not image_arg:
        image_arg = input("\n請輸入簽單圖片/PDF路徑 (或直接拖曳檔案至此): ").strip().strip('"').strip("'")

    if not os.path.exists(image_arg):
        print(f"[!] 找不到檔案: {image_arg}")
        sys.exit(1)

    # 4. 執行 Gemini OCR 辨識
    results = analyze_receipt_image(image_arg, api_key)
    if not results:
        print("[!] 未能辨識出有效交易紀錄。")
        sys.exit(1)

    # 5. 格式化輸出預覽
    print("\n" + "=" * 55)
    print("               【 辨識結果明細 】")
    print("=" * 55)
    rows_to_save = []
    headers = ["日期", "時間", "商店名稱(繁中)", "商店名稱(原文)", "商品品項", "數量", "單價/金額", "原幣總額", "幣別", "折合台幣(TWD)", "分類", "備註"]

    for r in results:
        store_zh = r.get("merchant_zh", "")
        store_orig = r.get("merchant_original", "")
        amt = r.get("amount", 0)
        curr = r.get("currency", "TWD")
        twd = convert_to_twd(amt, curr, rates)
        date = r.get("date", "")
        time = r.get("time", "")
        category = r.get("category", "其他")

        print(f"▶ 商店：{store_zh} ({store_orig})")
        print(f"  日期時間：{date} {time} | 總額：{curr} {amt} (約 NT$ {twd}) | 類別：{category}")

        items = r.get("lineItems", [])
        if items:
            for item in items:
                iname = item.get("name_zh") or item.get("name_original")
                iqty = item.get("quantity", 1)
                iprice = item.get("price", 0)
                is_discount = iprice < 0
                tag = "[折扣折讓]" if is_discount else ""
                print(f"    - 品項: {iname} x{iqty} | 金額: {iprice} {tag}")

                rows_to_save.append([
                    date, time, store_zh, store_orig, iname, iqty, iprice, amt, curr, twd, category, tag
                ])
        else:
            rows_to_save.append([
                date, time, store_zh, store_orig, "無品項明細", 1, amt, amt, curr, twd, category, ""
            ])

    # 6. 核心：詢問要存在那一個檔案及那一個工作表
    gas_webhook_url = os.getenv("GAS_WEBHOOK_URL")
    spreadsheet_id, worksheet_name = ask_user_target_sheet(gas_webhook_url)

    # 7. 執行轉存
    if gas_webhook_url:
        print(f"[*] 正在透過 Google Apps Script Webhook 轉存至試算表...")
        payload = {
            "spreadsheetId": spreadsheet_id,
            "sheetName": worksheet_name,
            "autoHeader": True,
            "header": headers,
            "rows": rows_to_save
        }
        try:
            req = urllib.request.Request(
                gas_webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("success"):
                    print(f"🎉 成功存入 Google 試算表！網址: {res.get('spreadsheetUrl')}")
                else:
                    print(f"[!] 轉存失敗: {res.get('error')}")
        except Exception as e:
            print(f"[!] 轉存過程發生異常: {e}")
    else:
        # 匯出 CSV 檔供使用者直接匯入或開啟
        out_csv = f"receipt_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(out_csv, "w", encoding="utf-8-sig") as f:
            f.write(",".join(headers) + "\n")
            for row in rows_to_save:
                f.write(",".join([f'"{str(c)}"' for c in row]) + "\n")
        print(f"\n[*] 備用 CSV 資料已輸出至: {out_csv}")
        print("💡 您亦可開啟隨附的 index.html 透過瀏覽器視覺化一鍵同步至 Google 試算表！")


if __name__ == "__main__":
    main()
