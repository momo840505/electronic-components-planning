
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Planner 決策 Dashboard",
    page_icon="📦",
    layout="wide",
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / "data"

STATUS_ZH = {
    "On Time": "🟢 按期",
    "At Risk": "🟠 風險",
    "Late": "🔴 延後",
    "Unscheduled": "⚫ 未排入",
}
PRIORITY_ZH = {"High": "高", "Normal": "一般"}
PRIORITY_RANK = {"High": 0, "Normal": 1}
AT_RISK_SLACK_THRESHOLD = 0.10

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.3rem; padding-bottom: 3rem;}
    [data-testid="stMetricLabel"] {font-size: 0.86rem;}
    [data-testid="stMetricValue"] {font-size: 1.55rem;}
    .stTabs [data-baseweb="tab-list"] {gap: 0.35rem;}
    .stTabs [data-baseweb="tab"] {padding-left: 0.85rem; padding-right: 0.85rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def load_csv(name: str, date_columns: list[str] | None = None) -> pd.DataFrame:
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
        "scenario_summary": load_csv("order_fulfillment_scenario_summary.csv"),
    }


def format_month(value) -> str:
    if pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m")


def allocate_orders(
    orders: pd.DataFrame,
    capacity: pd.DataFrame,
    quantity_multiplier: float,
    scenario_name: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    capacity_work = capacity.copy().sort_values("month").reset_index(drop=True)

    capacity_remaining = {
        row.month: float(row.net_new_order_capacity)
        for row in capacity_work.itertuples()
    }
    net_capacity_lookup = {
        row.month: float(row.net_new_order_capacity)
        for row in capacity_work.itertuples()
    }

    order_work = orders.copy()
    order_work["priority_rank"] = order_work["priority"].map(PRIORITY_RANK)
    order_work = order_work.sort_values(
        ["requested_due_month", "priority_rank", "order_id"]
    ).reset_index(drop=True)

    allocation_records = []
    order_summary_records = []
    planning_months_sorted = sorted(capacity_remaining.keys())

    for order in order_work.itertuples():
        adjusted_quantity = float(order.quantity * quantity_multiplier)
        remaining_quantity = adjusted_quantity
        final_commit_month = pd.NaT
        slack_after_commit_pct = np.nan

        for month in planning_months_sorted:
            if remaining_quantity <= 1e-9:
                break

            available = capacity_remaining[month]
            if available <= 1e-9:
                continue

            allocated = min(remaining_quantity, available)
            capacity_remaining[month] -= allocated
            remaining_quantity -= allocated

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

            final_commit_month = month
            slack_after_commit_pct = (
                capacity_remaining[month] / net_capacity_lookup[month]
            )

        if remaining_quantity > 1e-9:
            status = "Unscheduled"
        elif final_commit_month > order.requested_due_month:
            status = "Late"
        elif (
            final_commit_month == order.requested_due_month
            and slack_after_commit_pct < AT_RISK_SLACK_THRESHOLD
        ):
            status = "At Risk"
        else:
            status = "On Time"

        order_summary_records.append(
            {
                "scenario": scenario_name,
                "order_id": order.order_id,
                "customer": order.customer,
                "priority": order.priority,
                "base_quantity": float(order.quantity),
                "scenario_quantity": adjusted_quantity,
                "requested_due_month": order.requested_due_month,
                "feasible_commit_month": final_commit_month,
                "remaining_unscheduled": max(remaining_quantity, 0.0),
                "slack_after_commit_pct": slack_after_commit_pct,
                "status": status,
            }
        )

    allocation_detail = pd.DataFrame(allocation_records)
    order_summary = pd.DataFrame(order_summary_records)

    monthly_allocated = (
        allocation_detail.groupby("allocation_month", as_index=False)["allocated_quantity"]
        .sum()
        .rename(
            columns={
                "allocation_month": "month",
                "allocated_quantity": "allocated_new_orders",
            }
        )
    )

    capacity_result = capacity_work.merge(monthly_allocated, on="month", how="left")
    capacity_result["allocated_new_orders"] = capacity_result[
        "allocated_new_orders"
    ].fillna(0.0)
    capacity_result["remaining_new_order_capacity"] = (
        capacity_result["net_new_order_capacity"]
        - capacity_result["allocated_new_orders"]
    )
    capacity_result["new_order_capacity_utilization_pct"] = (
        capacity_result["allocated_new_orders"]
        / capacity_result["net_new_order_capacity"]
        * 100
    )
    capacity_result["operational_load_pct"] = (
        (
            capacity_result["existing_load"]
            + capacity_result["allocated_new_orders"]
        )
        / capacity_result["total_capacity"]
        * 100
    )

    return allocation_detail, order_summary, capacity_result


def summarize_scenario(
    scenario_name: str,
    multiplier: float,
    order_summary: pd.DataFrame,
    allocation_detail: pd.DataFrame,
    capacity_result: pd.DataFrame,
) -> dict:
    status_counts = order_summary["status"].value_counts()

    late_order_ids = set(
        order_summary.loc[order_summary["status"].eq("Late"), "order_id"]
    )

    late_quantity = float(
        allocation_detail.loc[
            (allocation_detail["order_id"].isin(late_order_ids))
            & (
                allocation_detail["allocation_month"]
                > allocation_detail["requested_due_month"]
            ),
            "allocated_quantity",
        ].sum()
    )

    december_spillover = float(
        allocation_detail.loc[
            allocation_detail["allocation_month"].eq(pd.Timestamp("2026-12-01")),
            "allocated_quantity",
        ].sum()
    )

    return {
        "scenario": scenario_name,
        "demand_multiplier": multiplier,
        "total_demand": float(order_summary["scenario_quantity"].sum()),
        "on_time_orders": int(status_counts.get("On Time", 0)),
        "at_risk_orders": int(status_counts.get("At Risk", 0)),
        "late_orders": int(status_counts.get("Late", 0)),
        "unscheduled_orders": int(status_counts.get("Unscheduled", 0)),
        "late_quantity": late_quantity,
        "december_spillover_quantity": december_spillover,
    }


def per_order_late_quantity(
    order_id: str,
    allocation_detail: pd.DataFrame,
) -> float:
    rows = allocation_detail.loc[
        allocation_detail["order_id"].eq(order_id)
        & (
            allocation_detail["allocation_month"]
            > allocation_detail["requested_due_month"]
        )
    ]
    return float(rows["allocated_quantity"].sum())


def status_style(value: str) -> str:
    if value == "🟢 按期":
        return "background-color:#dcfce7;color:#166534;font-weight:700"
    if value == "🟠 風險":
        return "background-color:#fef3c7;color:#92400e;font-weight:700"
    if value == "🔴 延後":
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    if value == "⚫ 未排入":
        return "background-color:#e5e7eb;color:#111827;font-weight:700"
    return ""


DATA = load_data()

forecast = DATA["forecast"].copy()
planning_ref = DATA["planning_ref"].copy()
evaluation = DATA["evaluation"].copy()
model_summary = DATA["model_summary"].copy()
capacity_base = DATA["capacity"].copy()
orders = DATA["orders"].copy()

eval_lookup = dict(zip(evaluation["metric"], evaluation["value"].astype(str)))

upper_multiplier = float(
    (
        planning_ref["upper_planning_reference"]
        / planning_ref["selected_forecast"]
    ).mean()
)

last_value_avg = float(forecast["last_value"].mean())
holt_winters_avg = float(forecast["holt_winters"].mean())
holt_winters_multiplier = holt_winters_avg / last_value_avg
holt_winters_uplift_pct = (holt_winters_multiplier - 1) * 100

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("情境控制")

    scenario_choice = st.radio(
        "需求情境",
        [
            "基準：Last Value",
            f"Holt-Winters 趨勢參考（+{holt_winters_uplift_pct:.2f}%）",
            "上修：Historical Error +2.96%",
            "壓力測試：+10%",
            "自訂 What-if",
        ],
    )

    if scenario_choice == "基準：Last Value":
        scenario_name = "Point Forecast"
        multiplier = 1.00
        scenario_short = "基準"
        scenario_source = "06 Notebook 固定情境"

    elif scenario_choice.startswith("Holt-Winters"):
        scenario_name = "Holt-Winters Trend Reference"
        multiplier = holt_winters_multiplier
        scenario_short = f"+{holt_winters_uplift_pct:.2f}%"
        scenario_source = "Dashboard 延伸情境：用兩個 Forecast 的相對比例做敏感度測試"

    elif scenario_choice == "上修：Historical Error +2.96%":
        scenario_name = "Upper Planning Reference"
        multiplier = upper_multiplier
        scenario_short = f"+{(upper_multiplier - 1) * 100:.2f}%"
        scenario_source = "05 / 06 Notebook 固定情境"

    elif scenario_choice == "壓力測試：+10%":
        scenario_name = "+10% Demand Stress"
        multiplier = 1.10
        scenario_short = "+10%"
        scenario_source = "06 Notebook 固定情境"

    else:
        custom_pct = st.slider(
            "需求調整",
            min_value=-5.0,
            max_value=15.0,
            value=5.0,
            step=0.5,
            format="%.1f%%",
        )
        scenario_name = "Custom What-if"
        multiplier = 1 + custom_pct / 100
        scenario_short = f"{custom_pct:+.1f}%"
        scenario_source = "Dashboard 自訂模擬，不是 Notebook 固定結果"

    st.caption(scenario_source)

    st.divider()
    st.markdown("### Forecast 快速判讀")
    st.caption(
        "WAPE：把所有預測差距加總後，相對於實際需求總量的誤差；越低越好。"
    )
    st.write(
        f"**Last Value：{eval_lookup.get('Pooled Backtest WAPE', 'N/A')}**  "
        "→ 四種方法中最低，所以拿來當 Base Forecast。"
    )
    st.write(
        f"**Bias：{eval_lookup.get('Aggregate Bias', 'N/A')}**  "
        "→ 負值代表近期整體偏低估。"
    )
    st.write(
        f"**低估：{eval_lookup.get('Under-Forecast Count', 'N/A')} / 18**  "
        "→ 18 次驗證中，大多數 Prediction 都低於 Actual。"
    )
    st.write(
        "**Holt-Winters：WAPE 1.991%**  "
        "→ 整體略差，但會把趨勢與季節性帶進預測，所以當第二個觀點。"
    )

# -----------------------------
# Main calculation
# -----------------------------
allocation, order_summary, capacity_result = allocate_orders(
    orders=orders,
    capacity=capacity_base,
    quantity_multiplier=multiplier,
    scenario_name=scenario_name,
)
summary = summarize_scenario(
    scenario_name,
    multiplier,
    order_summary,
    allocation,
    capacity_result,
)

st.title("Planner 決策 Dashboard")
st.caption(
    "重點不是看模型有多複雜，而是看需求變動後：哪張訂單會先出現風險、哪個月產能卡住、交期該不該直接承諾。"
)

# -----------------------------
# KPI
# -----------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("情境", scenario_short)
c2.metric("總需求", f"{summary['total_demand']:.2f} k")
c3.metric("風險單", summary["at_risk_orders"])
c4.metric("延後單", summary["late_orders"])
c5.metric("延後量", f"{summary['late_quantity']:.2f} k")

if summary["late_orders"] > 0:
    st.error(
        f"目前有 {summary['late_orders']} 張訂單至少有部分數量跨過原交期月，"
        f"真正延後的數量合計 {summary['late_quantity']:.2f} k。"
    )
elif summary["at_risk_orders"] > 0:
    st.warning(
        f"目前沒有延後單，但有 {summary['at_risk_orders']} 張風險單。"
        "意思是仍能在交期月完成，但完成後剩餘產能低於 10%，很容易被需求上修或異常吃掉。"
    )
else:
    st.success("目前沒有延後或風險訂單，產能仍有足夠緩衝。")

# -----------------------------
# Filters
# -----------------------------
st.subheader("先篩出要看的訂單")

f1, f2, f3 = st.columns(3)

status_options = list(STATUS_ZH.keys())
with f1:
    selected_status = st.multiselect(
        "狀態",
        status_options,
        default=status_options,
        format_func=lambda x: STATUS_ZH[x],
    )

priority_options = ["High", "Normal"]
with f2:
    selected_priority = st.multiselect(
        "優先級",
        priority_options,
        default=priority_options,
        format_func=lambda x: PRIORITY_ZH[x],
        help="這裡的『高』只代表同一交期月中先排，不代表真實客戶比較重要。",
    )

due_month_options = sorted(order_summary["requested_due_month"].dropna().unique())
with f3:
    selected_due = st.multiselect(
        "需求交期月",
        due_month_options,
        default=due_month_options,
        format_func=lambda x: format_month(x),
    )

filtered_orders = order_summary.loc[
    order_summary["status"].isin(selected_status)
    & order_summary["priority"].isin(selected_priority)
    & order_summary["requested_due_month"].isin(selected_due)
].copy()

fc1, fc2, fc3 = st.columns(3)
fc1.metric("篩選後訂單數", len(filtered_orders))
fc2.metric("篩選後需求量", f"{filtered_orders['scenario_quantity'].sum():.2f} k")
fc3.metric(
    "其中風險＋延後",
    int(filtered_orders["status"].isin(["At Risk", "Late"]).sum()),
)

# -----------------------------
# Tabs
# -----------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "訂單決策",
        "為什麼有風險",
        "產能怎麼被吃掉",
        "Forecast 怎麼判讀",
    ]
)

with tab1:
    st.subheader("目前情境的訂單結果")

    display_orders = filtered_orders.copy()
    display_orders["優先級"] = display_orders["priority"].map(PRIORITY_ZH)
    display_orders["狀態"] = display_orders["status"].map(STATUS_ZH)
    display_orders["需求交期"] = display_orders["requested_due_month"].map(format_month)
    display_orders["可承諾月份"] = display_orders["feasible_commit_month"].map(format_month)
    display_orders["承諾後餘裕(%)"] = (
        display_orders["slack_after_commit_pct"] * 100
    ).round(1)
    display_orders["情境需求量"] = display_orders["scenario_quantity"].round(2)

    display_orders = display_orders[
        [
            "order_id",
            "customer",
            "優先級",
            "情境需求量",
            "需求交期",
            "可承諾月份",
            "承諾後餘裕(%)",
            "狀態",
        ]
    ].rename(
        columns={
            "order_id": "訂單",
            "customer": "客戶",
        }
    )

    styled_orders = display_orders.style.map(
        status_style,
        subset=["狀態"],
    )

    st.dataframe(
        styled_orders,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "判讀順序：先看需求交期 → 再看可承諾月份 → 最後看狀態。"
        "『風險』不是已經延後，而是雖然還排得進去，但幾乎沒有產能緩衝。"
    )

    st.subheader("四種情境放在一起看")

    comparison_specs = [
        ("基準", 1.00, "06 Notebook"),
        ("Holt-Winters", holt_winters_multiplier, "Dashboard 延伸"),
        ("Upper +2.96%", upper_multiplier, "05/06 Notebook"),
        ("+10% Stress", 1.10, "06 Notebook"),
    ]

    comparison_rows = []
    for label, mult, source in comparison_specs:
        a, o, c = allocate_orders(
            orders=orders,
            capacity=capacity_base,
            quantity_multiplier=mult,
            scenario_name=label,
        )
        s = summarize_scenario(label, mult, o, a, c)
        comparison_rows.append(
            {
                "情境": label,
                "來源": source,
                "需求變化(%)": (mult - 1) * 100,
                "總需求": s["total_demand"],
                "風險單": s["at_risk_orders"],
                "延後單": s["late_orders"],
                "延後量": s["late_quantity"],
                "12月承接": s["december_spillover_quantity"],
            }
        )

    compare_df = pd.DataFrame(comparison_rows)

    fig_compare = go.Figure()
    fig_compare.add_bar(
        x=compare_df["情境"],
        y=compare_df["延後量"],
        name="延後量",
        marker_color=["#94a3b8", "#f59e0b", "#ef4444", "#991b1b"],
        text=[f"{v:.2f}" for v in compare_df["延後量"]],
        textposition="outside",
    )
    fig_compare.update_layout(
        height=360,
        yaxis_title="延後量（k planning units）",
        xaxis_title="",
        showlegend=False,
        margin=dict(l=10, r=10, t=25, b=10),
    )
    st.plotly_chart(fig_compare, use_container_width=True)

    st.dataframe(
        compare_df.round(
            {
                "需求變化(%)": 2,
                "總需求": 2,
                "延後量": 2,
                "12月承接": 2,
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        "Holt-Winters 不是 06 Notebook 原本的固定情境。這裡只把它相對 Last Value 的 "
        f"3 個月平均 Forecast 差異（約 +{holt_winters_uplift_pct:.2f}%）轉成一個 Dashboard 敏感度測試。"
    )

with tab2:
    st.subheader("點一張訂單，看它為什麼是這個狀態")

    order_choices = filtered_orders["order_id"].tolist()
    if not order_choices:
        st.info("目前 Filter 沒有訂單，請放寬篩選條件。")
    else:
        selected_order_id = st.selectbox("選擇訂單", order_choices)
        row = order_summary.loc[
            order_summary["order_id"].eq(selected_order_id)
        ].iloc[0]

        late_qty = per_order_late_quantity(selected_order_id, allocation)

        oc1, oc2, oc3, oc4 = st.columns(4)
        oc1.metric("需求交期", format_month(row["requested_due_month"]))
        oc2.metric("可承諾月份", format_month(row["feasible_commit_month"]))
        oc3.metric("情境需求量", f"{row['scenario_quantity']:.2f} k")
        oc4.metric(
            "承諾後餘裕",
            (
                "-"
                if pd.isna(row["slack_after_commit_pct"])
                else f"{row['slack_after_commit_pct'] * 100:.1f}%"
            ),
        )

        status = row["status"]
        if status == "On Time":
            st.success(
                "🟢 按期：最後一部分數量可以在需求交期月以前或當月完成，"
                "而且沒有觸發目前設定的風險條件。"
            )
        elif status == "At Risk":
            st.warning(
                "🟠 風險：目前還能在交期月完成，但完成這張單後，"
                f"該月剩餘的新訂單產能只有 {row['slack_after_commit_pct'] * 100:.1f}%。"
                "目前規則把低於 10% 視為風險，因為一點需求上修、重工或異常就可能把它推遲。"
            )
        elif status == "Late":
            st.error(
                f"🔴 延後：這張單有 {late_qty:.2f} k 排到需求交期月之後，"
                f"所以最後可承諾月份變成 {format_month(row['feasible_commit_month'])}。"
            )
        else:
            st.error("⚫ 未排入：目前規劃期間結束後，仍有數量找不到可用產能。")

        if row["priority"] == "High":
            st.info(
                "優先級 = 高：只有在『同一個需求交期月』的訂單之間，這張單會先排。"
                "這是 Synthetic Rule，不是在說真實客戶比較重要。"
            )
        else:
            st.info(
                "優先級 = 一般：如果同一個交期月同時有高優先級訂單，高優先級會先使用可用產能。"
                "因此當產能開始吃緊時，一般優先級通常會比較早承受 Spillover。"
            )

        order_alloc = allocation.loc[
            allocation["order_id"].eq(selected_order_id)
        ].copy()
        order_alloc["月份"] = order_alloc["allocation_month"].map(format_month)
        order_alloc["排入數量"] = order_alloc["allocated_quantity"].round(2)

        st.markdown("**這張訂單實際排到哪幾個月？**")
        st.dataframe(
            order_alloc[["月份", "排入數量"]],
            use_container_width=True,
            hide_index=True,
        )

with tab3:
    st.subheader("產能到底是怎麼算的？")
    st.markdown(
        """
**總產能**：這個月理論上可使用的全部產能。  
**既有負載**：這次新訂單進來以前，原本就已經排好的工作，所以會先占掉產能。  
**安全保留**：刻意不拿來接一般新單的緩衝，用來模擬停機、重工、急單等不確定性。  
**新訂單可用產能** = 總產能 − 既有負載 − 安全保留。  
**已排新訂單**：目前情境下真的塞進這個月的新單數量。  
**剩餘空間**：新訂單可用產能扣掉已排新單後，還剩多少。
        """
    )

    cap = capacity_result.copy()
    cap["月份"] = cap["month"].map(format_month)

    fig_cap = go.Figure()
    fig_cap.add_bar(
        x=cap["月份"],
        y=cap["existing_load"],
        name="既有負載",
        marker_color="#94a3b8",
    )
    fig_cap.add_bar(
        x=cap["月份"],
        y=cap["allocated_new_orders"],
        name="這次新訂單",
        marker_color="#0ea5e9",
    )
    fig_cap.add_bar(
        x=cap["月份"],
        y=cap["safety_reserve"],
        name="安全保留",
        marker_color="#f59e0b",
    )
    fig_cap.add_bar(
        x=cap["月份"],
        y=cap["remaining_new_order_capacity"],
        name="尚未使用的新訂單空間",
        marker_color="#22c55e",
    )

    fig_cap.update_layout(
        barmode="stack",
        height=430,
        yaxis_title="Synthetic k planning units",
        xaxis_title="",
        legend_title="",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_cap, use_container_width=True)

    cap_display = cap[
        [
            "月份",
            "total_capacity",
            "existing_load",
            "safety_reserve",
            "net_new_order_capacity",
            "allocated_new_orders",
            "remaining_new_order_capacity",
        ]
    ].rename(
        columns={
            "total_capacity": "總產能",
            "existing_load": "既有負載",
            "safety_reserve": "安全保留",
            "net_new_order_capacity": "新訂單可用",
            "allocated_new_orders": "已排新訂單",
            "remaining_new_order_capacity": "剩餘空間",
        }
    )
    st.dataframe(
        cap_display.round(2),
        use_container_width=True,
        hide_index=True,
    )

    full_months = cap.loc[
        cap["remaining_new_order_capacity"].abs() < 1e-9,
        "月份",
    ].tolist()
    if full_months:
        st.warning(
            "目前以下月份的新訂單可用產能已被吃滿："
            + "、".join(full_months)
            + "。需求再增加時，後面的訂單就會往下一個月 Spillover。"
        )

with tab4:
    st.subheader("為什麼 Last Value 有低估問題，還是拿它當 Base？")

    st.markdown(
        """
**因為「有 Bias」不等於「另一個模型整體更準」。**

Last Value 的缺點很清楚：近期需求往上時，它會反應得比較慢，所以 18 次驗證裡有 17 次低於 Actual。  
但模型選擇仍要看完整 Backtest；在四種方法中，Last Value 的 **WAPE 1.851% 仍是最低**。

因此比較合理的做法不是把 Last Value 丟掉，而是：

**Last Value 當 Base Forecast + Holt-Winters 當趨勢第二觀點 + Upper Reference 當誤差緩衝。**
        """
    )

    ranked = model_summary.sort_values("wape_pct").reset_index(drop=True)
    model_colors = [
        "#16a34a" if m == "last_value"
        else "#f59e0b" if m == "holt_winters"
        else "#94a3b8"
        for m in ranked["model"]
    ]

    fig_model = go.Figure()
    fig_model.add_bar(
        x=ranked["model"],
        y=ranked["wape_pct"],
        text=[f"{v:.3f}%" for v in ranked["wape_pct"]],
        textposition="outside",
        marker_color=model_colors,
    )
    fig_model.update_layout(
        height=380,
        yaxis_title="WAPE (%)，越低越好",
        xaxis_title="",
        showlegend=False,
        margin=dict(l=10, r=10, t=25, b=10),
    )
    st.plotly_chart(fig_model, use_container_width=True)

    fplot = forecast.copy()
    fplot["月份"] = fplot["date"].map(format_month)

    fig_forecast = go.Figure()
    fig_forecast.add_scatter(
        x=fplot["月份"],
        y=fplot["last_value"],
        mode="lines+markers+text",
        name="Last Value（Base）",
        text=[f"{v:.0f}" for v in fplot["last_value"]],
        textposition="top center",
        line=dict(color="#16a34a", width=3),
    )
    fig_forecast.add_scatter(
        x=fplot["月份"],
        y=fplot["holt_winters"],
        mode="lines+markers+text",
        name="Holt-Winters（趨勢參考）",
        text=[f"{v:.0f}" for v in fplot["holt_winters"]],
        textposition="bottom center",
        line=dict(color="#f59e0b", width=3),
    )
    fig_forecast.update_layout(
        height=390,
        yaxis_title="New Orders Forecast (USD mn)",
        xaxis_title="",
        legend_title="",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_forecast, use_container_width=True)

    f1, f2 = st.columns(2)
    with f1:
        st.success(
            "Last Value 為什麼保留？\n\n"
            "• WAPE 1.851%，四種方法最低\n\n"
            "• 3 個月都是 5,769\n\n"
            "• 適合當簡單、穩定的 Base Plan"
        )
    with f2:
        st.warning(
            "Holt-Winters 為什麼加進來？\n\n"
            "• WAPE 1.991%，整體只略差\n\n"
            "• Forecast 5,771 → 5,796 → 5,804\n\n"
            "• 有趨勢感，可當第二個檢查角度"
        )

    st.info(
        f"兩者 3 個月平均 Forecast 差約 +{holt_winters_uplift_pct:.2f}%。"
        "Dashboard 把這個相對差異轉成一個額外的 Planner 敏感度情境。"
        "因為 Synthetic units 和公開 Forecast 金額不是同一單位，所以只使用『相對比例』，不做直接單位換算。"
    )

    st.markdown("**Forecast 證據白話版**")
    evidence_df = pd.DataFrame(
        [
            ["WAPE 1.851%", "Last Value 的整體 Backtest 誤差最低，所以拿來當 Base。"],
            ["Bias -1.80%", "整體 Prediction 比 Actual 偏低，表示有低估方向。"],
            ["17 / 18 低估", "18 次近期驗證中有 17 次 Prediction 低於 Actual，不能只相信單一點預測。"],
            ["Holt-Winters 1.991%", "整體誤差略高，但提供趨勢型的第二觀點。"],
            ["Upper Reference +2.96%", "不是預測機率，而是用歷史誤差尺度做較保守的需求上修情境。"],
        ],
        columns=["證據", "白話意思"],
    )
    st.dataframe(evidence_df, use_container_width=True, hide_index=True)

st.divider()

with st.expander("名詞與規則｜不熟 Planner 術語可先看這裡"):
    st.markdown(
        """
- **需求交期月**：希望這張訂單最晚在哪個月完成。
- **可承諾月份**：依目前 Capacity 排完後，實際算出的最後完成月份。
- **既有負載**：新單進來以前就已經排好的工作。
- **安全保留**：刻意保留、不拿來塞一般新單的容量。
- **高優先級**：只在相同交期月中先排；這是模擬規則，不代表真實客戶價值。
- **按期**：最後完成月份沒有晚於交期月，也沒有觸發低餘裕風險。
- **風險**：還能按期，但完成後當月剩餘新訂單容量低於 10%。
- **延後**：至少有一部分數量被排到交期月之後。
- **Late Quantity**：真正跨過交期月的那一部分數量，不是整張訂單全部數量。
- **Spillover**：原本月份塞不下，往後月移動的數量。
        """
    )

with st.expander("資料範圍與限制"):
    st.markdown(
        """
- Demand / Backlog / Forecast 使用公開製造業資料。
- Capacity、Customer、Order Quantity、Priority、Due Month 為 Synthetic Planning Scenario。
- Dashboard 不代表 ASE / 日月光的真實訂單、產能或交期。
- Holt-Winters Planner Scenario 是 Dashboard 延伸敏感度測試，不是 06 Notebook 原始固定情境。
- 自訂 What-if 也是互動模擬，不是 Forecast。
        """
    )
