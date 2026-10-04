# Planner 決策 Dashboard v5

這版 Dashboard 的重點不是把 Notebook 表格全部搬上網頁，而是讓生管主管可以直接回答四個問題：

1. 現在是哪張訂單有風險？
2. 為什麼有風險？
3. 是哪個月份的 Capacity 被吃滿？
4. Forecast 如果換一個角度看，決策會不會改變？

## Forecast 為什麼不只看 Last Value？

04 的四模型 Backtest：

| Model | WAPE |
|---|---:|
| Last Value | **1.851%** |
| Holt-Winters | **1.991%** |
| XGBoost Direct | 4.164% |
| Seasonal Naive | 7.471% |

Last Value 雖然整體 WAPE 最低，但 05 又發現：

- Aggregate Bias = **-1.80%**
- **17 / 18** 次 Prediction 低於 Actual

因此 v5 不把 Last Value 當成唯一答案，而是：

- **Last Value**：Base Forecast
- **Holt-Winters**：趨勢型第二觀點
- **Upper Reference +2.96%**：歷史誤差尺度的上修情境
- **+10% Stress**：壓力測試
- **Custom What-if**：互動情境

Holt-Winters 的 3 個月 Forecast：

- 2026-09：5,771.39
- 2026-10：5,796.20
- 2026-11：5,803.92

Last Value 三個月都是 5,769。

兩者 3 個月平均差約 +0.37%，Dashboard 只取這個「相對比例」做一個額外敏感度測試，不把 USD 金額直接換成 synthetic production units。

## v5 主要互動

- 情境切換
- 自訂需求 -5% ～ +15%
- 狀態 Filter
- Priority Filter
- Due Month Filter
- 點一張 Order 看風險原因
- Capacity Stack 圖
- Scenario Late Quantity 比較
- Last Value vs Holt-Winters Forecast 比較
- 白話名詞說明

## 狀態顏色

- 🟢 按期
- 🟠 風險
- 🔴 延後
- ⚫ 未排入

## 白話名詞

- **既有負載**：新訂單進來以前，原本就已經排好的工作。
- **安全保留**：刻意不拿來接一般新單的緩衝。
- **高優先級**：只在相同交期月中先排，不代表真實客戶比較重要。
- **風險**：還能按期，但完成後剩餘新訂單容量低於 10%。
- **延後**：至少有部分數量排到需求交期月之後。
- **Late Quantity**：真正跨過交期月的那部分數量。

## Render

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```

如果 repo 根目錄直接包含 `app/`、`data/`、`requirements.txt`，Root Directory 留空。
