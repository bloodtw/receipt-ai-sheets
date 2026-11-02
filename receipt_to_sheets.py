#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 智慧刷卡簽單 & 收據辨識整理工具 (Python CLI 自動化版)
- 自動透過 Gemini 多模態視覺 API 辨識簽單收據
- 固定 14 欄由左至右依序擷取：
  1. 商店名稱 (中文)
  2. 商店名稱 (原文)
  3. 商品名稱 (中文)
  4. 商品名稱 (原文)
  5. 商品數量
  6. 商品價格
  7. 總金額
  8. 幣別
  9. 台幣金額
  10. 日期
  11. 時間
  12. 分類（餐飲、交通、購物）
  13. 購買人（留白）
  14. 匯率（依日期當天外幣vs台幣）
- 互動詢問儲存目標 Google 試算表檔案與工作表分頁
"""

import os
import sys
import json
import base64
import urllib.request
from datetime import datetime

# 常見幣別基準匯率 (如連網失敗時之備援)
DEFAULT_EXCHANGE_RATES = {
    "USD": 32.5,
    "JPY": 0.21,
    "EUR": 35.2,
    "CNY": 4.5,
    "HKD": 4.15,
    "KRW": 0.024,
    "GBP": 41.5,
    "THB": 0.95,
    "TWD": 1.0
}

STANDARD_HEADERS = [
    "商店名稱 (中文)",
    "商店名稱 (原文)",
    "商品名稱 (中文)",
    "商品名稱 (原文)",
    "商品數量",
    "商品價格",
    "總金額",
    "幣別",
    "台幣金額",
    "日期",
    "時間",
    "分類",
    "購買人",
    "匯率"
]

ALLOWED_CATEGORIES = ["餐飲", "交通", "購物"]
RATE_CACHE = {}


def normalize_category(cat):
    if not cat:
        return "購物"
    c = str(cat).strip()
    if c in ALLOWED_CATEGORIES:
        return c
    if any(k in c for k in ["餐", "飲", "食"]):
        return "餐飲"
    if any(k in c for k in ["交", "車", "運", "機票", "油"]):
        return "交通"
    return "購物"


def get_rate_on_date(currency, date_str, fallback_rates):
    """獲取指定日期當天之外幣對台幣匯率 (1 外幣 = X TWD)"""
    curr = (currency or "TWD").upper().strip()
    if curr in ["TWD", "NTD", "NT$"]:
        return 1.0

    clean_date = (date_str or "").strip()
    cache_key = f"{curr}_{clean_date or 'latest'}"
    if cache_key in RATE_CACHE:
        return RATE_CACHE[cache_key]

    curr_lower = curr.lower()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    urls = []
    if len(clean_date) == 10 and clean_date <= today_str:
        urls.append(f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{clean_date}/v1/currencies/{curr_lower}.json")
        urls.append(f"https://{clean_date}.currency-api.pages.dev/v1/currencies/{curr_lower}.json")
    urls.append(f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{curr_lower}.json")

    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                twd_rate = data.get(curr_lower, {}).get("twd")
                if isinstance(twd_rate, (int, float)) and twd_rate > 0:
                    rate = round(float(twd_rate), 4)
                    RATE_CACHE[cache_key] = rate
                    return rate
        except Exception:
            continue

    fallback = round(float(fallback_rates.get(curr, fallback_rates.get("USD", 32.5))), 4)
    RATE_CACHE[cache_key] = fallback
    return fallback


def analyze_receipt_image(image_path, api_key, model="gemini-3.1-flash-lite"):
    """使用 Gemini 多模態 API 辨識簽單內容"""
    print(f"\n[+] 正在分析收據圖片: {os.path.basename(image_path)} ...")

    with open(image_path, "rb") as f:
        img_bytes = f.read()
    b64_data = base64.b64encode(img_bytes).decode("utf-8")

    ext = os.path.splitext(image_path)[1].lower()
    mime_type = "image/jpeg"
    if ext == ".png":
        mime_type = "image/png"
    elif ext == ".webp":
        mime_type = "image/webp"
    elif ext == ".pdf":
        mime_type = "application/pdf"

    prompt = """你是一個專業的發票與信用卡簽單分析專家。請對圖片進行光學字元辨識 (OCR)，並嚴格依據 JSON Schema 回傳結構化資訊：
1. 提取商店名稱，同時包含繁體中文名稱 (merchant_zh) 與原始名稱 (merchant_original)。
2. 提取商品明細列表 (lineItems):
   - 商品繁體中文名稱 (name_zh)
   - 商品原始名稱 (name_original)
   - 商品數量 (quantity，預設 1)
   - 商品價格 (price: 若為折扣、優惠、折價券，金額請務必為負數，例如 -50)
3. 提取總金額 (amount: 數字) 與幣別 (currency: 如 TWD, USD, JPY 等)。
4. 提取交易日期 (date: YYYY-MM-DD) 與交易時間 (time: HH:MM)。
5. 提取簡單分類 (category: 僅限「餐飲」、「交通」、「購物」三選一)。
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
                        "merchant_zh": {"type": "STRING"},
                        "merchant_original": {"type": "STRING"},
                        "amount": {"type": "NUMBER"},
                        "currency": {"type": "STRING"},
                        "date": {"type": "STRING"},
                        "time": {"type": "STRING"},
                        "category": {
                            "type": "STRING",
                            "enum": ["餐飲", "交通", "購物"]
                        },
                        "lineItems": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "name_zh": {"type": "STRING"},
                                    "name_original": {"type": "STRING"},
                                    "quantity": {"type": "NUMBER"},
                                    "price": {"type": "NUMBER"}
                                },
                                "required": ["name_zh", "name_original", "quantity", "price"]
                            }
                        }
                    },
                    "required": ["merchant_zh", "merchant_original", "amount", "currency", "date", "category", "lineItems"]
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
    if "/spreadsheets/d/" in spreadsheet_id:
        spreadsheet_id = spreadsheet_id.split("/spreadsheets/d/")[1].split("/")[0]

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
    print("   AI 智慧刷卡簽單 & 收據自動辨識轉存系統 (14 欄標準版)")
    print("=" * 60)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        api_key = input("請輸入您的 Gemini API Key (或先設定 GEMINI_API_KEY 環境變數): ").strip()
        if not api_key:
            print("[!] 未提供 API Key，程式終止。")
            sys.exit(1)

    image_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if not image_arg:
        image_arg = input("\n請輸入簽單圖片/PDF路徑 (或直接拖曳檔案至此): ").strip().strip('"').strip("'")

    if not os.path.exists(image_arg):
        print(f"[!] 找不到檔案: {image_arg}")
        sys.exit(1)

    results = analyze_receipt_image(image_arg, api_key)
    if not results:
        print("[!] 未能辨識出有效交易紀錄。")
        sys.exit(1)

    print("\n" + "=" * 55)
    print("               【 辨識結果明細 (14 欄) 】")
    print("=" * 55)
    rows_to_save = []

    for r in results:
        store_zh = r.get("merchant_zh", "") or r.get("merchant_original", "")
        store_orig = r.get("merchant_original", "") or store_zh
        amt = float(r.get("amount", 0) or 0)
        curr = (r.get("currency", "TWD") or "TWD").upper()
        date = r.get("date", "")
        time = r.get("time", "")
        category = normalize_category(r.get("category", "購物"))
        rate = get_rate_on_date(curr, date, DEFAULT_EXCHANGE_RATES)
        twd = round(amt * rate, 2)
        buyer = ""  # 購買人（留白）

        print(f"▶ 商店：{store_zh} / {store_orig}")
        print(f"  日期時間：{date} {time} | 總金額：{curr} {amt} | 匯率：{rate} | 台幣：NT$ {twd} | 分類：{category}")

        items = r.get("lineItems", [])
        if items:
            for item in items:
                item_zh = item.get("name_zh") or item.get("name_original") or ""
                item_orig = item.get("name_original") or item_zh
                iqty = item.get("quantity", 1)
                iprice = item.get("price", 0)
                print(f"    - 品項: {item_zh} ({item_orig}) x{iqty} | 價格: {iprice}")

                rows_to_save.append([
                    store_zh,    # 1. 商店名稱 (中文)
                    store_orig,  # 2. 商店名稱 (原文)
                    item_zh,     # 3. 商品名稱 (中文)
                    item_orig,   # 4. 商品名稱 (原文)
                    iqty,        # 5. 商品數量
                    iprice,      # 6. 商品價格
                    amt,         # 7. 總金額
                    curr,        # 8. 幣別
                    twd,         # 9. 台幣金額
                    date,        # 10. 日期
                    time,        # 11. 時間
                    category,    # 12. 分類
                    buyer,       # 13. 購買人（留白）
                    rate         # 14. 匯率
                ])
        else:
            rows_to_save.append([
                store_zh, store_orig, "", "", 1, amt, amt, curr, twd, date, time, category, buyer, rate
            ])

    gas_webhook_url = os.getenv("GAS_WEBHOOK_URL")
    spreadsheet_id, worksheet_name = ask_user_target_sheet(gas_webhook_url)

    if gas_webhook_url:
        print(f"[*] 正在透過 Google Apps Script Webhook 轉存至試算表...")
        payload = {
            "spreadsheetId": spreadsheet_id,
            "sheetName": worksheet_name,
            "autoHeader": True,
            "header": STANDARD_HEADERS,
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
        out_csv = f"receipt_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(out_csv, "w", encoding="utf-8-sig") as f:
            f.write(",".join(STANDARD_HEADERS) + "\n")
            for row in rows_to_save:
                f.write(",".join([f'"{str(c)}"' for c in row]) + "\n")
        print(f"\n[*] 備用 CSV 資料已輸出至: {out_csv}")
        print("💡 您亦可開啟隨附的 index.html 透過瀏覽器視覺化一鍵同步至 Google 試算表！")


if __name__ == "__main__":
    main()
