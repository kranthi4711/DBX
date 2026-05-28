import json

import pandas as pd
import plotly.express as px
import streamlit as st

from bi_exports import (
    build_bi_manifest,
    build_powerbi_handoff_zip,
    generate_js_visual_html,
    generate_python_visual_app,
)

st.set_page_config(page_title="BI Visual Studio", layout="wide")

st.title("BI Visual Studio")
st.caption("Design KPI visuals from raw and target datasets. Export Python app, JavaScript HTML, or a Power BI handoff package.")

pipeline_name = st.session_state.get("pipeline", None)
pipeline_name = pipeline_name.name if pipeline_name else "New Pipeline"

source_aliases = [s.alias for s in st.session_state.get("sources", [])]
step_aliases = [step.output_alias for step in st.session_state.get("pipeline", {}).steps] if "pipeline" in st.session_state else []
output_aliases = [o.from_alias for o in st.session_state.get("pipeline", {}).outputs] if "pipeline" in st.session_state else []

all_aliases = sorted(set(source_aliases + step_aliases + output_aliases))
dataset_cols = st.session_state.get("dataset_cols", {})

left, right = st.columns([1, 1])

with left:
    st.subheader("1) Dataset scope")
    raw_selected = st.multiselect("Raw tables / aliases", options=all_aliases, default=source_aliases)
    target_selected = st.multiselect("Target tables / aliases", options=all_aliases, default=output_aliases)

    st.markdown("Optional fully qualified table names")
    raw_full = st.text_area(
        "Raw table full names (one per line)",
        placeholder="catalog.schema.raw_orders\ncatalog.schema.raw_customers",
        height=80,
    )
    target_full = st.text_area(
        "Target table full names (one per line)",
        placeholder="catalog.schema.fact_sales\ncatalog.schema.dim_customer",
        height=80,
    )

with right:
    st.subheader("2) KPI planning")
    kpi_text = st.text_area(
        "KPI list (one per line)",
        placeholder="Revenue\nGross Margin %\nOrder Count\nAverage Basket Size",
        height=180,
    )

st.divider()
st.subheader("3) Additional visuals")
st.caption("Define visuals by choosing dataset alias, x-axis, y-axis, and visual type.")

visual_count = st.number_input("How many visuals to define", min_value=1, max_value=20, value=3, step=1)
visual_types = ["bar", "line", "area", "scatter", "histogram", "box", "violin"]

visuals = []

for idx in range(int(visual_count)):
    with st.expander(f"Visual {idx + 1}", expanded=idx < 2):
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_input(f"Title #{idx+1}", value=f"KPI Visual {idx+1}", key=f"title_{idx}")
            dataset_alias = st.selectbox(
                f"Dataset alias #{idx+1}",
                options=all_aliases if all_aliases else ["manual_dataset"],
                key=f"dataset_{idx}",
            )
            vtype = st.selectbox(f"Visual type #{idx+1}", options=visual_types, key=f"vtype_{idx}")

        cols = dataset_cols.get(dataset_alias, [])
        axis_options = cols if cols else ["category", "value", "segment", "date"]

        with c2:
            x_axis = st.selectbox(f"X-axis #{idx+1}", options=axis_options, key=f"x_{idx}")
            y_axis = st.selectbox(f"Y-axis #{idx+1}", options=axis_options, index=min(1, len(axis_options) - 1), key=f"y_{idx}")
            color_by = st.selectbox(f"Color / segment #{idx+1}", options=[""] + axis_options, key=f"c_{idx}")

        visuals.append(
            {
                "title": title,
                "dataset_alias": dataset_alias,
                "visual_type": vtype,
                "x_axis": x_axis,
                "y_axis": y_axis,
                "color_by": color_by,
            }
        )

kpis = [k.strip() for k in kpi_text.splitlines() if k.strip()]
raw_tables = [t.strip() for t in raw_full.splitlines() if t.strip()]
target_tables = [t.strip() for t in target_full.splitlines() if t.strip()]

if raw_selected:
    raw_tables.extend(raw_selected)
if target_selected:
    target_tables.extend(target_selected)

raw_tables = sorted(set(raw_tables))
target_tables = sorted(set(target_tables))

manifest = build_bi_manifest(
    pipeline_name=pipeline_name,
    raw_tables=raw_tables,
    target_tables=target_tables,
    kpis=kpis,
    visuals=visuals,
)

st.divider()
st.subheader("4) Generate outputs")
mode = st.radio(
    "Choose output mode",
    ["Python visuals", "JavaScript HTML visuals", "Power BI package"],
    horizontal=True,
)

if mode == "Python visuals":
    py_code = generate_python_visual_app(manifest)
    st.code(py_code, language="python")
    st.download_button(
        "Download Python visual app",
        data=py_code.encode("utf-8"),
        file_name="auto_bi_visual_app.py",
        mime="text/x-python",
    )

elif mode == "JavaScript HTML visuals":
    html = generate_js_visual_html(manifest)
    st.download_button(
        "Download JavaScript HTML",
        data=html.encode("utf-8"),
        file_name="auto_bi_visuals.html",
        mime="text/html",
    )

    st.markdown("Preview")
    st.components.v1.html(html, height=760, scrolling=True)

else:
    st.info("Power BI .pbix binaries are not directly generated here. Download a complete handoff package for automation.")

    handoff = build_powerbi_handoff_zip(manifest)
    st.download_button(
        "Download Power BI handoff package",
        data=handoff,
        file_name="powerbi_handoff_package.zip",
        mime="application/zip",
    )

st.divider()
st.subheader("Manifest")
st.code(json.dumps(manifest, indent=2), language="json")

uploaded = st.file_uploader("Optional: Upload CSV to preview one visual in Streamlit", type=["csv"])
if uploaded:
    try:
        df = pd.read_csv(uploaded)
        st.success(f"Loaded preview data with {len(df)} rows")
        if visuals:
            v = visuals[0]
            fig = px.bar(
                df,
                x=v["x_axis"] if v["x_axis"] in df.columns else df.columns[0],
                y=v["y_axis"] if v["y_axis"] in df.columns else df.columns[min(1, len(df.columns)-1)],
                color=v["color_by"] if v["color_by"] in df.columns and v["color_by"] else None,
                title=f"Preview: {v['title']}",
                template="plotly_white",
            )
            fig.update_layout(height=460)
            st.plotly_chart(fig, use_container_width=True)
    except Exception as ex:
        st.error(f"Could not parse CSV: {ex}")
