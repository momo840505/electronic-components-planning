# 生產排程決策看板 v8

這版重新整理視覺與內容，重點是讓非資料科學背景使用者一眼看懂。

## v8 改動

- 修正頁首被切到的問題
- 拿掉「如果主管追問」等面試導向文字
- 主畫面所有規劃數量不再顯示 `k`
- 改成卡片式、柔和漸層、玻璃感排版
- 新增「產能被什麼占用」堆疊圖
- 堆疊項目：
  - 原本已排工作
  - 安全保留
  - 本次新訂單
  - 剩餘空間
- 情境切換後，訂單風險與產能圖會一起重新計算
- Forecast 技術細節移到「需求預測依據」折疊區

## Render

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```
