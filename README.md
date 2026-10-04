# 生產排程決策看板 v7

這一版完全以「非資料科學背景的生管主管」為使用者。

首頁只回答四件事：

1. 現在排得完嗎？
2. 哪張訂單需要先處理？
3. 哪個月份最容易卡住？
4. 需求如果增加，結果會差多少？

Forecast 模型、WAPE、Bias 等內容全部放到折疊區，只有主管追問時才展開。

## 首頁用語

- 「按期」：可以照原交期完成
- 「先注意」：目前還沒延後，但安全空間很小
- 「延後」：至少一部分數量會跨過原交期
- 「已滿」：這個月可排新訂單的空間已用完

## 三個情境

- 目前需求
- 需求多約 3%
- 需求多 10%

## Render

Build:

```text
pip install -r requirements.txt
```

Start:

```text
streamlit run app/app.py --server.port $PORT --server.address 0.0.0.0
```
