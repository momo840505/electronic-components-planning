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

STATUS_COLOR = {
    "On Time": "#16a34a",
    "At Risk": "#f59e0b",
    "Late": "#dc2626",
    "Unscheduled": "#7f1d1d",
}

STATUS_ZH = {
    "On Time": "按期",
    "At Risk": "風險",
    "Late": "延後",
    "Unscheduled": "未排入",
}

PRIORITY_ZH = {
    "High": "高",
    "Normal": "一般",
}

PRIORITY_RANK = {"High": 0, "Normal": 1}
AT_RISK_SLACK_THRESHOLD = 0.10

CUSTOM_CSS = """
<style>
.main .block-container { padding-top: 2rem; }
.small-caption { color:#64748b; font-size:0.88rem; margin-bottom:0.8rem; }
.kpi-row { display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:0.8rem; margin: 0.4rem 0 1rem 0; }
.kpi-card { border:1px solid #e5e7eb; border-radius:14px; padding:0.8rem 0.9rem; background:#ffffff; min-height:88px; }
.kpi-label { font-size:0.76rem; color:#64748b; margin-bottom:0.25rem; white-space:normal; }
.kpi-value { font-size:1.25rem; font-weight:750; color:#111827; line-height:1.25; white-space:normal; overflow-wrap:anywhere; }
.kpi-sub { color:#64748b; font-size:0.75rem; margin-top:0.25rem; }
.note-box { border-radius:12px; padding:0.85rem 1rem; margin:0.5rem 0 1rem 0; background:#fff7ed; border:1px solid #fed7aa; color:#7c2d12; }
.good-box { border-radius:12px; padding:0.85rem 1rem; margin:0.5rem 0 1rem 0; background:#f0fdf4; border:1px solid #bbf7d0; color:#14532d; }
.info-box { border-radius:12px; padding:0.85rem 1rem; margin:0.5rem 0 1rem 0; background:#eff6ff; border:1px solid #bfdbfe; color:#1e3a8a; }
.section-title { font-size:1.3rem; font-weight:800; margin:1.2rem 0 0.6rem 0; }
.decision { background:#f8fafc; border-left:5px solid #0f766e; padding:1rem 1.1rem; border-radius:10px; }
@media (max-width: 1000px) { .kpi-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


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
            slack_after_commit_pct = capacity_remaining[month] / net_capacity_lookup[month]

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


def format_month(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%Y-%m")


def kpi_card(label: str, value: str, subtext: str = "") -> str:
    return f"""
    <div class='kpi-card'>
      <div class='kpi-label'>{label}</div>
      <div class='kpi-value'>{value}</div>
      <div class='kpi-sub'>{subtext}</div>
    </div>
    """


def rename_status(status: str) -> str:
    return STATUS_ZH.get(status, status)


def rename_priority(priority: str) -> str:
    return PRIORITY_ZH.get(priority, priority)


DATA = load_data()
forecast = DATA["forecast"]
planning_ref = DATA["planning_ref"]
evaluation = DATA["evaluation"]
model_summary = DATA["model_summary"]
capacity_base = DATA["capacity"]
orders = DATA["orders"]

upper_multiplier = float(
    (planning_ref["upper_planning_reference"] / planning_ref["selected_forecast"]).mean()
)

SCENARIO_OPTIONS = {
    "基準情境：Point Forecast": ("Point Forecast", 1.00, "基準"),
    "上修情境：Upper Reference (+2.96%)": (
        "Upper Planning Reference",
        upper_multiplier,
        "+2.96%",
    ),
    "壓力測試：+10% Demand Stress": ("+10% Demand Stress", 1.10, "+10%"),
}

st.title("Planner 決策 Dashboard")
st.markdown(
    "<div class='small-caption'>公開製造業 Forecast + Synthetic Capacity Planning。產能與客戶訂單皆為模擬情境，只用於展示 Planner 決策邏輯。</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("情境控制")
    scenario_label = st.radio("需求情境", list(SCENARIO_OPTIONS.keys()))
    scenario_name, multiplier, scenario_short = SCENARIO_OPTIONS[scenario_label]

    st.markdown("---")
    st.markdown("**Forecast 證據**")
    eval_lookup = dict(zip(evaluation["metric"], evaluation["value"].astype(str)))
    st.write(f"模型：**{eval_lookup.get('Selected Model', 'N/A')}**")
    st.write(f"WAPE：**{eval_lookup.get('Pooled Backtest WAPE', 'N/A')}**")
    st.write(f"Bias：**{eval_lookup.get('Aggregate Bias', 'N/A')}**")
    st.write(f"低估次數：**{eval_lookup.get('Under-Forecast Count', 'N/A')} / 18**")

allocation, order_summary, capacity_result = allocate_orders(
    orders=orders,
    capacity=capacity_base,
    quantity_multiplier=multiplier,
    scenario_name=scenario_name,
)
summary = summarize_scenario(scenario_name, multiplier, order_summary, allocation, capacity_result)

st.markdown(
    "<div class='kpi-row'>"
    + kpi_card("需求情境", scenario_short, scenario_name)
    + kpi_card("總需求", f"{summary['total_demand']:.2f} k", "Synthetic units")
    + kpi_card("Late 訂單", f"{summary['late_orders']}", "部分數量跨過 Due Month")
    + kpi_card("Late 數量", f"{summary['late_quantity']:.2f} k", "真正延後的數量")
    + kpi_card("12月承接", f"{summary['december_spillover_quantity']:.2f} k", "Spillover")
    + "</div>",
    unsafe_allow_html=True,
)

if summary["late_orders"] > 0:
    st.markdown(
        "<div class='note-box'>此情境會產生 Late Orders。Late 訂單代表至少部分數量排到 requested due month 之後，不代表整張訂單全部延後。</div>",
        unsafe_allow_html=True,
    )
elif summary["at_risk_orders"] > 0:
    st.markdown(
        "<div class='info-box'>此情境沒有 Late Order，但仍有 At Risk 訂單，原因是完成承諾後的 capacity slack 低於 10%。</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        "<div class='good-box'>此情境沒有 Late 或 At Risk 訂單。</div>",
        unsafe_allow_html=True,
    )

tab1, tab2, tab3, tab4 = st.tabs(["決策總覽", "Capacity", "Forecast 證據", "專案範圍"])

with tab1:
    st.markdown("<div class='section-title'>Order-level 決策表</div>", unsafe_allow_html=True)
    display_orders = order_summary.copy()
    display_orders["requested_due_month"] = format_month(display_orders["requested_due_month"])
    display_orders["feasible_commit_month"] = format_month(display_orders["feasible_commit_month"])
    display_orders["slack_after_commit_pct"] = display_orders["slack_after_commit_pct"] * 100
    display_orders["priority"] = display_orders["priority"].map(rename_priority)
    display_orders["status"] = display_orders["status"].map(rename_status)
    display_orders = display_orders[
        [
            "order_id",
            "customer",
            "priority",
            "base_quantity",
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
            "base_quantity": "基準數量",
            "scenario_quantity": "情境數量",
            "requested_due_month": "需求交期月",
            "feasible_commit_month": "可承諾月份",
            "slack_after_commit_pct": "承諾後餘裕(%)",
            "status": "狀態",
        }
    )
    st.dataframe(
        display_orders,
        use_container_width=True,
        hide_index=True,
        column_config={
            "基準數量": st.column_config.NumberColumn(format="%.2f"),
            "情境數量": st.column_config.NumberColumn(format="%.2f"),
            "承諾後餘裕(%)": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    st.markdown("<div class='section-title'>Notebook Scenario 比較</div>", unsafe_allow_html=True)
    scenario_summary = DATA["scenario_summary"].copy()
    scenario_summary["scenario"] = scenario_summary["scenario"].replace(
        {
            "Point Forecast": "基準 Point",
            "Upper Planning Reference": "上修 +2.96%",
            "+10% Demand Stress": "+10% 壓力測試",
        }
    )
    scenario_summary = scenario_summary.rename(
        columns={
            "scenario": "情境",
            "demand_multiplier": "需求倍率",
            "total_demand": "總需求",
            "on_time_orders": "按期訂單",
            "at_risk_orders": "風險訂單",
            "late_orders": "Late訂單",
            "unscheduled_orders": "未排入訂單",
            "late_quantity": "Late數量",
            "peak_new_order_utilization_pct": "最高新訂單產能使用率(%)",
            "december_spillover_quantity": "12月承接",
        }
    )
    st.dataframe(
        scenario_summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "需求倍率": st.column_config.NumberColumn(format="%.4f"),
            "總需求": st.column_config.NumberColumn(format="%.2f"),
            "Late數量": st.column_config.NumberColumn(format="%.2f"),
            "最高新訂單產能使用率(%)": st.column_config.NumberColumn(format="%.1f"),
            "12月承接": st.column_config.NumberColumn(format="%.2f"),
        },
    )

with tab2:
    st.markdown("<div class='section-title'>Monthly Capacity Loading</div>", unsafe_allow_html=True)
    cap_plot = capacity_result.copy()
    cap_plot["month_label"] = format_month(cap_plot["month"])
    fig = go.Figure()
    fig.add_bar(
        x=cap_plot["month_label"],
        y=cap_plot["net_new_order_capacity"],
        name="可用新訂單產能",
        marker_color="#64748b",
    )
    fig.add_bar(
        x=cap_plot["month_label"],
        y=cap_plot["allocated_new_orders"],
        name="已排新訂單",
        marker_color="#0891b2",
    )
    fig.update_layout(
        barmode="group",
        yaxis_title="Synthetic k planning units",
        xaxis_title="月份",
        legend_title="",
        height=430,
        margin=dict(l=20, r=20, t=30, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    cap_table = capacity_result.copy()
    cap_table["month"] = format_month(cap_table["month"])
    cap_table = cap_table.rename(
        columns={
            "month": "月份",
            "total_capacity": "總產能",
            "existing_load": "既有負載",
            "safety_reserve": "安全保留",
            "net_new_order_capacity": "新訂單可用產能",
            "allocated_new_orders": "已排新訂單",
            "remaining_new_order_capacity": "剩餘新訂單產能",
            "new_order_capacity_utilization_pct": "新訂單產能使用率(%)",
            "operational_load_pct": "總營運負載(%)",
        }
    )
    st.dataframe(cap_table, use_container_width=True, hide_index=True)

    st.markdown("<div class='section-title'>Allocation Detail</div>", unsafe_allow_html=True)
    alloc_display = allocation.copy()
    alloc_display["requested_due_month"] = format_month(alloc_display["requested_due_month"])
    alloc_display["allocation_month"] = format_month(alloc_display["allocation_month"])
    alloc_display["priority"] = alloc_display["priority"].map(rename_priority)
    alloc_display = alloc_display.rename(
        columns={
            "scenario": "情境",
            "order_id": "訂單",
            "customer": "客戶",
            "priority": "優先級",
            "requested_due_month": "需求交期月",
            "allocation_month": "排入月份",
            "allocated_quantity": "排入數量",
        }
    )
    st.dataframe(alloc_display, use_container_width=True, hide_index=True)

with tab3:
    st.markdown("<div class='section-title'>Model Backtest Summary</div>", unsafe_allow_html=True)
    model_df = model_summary.sort_values("wape_pct")
    model_fig = go.Figure()
    model_fig.add_bar(
        x=model_df["model"],
        y=model_df["wape_pct"],
        text=[f"{v:.3f}%" for v in model_df["wape_pct"]],
        textposition="outside",
        marker_color="#0ea5e9",
    )
    model_fig.update_layout(
        yaxis_title="WAPE (%)",
        xaxis_title="模型",
        height=420,
        margin=dict(l=20, r=20, t=50, b=20),
    )
    st.plotly_chart(model_fig, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Final 3-Month Forecast**")
        forecast_display = forecast.copy()
        forecast_display["date"] = format_month(forecast_display["date"])
        forecast_display = forecast_display.rename(columns={"date": "月份", "selected_forecast": "選定Forecast"})
        st.dataframe(forecast_display, use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**Planning Reference**")
        ref_display = planning_ref.copy()
        ref_display["date"] = format_month(ref_display["date"])
        ref_display = ref_display.rename(
            columns={
                "date": "月份",
                "lower_planning_reference": "下方參考",
                "selected_forecast": "Point Forecast",
                "upper_planning_reference": "上方參考",
            }
        )
        st.dataframe(ref_display, use_container_width=True, hide_index=True)

    st.markdown("**Evaluation Summary**")
    eval_display = evaluation.rename(columns={"metric": "指標", "value": "結果"})
    st.dataframe(eval_display, use_container_width=True, hide_index=True)

with tab4:
    st.markdown("<div class='section-title'>範圍與限制</div>", unsafe_allow_html=True)
    st.markdown(
        """
- 公開製造業資料只支援 demand、backlog 與 forecast analysis。
- Capacity 與 customer order book 是 synthetic planning scenarios。
- 客戶名稱、交期月、數量與優先級不是任何公司的內部資料。
- Dashboard 展示的是 planning logic：forecast → scenario → capacity → order status。
- Dashboard 不估算任何真實 ASE 客戶訂單、工廠產能或交期風險機率。
        """
    )
    st.markdown("<div class='section-title'>Planning Decision</div>", unsafe_allow_html=True)
    st.markdown(
        """
<div class='decision'>
Base plan 可以完成所有 synthetic orders，但 9～11 月可用的新訂單產能已經全部用滿。由於 selected forecast model 在歷史驗證中有 17 / 18 次低估需求，交期承諾前應同時檢查 Upper Demand Scenario。Upper Scenario 下 O004 與 O006 會變成 Late，因此這兩張訂單應列為風險訂單；若無法增加或重新分配產能，就需要調整 priority、split delivery 或 commit month。
</div>
        """,
        unsafe_allow_html=True,
    )
