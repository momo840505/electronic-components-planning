
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

# --------------------------------------------------
# Visual style: soft glass cards / rounded dashboard
# --------------------------------------------------
st.markdown(
    """
<style>
:root {
  --text: #153047;
  --muted: #6b7f91;
  --blue: #0ea5e9;
  --green: #22c55e;
  --yellow: #f59e0b;
  --red: #ef4444;
  --panel: rgba(255,255,255,.88);
  --border: rgba(255,255,255,.95);
  --shadow: rgba(71,110,143,.14);
}

.stApp {
  background:
    radial-gradient(circle at 8% 8%, rgba(255,218,121,.36), transparent 25%),
    radial-gradient(circle at 92% 8%, rgba(125,211,252,.34), transparent 27%),
    radial-gradient(circle at 48% 96%, rgba(134,239,172,.23), transparent 30%),
    linear-gradient(135deg, #fffdf4 0%, #f4fbff 52%, #f8fff4 100%);
}

.block-container {
  padding-top: 3.1rem !important;
  padding-bottom: 4rem !important;
  max-width: 1320px !important;
}

#MainMenu, footer, header {visibility: hidden;}

.hero-title {
  font-size: clamp(2rem, 4vw, 3.3rem);
  font-weight: 900;
  letter-spacing: -1.2px;
  color: var(--text);
  line-height: 1.08;
  margin: 0 0 .6rem 0;
}

.hero-subtitle {
  color: var(--muted);
  font-size: 1rem;
  line-height: 1.65;
  max-width: 900px;
  margin-bottom: 1.3rem;
}

.glass {
  background: var(--panel);
  border: 1px solid var(--border);
  box-shadow: 0 16px 45px var(--shadow);
  border-radius: 24px;
  backdrop-filter: blur(14px);
}

.summary-card {
  padding: 1.15rem 1.25rem;
  min-height: 145px;
}

.summary-label {
  color: var(--muted);
  font-size: .86rem;
  font-weight: 700;
  margin-bottom: .35rem;
}

.summary-value {
  font-size: 2rem;
  line-height: 1.05;
  font-weight: 900;
  color: var(--text);
}

.summary-note {
  color: var(--muted);
  font-size: .86rem;
  line-height: 1.45;
  margin-top: .5rem;
}

.decision-card {
  padding: 1.25rem 1.35rem;
  margin: .4rem 0 1.2rem 0;
}

.decision-title {
  font-size: 1.28rem;
  font-weight: 900;
  color: var(--text);
  margin-bottom: .4rem;
}

.decision-body {
  font-size: .98rem;
  line-height: 1.7;
  color: #3a5368;
}

.decision-safe {
  background: linear-gradient(135deg, rgba(236,253,245,.95), rgba(255,255,255,.90));
}

.decision-watch {
  background: linear-gradient(135deg, rgba(255,251,235,.97), rgba(255,255,255,.90));
}

.decision-risk {
  background: linear-gradient(135deg, rgba(254,242,242,.97), rgba(255,255,255,.90));
}

.section-title {
  font-size: 1.35rem;
  font-weight: 900;
  color: var(--text);
  margin: 2rem 0 .25rem 0;
}

.section-sub {
  color: var(--muted);
  font-size: .92rem;
  margin-bottom: .9rem;
}

.order-card {
  padding: 1rem 1.05rem;
  min-height: 170px;
}

.order-id {
  font-size: 1rem;
  font-weight: 900;
  color: var(--text);
}

.order-state {
  display: inline-block;
  margin: .5rem 0 .6rem;
  padding: .28rem .7rem;
  border-radius: 999px;
  font-size: .82rem;
  font-weight: 900;
}

.state-green {background:#dcfce7; color:#166534;}
.state-yellow {background:#fef3c7; color:#92400e;}
.state-red {background:#fee2e2; color:#991b1b;}

.order-copy {
  color:#486176;
  font-size:.9rem;
  line-height:1.55;
}

.order-action {
  margin-top:.55rem;
  color:#1e3a8a;
  font-size:.88rem;
  font-weight:700;
}

.scenario-card {
  padding: 1rem 1.05rem;
  min-height: 135px;
}

.scenario-name {
  color:var(--muted);
  font-size:.83rem;
  font-weight:800;
}

.scenario-result {
  font-size:1.22rem;
  font-weight:900;
  color:var(--text);
  margin:.35rem 0;
}

.scenario-copy {
  color:var(--muted);
  font-size:.86rem;
  line-height:1.45;
}

div[data-testid="stRadio"] > div {
  gap: .65rem;
}

div[data-testid="stRadio"] label {
  background: rgba(255,255,255,.88);
  border: 1px solid rgba(203,213,225,.8);
  border-radius: 999px;
  padding: .38rem .75rem;
  box-shadow: 0 5px 16px rgba(71,110,143,.08);
}

div[data-testid="stExpander"] {
  background: rgba(255,255,255,.80);
  border-radius: 16px;
  border: 1px solid rgba(226,232,240,.9);
}

[data-testid="stDataFrame"] {
  border-radius: 16px;
  overflow: hidden;
}

@media (max-width: 900px) {
  .block-container {padding-left: 1rem !important; padding-right: 1rem !important;}
  .hero-title {font-size: 2.2rem;}
}
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


def fmt_month(v) -> str:
    if pd.isna(v):
        return "-"
    return pd.Timestamp(v).strftime("%Y-%m")


def fmt_num(v: float) -> str:
    # Main dashboard intentionally shows the original planning numbers without "k".
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def allocate_orders(
    orders: pd.DataFrame,
    capacity: pd.DataFrame,
    multiplier: float,
    scenario_name: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cap = capacity.copy().sort_values("month").reset_index(drop=True)
    remaining = {
        r.month: float(r.net_new_order_capacity)
        for r in cap.itertuples()
    }
    net_lookup = {
        r.month: float(r.net_new_order_capacity)
        for r in cap.itertuples()
    }

    work = orders.copy()
    work["priority_rank"] = work["priority"].map(PRIORITY_RANK)
    work = work.sort_values(
        ["requested_due_month", "priority_rank", "order_id"]
    ).reset_index(drop=True)

    alloc_records = []
    order_records = []
    months = sorted(remaining.keys())

    for order in work.itertuples():
        qty = float(order.quantity * multiplier)
        left = qty
        final_month = pd.NaT
        slack_after = np.nan

        for month in months:
            if left <= 1e-9:
                break
            available = remaining[month]
            if available <= 1e-9:
                continue

            used = min(left, available)
            remaining[month] -= used
            left -= used

            alloc_records.append(
                {
                    "scenario": scenario_name,
                    "order_id": order.order_id,
                    "customer": order.customer,
                    "priority": order.priority,
                    "requested_due_month": order.requested_due_month,
                    "allocation_month": month,
                    "allocated_quantity": used,
                }
            )

            final_month = month
            slack_after = remaining[month] / net_lookup[month]

        if left > 1e-9:
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

        order_records.append(
            {
                "order_id": order.order_id,
                "customer": order.customer,
                "priority": order.priority,
                "base_quantity": float(order.quantity),
                "scenario_quantity": qty,
                "requested_due_month": order.requested_due_month,
                "feasible_commit_month": final_month,
                "slack_after_commit_pct": slack_after,
                "status": status,
            }
        )

    allocation = pd.DataFrame(alloc_records)
    order_summary = pd.DataFrame(order_records)

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

    cap = cap.merge(monthly_alloc, on="month", how="left")
    cap["allocated_new_orders"] = cap["allocated_new_orders"].fillna(0.0)
    cap["remaining_new_order_capacity"] = (
        cap["net_new_order_capacity"] - cap["allocated_new_orders"]
    )
    cap["util_pct"] = (
        cap["allocated_new_orders"] / cap["net_new_order_capacity"] * 100
    )

    return allocation, order_summary, cap


def late_quantity(order_summary: pd.DataFrame, allocation: pd.DataFrame) -> float:
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


def order_late_quantity(order_id: str, allocation: pd.DataFrame) -> float:
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

# -----------------------------
# Header
# -----------------------------
st.markdown(
    """
<div class="hero-title">生產排程決策看板</div>
<div class="hero-subtitle">
把需求變化直接轉成排程結果：哪些訂單能照原交期、哪些需要先處理，以及每個月的產能被什麼占用。
</div>
""",
    unsafe_allow_html=True,
)

SCENARIOS = {
    "目前需求": ("Base", 1.00),
    "需求多約 3%": ("Upper", upper_multiplier),
    "需求多 10%": ("Stress", 1.10),
}

scenario_label = st.radio(
    "需求情境",
    list(SCENARIOS.keys()),
    horizontal=True,
)
scenario_name, multiplier = SCENARIOS[scenario_label]

allocation, summary, cap = allocate_orders(
    orders, capacity, multiplier, scenario_name
)

on_time = int((summary["status"] == "On Time").sum())
watch = int((summary["status"] == "At Risk").sum())
late = int((summary["status"] == "Late").sum())
late_qty = late_quantity(summary, allocation)
total_demand = float(summary["scenario_quantity"].sum())

# -----------------------------
# Decision message
# -----------------------------
if scenario_name == "Base":
    decision_class = "decision-watch"
    decision_icon = "🟠"
    decision_title = "目前排得完，但安全空間很小"
    decision_body = (
        "6 張訂單目前都能完成；其中 O004、O006 已經接近可用產能上限。"
        "如果需求再增加、臨時插單或發生重工，這兩張會最先受到影響。"
    )
    next_step = (
        "交期先照目前計畫，但 O004、O006 在正式回覆前，再確認需求與可用產能是否有變化。"
    )

elif scenario_name == "Upper":
    decision_class = "decision-risk"
    decision_icon = "🔴"
    decision_title = "需求只多約 3%，O004、O006 就開始延後"
    decision_body = (
        f"這兩張訂單有部分數量會跨過原交期，合計延後數量 {fmt_num(late_qty)}。"
        "這表示目前排程的緩衝已經非常有限。"
    )
    next_step = (
        "先處理 O004、O006：確認能否挪產能或拆批交貨；若無法補足，再調整可承諾月份。"
    )

else:
    decision_class = "decision-risk"
    decision_icon = "🚨"
    decision_title = "需求多 10% 時，延後量明顯放大"
    decision_body = (
        f"仍然是 O004、O006 受影響，但真正跨過原交期的數量增加到 {fmt_num(late_qty)}。"
        "這時需要提前協調產能與交期。"
    )
    next_step = (
        "優先確認 O004、O006 的產能來源；若補不到，改用拆批或重新確認交期。"
    )

st.markdown(
    f"""
<div class="glass decision-card {decision_class}">
  <div class="decision-title">{decision_icon} {decision_title}</div>
  <div class="decision-body">{decision_body}</div>
  <div class="decision-body" style="margin-top:.55rem;"><b>建議處理：</b>{next_step}</div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# High-level numbers
# -----------------------------
c1, c2, c3, c4 = st.columns(4)
cards = [
    ("本情境需求量", fmt_num(total_demand), "依目前選擇的需求情境重新計算"),
    ("可照原交期", str(on_time), "目前沒有跨過原交期"),
    ("先注意", str(watch), "還沒延後，但剩餘空間很小"),
    ("會延後", str(late), f"延後數量 {fmt_num(late_qty)}"),
]

for col, (label, value, note) in zip([c1, c2, c3, c4], cards):
    with col:
        st.markdown(
            f"""
<div class="glass summary-card">
  <div class="summary-label">{label}</div>
  <div class="summary-value">{value}</div>
  <div class="summary-note">{note}</div>
</div>
""",
            unsafe_allow_html=True,
        )

# -----------------------------
# Orders that need attention
# -----------------------------
st.markdown('<div class="section-title">需要先處理的訂單</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">只把「先注意」或「已延後」的訂單拉出來，避免主管一開始被完整表格淹沒。</div>',
    unsafe_allow_html=True,
)

problem = summary.loc[summary["status"].isin(["At Risk", "Late", "Unscheduled"])].copy()

if problem.empty:
    st.success("目前沒有需要特別處理的訂單。")
else:
    cols = st.columns(min(len(problem), 3))
    for i, row in enumerate(problem.itertuples()):
        if row.status == "At Risk":
            state_cls = "state-yellow"
            state_text = "🟠 先注意"
            slack = row.slack_after_commit_pct * 100
            copy = (
                f"原交期 {fmt_month(row.requested_due_month)}，目前仍能按期完成。"
                f"但排完後只剩 {slack:.1f}% 可用空間。"
            )
            action = "先確認需求或產能是否有變動。"
        elif row.status == "Late":
            state_cls = "state-red"
            state_text = "🔴 已延後"
            qty_late = order_late_quantity(row.order_id, allocation)
            copy = (
                f"原交期 {fmt_month(row.requested_due_month)}，目前要到 "
                f"{fmt_month(row.feasible_commit_month)} 才能全部排完。"
            )
            action = f"有 {fmt_num(qty_late)} 跨月，先看能否挪產能或拆批。"
        else:
            state_cls = "state-red"
            state_text = "⚫ 排不進去"
            copy = "目前規劃期間內沒有足夠產能排完。"
            action = "需要增加產能、拆單或重新確認交期。"

        with cols[i % len(cols)]:
            st.markdown(
                f"""
<div class="glass order-card">
  <div class="order-id">{row.order_id}｜{row.customer}</div>
  <div class="order-state {state_cls}">{state_text}</div>
  <div class="order-copy">{copy}</div>
  <div class="order-action">建議：{action}</div>
</div>
""",
                unsafe_allow_html=True,
            )

# -----------------------------
# Capacity composition chart
# -----------------------------
st.markdown('<div class="section-title">每個月的產能被什麼占用？</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">堆疊圖的整根柱子就是「總產能」；往上依序看原本已排工作、安全保留、本次新訂單，以及最後還剩多少。</div>',
    unsafe_allow_html=True,
)

cap_chart = cap.copy()
cap_chart["月份"] = cap_chart["month"].map(fmt_month)

fig = go.Figure()
fig.add_bar(
    x=cap_chart["月份"],
    y=cap_chart["existing_load"],
    name="原本已排工作",
    marker_color="#8ea6ba",
    hovertemplate="原本已排工作：%{y:.0f}<extra></extra>",
)
fig.add_bar(
    x=cap_chart["月份"],
    y=cap_chart["safety_reserve"],
    name="安全保留",
    marker_color="#f6c453",
    hovertemplate="安全保留：%{y:.0f}<extra></extra>",
)
fig.add_bar(
    x=cap_chart["月份"],
    y=cap_chart["allocated_new_orders"],
    name="本次新訂單",
    marker_color="#39a7e8",
    hovertemplate="本次新訂單：%{y:.0f}<extra></extra>",
)
fig.add_bar(
    x=cap_chart["月份"],
    y=cap_chart["remaining_new_order_capacity"],
    name="剩餘空間",
    marker_color="#72d39b",
    hovertemplate="剩餘空間：%{y:.0f}<extra></extra>",
)

fig.update_layout(
    barmode="stack",
    height=450,
    xaxis=dict(type="category", title=""),
    yaxis=dict(title="規劃數量", gridcolor="rgba(148,163,184,.18)"),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        title="",
    ),
    margin=dict(l=20, r=20, t=65, b=20),
    plot_bgcolor="rgba(255,255,255,.0)",
    paper_bgcolor="rgba(255,255,255,.0)",
)
st.plotly_chart(fig, use_container_width=True)

# Capacity interpretation row
capacity_cols = st.columns(len(cap_chart))
for col, row in zip(capacity_cols, cap_chart.itertuples()):
    used = float(row.allocated_new_orders)
    available = float(row.net_new_order_capacity)
    remain = float(row.remaining_new_order_capacity)
    util = float(row.util_pct)

    if util >= 99.9:
        state = "🔴 新訂單空間已滿"
        desc = "需求再增加就會往後月移。"
    elif util >= 90:
        state = "🟠 空間很緊"
        desc = "建議先確認後續需求。"
    else:
        state = "🟢 還有空間"
        desc = "目前仍有明顯緩衝。"

    with col:
        st.markdown(
            f"""
<div class="glass scenario-card">
  <div class="scenario-name">{row.月份}</div>
  <div class="scenario-result">{fmt_num(used)} / {fmt_num(available)}</div>
  <div class="scenario-copy">{state}<br>剩餘 {fmt_num(remain)}<br>{desc}</div>
</div>
""",
            unsafe_allow_html=True,
        )

# -----------------------------
# Scenario comparison
# -----------------------------
st.markdown('<div class="section-title">需求變多時，結果會怎麼變？</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">不需要理解模型，只看需求變動後有沒有開始影響交期。</div>',
    unsafe_allow_html=True,
)

scenario_specs = [
    ("目前需求", 1.00),
    ("需求多約 3%", upper_multiplier),
    ("需求多 10%", 1.10),
]

scols = st.columns(3)
for col, (label, mult) in zip(scols, scenario_specs):
    a, s, c = allocate_orders(orders, capacity, mult, label)
    r = int((s["status"] == "At Risk").sum())
    l = int((s["status"] == "Late").sum())
    lq = late_quantity(s, a)

    if l > 0:
        result = f"🔴 {l} 張延後"
        detail = f"延後數量 {fmt_num(lq)}"
    elif r > 0:
        result = f"🟠 {r} 張先注意"
        detail = "目前尚未真正延後"
    else:
        result = "🟢 全部穩定"
        detail = "沒有風險或延後"

    with col:
        st.markdown(
            f"""
<div class="glass scenario-card">
  <div class="scenario-name">{label}</div>
  <div class="scenario-result">{result}</div>
  <div class="scenario-copy">{detail}</div>
</div>
""",
            unsafe_allow_html=True,
        )

# -----------------------------
# Details: not interview-meta wording
# -----------------------------
with st.expander("查看全部訂單"):
    full = summary.copy()
    full["數量"] = full["scenario_quantity"].map(fmt_num)
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
    full = full[
        ["order_id", "customer", "數量", "原交期", "目前完成", "狀態"]
    ].rename(columns={"order_id": "訂單", "customer": "客戶"})
    st.dataframe(full, use_container_width=True, hide_index=True)

with st.expander("需求預測依據"):
    st.markdown(
        """
**為什麼不是只看一個預估值？**

目前的基準預估在整體歷史測試中誤差最低，所以適合拿來當日常排程基準；
但近期驗證又發現它大多數時候估得稍微偏低，因此再用另一個會反映趨勢的方法做交叉檢查，
並另外保留「需求多約 3%」的較保守情境。
        """
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**基準預估｜Last Value**")
        st.write("歷史測試 WAPE：**1.851%**")
        st.write("未來三個月：**5,769 → 5,769 → 5,769**")
        st.caption("整體誤差最低，所以作為 Base Plan。")

    with c2:
        st.markdown("**趨勢參考｜Holt-Winters**")
        st.write("歷史測試 WAPE：**1.991%**")
        st.write("未來三個月：**5,771 → 5,796 → 5,804**")
        st.caption("整體略差，但會反映緩慢上升的趨勢。")

    st.write(
        f"近期 18 次驗證中，有 **17 次低估**；Aggregate Bias 為 **-1.80%**。"
    )
    st.caption(
        "這代表基準預估可以用，但正式做交期判斷時，不宜只看一個點，還要一起看較保守情境。"
    )

    f = forecast.copy()
    f["月份"] = f["date"].map(fmt_month)
    ffig = go.Figure()
    ffig.add_scatter(
        x=f["月份"],
        y=f["last_value"],
        mode="lines+markers",
        name="基準預估",
        line=dict(color="#22c55e", width=3),
    )
    ffig.add_scatter(
        x=f["月份"],
        y=f["holt_winters"],
        mode="lines+markers",
        name="趨勢參考",
        line=dict(color="#f59e0b", width=3),
    )
    ffig.update_layout(
        height=330,
        xaxis=dict(type="category", title=""),
        yaxis=dict(title="公開市場需求指標（USD mn）"),
        legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=10, r=10, t=45, b=10),
        plot_bgcolor="rgba(255,255,255,0)",
        paper_bgcolor="rgba(255,255,255,0)",
    )
    st.plotly_chart(ffig, use_container_width=True)

with st.expander("名詞白話解釋"):
    st.markdown(
        """
- **原本已排工作**：這次新訂單進來之前，原本就已經占用的產能。
- **安全保留**：刻意留下來應付急單、重工或設備異常的空間。
- **本次新訂單**：目前情境下，這批新訂單實際排進各月份的數量。
- **剩餘空間**：排完之後還能再接多少新需求。
- **先注意**：目前還沒延後，但完成後的安全空間已經很少。
- **延後**：至少有一部分數量會跨過原本交期。
- **拆批**：先完成、先交一部分，不必整張訂單一起等。
        """
    )

st.caption(
    "展示資料說明：需求預測使用公開製造業資料；客戶、訂單與產能為模擬案例，用來展示生產規劃的判斷方式。"
)
