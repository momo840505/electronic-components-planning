
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="生產排程決策看板",
    page_icon="📦",
    layout="wide",
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / "data"

PRIORITY_RANK = {"High": 0, "Normal": 1}
AT_RISK_SLACK_THRESHOLD = 0.10

st.markdown(
    """
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 3rem;
    max-width: 1280px;
}
h1 {font-size: 2rem !important; margin-bottom: .1rem !important;}
h2 {font-size: 1.35rem !important;}
h3 {font-size: 1.05rem !important;}

.hero {
    border-radius: 18px;
    padding: 1.2rem 1.35rem;
    margin: .6rem 0 1rem 0;
}
.hero-green {background:#ecfdf5; border:1px solid #a7f3d0;}
.hero-amber {background:#fffbeb; border:1px solid #fde68a;}
.hero-red {background:#fef2f2; border:1px solid #fecaca;}
.hero-title {font-size:1.35rem; font-weight:800; margin-bottom:.35rem;}
.hero-text {font-size:1rem; line-height:1.65; color:#334155;}

.action-card {
    border-radius: 14px;
    padding: 1rem 1.15rem;
    background:#eff6ff;
    border:1px solid #bfdbfe;
    margin-bottom: 1.2rem;
}
.action-title {font-weight:800; color:#1d4ed8; margin-bottom:.25rem;}

.order-card {
    border-radius: 14px;
    padding: 1rem 1.05rem;
    border:1px solid #e2e8f0;
    background:white;
    min-height:170px;
}
.order-red {border-left:6px solid #ef4444;}
.order-amber {border-left:6px solid #f59e0b;}
.order-green {border-left:6px solid #22c55e;}
.order-title {font-size:1.05rem; font-weight:800; margin-bottom:.35rem;}
.order-meta {font-size:.9rem; color:#64748b; margin-bottom:.4rem;}
.order-body {font-size:.95rem; line-height:1.55; color:#334155;}

.month-card {
    border-radius: 14px;
    padding: .9rem 1rem;
    border:1px solid #e2e8f0;
    background:#fff;
}
.month-name {font-weight:800; font-size:1rem;}
.month-value {font-weight:800; font-size:1.4rem; margin:.25rem 0;}
.small-note {color:#64748b; font-size:.86rem;}

.scenario-card {
    border-radius: 14px;
    border:1px solid #e2e8f0;
    padding:.9rem 1rem;
    background:#f8fafc;
}
.scenario-title {font-weight:800;}
.scenario-result {font-size:1.15rem; font-weight:800; margin:.35rem 0;}
</style>
""",
    unsafe_allow_html=True,
)


def load_csv(name: str, date_columns=None) -> pd.DataFrame:
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
    }


def fmt_month(v):
    if pd.isna(v):
        return "-"
    return pd.Timestamp(v).strftime("%Y-%m")


def allocate_orders(
    orders: pd.DataFrame,
    capacity: pd.DataFrame,
    multiplier: float,
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
        qty = float(order.quantity * multiplier)
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
    summary = pd.DataFrame(summary_records)

    monthly = (
        allocation.groupby("allocation_month", as_index=False)["allocated_quantity"]
        .sum()
        .rename(
            columns={
                "allocation_month": "month",
                "allocated_quantity": "allocated_new_orders",
            }
        )
    )

    cap = capacity_work.merge(monthly, on="month", how="left")
    cap["allocated_new_orders"] = cap["allocated_new_orders"].fillna(0.0)
    cap["remaining_new_order_capacity"] = (
        cap["net_new_order_capacity"] - cap["allocated_new_orders"]
    )
    cap["util_pct"] = (
        cap["allocated_new_orders"] / cap["net_new_order_capacity"] * 100
    )

    return allocation, summary, cap


def get_late_qty(summary: pd.DataFrame, allocation: pd.DataFrame) -> float:
    late_ids = set(summary.loc[summary["status"].eq("Late"), "order_id"])
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


def get_order_late_qty(order_id: str, allocation: pd.DataFrame) -> float:
    return float(
        allocation.loc[
            allocation["order_id"].eq(order_id)
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
    "① 目前需求": ("目前需求", 1.00),
    "② 需求多約 3%": ("需求多約3%", upper_multiplier),
    "③ 需求多 10%": ("需求多10%", 1.10),
}

st.title("生產排程決策看板")
st.caption("不用懂模型也能看：現在能不能照原交期走？哪張單要先處理？哪個月卡住？")

scenario_label = st.radio(
    "假設接下來需求是：",
    list(SCENARIOS.keys()),
    horizontal=True,
)
scenario_name, multiplier = SCENARIOS[scenario_label]

allocation, summary, cap = allocate_orders(
    orders, capacity, multiplier, scenario_name
)

on_time = int((summary["status"] == "On Time").sum())
risk = int((summary["status"] == "At Risk").sum())
late = int((summary["status"] == "Late").sum())
late_qty = get_late_qty(summary, allocation)

# 1. Business conclusion
if scenario_name == "目前需求":
    hero_class = "hero-amber"
    hero_icon = "🟠"
    hero_title = "現在排得完，但幾乎沒有安全空間"
    hero_text = (
        "6 張訂單目前都能完成，不會真正超過原交期；"
        "但 O004、O006 已經貼近產能上限。只要需求再多一點、臨時插單或發生重工，就可能往後延。"
    )
    action = "先照目前交期規劃，但回覆 O004、O006 前，再確認產能與需求有沒有變動。"

elif scenario_name == "需求多約3%":
    hero_class = "hero-red"
    hero_icon = "🔴"
    hero_title = "需求只多約 3%，就有 2 張訂單會延後"
    hero_text = (
        f"O004、O006 會有部分數量跨過原交期，合計約 {late_qty:.2f} k。"
        "代表目前排程的緩衝非常小。"
    )
    action = "優先處理 O004、O006：先看能不能挪產能或拆批交貨，再決定是否調整承諾交期。"

else:
    hero_class = "hero-red"
    hero_icon = "🚨"
    hero_title = "需求多 10% 時，延後問題明顯放大"
    hero_text = (
        f"2 張訂單延後，真正跨過原交期的數量增加到 {late_qty:.2f} k。"
        "這時不能只監控，需要提前協調產能與交期。"
    )
    action = "立即檢查 O004、O006 的產能來源；若補不到，就要拆批或重談交期。"

st.markdown(
    f"""
<div class="hero {hero_class}">
  <div class="hero-title">{hero_icon} {hero_title}</div>
  <div class="hero-text">{hero_text}</div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="action-card">
  <div class="action-title">下一步建議</div>
  <div>{action}</div>
</div>
""",
    unsafe_allow_html=True,
)

# 2. Three numbers only
m1, m2, m3 = st.columns(3)
m1.metric("🟢 可以照原交期", on_time)
m2.metric("🟠 先注意", risk)
m3.metric("🔴 會延後", late)

# 3. Only problematic orders
st.subheader("先看需要處理的訂單")

problem_orders = summary.loc[
    summary["status"].isin(["At Risk", "Late", "Unscheduled"])
].copy()

if problem_orders.empty:
    st.success("目前沒有需要特別處理的訂單。")
else:
    cols = st.columns(min(3, len(problem_orders)))
    for i, row in enumerate(problem_orders.itertuples()):
        if row.status == "Late":
            css = "order-red"
            badge = "🔴 會延後"
            late_piece = get_order_late_qty(row.order_id, allocation)
            reason = (
                f"原交期 {fmt_month(row.requested_due_month)}，"
                f"目前要到 {fmt_month(row.feasible_commit_month)} 才能全部排完。"
            )
            suggestion = (
                f"約 {late_piece:.2f} k 會跨月。先看能不能挪產能或拆批。"
            )
        elif row.status == "At Risk":
            css = "order-amber"
            badge = "🟠 先注意"
            slack = row.slack_after_commit_pct * 100
            reason = (
                f"目前仍能在 {fmt_month(row.requested_due_month)} 完成，"
                f"但排完後只剩 {slack:.1f}% 空間。"
            )
            suggestion = "現在還沒延後，但很容易被臨時需求或異常推遲。"
        else:
            css = "order-red"
            badge = "⚫ 排不進去"
            reason = "目前規劃期間內沒有足夠產能排完。"
            suggestion = "需要增加產能、拆單或重新談交期。"

        with cols[i % len(cols)]:
            st.markdown(
                f"""
<div class="order-card {css}">
  <div class="order-title">{row.order_id}｜{row.customer}</div>
  <div class="order-meta">{badge}</div>
  <div class="order-body">{reason}<br><br><b>建議：</b>{suggestion}</div>
</div>
""",
                unsafe_allow_html=True,
            )

# 4. Capacity as four simple cards
st.subheader("哪個月份最容易卡住？")
st.caption("只看一件事：這個月可以排的新訂單空間，已經用了多少。")

month_cols = st.columns(len(cap))
for col, row in zip(month_cols, cap.itertuples()):
    util = float(row.util_pct)
    remaining = float(row.remaining_new_order_capacity)

    if util >= 99.9:
        status = "🔴 已滿"
        note = "再有新需求，就可能往下個月移。"
    elif util >= 90:
        status = "🟠 很緊"
        note = "剩餘空間不多，需要注意。"
    else:
        status = "🟢 有空間"
        note = "目前仍有明顯緩衝。"

    with col:
        st.markdown(
            f"""
<div class="month-card">
  <div class="month-name">{fmt_month(row.month)}</div>
  <div class="month-value">{util:.0f}% 已使用</div>
  <div>{status}</div>
  <div class="small-note">還剩 {remaining:.0f} k<br>{note}</div>
</div>
""",
            unsafe_allow_html=True,
        )

# 5. Scenario comparison in one glance
st.subheader("需求如果增加，結果會差多少？")

scenario_specs = [
    ("目前需求", 1.00),
    ("多約 3%", upper_multiplier),
    ("多 10%", 1.10),
]

scenario_cols = st.columns(3)
for col, (label, mult) in zip(scenario_cols, scenario_specs):
    a, s, c = allocate_orders(orders, capacity, mult, label)
    r = int((s["status"] == "At Risk").sum())
    l = int((s["status"] == "Late").sum())
    lq = get_late_qty(s, a)

    if l > 0:
        result = f"🔴 {l} 張延後"
        detail = f"延後量 {lq:.2f} k"
    elif r > 0:
        result = f"🟠 {r} 張需注意"
        detail = "目前沒有真正延後"
    else:
        result = "🟢 全部穩定"
        detail = "沒有風險或延後"

    with col:
        st.markdown(
            f"""
<div class="scenario-card">
  <div class="scenario-title">{label}</div>
  <div class="scenario-result">{result}</div>
  <div class="small-note">{detail}</div>
</div>
""",
            unsafe_allow_html=True,
        )

# 6. Full order table only if wanted
with st.expander("查看全部 6 張訂單"):
    full = summary.copy()
    full["原交期"] = full["requested_due_month"].map(fmt_month)
    full["目前完成"] = full["feasible_commit_month"].map(fmt_month)
    full["狀態"] = full["status"].map(
        {
            "On Time": "🟢 按期",
            "At Risk": "🟠 先注意",
            "Late": "🔴 延後",
            "Unscheduled": "⚫ 排不進去",
        }
    )
    full["數量"] = full["scenario_quantity"].round(2)
    full = full[
        ["order_id", "customer", "數量", "原交期", "目前完成", "狀態"]
    ].rename(
        columns={
            "order_id": "訂單",
            "customer": "客戶",
        }
    )
    st.dataframe(full, use_container_width=True, hide_index=True)

# 7. Forecast only for follow-up
with st.expander("如果主管追問：為什麼還要看另一種 Forecast？"):
    st.markdown(
        """
**先講白話：不是因為原本的預測不能用，而是因為它最近常常估得稍微偏低。**

所以實際做交期判斷時，不只看一個數字，而是再拿一個「有趨勢感的預測」做交叉檢查。
        """
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 基準預測")
        st.write("**Last Value**")
        st.write("未來 3 個月：**5,769 → 5,769 → 5,769**")
        st.write("整體歷史測試誤差最低，所以保留它當基準。")

    with c2:
        st.markdown("### 第二個觀點")
        st.write("**Holt-Winters**")
        st.write("未來 3 個月：**5,771 → 5,796 → 5,804**")
        st.write("它看到需求有緩慢往上的可能，所以拿來提醒風險。")

    f = forecast.copy()
    f["月份"] = f["date"].map(fmt_month)

    fig = go.Figure()
    fig.add_scatter(
        x=f["月份"],
        y=f["last_value"],
        mode="lines+markers",
        name="基準預測",
        line=dict(color="#16a34a", width=3),
    )
    fig.add_scatter(
        x=f["月份"],
        y=f["holt_winters"],
        mode="lines+markers",
        name="趨勢型參考",
        line=dict(color="#f59e0b", width=3),
    )
    fig.update_layout(
        height=320,
        xaxis=dict(type="category", title=""),
        yaxis_title="公開市場需求指標（USD mn）",
        legend_title="",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.info(
        f"兩種方法的 3 個月平均只差約 {holt_uplift:.2f}%；"
        "但因為目前排程本來就接近滿載，所以即使只多一點需求，也可能影響最後幾張訂單的交期。"
    )

with st.expander("名詞白話解釋"):
    st.markdown(
        """
- **產能已滿**：這個月能拿來排新訂單的空間已經用完。
- **先注意**：目前還沒延後，但只剩很少緩衝。
- **延後**：至少有一部分數量會超過原本交期。
- **拆批**：不要整張訂單一起等，先完成一部分、先交一部分。
- **優先順序**：這個作品只用來決定「交期相同時誰先排」，不是說哪個真實客戶比較重要。
        """
    )

st.caption(
    "展示資料說明：需求預測使用公開製造業資料；客戶、訂單與產能為模擬案例，用來展示生產規劃判斷方式。"
)
