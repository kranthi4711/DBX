import re
from typing import Dict, List

import pandas as pd
import plotly.express as px
import streamlit as st


_VISUAL_TYPES = ["bar", "line", "area", "scatter", "box", "violin", "histogram"]
_AGG_TYPES = ["sum", "avg", "min", "max", "count", "none"]
_STOP_WORDS = {
    "show",
    "plot",
    "display",
    "graph",
    "chart",
    "kpi",
    "the",
    "a",
    "an",
    "for",
    "and",
    "with",
    "over",
    "across",
}


def _normalize_tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (text or "").lower()) if t not in _STOP_WORDS]


def _find_best_column(term: str, columns: List[str]) -> str:
    if not term:
        return ""
    term_l = term.lower()
    if not columns:
        return ""

    exact = [c for c in columns if c.lower() == term_l]
    if exact:
        return exact[0]

    partial = [c for c in columns if term_l in c.lower() or c.lower() in term_l]
    if partial:
        return partial[0]

    term_parts = [p for p in term_l.split("_") if p]
    scored = []
    for c in columns:
        cl = c.lower()
        score = sum(1 for p in term_parts if p in cl)
        if score:
            scored.append((score, c))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    return ""


def _infer_chart_type(text: str) -> str:
    t = (text or "").lower()
    if "line" in t or "trend" in t or "over time" in t:
        return "line"
    if "area" in t:
        return "area"
    if "scatter" in t or "correlation" in t:
        return "scatter"
    if "hist" in t or "distribution" in t:
        return "histogram"
    if "box" in t:
        return "box"
    if "violin" in t:
        return "violin"
    return "bar"


def _infer_aggregation(text: str) -> str:
    t = (text or "").lower()
    if "average" in t or "avg" in t or "mean" in t:
        return "avg"
    if "minimum" in t or "min" in t:
        return "min"
    if "maximum" in t or "max" in t:
        return "max"
    if "count" in t or "number of" in t:
        return "count"
    if "raw" in t or "no aggregation" in t:
        return "none"
    return "sum"


def _infer_alias(text: str, aliases: List[str]) -> str:
    t = (text or "").lower()
    for a in aliases:
        if a.lower() in t:
            return a
    return aliases[0] if aliases else ""


def _infer_x_y(text: str, columns: List[str]) -> Dict[str, str]:
    if not columns:
        return {"x": "", "y": ""}

    t = (text or "").lower()
    tokens = _normalize_tokens(text)

    x_term = ""
    y_term = ""

    if " by " in t:
        left, right = t.split(" by ", 1)
        left_tokens = _normalize_tokens(left)
        right_tokens = _normalize_tokens(right)
        if left_tokens:
            y_term = left_tokens[-1]
        if right_tokens:
            x_term = right_tokens[0]

    if not y_term and tokens:
        metric_keywords = ["revenue", "sales", "amount", "profit", "margin", "cost", "count", "qty", "quantity"]
        m = next((tok for tok in tokens if tok in metric_keywords), "")
        y_term = m or tokens[0]

    if not x_term:
        dim_keywords = ["date", "month", "year", "day", "region", "country", "category", "segment", "state"]
        d = next((tok for tok in tokens if tok in dim_keywords), "")
        x_term = d

    y_col = _find_best_column(y_term, columns)
    x_col = _find_best_column(x_term, columns)

    if not x_col:
        x_col = columns[0]
    if not y_col:
        y_col = columns[min(1, len(columns) - 1)]

    return {"x": x_col, "y": y_col}


def _spec_from_text(line: str, aliases: List[str], dataset_cols: Dict[str, List[str]]) -> Dict[str, str]:
    alias = _infer_alias(line, aliases)
    cols = dataset_cols.get(alias, [])
    axes = _infer_x_y(line, cols)
    return {
        "title": line.strip()[:100] or "KPI Visual",
        "nlp": line.strip(),
        "dataset_alias": alias,
        "chart_type": _infer_chart_type(line),
        "x_axis": axes["x"],
        "y_axis": axes["y"],
        "aggregation": _infer_aggregation(line),
    }


def _apply_aggregation(df: pd.DataFrame, spec: Dict[str, str]) -> pd.DataFrame:
    x_col = spec.get("x_axis", "")
    y_col = spec.get("y_axis", "")
    agg = spec.get("aggregation", "sum")

    if x_col not in df.columns:
        return df
    if agg == "none":
        return df
    if agg == "count":
        return df.groupby(x_col, dropna=False).size().reset_index(name="kpi_value")
    if y_col not in df.columns:
        return df

    func = {"sum": "sum", "avg": "mean", "min": "min", "max": "max"}.get(agg, "sum")
    out = df.groupby(x_col, dropna=False)[y_col].agg(func).reset_index()
    out = out.rename(columns={y_col: "kpi_value"})
    return out


def _render_plot(df: pd.DataFrame, spec: Dict[str, str]):
    chart = spec.get("chart_type", "bar")
    x_col = spec.get("x_axis", "")
    y_col = spec.get("y_axis", "")

    source = _apply_aggregation(df, spec)
    y_field = "kpi_value" if "kpi_value" in source.columns else y_col

    if x_col not in source.columns:
        st.warning(f"Cannot render '{spec.get('title', 'KPI')}': x-axis column not found in uploaded CSV.")
        return

    if chart == "line":
        fig = px.line(source, x=x_col, y=y_field, title=spec.get("title", "KPI"), markers=True)
    elif chart == "area":
        fig = px.area(source, x=x_col, y=y_field, title=spec.get("title", "KPI"))
    elif chart == "scatter":
        fig = px.scatter(source, x=x_col, y=y_field, title=spec.get("title", "KPI"))
    elif chart == "box":
        fig = px.box(source, x=x_col, y=y_field, title=spec.get("title", "KPI"))
    elif chart == "violin":
        fig = px.violin(source, x=x_col, y=y_field, title=spec.get("title", "KPI"), box=True)
    elif chart == "histogram":
        fig = px.histogram(source, x=x_col, y=y_field if y_field in source.columns else None, title=spec.get("title", "KPI"))
    else:
        fig = px.bar(source, x=x_col, y=y_field, title=spec.get("title", "KPI"))

    fig.update_layout(template="plotly_white", height=440, margin=dict(l=20, r=20, t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_kpi_visual_tab():
    st.subheader("NLP KPI to Visuals")
    st.caption("Enter KPI requests in natural language, generate chart specs, then preview using a CSV or Excel file.")

    aliases = sorted(st.session_state.get("datasets", {}).keys())
    dataset_cols = st.session_state.get("dataset_cols", {})

    if not aliases:
        st.info("Add at least one source/step first so KPI visuals can map to dataset aliases and columns.")
        return

    if "kpi_visual_specs" not in st.session_state:
        st.session_state.kpi_visual_specs = []

    default_text = "Revenue by month as line chart\nOrder count by region\nProfit by category"
    kpi_nlp = st.text_area(
        "KPI prompts (one per line)",
        value=default_text,
        height=140,
        placeholder="Revenue by month as line chart\nAverage basket size by segment\nOrder count by state",
    )

    if st.button("Generate visuals from NLP", type="primary"):
        lines = [ln.strip() for ln in kpi_nlp.splitlines() if ln.strip()]
        st.session_state.kpi_visual_specs = [_spec_from_text(ln, aliases, dataset_cols) for ln in lines]
        st.success(f"Generated {len(st.session_state.kpi_visual_specs)} visual spec(s).")

    specs = st.session_state.kpi_visual_specs
    if not specs:
        st.info("Generate visual specs from NLP to continue.")
        return

    st.markdown("### Generated visual specs")
    for i, spec in enumerate(specs):
        with st.expander(f"Visual {i+1}: {spec.get('title', 'KPI Visual')}", expanded=i == 0):
            c1, c2, c3 = st.columns(3)
            with c1:
                spec["title"] = st.text_input("Title", value=spec.get("title", ""), key=f"kpi_title_{i}")
                spec["dataset_alias"] = st.selectbox(
                    "Dataset alias",
                    options=aliases,
                    index=max(0, aliases.index(spec.get("dataset_alias", aliases[0]))),
                    key=f"kpi_ds_{i}",
                )
            with c2:
                spec["chart_type"] = st.selectbox(
                    "Chart type",
                    options=_VISUAL_TYPES,
                    index=max(0, _VISUAL_TYPES.index(spec.get("chart_type", "bar"))),
                    key=f"kpi_chart_{i}",
                )
                spec["aggregation"] = st.selectbox(
                    "Aggregation",
                    options=_AGG_TYPES,
                    index=max(0, _AGG_TYPES.index(spec.get("aggregation", "sum"))),
                    key=f"kpi_agg_{i}",
                )
            with c3:
                cols = dataset_cols.get(spec["dataset_alias"], []) or ["category", "value"]
                x_idx = cols.index(spec.get("x_axis")) if spec.get("x_axis") in cols else 0
                y_idx = cols.index(spec.get("y_axis")) if spec.get("y_axis") in cols else min(1, len(cols) - 1)
                spec["x_axis"] = st.selectbox("X-axis", options=cols, index=x_idx, key=f"kpi_x_{i}")
                spec["y_axis"] = st.selectbox("Y-axis", options=cols, index=y_idx, key=f"kpi_y_{i}")

    st.session_state.kpi_visual_specs = specs

    st.divider()
    st.markdown("### Preview generated visuals")
    uploaded = st.file_uploader("Upload CSV or Excel for KPI visual preview", type=["csv", "xlsx"], key="kpi_visual_csv")
    if not uploaded:
        st.caption("Upload a CSV or Excel file to render the visuals above.")
        return

    try:
        name = (getattr(uploaded, "name", "") or "").lower()
        if name.endswith(".xlsx") or name.endswith(".xls"):
            df = pd.read_excel(uploaded)
            st.success(f"Loaded {len(df)} rows from Excel.")
        else:
            df = pd.read_csv(uploaded)
            st.success(f"Loaded {len(df)} rows from CSV.")
    except Exception as ex:
        st.error(f"Could not parse uploaded file: {ex}")
        return

    for spec in specs:
        _render_plot(df, spec)
