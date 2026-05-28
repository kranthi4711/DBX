import streamlit as st
from graphviz import Digraph

from model import Pipeline, Source, Step, OutputTarget
from uc import UCBrowser
from ops import OP_REGISTRY, list_operations, resolve_operation
from codegen import generate_pyspark_code
from excel_export import export_pipeline_to_excel
from export_zip import build_export_zip
from kpi_visualizations import render_kpi_visual_tab

st.set_page_config(page_title="Databricks Pipeline Designer", layout="wide")

st.title("Databricks PySpark Pipeline Designer")
st.caption("Client-facing • Dropdown-driven operations • Unity Catalog sources • Export: Diagram + PySpark + Excel + JSON")


# =============================================================================
# Session state initialization
# =============================================================================
if "pipeline" not in st.session_state:
    st.session_state.pipeline = Pipeline(name="New Pipeline")

if "sources" not in st.session_state:
    st.session_state.sources = []

if "datasets" not in st.session_state:
    # alias -> full table name for sources, '__INTERMEDIATE__' for derived
    st.session_state.datasets = {}

if "dataset_cols" not in st.session_state:
    # alias -> inferred columns
    st.session_state.dataset_cols = {}

if "edit_idx" not in st.session_state:
    st.session_state.edit_idx = None

# Demo state
if "demo_excel_bytes" not in st.session_state:
    st.session_state.demo_excel_bytes = None

if "demo_sheet" not in st.session_state:
    st.session_state.demo_sheet = None

if "browser" not in st.session_state:
    st.session_state.browser = None


# =============================================================================
# Helper: Create/refresh browser safely (LIVE vs DEMO)
# =============================================================================
def _refresh_browser():
    """
    Creates a single browser instance and stores it in session_state.
    - If demo_excel_bytes is set -> DEMO mode forced
    - Else -> LIVE mode (Databricks Spark UC)
    """
    if st.session_state.demo_excel_bytes:
        # Force demo mode even in Databricks
        try:
            st.session_state.browser = UCBrowser(
                demo_excel=st.session_state.demo_excel_bytes,
                force_demo=True,
                demo_sheet=st.session_state.demo_sheet if st.session_state.demo_sheet is not None else 0,
            )
        except TypeError:
            # Backward compatibility: if older uc.py is still being imported
            st.error("Your uc.py does not support demo_excel/force_demo yet. Please update uc.py first.")
            st.session_state.browser = UCBrowser()
    else:
        st.session_state.browser = UCBrowser()


def _get_browser():
    if st.session_state.browser is None:
        _refresh_browser()
    return st.session_state.browser


# =============================================================================
# Helper: Safe selectbox (fixes blank dropdowns due to stale Streamlit state)
# =============================================================================
def safe_selectbox(label: str, options, key: str):
    """
    Streamlit selectbox can appear blank when:
    - options change between reruns, but the stored selected value is no longer valid.
    This wrapper resets the key if the stored value isn't in options.
    """
    options = list(options) if options is not None else []
    if key in st.session_state and st.session_state[key] not in options:
        st.session_state.pop(key, None)
    if not options:
        # Render disabled selectbox for UX
        return st.selectbox(label, ["<empty>"], key=key, disabled=True)
    return st.selectbox(label, options, key=key)


# =============================================================================
# Helper: Column resolution and propagation
# =============================================================================
def _get_cols(browser: UCBrowser, alias: str):
    if alias in st.session_state.dataset_cols:
        return st.session_state.dataset_cols[alias]

    full = st.session_state.datasets.get(alias, "")
    if full and full.count(".") == 2:
        try:
            cols = browser.columns_from_fullname(full)
        except Exception:
            cols = []
        st.session_state.dataset_cols[alias] = cols
        return cols
    return []


def _propagate_cols(step: Step, browser: UCBrowser):
    """
    Best-effort propagation without execution.
    """
    in1 = _get_cols(browser, step.input1)
    in2 = _get_cols(browser, step.input2) if step.input2 else []
    op = step.operation
    p = step.params or {}

    out_cols = list(in1)

    if op == "Select Columns":
        out_cols = [c for c in (p.get("columns", []) or []) if c]

    elif op == "Drop Columns":
        drops = set(p.get("columns", []) or [])
        out_cols = [c for c in out_cols if c not in drops]

    elif op == "Rename Columns":
        mp = p.get("mappings", []) or []
        rename = {m.get("from"): m.get("to") for m in mp if m.get("from") and m.get("to")}
        out_cols = [rename.get(c, c) for c in out_cols]

    elif op == "Create/Update Column":
        newc = p.get("new_column")
        if newc and newc not in out_cols:
            out_cols.append(newc)

    elif op == "Join":
        # naive merge with collision prefix
        if in2:
            left = list(in1)
            left_set = set(left)
            right = [f"right_{c}" if c in left_set else c for c in in2]
            out_cols = left + right

    elif op == "Union":
        out_cols = list(dict.fromkeys(list(in1) + list(in2)))

    elif op in ["Aggregate", "Pivot"]:
        gb = p.get("group_by", []) or []
        aggs = p.get("aggs", []) or []
        agg_cols = [a.get("alias") for a in aggs if a.get("alias")] or []
        out_cols = gb + (agg_cols if op == "Aggregate" else ["<pivot_columns>"])

    st.session_state.dataset_cols[step.output_alias] = out_cols


def _rebuild_datasets_after_steps(browser: UCBrowser):
    """
    Rebuild alias registry from sources then sequentially add step outputs.
    """
    st.session_state.datasets = {s.alias: s.full_name for s in st.session_state.sources}

    # refresh source cols
    for s in st.session_state.sources:
        try:
            st.session_state.dataset_cols[s.alias] = browser.columns_from_fullname(s.full_name)
        except Exception:
            st.session_state.dataset_cols[s.alias] = []

    # remove derived cols, keep only sources
    keep = {k: v for k, v in st.session_state.dataset_cols.items() if k in st.session_state.datasets}
    st.session_state.dataset_cols = keep

    for step in st.session_state.pipeline.steps:
        st.session_state.datasets[step.output_alias] = "__INTERMEDIATE__"
        _propagate_cols(step, browser)


def _delete_step(idx: int, browser: UCBrowser):
    st.session_state.pipeline.steps.pop(idx)
    _rebuild_datasets_after_steps(browser)
    aliases = set(st.session_state.datasets.keys())
    st.session_state.pipeline.outputs = [o for o in st.session_state.pipeline.outputs if o.from_alias in aliases]


def _delete_last_step(browser: UCBrowser):
    if st.session_state.pipeline.steps:
        _delete_step(len(st.session_state.pipeline.steps) - 1, browser)


# =============================================================================
# Sidebar: Demo Excel + Multiple output targets
# =============================================================================
with st.sidebar:
    st.header("Pipeline")
    st.session_state.pipeline.name = st.text_input("Name", st.session_state.pipeline.name)
    st.session_state.pipeline.description = st.text_area("Description", st.session_state.pipeline.description, height=90)

    st.divider()
    st.subheader("Unity Catalog mode")

    uploaded = st.file_uploader("Upload Demo UC Excel (.xlsx)", type=["xlsx"])

    # Sheet picker only if Excel uploaded
    if uploaded:
        try:
            import pandas as pd
            xls = pd.ExcelFile(uploaded.getvalue(), engine="openpyxl")
            sheet = st.selectbox("Select sheet", xls.sheet_names, key="demo_sheet_picker")
        except Exception:
            sheet = 0
            st.warning("Unable to list sheets. Defaulting to first sheet (0).")

        colA, colB = st.columns(2)

        with colA:
            if st.button("Activate Demo Excel", type="primary"):
                st.session_state.demo_excel_bytes = uploaded.getvalue()
                st.session_state.demo_sheet = sheet
                st.session_state.browser = None  # force recreate
                st.session_state.uc_catalog = None if "uc_catalog" in st.session_state else None
                st.session_state.uc_schema = None if "uc_schema" in st.session_state else None
                st.session_state.uc_table = None if "uc_table" in st.session_state else None
                st.rerun()

        with colB:
            if st.button("Disable Demo"):
                st.session_state.demo_excel_bytes = None
                st.session_state.demo_sheet = None
                st.session_state.browser = None  # force recreate
                st.session_state.uc_catalog = None if "uc_catalog" in st.session_state else None
                st.session_state.uc_schema = None if "uc_schema" in st.session_state else None
                st.session_state.uc_table = None if "uc_table" in st.session_state else None
                st.rerun()

    # Ensure browser exists for mode indicator
    browser = _get_browser()

    if hasattr(browser, "is_demo") and browser.is_demo():
        st.success("Mode: DEMO (Excel-driven)")
    else:
        st.info("Mode: LIVE (Databricks Unity Catalog)")

    st.divider()
    st.subheader("Output targets (multiple)")
    st.caption("Add one or more Unity Catalog tables to write (exported as **commented** code).")

    all_aliases = list(st.session_state.datasets.keys()) if st.session_state.datasets else []
    from_alias = st.selectbox(
        "Write from dataset alias",
        all_aliases if all_aliases else ["<no datasets yet>"],
        disabled=not bool(all_aliases),
        key="out_from_alias",
    )

    oc = st.text_input("Target catalog", key="out_catalog")
    osch = st.text_input("Target schema", key="out_schema")
    otbl = st.text_input("Target table", key="out_table")
    mode = st.selectbox("Write mode", ["overwrite", "append"], key="out_mode")

    if st.button("Add output target"):
        if not all_aliases:
            st.error("Add a source and at least one step first.")
        elif not from_alias or from_alias == "<no datasets yet>":
            st.error("Select a dataset alias")
        elif not (oc and osch and otbl):
            st.error("Enter catalog, schema and table")
        else:
            st.session_state.pipeline.outputs.append(
                OutputTarget(from_alias=from_alias, catalog=oc, schema=osch, table=otbl, mode=mode)
            )
            st.success("Output target added")

    if st.session_state.pipeline.outputs:
        st.markdown("**Current targets**")
        for i, o in enumerate(list(st.session_state.pipeline.outputs)):
            cols = st.columns([5, 1])
            with cols[0]:
                st.write(f"{i+1}. {o.from_alias} → {o.full_name()} ({o.mode})")
            with cols[1]:
                if st.button("🗑", key=f"del_out_{i}"):
                    st.session_state.pipeline.outputs.pop(i)
                    st.rerun()

    st.divider()
    st.caption("Note: This app is **preview/export only** (no execution, no writes).")


# =============================================================================
# Tabs
# =============================================================================
t_build, t_graph, t_code, t_kpi, t_docs = st.tabs([
    "Build",
    "Diagram",
    "Code Preview",
    "Visualizations/KPI's",
    "Export",
])


# =============================================================================
# BUILD TAB
# =============================================================================
with t_build:
    browser = _get_browser()

    st.subheader("1) Add Source Delta Tables")

    c1, c2 = st.columns([2, 1])
    with c1:
        src_mode = st.radio("Source selection", ["Browse Unity Catalog", "Type full name"], horizontal=True)
    with c2:
        alias = st.text_input("Dataset alias", value=f"src{len(st.session_state.sources)+1}")

    full_name = ""

    if src_mode == "Browse Unity Catalog":
        # ✅ Use safe_selectbox to avoid blank dropdown due to stale state
        colA, colB, colC = st.columns(3)

        with colA:
            cats = browser.catalogs()
            catalog = safe_selectbox("Catalog", cats, key="uc_catalog")

        with colB:
            schemas = browser.schemas(catalog) if catalog and catalog != "<empty>" else []
            schema = safe_selectbox("Schema", schemas, key="uc_schema")

        with colC:
            tables = browser.tables(catalog, schema) if schema and schema != "<empty>" else []
            table = safe_selectbox("Table", tables, key="uc_table")

        if catalog and schema and table and "<empty>" not in (catalog, schema, table):
            full_name = f"{catalog}.{schema}.{table}"

    else:
        full_name = st.text_input("Source table (catalog.schema.table)", placeholder="main.sales.orders")

    if st.button("Add Source", type="primary"):
        if not alias:
            st.error("Alias is required")
        elif not full_name or full_name.count(".") != 2:
            st.error("Source must be in catalog.schema.table format")
        else:
            src = Source(alias=alias, full_name=full_name)
            st.session_state.sources.append(src)
            st.session_state.datasets[alias] = full_name
            try:
                st.session_state.dataset_cols[alias] = browser.columns_from_fullname(full_name)
            except Exception:
                st.session_state.dataset_cols[alias] = []
            st.success(f"Added source {alias} → {full_name}")

    if st.session_state.sources:
        st.write("Current sources")
        st.json([s.to_dict() for s in st.session_state.sources])

    st.divider()
    st.subheader("2) Add / Edit Step")

    if not st.session_state.datasets:
        st.info("Add at least one source dataset first.")
    else:
        datasets = list(st.session_state.datasets.keys())
        edit_mode = st.session_state.edit_idx is not None
        step0 = st.session_state.pipeline.steps[st.session_state.edit_idx] if edit_mode else None

        if edit_mode:
            st.warning(f"Editing Step {st.session_state.edit_idx + 1}. Update and click **Save Changes**.")

        cA, cB = st.columns(2)
        with cA:
            input1_default = step0.input1 if step0 else datasets[0]
            input1 = st.selectbox("Input dataset", datasets, index=datasets.index(input1_default), key="step_input1")
        with cB:
            op_labels = list_operations()
            op_default = step0.operation if step0 else resolve_operation(op_labels[0])
            def_label = next((lab for lab in op_labels if resolve_operation(lab) == op_default), op_labels[0])
            op_label = st.selectbox("Operation", op_labels, index=op_labels.index(def_label), key="step_op")

        op_name = resolve_operation(op_label)
        op_def = OP_REGISTRY[op_name]

        input2 = ""
        if op_def.get("needs_second_input"):
            input2_default = step0.input2 if step0 else datasets[0]
            input2 = st.selectbox(
                "Second input dataset", datasets, index=datasets.index(input2_default), key="step_input2"
            )

        cols1 = _get_cols(browser, input1)
        cols2 = _get_cols(browser, input2) if input2 else []

        defaults = step0.params if step0 else {}
        key_prefix = f"{'edit' if edit_mode else 'add'}_{op_name}_"
        params = op_def["ui"](cols1=cols1, cols2=cols2, defaults=defaults, key_prefix=key_prefix)

        out_alias_default = step0.output_alias if step0 else f"step{len(st.session_state.pipeline.steps)+1}"
        out_alias = st.text_input("Output alias", value=out_alias_default, key="step_out")

        actions_default = step0.actions if step0 else []
        actions = st.multiselect(
            "Actions (preview in generated code)",
            ["printSchema", "explain", "show(20)", "count"],
            default=actions_default,
            key="step_actions",
        )

        b1, b2, b3 = st.columns([1, 1, 2])
        with b1:
            if not edit_mode:
                if st.button("Add Step", type="primary"):
                    if not out_alias:
                        st.error("Output alias is required")
                    else:
                        step = Step(input1=input1, input2=input2, operation=op_name, params=params,
                                    output_alias=out_alias, actions=actions)
                        st.session_state.pipeline.steps.append(step)
                        st.session_state.datasets[out_alias] = "__INTERMEDIATE__"
                        _propagate_cols(step, browser)
                        st.success(f"Added step {op_name} → {out_alias}")
            else:
                if st.button("Save Changes", type="primary"):
                    if not out_alias:
                        st.error("Output alias is required")
                    else:
                        idx = st.session_state.edit_idx
                        st.session_state.pipeline.steps[idx] = Step(
                            input1=input1, input2=input2, operation=op_name, params=params,
                            output_alias=out_alias, actions=actions
                        )
                        st.session_state.edit_idx = None
                        _rebuild_datasets_after_steps(browser)
                        st.success("Step updated")
                        st.rerun()

        with b2:
            if edit_mode:
                if st.button("Cancel"):
                    st.session_state.edit_idx = None
                    st.rerun()
            else:
                if st.button("Delete last step"):
                    _delete_last_step(browser)
                    st.rerun()

        with b3:
            st.info("Use Edit/Delete below to manage steps.")

    st.divider()
    st.subheader("3) Current steps (Edit / Delete)")

    if st.session_state.pipeline.steps:
        for i, s in enumerate(list(st.session_state.pipeline.steps)):
            with st.expander(f"Step {i+1}: {s.operation} → {s.output_alias}"):
                st.json(s.to_dict())
                st.caption(f"Inferred output columns: {st.session_state.dataset_cols.get(s.output_alias, [])}")

                c1, c2, c3 = st.columns([1, 1, 4])
                with c1:
                    if st.button("✏️ Edit", key=f"edit_{i}"):
                        st.session_state.edit_idx = i
                        st.rerun()
                with c2:
                    if st.button("🗑 Delete", key=f"del_{i}"):
                        _delete_step(i, browser)
                        st.rerun()
                with c3:
                    st.caption("Edit loads the step into the form above.")
    else:
        st.write("No steps yet")

    st.divider()
    st.subheader("4) Reset")
    if st.button("Reset pipeline"):
        st.session_state.pipeline = Pipeline(name="New Pipeline")
        st.session_state.sources = []
        st.session_state.datasets = {}
        st.session_state.dataset_cols = {}
        st.session_state.edit_idx = None
        st.session_state.pipeline.outputs = []
        st.toast("Reset complete")
        st.rerun()


# =============================================================================
# DIAGRAM TAB
# =============================================================================

def apply_graph_style(dot: Digraph, colorful: bool):
    """
    Apply global styling to the Graphviz Digraph.
    """
    if colorful:
        dot.attr(
            "graph",
            bgcolor="white",
            rankdir="LR",
            splines="spline",
            nodesep="0.35",
            ranksep="0.55",
            fontname="Segoe UI",
            fontsize="12",
        )
        dot.attr(
            "node",
            shape="box",
            style="rounded,filled",
            fontname="Segoe UI",
            fontsize="11",
            color="#334155",         # slate border
            fontcolor="#0f172a",     # slate text
            penwidth="1.2",
        )
        dot.attr(
            "edge",
            color="#475569",         # slate edge
            penwidth="1.1",
            arrowsize="0.8",
            fontname="Segoe UI",
            fontsize="10",
        )
    else:
        dot.attr("graph", rankdir="LR", bgcolor="white")
        dot.attr("node", shape="box", style="rounded", color="black", fontname="Arial", fontsize="11")
        dot.attr("edge", color="black", fontname="Arial", fontsize="10", arrowsize="0.8")


def node_style(kind: str, colorful: bool) -> dict:
    """
    Return node style dict based on node kind.
    kinds: source, op, intermediate, target
    """
    if not colorful:
        # simple B/W shapes
        if kind == "op":
            return {"shape": "ellipse"}
        if kind == "target":
            return {"shape": "box", "style": "rounded,bold"}
        return {"shape": "box", "style": "rounded"}

    # Colorful palette
    palette = {
        "source":      {"fillcolor": "#DBEAFE"},  # blue-100
        "op":          {"fillcolor": "#FEF3C7", "shape": "ellipse"},  # amber-100
        "intermediate":{"fillcolor": "#DCFCE7"},  # green-100
        "target":      {"fillcolor": "#E9D5FF", "color": "#7C3AED", "penwidth": "1.6"},  # purple
    }
    return palette.get(kind, {"fillcolor": "#F1F5F9"})

with t_graph:
    st.subheader("Operational Diagram")

    # ✅ Toggle: Colorful vs Black & White
    colorful = st.toggle("Colorful diagram", value=True)

    if not st.session_state.pipeline.steps:
        st.info("Add sources and steps to view the diagram.")
    else:
        dot = Digraph(graph_attr={"rankdir": "LR"})
        apply_graph_style(dot, colorful)

        # ---- Sources ----
        for src in st.session_state.sources:
            label = f"{src.alias}\n{src.full_name}"
            dot.node(src.alias, label=label, **node_style("source", colorful))

        # ---- Steps ----
        for idx, step in enumerate(st.session_state.pipeline.steps, start=1):
            op_node = f"op{idx}"

            # operation node
            dot.node(op_node, label=step.operation, **node_style("op", colorful))

            # edges from inputs to operation
            dot.edge(step.input1, op_node)
            if step.input2:
                dot.edge(step.input2, op_node)

            # output alias node
            dot.node(step.output_alias, label=step.output_alias, **node_style("intermediate", colorful))
            dot.edge(op_node, step.output_alias)

        # ---- Output targets (multiple) ----
        for j, o in enumerate(st.session_state.pipeline.outputs, start=1):
            tgt = o.full_name()
            if tgt:
                node_id = f"TARGET_{j}"
                label = f"OUTPUT TABLE\n{tgt}\n(mode={o.mode})"
                dot.node(node_id, label=label, **node_style("target", colorful))
                dot.edge(o.from_alias, node_id, label="export")

        st.graphviz_chart(dot)
        
# =============================================================================
# CODE PREVIEW TAB
# =============================================================================
with t_code:
    st.subheader("Generated PySpark Code (Preview only)")

    if not st.session_state.pipeline.steps:
        st.info("Add sources and steps to preview code.")
    else:
        st.code(generate_pyspark_code(st.session_state.pipeline, st.session_state.sources), language="python")


# =============================================================================
# VISUALIZATIONS / KPI TAB
# =============================================================================
with t_kpi:
    render_kpi_visual_tab()


# =============================================================================
# EXPORT TAB
# =============================================================================
with t_docs:
    st.subheader("Export deliverables")

    if not st.session_state.pipeline.steps:
        st.info("Add sources and steps first.")
    else:
        pipeline_dict = st.session_state.pipeline.to_dict()
        pipeline_dict["sources"] = [s.to_dict() for s in st.session_state.sources]

        code = generate_pyspark_code(st.session_state.pipeline, st.session_state.sources)
        excel_bytes = export_pipeline_to_excel(pipeline_dict)

        st.download_button(
            "Download Excel documentation",
            data=excel_bytes,
            file_name=f"{st.session_state.pipeline.name}_documentation.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        zip_bytes = build_export_zip(
            pipeline_name=st.session_state.pipeline.name,
            code_text=code,
            pipeline_json=pipeline_dict,
            excel_bytes=excel_bytes,
        )

        st.download_button(
            "Download ZIP (code + json + excel)",
            data=zip_bytes,
            file_name=f"{st.session_state.pipeline.name}_export.zip",
            mime="application/zip",
        )