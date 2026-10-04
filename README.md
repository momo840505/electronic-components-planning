# Planner 決策 Dashboard

這個 Dashboard 是 `electronic-components-planning` 專案的展示層，重點不是重新訓練模型，而是把 01～06 Notebook 的輸出整理成面試可以操作的 Planner Decision Support Demo。

## 這個 Dashboard 做什麼？

它展示一個完整 Planner 決策流程：

`Forecast → Demand Scenario → Capacity → Order Allocation → Commit Month → On Time / At Risk / Late`

三個可切換情境：

| 情境 | 意義 | 主要結果 |
|---|---|---|
| 基準情境：Point Forecast | 使用 04 選出的 Last Value forecast 作 base plan | 0 Late、2 At Risk |
| 上修情境：Upper Reference (+2.96%) | 使用 05 的 80th percentile historical error 作需求上修 | 2 Late、Late Quantity 21.37 k |
| 壓力測試：+10% Demand Stress | 人工 what-if scenario | 2 Late、1 At Risk、Late Quantity 96 k |

## 重要限制

- 公開資料只用於 demand、backlog、forecast analysis。
- Capacity、customer order book、priority、due month 都是 synthetic planning scenario。
- Dashboard 不代表 ASE / 日月光真實客戶訂單、真實產能或真實交期。
- Late order 代表該訂單至少部分數量排到 requested due month 之後，不代表整張訂單全部延誤。

## 本機啟動方式

### 方法 A：雙擊啟動

Windows 直接雙擊：

```text
run_dashboard.bat
```

它會自動：

1. 建立 `.venv`
2. 安裝 `requirements.txt`
3. 啟動 Streamlit

成功後開啟：

```text
http://localhost:8501
```

### 方法 B：PowerShell 手動啟動

```powershell
cd C:\你的路徑\planner_dashboard_render_zh_v2
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app\app.py
```

## Render 部署方式

### 1. 建立 GitHub repo

把資料夾內容推到 GitHub，repo 根目錄應包含：

```text
app/
data/
assets/
requirements.txt
render.yaml
README.md
```

### 2. Render 設定

到 Render：

```text
New → Web Service
```

選擇 GitHub repo。

### 3. Build / Start Command

如果使用畫面手動設定：

```text
Build Command:
pip install -r requirements.txt
```

```text
Start Command:
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```

如果 Render 自動偵測 `render.yaml`，通常不用手動輸入。

### 4. 如果放在主專案子資料夾

若 repo 結構是：

```text
electronic-components-planning/
├── notebooks/
├── reports/
└── dashboard/
    ├── app/
    ├── data/
    ├── requirements.txt
    └── render.yaml
```

Render 的 Root Directory 要填：

```text
dashboard
```

Build / Start Command 一樣使用上面的指令。

## 面試 Demo 建議順序

1. 先切 `Point Forecast`：說明 base plan 可以排完，但有 2 張 At Risk。
2. 再切 `Upper Reference (+2.96%)`：說明需求只上修約 3%，O004 與 O006 就變 Late。
3. 最後切 `+10% Demand Stress`：說明 Late Order 數量一樣是 2，但 Late Quantity 從 21.37 k 增加到 96 k。

面試時重點可以說：

> Point forecast 可作為 base plan，但因為 forecast evaluation 顯示模型有 under-forecast bias，所以交期承諾前應同步檢查 upper demand scenario。若需求落在上方情境，O004 與 O006 要提前列為風險訂單，並評估 capacity reallocation、split delivery 或 commit month 調整。

## 需要注意的數字

| 指標 | 結果 |
|---|---:|
| Selected model | Last Value |
| Backtest WAPE | 1.851% |
| Aggregate Bias | -1.80% |
| Under-Forecast Count | 17 / 18 |
| Upper Reference Multiplier | 1.0296 |
| Point Scenario Late Orders | 0 |
| Upper Scenario Late Orders | 2 |
| Stress Scenario Late Quantity | 96 k |

