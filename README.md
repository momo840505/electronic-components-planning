# 生產規劃決策看板｜主管簡化版 v6

這版刻意拿掉大部分資料科學術語，把首頁改成一般主管先看得懂的順序：

1. 現在的結論是什麼？
2. 哪張訂單要注意？
3. 哪個月份最擠？
4. 建議做什麼？
5. 如果主管想追問，才展開 Forecast 分析依據。

## 首頁三個情境

- **目前預估**：Point / Last Value Base Plan
- **較保守預估（+2.96%）**：Historical Error 上修情境
- **需求增加 10%**：Stress Test

## 首頁不用懂的東西

WAPE、Bias、Holt-Winters 等分析不再放首頁。
它們全部收在：

`為什麼不能只看一個 Forecast？`

的折疊區。

## Forecast 邏輯

- Last Value WAPE = 1.851%，四模型最低，所以保留為 Base。
- 但 18 次 Backtest 中有 17 次低估，因此不能只看一個點。
- Holt-Winters WAPE = 1.991%，略差，但 3 個月 Forecast 為 5771 / 5796 / 5804，帶出輕微上升趨勢。
- 因此 Dashboard 把 Holt-Winters 當第二觀點，不取代 Base。

## Render

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```
