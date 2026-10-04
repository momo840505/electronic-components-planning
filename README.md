# Planner 決策 Dashboard

這個 Dashboard 是 `electronic-components-planning` 專案的互動展示層。它不重新訓練模型，而是把 01～06 Notebook 的正式輸出轉成比較接近 Planner 日常使用方式的畫面。

核心流程：

`Forecast → 需求情境 → 產能 → 訂單排程 → 可承諾月份 → 按期 / 風險 / 延後`

## 這版 Dashboard 有什麼互動？

### 1. 需求情境

可以切換：

- **基準：Point Forecast**
- **上修：Upper Reference (+2.96%)**
- **壓力測試：+10%**
- **自訂 What-if：-5% ～ +15%**

前三個情境會重新計算並自動檢查，確認是否與 06 Notebook 的固定輸出一致。

自訂 What-if 是即時模擬，不是 Notebook 固定結果。

### 2. 顯示範圍 Filter

可以依下列條件篩選：

- 狀態
- 優先級
- 需求交期月
- 訂單

這些 Filter **只改畫面要看哪些訂單，不會偷偷重排整體 Capacity**。

### 3. 訂單風險互動

可以選一張訂單，直接看到：

- 需求交期月
- 可承諾月份
- 優先級
- 承諾後餘裕
- 為什麼是按期 / 風險 / 延後
- 這張訂單實際被排到哪些月份

### 4. Capacity 互動

可以選月份查看：

- 總產能
- 既有負載
- 安全保留
- 新訂單可用產能

並用堆疊圖顯示每個月的 Capacity 到底被誰占用。

### 5. Forecast 證據

Dashboard 會同步顯示：

- Selected Model = Last Value
- Backtest WAPE = 1.851%
- Aggregate Bias = -1.80%
- Under-Forecast = 17 / 18
- Point Forecast / Upper / Lower Planning Reference

## 名詞白話解釋

| 名詞 | 白話意思 |
|---|---|
| 總產能 | 這個月最多可以做多少 |
| 既有負載 | 這次新訂單進來前，原本就排好的工作 |
| 安全保留 | 刻意保留、不拿來接一般新單的緩衝 |
| 新訂單可用產能 | 總產能 - 既有負載 - 安全保留 |
| 高優先級 | 同一交期月時優先排；只是模擬規則，不是真實客戶等級 |
| 按期 | 不晚於交期月，而且完成後仍有至少 10% 餘裕 |
| 風險 | 還能按期，但完成後餘裕低於 10% |
| 延後 | 至少一部分數量被排到交期月之後 |
| Late Quantity | 真正跨過交期月的那部分數量 |
| Spillover | 前面月份放不下，往後月移動的數量 |

## 三個 Notebook 固定情境結果

| 情境 | 總需求 | 按期 | 風險 | 延後 | Late Quantity | 12月承接 |
|---|---:|---:|---:|---:|---:|---:|
| Point Forecast | 650.00 k | 4 | 2 | 0 | 0.00 k | 0.00 k |
| Upper +2.96% | 669.24 k | 4 | 0 | 2 | 21.37 k | 19.24 k |
| +10% Stress | 715.00 k | 3 | 1 | 2 | 96.00 k | 65.00 k |

## 本機啟動

Windows 可以直接雙擊：

```text
run_dashboard.bat
```

或 PowerShell：

```powershell
cd C:\你的路徑\electronic-components-planning
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app\app.py
```

成功後開：

```text
http://localhost:8501
```

## Render 部署

如果 Dashboard 放在 repo 根目錄：

```text
app/
data/
.streamlit/
requirements.txt
render.yaml
README.md
```

Render 設定：

```text
Build Command
pip install -r requirements.txt
```

```text
Start Command
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```

Root Directory 留白。

Push 新 commit 後，Render 通常會自動部署；若沒有：

```text
Manual Deploy → Deploy latest commit
```

## 面試時怎麼 Demo

建議 2～4 分鐘：

1. 先選 **Point Forecast**：說明 0 Late，但有 2 張 At Risk，而且 9～11 月新訂單產能已滿。
2. 切 **Upper +2.96%**：直接看到 O004 / O006 變 Late。
3. 切 **+10% Stress**：Late Order 還是 2 張，但 Late Quantity 由 21.37 k 增加到 96 k。
4. 點進「訂單風險」看 O004 或 O006，說明它為什麼跨月。
5. 點「產能」說明既有負載、安全保留、新訂單可用產能。
6. 如果主管想玩，可以切 **自訂 What-if**，讓需求變動後結果即時計算。

## 重要限制

- Public manufacturing data 只用於 demand / backlog / forecast。
- Capacity、Customer Order、Priority、Due Month 都是 Synthetic Scenario。
- High Priority 不代表任何真實客戶等級。
- Dashboard 不代表 ASE / 日月光真實產能、訂單或交期風險。
- 自訂 What-if 只是模擬，不是新的 Forecast。
