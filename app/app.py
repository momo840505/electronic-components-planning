
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="生產規劃決策看板",
    page_icon="📦",
    layout="wide",
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / "data"

STATUS_ZH = {
    "On Time": "🟢 按期",
    "At Risk": "🟠 需注意",
    "Late": "🔴 延後",
    "Unscheduled": "⚫ 未排入",
}
PRIORITY_ZH = {"High": "高", "Normal": "一般"}
PRIORITY_RANK = {"High": 0, "Normal": 1}
AT_RISK_SLACK_THRESHOLD = 0.10

st.markdown(
    """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2.5rem; max-width: 1350px;}
h1 {font-size: 2rem !important;}
h2 {font-size: 1.45rem !important;}
h3 {font-size: 1.15rem !important;}
[data-testid="stMetricLabel"] {font-size: 0.88rem;}
[data-testid="stMetricValue"] {font-size: 1.65rem;}
div[data-testid="stAlert"] {border-radius: 12px;}
</style>
""",
    unsafe_allow_html=True,
)


def load_csv(name: str, date_columns=None) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"找不到資料檔：{path}")
    if date_columns:
        return pd.read_csv(path, parse_dates=date_columns)
    return pd.read_csv(path)


@st.cache_data
def load_data() -> Dict[str, pd.DataFrame]:
    return {
        "forecast": load_csv("final_3_month_order_forecast.csv", ["date"]),
        "planning_ref": load_csv("forecast_planning_reference.csv", ["date"]),
        "evaluation": load_csv("forecast_evaluation_summary.csv"),
        "model_summary": load_csv("order_forecast_model_summary.csv"),
        "capacity": load_csv("synthetic_capacity_plan.csv", ["month"]),
        "orders": load_csv("synthetic_order_book.csv", ["requested_due_month"]),
    }


def fmt_month(v):
    if pd.isna(v):
        return "-"
    return pd.Timestamp(v).strftime("%Y-%m")


def allocate_orders(
    orders: pd.DataFrame,
    capacity: pd.DataFrame,
    quantity_multiplier: float,
    scenario_name: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    capacity_work = capacity.copy().sort_values("month").reset_index(drop=True)
    remaining = {
        r.month: float(r.net_new_order_capacity)
        for r in capacity_work.itertuples()
    }
    net_lookup = {
        r.month: float(r.net_new_order_capacity)
        for r in capacity_work.itertuples()
    }

    work = orders.copy()
    work["priority_rank"] = work["priority"].map(PRIORITY_RANK)
    work = work.sort_values(
        ["requested_due_month", "priority_rank", "order_id"]
    ).reset_index(drop=True)

    allocation_records = []
    summary_records = []
    months = sorted(remaining.keys())

    for order in work.itertuples():
        qty = float(order.quantity * quantity_multiplier)
        qty_left = qty
        final_month = pd.NaT
        slack_after = np.nan

        for month in months:
            if qty_left <= 1e-9:
                break
            available = remaining[month]
            if available <= 1e-9:
                continue

            allocated = min(qty_left, available)
            remaining[month] -= allocated
            qty_left -= allocated

            allocation_records.append(
                {
                    "scenario": scenario_name,
                    "order_id": order.order_id,
                    "customer": order.customer,
                    "priority": order.priority,
                    "requested_due_month": order.requested_due_month,
                    "allocation_month": month,
                    "allocated_quantity": allocated,
                }
            )
            final_month = month
            slack_after = remaining[month] / net_lookup[month]

        if qty_left > 1e-9:
            status = "Unscheduled"
        elif final_month > order.requested_due_month:
            status = "Late"
        elif (
            final_month == order.requested_due_month
            and slack_after < AT_RISK_SLACK_THRESHOLD
        ):
            status = "At Risk"
        else:
            status = "On Time"

        summary_records.append(
            {
                "order_id": order.order_id,
                "customer": order.customer,
                "priority": order.priority,
                "scenario_quantity": qty,
                "requested_due_month": order.requested_due_month,
                "feasible_commit_month": final_month,
                "slack_after_commit_pct": slack_after,
                "status": status,
            }
        )

    allocation = pd.DataFrame(allocation_records)
    order_summary = pd.DataFrame(summary_records)

    monthly_alloc = (
        allocation.groupby("allocation_month", as_index=False)["allocated_quantity"]
        .sum()
        .rename(
            columns={
                "allocation_month": "month",
                "allocated_quantity": "allocated_new_orders",
            }
        )
    )

    capacity_result = capacity_work.merge(monthly_alloc, on="month", how="left")
    capacity_result["allocated_new_orders"] = (
        capacity_result["allocated_new_orders"].fillna(0.0)
    )
    capacity_result["remaining_new_order_capacity"] = (
        capacity_result["net_new_order_capacity"]
        - capacity_result["allocated_new_orders"]
    )
    capacity_result["new_order_utilization_pct"] = (
        capacity_result["allocated_new_orders"]
        / capacity_result["net_new_order_capacity"]
        * 100
    )

    return allocation, order_summary, capacity_result


def late_quantity(order_summary, allocation):
    late_ids = set(
        order_summary.loc[order_summary["status"].eq("Late"), "order_id"]
    )
    return float(
        allocation.loc[
            allocation["order_id"].isin(late_ids)
            & (
                allocation["allocation_month"]
                > allocation["requested_due_month"]
            ),
            "allocated_quantity",
        ].sum()
    )


DATA = load_data()
forecast = DATA["forecast"]
planning_ref = DATA["planning_ref"]
evaluation = DATA["evaluation"]
model_summary = DATA["model_summary"]
capacity = DATA["capacity"]
orders = DATA["orders"]

eval_lookup = dict(zip(evaluation["metric"], evaluation["value"].astype(str)))

upper_multiplier = float(
    (
        planning_ref["upper_planning_reference"]
        / planning_ref["selected_forecast"]
    ).mean()
)

last_avg = float(forecast["last_value"].mean())
holt_avg = float(forecast["holt_winters"].mean())
holt_multiplier = holt_avg / last_avg
holt_uplift = (holt_multiplier - 1) * 100

SCENARIOS = {
    "目前預估": ("Base", 1.00),
    "較保守預估（+2.96%）": ("Upper", upper_multiplier),
    "需求增加 10%": ("Stress", 1.10),
}

# -----------------------------
# Header
# -----------------------------
st.title("生產規劃決策看板")
st.caption(
    "一眼看懂：目前需求排不排得下、哪張訂單要注意、哪個月份產能最緊。"
)

scenario_label = st.radio(
    "先選一個情境",
    list(SCENARIOS.keys()),
    horizontal=True,
)
scenario_name, multiplier = SCENARIOS[scenario_label]

allocation, order_summary, cap_result = allocate_orders(
    orders, capacity, multiplier, scenario_name
)

late_qty = late_quantity(order_summary, allocation)
on_time_count = int((order_summary["status"] == "On Time").sum())
risk_count = int((order_summary["status"] == "At Risk").sum())
late_count = int((order_summary["status"] == "Late").sum())
total_demand = float(order_summary["scenario_quantity"].sum())

# -----------------------------
# Executive result
# -----------------------------
st.subheader("現在的結論")

if scenario_name == "Base":
    st.warning(
        "✅ 目前全部訂單都排得完，但 9～11 月可用的新訂單產能已經全部用滿。"
        "O004、O006 雖然還能按期完成，但已經幾乎沒有緩衝。"
    )
    action_text = (
        "交期可以先照目前計畫，但 O004、O006 不適合直接當成完全安全；"
        "回覆客戶前應再確認是否有需求上修、急單、重工或設備異常。"
    )
elif scenario_name == "Upper":
    st.error(
        "⚠️ 需求只比目前預估多約 3%，O004、O006 就會有部分數量延後。"
        f"真正跨過原交期月的數量合計 {late_qty:.2f} k。"
    )
    action_text = (
        "先處理 O004、O006：確認能否挪產能、拆批出貨，"
        "若無法補足，再重新確認可承諾月份。"
    )
else:
    st.error(
        f"🚨 需求增加 10% 時，仍有 {late_count} 張訂單延後，"
        f"但延後量放大到 {late_qty:.2f} k。"
    )
    action_text = (
        "這時已不是單純監控，而是需要提前協調產能、訂單優先順序與交期。"
    )

st.info("**建議動作：** " + action_text)

# -----------------------------
# KPIs
# -----------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("本情境總需求", f"{total_demand:.2f} k")
k2.metric("🟢 按期", on_time_count)
k3.metric("🟠 需注意", risk_count)
k4.metric("🔴 延後", late_count, f"延後量 {late_qty:.2f} k")

# -----------------------------
# Orders first
# -----------------------------
st.subheader("哪些訂單要注意？")

table = order_summary.copy()
table["交期"] = table["requested_due_month"].map(fmt_month)
table["預計完成"] = table["feasible_commit_month"].map(fmt_month)
table["狀態"] = table["status"].map(STATUS_ZH)
table["數量"] = table["scenario_quantity"].round(2)
table["優先順序"] = table["priority"].map(PRIORITY_ZH)
table["完成後剩餘空間"] = (
    table["slack_after_commit_pct"] * 100
).round(1)

table = table[
    [
        "order_id",
        "customer",
        "數量",
        "交期",
        "預計完成",
        "優先順序",
        "完成後剩餘空間",
        "狀態",
    ]
].rename(
    columns={
        "order_id": "訂單",
        "customer": "客戶",
    }
)

def style_status(v):
    if "按期" in str(v):
        return "background-color:#dcfce7;color:#166534;font-weight:700"
    if "需注意" in str(v):
        return "background-color:#fef3c7;color:#92400e;font-weight:700"
    if "延後" in str(v):
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    return ""

st.dataframe(
    table.style.map(style_status, subset=["狀態"]),
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "「需注意」= 還能按期，但完成這張單後，當月剩餘可用空間低於 10%。"
    "「延後」= 至少有一部分數量被排到原交期月之後。"
)

# -----------------------------
# Capacity simple view
# -----------------------------
st.subheader("哪個月份最擠？")

cap = cap_result.copy()
cap["月份"] = cap["month"].map(fmt_month)

fig = go.Figure()
fig.add_bar(
    x=cap["月份"],
    y=cap["net_new_order_capacity"],
    name="這個月最多可排的新訂單",
    marker_color="#cbd5e1",
)
fig.add_bar(
    x=cap["月份"],
    y=cap["allocated_new_orders"],
    name="目前已排的新訂單",
    marker_color=[
        "#ef4444" if x >= 99.9 else "#f59e0b" if x >= 90 else "#22c55e"
        for x in cap["new_order_utilization_pct"]
    ],
)
fig.update_layout(
    barmode="overlay",
    height=390,
    yaxis_title="k planning units",
    xaxis_title="",
    legend_title="",
    margin=dict(l=10, r=10, t=20, b=10),
)
st.plotly_chart(fig, use_container_width=True)

capacity_text = []
for r in cap.itertuples():
    util = r.new_order_utilization_pct
    if util >= 99.9:
        label = "🔴 已滿"
    elif util >= 90:
        label = "🟠 很緊"
    else:
        label = "🟢 尚有空間"
    capacity_text.append(
        {
            "月份": r.月份,
            "最多可排": round(r.net_new_order_capacity, 2),
            "目前已排": round(r.allocated_new_orders, 2),
            "剩餘": round(r.remaining_new_order_capacity, 2),
            "判斷": label,
        }
    )

st.dataframe(
    pd.DataFrame(capacity_text),
    use_container_width=True,
    hide_index=True,
)

# -----------------------------
# Simple order drill-down
# -----------------------------
with st.expander("想知道某張訂單為什麼被標成『需注意／延後』？"):
    order_id = st.selectbox(
        "選擇訂單",
        order_summary["order_id"].tolist(),
    )
    row = order_summary.loc[
        order_summary["order_id"].eq(order_id)
    ].iloc[0]

    st.write(
        f"**{order_id}｜{row['customer']}**："
        f"需求交期是 **{fmt_month(row['requested_due_month'])}**，"
        f"目前排完後預計在 **{fmt_month(row['feasible_commit_month'])}** 完成。"
    )

    if row["status"] == "On Time":
        st.success("這張單目前可以按期完成，而且沒有觸發低緩衝警示。")
    elif row["status"] == "At Risk":
        st.warning(
            f"這張單目前還能按期，但完成後只剩 "
            f"{row['slack_after_commit_pct'] * 100:.1f}% 可用空間。"
            "因此一旦有臨時需求、重工或設備異常，就很容易被推遲。"
        )
    elif row["status"] == "Late":
        st.error(
            "這張單至少有一部分數量被排到原交期月之後，"
            "所以不能再照原交期直接承諾。"
        )
    else:
        st.error("這張單在目前規劃期間內排不完。")

# -----------------------------
# Forecast evidence hidden from executive view
# -----------------------------
with st.expander("為什麼不能只看一個 Forecast？｜給想追問分析依據的人"):
    st.markdown(
        """
**先講結論：**  
Last Value 不是「錯的模型」，它只是有一個限制：當需求持續往上時，它容易反應得比較慢。

所以做法不是把它丟掉，而是把它當 **Base Forecast**，再用另一個方法和較保守情境做交叉檢查。
        """
    )

    ranked = model_summary.sort_values("wape_pct")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### Base：Last Value")
        st.write("Backtest WAPE：**1.851%（四種方法最低）**")
        st.write("3 個月預估：**5,769 / 5,769 / 5,769**")
        st.write("優點：簡單、短期整體誤差最低。")
        st.write("限制：近期 18 次驗證中有 **17 次低估**。")

    with c2:
        st.markdown("#### 第二觀點：Holt-Winters")
        st.write("Backtest WAPE：**1.991%**")
        st.write("3 個月預估：**5,771 / 5,796 / 5,804**")
        st.write("優點：會反映趨勢，所以預估有緩慢上升。")
        st.write("用途：不是取代 Last Value，而是提醒『需求可能比基準高一點』。")

    f = forecast.copy()
    f["月份"] = f["date"].map(fmt_month)

    fig_f = go.Figure()
    fig_f.add_scatter(
        x=f["月份"],
        y=f["last_value"],
        mode="lines+markers",
        name="Last Value（基準）",
        line=dict(color="#16a34a", width=3),
    )
    fig_f.add_scatter(
        x=f["月份"],
        y=f["holt_winters"],
        mode="lines+markers",
        name="Holt-Winters（第二觀點）",
        line=dict(color="#f59e0b", width=3),
    )
    fig_f.update_layout(
        height=330,
        yaxis_title="New Orders Forecast (USD mn)",
        xaxis_title="",
        legend_title="",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_f, use_container_width=True)

    st.info(
        f"Holt-Winters 的 3 個月平均 Forecast 比 Last Value 約高 **{holt_uplift:.2f}%**。"
        "這個差距雖然很小，但 Base Capacity 本來就已經滿載，"
        "所以一點點需求差異也可能改變最後一張訂單的交期結果。"
    )

with st.expander("名詞看不懂？用白話看"):
    st.markdown(
        """
- **既有負載**：新訂單進來以前，工廠本來就已經排好的工作。
- **安全保留**：故意留一點空間，不拿去塞一般新單，用來應付急單、重工、停機等狀況。
- **優先順序**：這個作品只設定「同一個交期月，高優先先排」，不是說真實客戶比較重要。
- **按期**：預計完成月份沒有晚於交期。
- **需注意**：目前還能按期，但完成後剩餘空間低於 10%。
- **延後**：至少有一部分數量會超過原交期月。
- **延後量**：真正跨過原交期月的那部分數量。
        """
    )

st.caption(
    "資料限制：Demand / Forecast 使用公開製造業資料；Capacity、客戶、訂單數量、優先順序與交期皆為 Synthetic Planning Scenario。"
)
