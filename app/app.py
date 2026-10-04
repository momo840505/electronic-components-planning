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

STATUS_ORDER = ["On Time", "At Risk", "Late", "Unscheduled"]
STATUS_ZH = {
    "On Time": "🟢 按期",
    "At Risk": "🟠 風險",
    "Late": "🔴 延後",
    "Unscheduled": "⚫ 未排入",
}
STATUS_COLOR = {
    "On Time": "#16a34a",
    "At Risk": "#f59e0b",
    "Late": "#dc2626",
    "Unscheduled": "#475569",
}
PRIORITY_ZH = {"High": "🔺 高", "Normal": "一般"}
PRIORITY_RANK = {"High": 0, "Normal": 1}
AT_RISK_SLACK_THRESHOLD = 0.10

st.markdown(
    """
<style>
.main .block-container {padding-top: 1.3rem; padding-bottom: 3rem;}
h1 {font-size: 2rem !important; letter-spacing: -0.02em;}
h2 {font-size: 1.35rem !important;}
h3 {font-size: 1.08rem !important;}
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 0.75rem 0.85rem;
    min-height: 104px;
}
[data-testid="stMetricLabel"] {font-size: 0.82rem; color: #64748b;}
[data-testid="stMetricValue"] {font-size: 1.45rem;}
[data-testid="stMetricDelta"] {font-size: 0.76rem; white-space: normal;}
.explain-box {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 0.9rem 1rem;
    margin: 0.35rem 0 0.9rem 0;
}
.micro {color:#64748b; font-size:0.84rem; line-height:1.55;}
.badge-line {font-size: 0.92rem; margin: 0.1rem 0;}
.stTabs [data-baseweb="tab-list"] {gap: 0.3rem;}
.stTabs [data-baseweb="tab"] {padding-left: 0.8rem; padding-right: 0.8rem;}
</style>
""",
    unsafe_allow_html=True,
)


def load_csv(name: str, date_columns: list[str] | None = None) -> pd.DataFrame:
    path = DATA_DIR / name
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
        "scenario_capacity": load_csv("all_scenario_capacity.csv", ["month"]),
        "scenario_orders": load_csv(
            "all_scenario_order_summary.csv",
            ["requested_due_month", "feasible_commit_month"],
        ),
        "scenario_allocation": load_csv(
            "all_scenario_allocation.csv",
            ["requested_due_month", "allocation_month"],
        ),
        "order_comparison": load_csv(
            "order_scenario_comparison.csv",
            ["commit_point", "commit_upper", "commit_stress", "requested_due_month"],
        ),
        "decision": load_csv("planner_decision_summary.csv"),
    }


def allocate_orders(
    orders: pd.DataFrame,
    capacity: pd.DataFrame,
    quantity_multiplier: float,
    scenario_name: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reproduce the transparent allocation rules from Notebook 06."""
    capacity_work = capacity.copy().sort_values("month").reset_index(drop=True)
    capacity_remaining = {
        row.month: float(row.net_new_order_capacity) for row in capacity_work.itertuples()
    }
    net_capacity_lookup = {
        row.month: float(row.net_new_order_capacity) for row in capacity_work.itertuples()
    }

    order_work = orders.copy()
    order_work["priority_rank"] = order_work["priority"].map(PRIORITY_RANK)
    order_work = order_work.sort_values(
        ["requested_due_month", "priority_rank", "order_id"]
    ).reset_index(drop=True)

    allocation_records: list[dict] = []
    order_summary_records: list[dict] = []
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
        (capacity_result["existing_load"] + capacity_result["allocated_new_orders"])
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
        "peak_new_order_utilization_pct": float(
            capacity_result["new_order_capacity_utilization_pct"].max()
        ),
        "december_spillover_quantity": december_spillover,
    }


def format_month(value: pd.Series | pd.Timestamp) -> pd.Series | str:
    if isinstance(value, pd.Series):
        return pd.to_datetime(value).dt.strftime("%Y-%m")
    if pd.isna(value):
        return "—"
    return pd.to_datetime(value).strftime("%Y-%m")


def status_badge(status: str) -> str:
    return STATUS_ZH.get(status, status)


def priority_badge(priority: str) -> str:
    return PRIORITY_ZH.get(priority, priority)


def status_style(value: str) -> str:
    if "按期" in value:
        return "background-color:#dcfce7;color:#166534;font-weight:700"
    if "風險" in value:
        return "background-color:#fef3c7;color:#92400e;font-weight:700"
    if "延後" in value:
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    if "未排入" in value:
        return "background-color:#e2e8f0;color:#334155;font-weight:700"
    return ""


def preset_validation(
    scenario_name: str,
    live_summary: dict,
    saved_summary: pd.DataFrame,
) -> tuple[bool, str]:
    row = saved_summary.loc[saved_summary["scenario"].eq(scenario_name)]
    if row.empty:
        return False, "找不到 06 Notebook 的對照情境。"
    row = row.iloc[0]
    numeric_checks = {
        "total_demand": 1e-6,
        "late_quantity": 1e-6,
        "december_spillover_quantity": 1e-6,
    }
    integer_checks = ["on_time_orders", "at_risk_orders", "late_orders", "unscheduled_orders"]
    for key, tol in numeric_checks.items():
        if abs(float(live_summary[key]) - float(row[key])) > tol:
            return False, f"{key} 與 06 Notebook 不一致。"
    for key in integer_checks:
        if int(live_summary[key]) != int(row[key]):
            return False, f"{key} 與 06 Notebook 不一致。"
    return True, "即時計算與 06 Notebook 固定輸出一致。"


def filtered_late_quantity(allocation: pd.DataFrame, filtered_orders: pd.DataFrame) -> float:
    late_ids = set(filtered_orders.loc[filtered_orders["status"].eq("Late"), "order_id"])
    if not late_ids:
        return 0.0
    return float(
        allocation.loc[
            allocation["order_id"].isin(late_ids)
            & (allocation["allocation_month"] > allocation["requested_due_month"]),
            "allocated_quantity",
        ].sum()
    )


def generate_decision_text(order_summary: pd.DataFrame, allocation: pd.DataFrame) -> tuple[str, str]:
    late_ids = order_summary.loc[order_summary["status"].eq("Late"), "order_id"].tolist()
    risk_ids = order_summary.loc[order_summary["status"].eq("At Risk"), "order_id"].tolist()
    unscheduled_ids = order_summary.loc[
        order_summary["status"].eq("Unscheduled"), "order_id"
    ].tolist()

    if unscheduled_ids:
        return (
            "error",
            "目前甚至有訂單在規劃期間內排不完："
            + "、".join(unscheduled_ids)
            + "。模擬上應先確認能否增加或調度產能；若做不到，再討論拆批或重新承諾交期。",
        )
    if late_ids:
        qty = filtered_late_quantity(allocation, order_summary)
        return (
            "error",
            f"目前有 {len(late_ids)} 張訂單發生延後（{'、'.join(late_ids)}），真正跨過交期月的數量約 {qty:.2f} k。"
            "優先動作是先看交期月以前還有沒有可調度產能；若沒有，再評估拆批出貨或調整可承諾月份。",
        )
    if risk_ids:
        return (
            "warning",
            f"目前沒有延後訂單，但 {len(risk_ids)} 張訂單已是風險狀態（{'、'.join(risk_ids)}）。"
            "意思是目前還排得完，但完成後剩下的產能空間不到 10%，再多一點需求就可能跨月。",
        )
    return (
        "success",
        "目前篩選範圍內沒有風險或延後訂單，代表這個情境下仍有足夠的排程空間。",
    )


def render_alert(level: str, text: str) -> None:
    if level == "error":
        st.error(text)
    elif level == "warning":
        st.warning(text)
    else:
        st.success(text)


DATA = load_data()
forecast = DATA["forecast"]
planning_ref = DATA["planning_ref"]
evaluation = DATA["evaluation"]
model_summary = DATA["model_summary"]
capacity_base = DATA["capacity"]
orders = DATA["orders"]
saved_scenario_summary = DATA["scenario_summary"]

eval_lookup = dict(zip(evaluation["metric"], evaluation["value"].astype(str)))
upper_multiplier = float(
    (planning_ref["upper_planning_reference"] / planning_ref["selected_forecast"]).mean()
)

PRESET_SCENARIOS = {
    "基準：Point Forecast": ("Point Forecast", 1.00, "基準"),
    "上修：Upper Reference (+2.96%)": (
        "Upper Planning Reference",
        upper_multiplier,
        "+2.96%",
    ),
    "壓力測試：+10%": ("+10% Demand Stress", 1.10, "+10%"),
}

st.title("Planner 決策 Dashboard")
st.caption(
    "把 Forecast 轉成『能不能按期交、哪張單有風險、哪個月產能太滿』。公開資料用於需求/預測；產能與訂單為 Synthetic 模擬。"
)

with st.sidebar:
    st.header("🎛️ 情境與篩選")
    scenario_mode = st.radio(
        "1｜需求情境",
        list(PRESET_SCENARIOS.keys()) + ["自訂 What-if"],
        help="前三個情境會重現 06 Notebook；自訂情境是即時計算，不是 Notebook 固定輸出。",
    )

    if scenario_mode == "自訂 What-if":
        custom_change_pct = st.slider(
            "自訂需求變化 (%)",
            min_value=-5.0,
            max_value=15.0,
            value=5.0,
            step=0.5,
            help="只改需求量，不改原本的 Synthetic Capacity。",
        )
        scenario_name = f"Custom {custom_change_pct:+.1f}%"
        multiplier = 1 + custom_change_pct / 100
        scenario_short = f"{custom_change_pct:+.1f}%"
        preset_mode = False
    else:
        scenario_name, multiplier, scenario_short = PRESET_SCENARIOS[scenario_mode]
        preset_mode = True

    st.markdown("---")
    st.markdown("**2｜顯示範圍**")
    st.caption("這些篩選只改『畫面要看哪些訂單』，不會偷偷重排整體產能。")

allocation, order_summary, capacity_result = allocate_orders(
    orders=orders,
    capacity=capacity_base,
    quantity_multiplier=multiplier,
    scenario_name=scenario_name,
)
summary = summarize_scenario(
    scenario_name, multiplier, order_summary, allocation, capacity_result
)

# Sidebar display filters depend on the recalculated order status.
with st.sidebar:
    status_options = [s for s in STATUS_ORDER if s in set(order_summary["status"])]
    selected_statuses = st.multiselect(
        "狀態",
        status_options,
        default=status_options,
        format_func=lambda x: STATUS_ZH[x],
    )
    selected_priorities = st.multiselect(
        "優先級",
        ["High", "Normal"],
        default=["High", "Normal"],
        format_func=lambda x: PRIORITY_ZH[x],
    )
    due_month_values = sorted(order_summary["requested_due_month"].dropna().unique())
    selected_due_months = st.multiselect(
        "需求交期月",
        due_month_values,
        default=due_month_values,
        format_func=lambda x: pd.to_datetime(x).strftime("%Y-%m"),
    )
    selected_orders = st.multiselect(
        "訂單",
        order_summary["order_id"].tolist(),
        default=order_summary["order_id"].tolist(),
    )

    st.markdown("---")
    st.markdown("**Forecast 證據**")
    st.write(f"模型：**Last Value（沿用最新值）**")
    st.write(f"WAPE：**{eval_lookup.get('Pooled Backtest WAPE', 'N/A')}**")
    st.write(f"Bias：**{eval_lookup.get('Aggregate Bias', 'N/A')}**")
    st.write(f"低估：**{eval_lookup.get('Under-Forecast Count', 'N/A')} / 18 次**")

filtered_orders = order_summary.loc[
    order_summary["status"].isin(selected_statuses)
    & order_summary["priority"].isin(selected_priorities)
    & order_summary["requested_due_month"].isin(selected_due_months)
    & order_summary["order_id"].isin(selected_orders)
].copy()
filtered_ids = set(filtered_orders["order_id"])
filtered_allocation = allocation.loc[allocation["order_id"].isin(filtered_ids)].copy()

# Global scenario KPIs — these change when the scenario changes.
st.subheader("目前情境｜整體結果")
k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    st.metric("需求變化", scenario_short)
    st.caption("相對基準需求")
with k2:
    st.metric("總需求", f"{summary['total_demand']:.2f} k")
    st.caption("Synthetic planning units")
with k3:
    st.metric("🟢 按期", summary["on_time_orders"])
    st.caption("在交期月前／當月完成")
with k4:
    st.metric("🟠 風險", summary["at_risk_orders"])
    st.caption("按期但餘裕 < 10%")
with k5:
    st.metric("🔴 延後", summary["late_orders"])
    st.caption(f"Late 量 {summary['late_quantity']:.2f} k")
with k6:
    st.metric("12月承接", f"{summary['december_spillover_quantity']:.2f} k")
    st.caption("前面月份排不下而往後移")

if preset_mode:
    is_match, match_message = preset_validation(
        scenario_name, summary, saved_scenario_summary
    )
    if is_match:
        st.success(f"✅ 數據檢核：{match_message}")
    else:
        st.error(f"⚠️ 數據檢核失敗：{match_message}")
else:
    st.info("🧪 自訂 What-if：這是即時計算情境，不是 06 Notebook 的固定輸出。")

level, overall_text = generate_decision_text(order_summary, allocation)
render_alert(level, overall_text)

with st.expander("看不懂『既有負載、優先級、風險、Late』？先看這裡", expanded=False):
    st.markdown(
        """
**既有負載**：這個月原本就已經排好的工作量。它不是這次新訂單，所以會先占掉總產能。  
**安全保留**：刻意不拿來接一般新單的緩衝，用來模擬停機、重工、急單等不確定性。  
**新訂單可用產能**：`總產能 - 既有負載 - 安全保留`，這才是能拿來排這批新訂單的空間。  
**高優先級**：這裡只是 Synthetic 排程規則；**同一個交期月**時，高優先級先吃產能。它不代表真實客戶比較重要。  
**按期**：最後一部分在交期月以前或當月完成，而且完成後仍有至少 10% 產能餘裕。  
**風險**：目前還能按期，但完成後剩餘的新訂單產能不到 10%，再多一點需求就容易跨月。  
**延後**：至少有一部分數量排到需求交期月之後。不是整張訂單全部延誤。  
**承諾後餘裕**：這張訂單完成所在月份，還剩多少比例的新訂單可用產能。
        """
    )

# Tabs
overview_tab, risk_tab, capacity_tab, forecast_tab, glossary_tab = st.tabs(
    ["📊 決策總覽", "📦 訂單風險", "🏭 產能", "📈 Forecast", "📘 名詞與規則"]
)

with overview_tab:
    left, right = st.columns([1, 1.25])

    with left:
        st.markdown("### 訂單狀態分布")
        status_counts = order_summary["status"].value_counts().reindex(STATUS_ORDER, fill_value=0)
        nonzero_status = status_counts[status_counts > 0]
        fig_status = go.Figure(
            data=[
                go.Pie(
                    labels=[STATUS_ZH[s] for s in nonzero_status.index],
                    values=nonzero_status.values,
                    hole=0.58,
                    marker=dict(colors=[STATUS_COLOR[s] for s in nonzero_status.index]),
                    textinfo="label+value",
                    hovertemplate="%{label}<br>訂單數：%{value}<extra></extra>",
                )
            ]
        )
        fig_status.update_layout(height=330, margin=dict(l=10, r=10, t=20, b=10), showlegend=False)
        st.plotly_chart(fig_status, use_container_width=True)

    with right:
        st.markdown("### 三個 Notebook 情境比較")
        compare_df = saved_scenario_summary.copy()
        compare_df["情境"] = compare_df["scenario"].replace(
            {
                "Point Forecast": "基準",
                "Upper Planning Reference": "上修 +2.96%",
                "+10% Demand Stress": "+10% 壓力測試",
            }
        )
        if not preset_mode:
            custom_row = pd.DataFrame([summary])
            custom_row["情境"] = f"自訂 {scenario_short}"
            compare_df = pd.concat([compare_df, custom_row], ignore_index=True)

        fig_compare = go.Figure()
        fig_compare.add_bar(
            x=compare_df["情境"],
            y=compare_df["late_quantity"],
            name="Late 數量",
            marker_color=["#dc2626" if (not preset_mode and x == f"自訂 {scenario_short}") else "#fca5a5" for x in compare_df["情境"]],
            text=[f"{x:.2f} k" for x in compare_df["late_quantity"]],
            textposition="outside",
        )
        fig_compare.add_scatter(
            x=compare_df["情境"],
            y=compare_df["late_orders"],
            name="Late 訂單數",
            yaxis="y2",
            mode="lines+markers+text",
            text=compare_df["late_orders"].astype(int).astype(str),
            textposition="top center",
            line=dict(color="#7c3aed", width=3),
        )
        fig_compare.update_layout(
            height=330,
            margin=dict(l=20, r=20, t=20, b=20),
            yaxis=dict(title="Late 數量 (k)"),
            yaxis2=dict(title="Late 訂單數", overlaying="y", side="right", rangemode="tozero"),
            legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(fig_compare, use_container_width=True)

    st.markdown("### 目前最需要注意什麼？")
    late_rows = order_summary.loc[order_summary["status"].eq("Late")]
    risk_rows = order_summary.loc[order_summary["status"].eq("At Risk")]
    if not late_rows.empty:
        st.error(
            "目前最先要處理的是："
            + "、".join(late_rows["order_id"].tolist())
            + "。因為它們最後一部分已經排到需求交期月之後。"
        )
    elif not risk_rows.empty:
        st.warning(
            "目前還沒有 Late，但 "
            + "、".join(risk_rows["order_id"].tolist())
            + " 已經進入風險區；代表可以按期，但幾乎沒有緩衝。"
        )
    else:
        st.success("目前所有訂單都有較足夠的排程空間。")

    st.markdown("### 目前篩選範圍")
    if filtered_orders.empty:
        st.info("目前篩選條件沒有符合的訂單。請調整左側篩選。")
    else:
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("顯示訂單", len(filtered_orders))
        f2.metric("篩選需求量", f"{filtered_orders['scenario_quantity'].sum():.2f} k")
        f3.metric("風險 + 延後", int(filtered_orders["status"].isin(["At Risk", "Late", "Unscheduled"]).sum()))
        f4.metric("篩選 Late 量", f"{filtered_late_quantity(filtered_allocation, filtered_orders):.2f} k")

with risk_tab:
    st.markdown("### 訂單風險表")
    st.caption("左側『狀態 / 優先級 / 交期月 / 訂單』篩選會直接改變這張表與下方的訂單解讀。")

    if filtered_orders.empty:
        st.info("目前沒有符合篩選條件的訂單。")
    else:
        display_orders = filtered_orders.copy()
        display_orders["priority"] = display_orders["priority"].map(priority_badge)
        display_orders["status"] = display_orders["status"].map(status_badge)
        display_orders["requested_due_month"] = format_month(display_orders["requested_due_month"])
        display_orders["feasible_commit_month"] = format_month(display_orders["feasible_commit_month"])
        display_orders["slack_after_commit_pct"] = display_orders["slack_after_commit_pct"] * 100
        display_orders = display_orders[
            [
                "order_id",
                "customer",
                "priority",
                "scenario_quantity",
                "requested_due_month",
                "feasible_commit_month",
                "slack_after_commit_pct",
                "status",
            ]
        ].rename(
            columns={
                "order_id": "訂單",
                "customer": "客戶",
                "priority": "優先級",
                "scenario_quantity": "情境數量",
                "requested_due_month": "需求交期月",
                "feasible_commit_month": "可承諾月份",
                "slack_after_commit_pct": "承諾後餘裕(%)",
                "status": "狀態",
            }
        )
        styled = display_orders.style.map(status_style, subset=["狀態"]).format(
            {"情境數量": "{:.2f}", "承諾後餘裕(%)": "{:.1f}"}
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

        csv_bytes = display_orders.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "下載目前篩選結果 CSV",
            data=csv_bytes,
            file_name="filtered_order_risk.csv",
            mime="text/csv",
        )

        st.markdown("### 點一張訂單，看它為什麼是這個狀態")
        focus_order_id = st.selectbox("聚焦訂單", filtered_orders["order_id"].tolist())
        row = filtered_orders.loc[filtered_orders["order_id"].eq(focus_order_id)].iloc[0]
        focus_alloc = allocation.loc[allocation["order_id"].eq(focus_order_id)].copy()

        a, b, c, d = st.columns(4)
        a.metric("需求交期月", format_month(row["requested_due_month"]))
        b.metric("可承諾月份", format_month(row["feasible_commit_month"]))
        c.metric("優先級", priority_badge(row["priority"]))
        d.metric("承諾後餘裕", f"{row['slack_after_commit_pct']*100:.1f}%")

        if row["status"] == "On Time":
            st.success("🟢 按期：最後一部分在交期月以前或當月完成，而且完成後餘裕至少 10%。")
        elif row["status"] == "At Risk":
            st.warning("🟠 風險：目前仍能按期，但完成後的剩餘新訂單產能不到 10%。再多一點需求就容易跨月。")
        elif row["status"] == "Late":
            st.error("🔴 延後：至少有一部分數量排到需求交期月之後，所以整張訂單被標成 Late。")
        else:
            st.error("⚫ 未排入：規劃期間結束後仍有數量沒有可用產能可以安排。")

        if row["priority"] == "High":
            st.info("優先級為『高』只代表：在相同需求交期月的訂單中，這張會先排。這是 Synthetic 規則，不代表真實客戶等級。")
        else:
            st.info("優先級為『一般』代表：如果和高優先級訂單同一個交期月，高優先級會先排；較早交期的一般訂單仍會先於較晚交期的高優先級訂單。")

        focus_alloc["月份"] = format_month(focus_alloc["allocation_month"])
        focus_alloc = focus_alloc[["月份", "allocated_quantity"]].rename(columns={"allocated_quantity": "排入數量"})
        fig_focus = go.Figure(
            go.Bar(
                x=focus_alloc["月份"],
                y=focus_alloc["排入數量"],
                marker_color=STATUS_COLOR[row["status"]],
                text=[f"{v:.2f}" for v in focus_alloc["排入數量"]],
                textposition="outside",
            )
        )
        due_label = format_month(row["requested_due_month"])
        marker_y = max(float(focus_alloc["排入數量"].max()) * 1.12, 1.0)
        fig_focus.add_scatter(
            x=[due_label],
            y=[marker_y],
            mode="markers+text",
            marker=dict(symbol="triangle-down", size=13, color="#dc2626"),
            text=["需求交期月"],
            textposition="top center",
            name="需求交期月",
            hoverinfo="skip",
        )
        fig_focus.update_layout(
            height=300,
            yaxis_title="排入數量 (k)",
            xaxis_title="實際排入月份",
            margin=dict(l=20, r=20, t=25, b=20),
        )
        st.plotly_chart(fig_focus, use_container_width=True)

with capacity_tab:
    st.markdown("### 先把四個產能名詞看懂")
    st.markdown(
        """
<div class="explain-box">
<b>總產能</b>：這個月最多能做多少。<br>
<b>既有負載</b>：原本就已經排進去的工作，會先占掉產能。<br>
<b>安全保留</b>：刻意留著不接一般新單，當作停機、重工、急單等緩衝。<br>
<b>新訂單可用產能</b>：總產能扣掉前兩項後，真正可以拿來排這批新訂單的空間。
</div>
        """,
        unsafe_allow_html=True,
    )

    month_labels = [format_month(x) for x in capacity_result["month"]]
    selected_month_label = st.select_slider("選一個月份看產能拆解", options=month_labels, value=month_labels[0])
    selected_month_row = capacity_result.loc[
        format_month(capacity_result["month"]).eq(selected_month_label)
    ].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("總產能", f"{selected_month_row['total_capacity']:.0f} k")
        st.caption("這個月最多可以做多少")
    with c2:
        st.metric("既有負載", f"{selected_month_row['existing_load']:.0f} k")
        st.caption("先前已經排好的工作")
    with c3:
        st.metric("安全保留", f"{selected_month_row['safety_reserve']:.0f} k")
        st.caption("刻意不拿來接一般新單")
    with c4:
        st.metric("新訂單可用", f"{selected_month_row['net_new_order_capacity']:.0f} k")
        st.caption("總產能－既有負載－安全保留")

    st.markdown("### 每月產能到底被誰用掉？")
    cap = capacity_result.copy()
    cap["月份"] = format_month(cap["month"])
    cap["剩餘未用"] = cap["remaining_new_order_capacity"].clip(lower=0)
    fig_cap = go.Figure()
    fig_cap.add_bar(x=cap["月份"], y=cap["existing_load"], name="既有負載", marker_color="#64748b")
    fig_cap.add_bar(x=cap["月份"], y=cap["safety_reserve"], name="安全保留", marker_color="#cbd5e1")
    fig_cap.add_bar(x=cap["月份"], y=cap["allocated_new_orders"], name="這次排入的新訂單", marker_color="#0f766e")
    fig_cap.add_bar(x=cap["月份"], y=cap["剩餘未用"], name="新訂單剩餘空間", marker_color="#bbf7d0")
    fig_cap.update_layout(
        barmode="stack",
        height=410,
        yaxis_title="Synthetic k planning units",
        xaxis_title="月份",
        legend=dict(orientation="h", y=1.12),
        margin=dict(l=20, r=20, t=25, b=20),
    )
    st.plotly_chart(fig_cap, use_container_width=True)

    st.markdown("### 白話判讀")
    full_months = cap.loc[cap["remaining_new_order_capacity"] <= 1e-9, "月份"].tolist()
    if full_months:
        st.warning(
            "新訂單可用產能已被用滿的月份："
            + "、".join(full_months)
            + "。這些月份再多一點需求，就必須往後月移。"
        )
    spill = summary["december_spillover_quantity"]
    if spill > 0:
        st.error(f"目前有 {spill:.2f} k 被推到 12 月，代表前面交期窗口已經放不下。")
    else:
        st.success("目前沒有數量被推到 12 月。")

    cap_table = cap[
        [
            "月份",
            "total_capacity",
            "existing_load",
            "safety_reserve",
            "net_new_order_capacity",
            "allocated_new_orders",
            "remaining_new_order_capacity",
            "new_order_capacity_utilization_pct",
        ]
    ].rename(
        columns={
            "total_capacity": "總產能",
            "existing_load": "既有負載",
            "safety_reserve": "安全保留",
            "net_new_order_capacity": "新訂單可用",
            "allocated_new_orders": "已排新訂單",
            "remaining_new_order_capacity": "剩餘新訂單空間",
            "new_order_capacity_utilization_pct": "新訂單使用率(%)",
        }
    )
    st.dataframe(cap_table, use_container_width=True, hide_index=True)

with forecast_tab:
    st.markdown("### Forecast 為什麼不能只看一個數字？")
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("選定模型", "Last Value", "沿用最新訂單水準")
    f2.metric("Backtest WAPE", eval_lookup.get("Pooled Backtest WAPE", "N/A"), "整體歷史驗證誤差")
    f3.metric("Bias", eval_lookup.get("Aggregate Bias", "N/A"), "負值 = 整體偏低估")
    f4.metric("低估次數", f"{eval_lookup.get('Under-Forecast Count', 'N/A')} / 18", "近期驗證中多數低估")

    st.info(
        "WAPE 1.851% 的意思是：近期 Rolling Backtest 的加權絕對誤差約 1.85%。它不是『準確率 98.149%』。"
    )
    st.warning(
        "Bias = -1.80%，而且 18 次中有 17 次低估，所以 Point Forecast 雖然誤差小，仍要額外看上修需求情境。"
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### 模型比較：越複雜不一定越好")
        model_df = model_summary.sort_values("wape_pct").copy()
        colors = ["#0f766e" if m == "last_value" else "#94a3b8" for m in model_df["model"]]
        fig_model = go.Figure(
            go.Bar(
                x=model_df["model"],
                y=model_df["wape_pct"],
                marker_color=colors,
                text=[f"{x:.3f}%" for x in model_df["wape_pct"]],
                textposition="outside",
            )
        )
        fig_model.update_layout(height=340, yaxis_title="WAPE (%)", xaxis_title="", margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_model, use_container_width=True)

    with right:
        st.markdown("#### 未來 3 個月：Point vs 上下參考")
        ref = planning_ref.copy()
        ref["月份"] = format_month(ref["date"])
        fig_ref = go.Figure()
        fig_ref.add_scatter(x=ref["月份"], y=ref["upper_planning_reference"], name="上方參考", mode="lines+markers", line=dict(color="#dc2626"))
        fig_ref.add_scatter(x=ref["月份"], y=ref["selected_forecast"], name="Point Forecast", mode="lines+markers", line=dict(color="#0f766e", width=3))
        fig_ref.add_scatter(x=ref["月份"], y=ref["lower_planning_reference"], name="下方參考", mode="lines+markers", line=dict(color="#64748b"))
        fig_ref.update_layout(height=340, yaxis_title="Millions of USD", xaxis_title="", legend=dict(orientation="h", y=1.12), margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_ref, use_container_width=True)

    st.markdown("#### 這和 Planner 有什麼關係？")
    st.markdown(
        """
- Point Forecast 可以拿來做基準計畫。  
- 但模型近期有明顯低估傾向，所以交期承諾前還要看 Upper Scenario。  
- Dashboard 的 `+2.96%` 就是把 05 的歷史誤差尺度轉成需求上修測試，而不是宣稱未來一定會增加 2.96%。
        """
    )

with glossary_tab:
    st.markdown("### 名詞白話表")
    glossary = pd.DataFrame(
        [
            ["總產能", "某月份最多可以處理的 Synthetic 工作量。"],
            ["既有負載", "這次新訂單進來前，原本就已經排好的工作。"],
            ["安全保留", "刻意留下來的緩衝，不拿來接一般新單。"],
            ["新訂單可用產能", "總產能扣掉既有負載與安全保留後，真正能排新單的空間。"],
            ["高優先級", "同一個交期月時先排；只是模擬規則，不是真實客戶等級。"],
            ["按期", "最後一部分不晚於交期月，而且完成後仍有至少 10% 產能餘裕。"],
            ["風險", "還能按期，但完成後餘裕不到 10%。"],
            ["延後", "至少一部分數量排到交期月之後。"],
            ["Late Quantity", "真正被排到交期月之後的那部分數量。"],
            ["12月承接 / Spillover", "9～11 月放不下，最後被排到 12 月的數量。"],
            ["WAPE", "Forecast 整體誤差大小；越低越好。"],
            ["Bias", "Forecast 整體偏高還偏低；負值代表整體偏低估。"],
        ],
        columns=["名詞", "白話解釋"],
    )
    st.dataframe(glossary, use_container_width=True, hide_index=True)

    st.markdown("### 排程規則")
    st.markdown(
        """
1. **先看交期月**：交期越早，越早排。  
2. **同一交期月才看優先級**：High 先於 Normal。  
3. **可以拆批**：同一張訂單可以分散到不同月份。  
4. **最後完成月份 = 可承諾月份**。  
5. 最後完成月份晚於交期月 → **🔴 延後**。  
6. 剛好按期但完成後餘裕 < 10% → **🟠 風險**。  
7. 否則 → **🟢 按期**。
        """
    )

    st.markdown("### 資料範圍")
    st.info(
        "公開資料只支援 demand / backlog / forecast analysis。Capacity、Customer Order、Priority、Due Month 都是 Synthetic。這個 Dashboard 展示的是 Planner 決策邏輯，不代表任何公司真實產能或客戶訂單。"
    )
