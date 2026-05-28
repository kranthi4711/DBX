import streamlit as st
from graphviz import Digraph

from model import Pipeline, Source, Step
from uc import UCBrowser
from ops import OP_REGISTRY, list_operations, resolve_operation
from codegen import generate_pyspark_code
from excel_export import export_pipeline_to_excel
from export_zip import build_export_zip

st.set_page_config(page_title="Databricks Pipeline Designer", layout="wide")

st.title("Databricks PySpark Pipeline Designer")
st.caption("Client-facing • Dropdown-driven operations • Unity Catalog sources • Export: Diagram + PySpark + Excel + JSON")

# ---------------- state ----------------
if "pipeline" not in st.session_state:
    st.session_state.pipeline = Pipeline(name="New Pipeline")

if "sources" not in st.session_state:
    st.session_state.sources = []  # list[Source]

# alias -> full table name (for sources) or '__INTERMEDIATE__'
if "datasets" not in st.session_state:
    st.session_state.datasets = {}

# alias -> list of column names (best-effort metadata propagation without execution)
if "dataset_cols" not in st.session_state:
    st.session_state.dataset_cols = {}

browser = UCBrowser()


def _get_cols(alias: str):
    # Prefer propagated cols
    if alias in st.session_state.dataset_cols:
        return st.session_state.dataset_cols[alias]
    # If it's a source, fetch from UC
    full = st.session_state.datasets.get(alias, "")
    if full and full.count(".") == 2:
        try:
            cols = browser.columns_from_fullname(full)
        except Exception:
            cols = []
        st.session_state.dataset_cols[alias] = cols
        return cols
    return []


def _propagate_cols(step: Step):
    """Best-effort output column propagation for dropdown UX (no execution)."""
    in1 = _get_cols(step.input1)
    in2 = _get_cols(step.input2) if step.input2 else []
    op = step.operation
    p = step.params or {}

    out_cols = list(in1)

    if op == "Select Columns":
        out_cols = [c for c in p.get("columns", []) if c]

    elif op == "Drop Columns":
        drops = set(p.get("columns", []) or [])
        out_cols = [c for c in out_cols if c not in drops]

    elif op == "Rename Columns":
        mp = p.get("mappings", []) or []
        rename = {m.get("from"): m.get("to") for m in mp if m.get("from") and m.get("to")}
        out_cols = [rename.get(c, c) for c in out_cols]

    elif op == "Create/Update Column":
        newc = p.get("new_column")
        if newc:
            if newc not in out_cols:
                out_cols = out_cols + [newc]

    elif op == "Join":
        # naive: concat both, de-dup, prefix collisions from right
        if in2:
            left = list(in1)
            right = []
            left_set = set(left)
            for c in in2:
                if c in left_set:
                    right.append(f"right_{c}")
                else:
                    right.append(c)
            out_cols = left + right

    elif op == "Union":
        # union by name: union columns, keep stable order
        out_cols = list(dict.fromkeys(list(in1) + list(in2)))

    elif op in ["Aggregate", "Pivot"]:
        # unknown agg output precisely; best effort from params
        gb = p.get("group_by", []) or []
        aggs = p.get("aggs", []) or []
        agg_cols = [a.get("alias") for a in aggs if a.get("alias")] or []
        if op == "Aggregate":
            out_cols = gb + agg_cols
        else:
            # pivot columns depend on data values; keep gb + placeholder
            out_cols = gb + ["<pivot_columns>"]

    # Others: keep same columns
    st.session_state.dataset_cols[step.output_alias] = out_cols


# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Pipeline")
    st.session_state.pipeline.name = st.text_input("Name", st.session_state.pipeline.name)
    st.session_state.pipeline.description = st.text_area("Description", st.session_state.pipeline.description, height=90)

    st.divider()
    st.subheader("Output (logical target; client types schema)")
    st.session_state.pipeline.output_catalog = st.text_input("Output catalog", value=st.session_state.pipeline.output_catalog)
    st.session_state.pipeline.output_schema = st.text_input("Output schema", value=st.session_state.pipeline.output_schema)
    st.session_state.pipeline.output_table = st.text_input("Output table", value=st.session_state.pipeline.output_table)

    st.caption("Note: This app **does not execute** writes. It generates code, documentation, and a diagram.")

# ---------------- tabs ----------------
t_build, t_graph, t_code, t_docs = st.tabs(["Build", "Diagram", "Code Preview", "Export"])

# ============================================================
# BUILD
# ============================================================
with t_build:
    st.subheader("1) Add Source Delta Tables")

    c1, c2 = st.columns([2, 1])
    with c1:
        mode = st.radio("Source selection", ["Browse Unity Catalog", "Type full name"], horizontal=True)
    with c2:
        alias = st.text_input("Dataset alias", value=f"src{len(st.session_state.sources)+1}")

    full_name = ""
    if mode == "Browse Unity Catalog":
        colA, colB, colC = st.columns(3)
        with colA:
            catalog = st.selectbox("Catalog", browser.catalogs())
        with colB:
            schema = st.selectbox("Schema", browser.schemas(catalog))
        with colC:
            table = st.selectbox("Table", browser.tables(catalog, schema))
        if catalog and schema and table:
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
            st.session_state.dataset_cols[alias] = browser.columns_from_fullname(full_name)
            st.success(f"Added source {alias} → {full_name}")

    if st.session_state.sources:
        st.write("Current sources")
        st.json([s.to_dict() for s in st.session_state.sources])

    st.divider()
    st.subheader("2) Add Step (Dropdown-driven transformations/actions)")

    if not st.session_state.datasets:
        st.info("Add at least one source dataset first.")
    else:
        datasets = list(st.session_state.datasets.keys())
        cA, cB = st.columns(2)
        with cA:
            input1 = st.selectbox("Input dataset", datasets, key="input1")
        with cB:
            op_label = st.selectbox("Operation", list_operations(), key="op")

        op_name = resolve_operation(op_label)
        op_def = OP_REGISTRY[op_name]

        input2 = ""
        if op_def.get("needs_second_input"):
            input2 = st.selectbox("Second input dataset", datasets, key="input2")

        cols1 = _get_cols(input1)
        cols2 = _get_cols(input2) if input2 else []

        params = op_def["ui"](cols1=cols1, cols2=cols2)

        st.markdown("**Output alias**")
        out_alias = st.text_input("Output alias", value=f"step{len(st.session_state.pipeline.steps)+1}")

        st.markdown("**Optional: action(s) for preview in code**")
        actions = st.multiselect("Actions", ["none", "printSchema", "explain", "show(20)", "count"], default=["none"])
        actions = [a for a in actions if a != "none"]

        if st.button("Add Step", type="primary", key="add_step"):
            if not out_alias:
                st.error("Output alias is required")
            else:
                step = Step(
                    input1=input1,
                    input2=input2,
                    operation=op_name,
                    params=params,
                    output_alias=out_alias,
                    actions=actions,
                )
                st.session_state.pipeline.steps.append(step)

                # register output alias for chaining
                st.session_state.datasets[out_alias] = "__INTERMEDIATE__"
                _propagate_cols(step)
                st.success(f"Added step {op_name} → {out_alias}")

        st.divider()
        st.subheader("Current steps")
        if st.session_state.pipeline.steps:
            for i, s in enumerate(st.session_state.pipeline.steps, start=1):
                with st.expander(f"Step {i}: {s.operation}"):
                    st.json(s.to_dict())
                    st.caption(f"Inferred output columns: {st.session_state.dataset_cols.get(s.output_alias, [])}")
        else:
            st.write("No steps yet")

        st.divider()
        st.subheader("3) Reset")
        r1, r2 = st.columns(2)
        with r1:
            if st.button("Reset pipeline"):
                st.session_state.pipeline = Pipeline(name="New Pipeline")
                st.session_state.sources = []
                st.session_state.datasets = {}
                st.session_state.dataset_cols = {}
                st.toast("Reset complete")
        with r2:
            st.caption("Reset clears sources + steps")

# ============================================================
# DIAGRAM
# ============================================================
with t_graph:
    st.subheader("Operational Diagram (Source → Transformation → Output)")
    if not st.session_state.pipeline.steps:
        st.info("Add sources and steps to view the diagram.")
    else:
        dot = Digraph(graph_attr={"rankdir": "LR"})

        for src in st.session_state.sources:
            dot.node(src.alias, f"{src.alias}\n{src.full_name}", shape="box")

        for idx, step in enumerate(st.session_state.pipeline.steps, start=1):
            op_node = f"op{idx}"
            dot.node(op_node, step.operation, shape="ellipse")
            dot.edge(step.input1, op_node)
            if step.input2:
                dot.edge(step.input2, op_node)
            dot.node(step.output_alias, step.output_alias, shape="box", style="rounded")
            dot.edge(op_node, step.output_alias)

        final_alias = st.session_state.pipeline.final_output_alias()
        target = st.session_state.pipeline.output_fullname()
        if final_alias and target:
            dot.node("TARGET", f"OUTPUT TABLE\n{target}", shape="box", color="blue")
            dot.edge(final_alias, "TARGET", label="export")

        st.graphviz_chart(dot)

# ============================================================
# CODE PREVIEW
# ============================================================
with t_code:
    st.subheader("Generated PySpark Code (Preview only)")
    if not st.session_state.pipeline.steps:
        st.info("Add sources and steps to preview code.")
    else:
        code = generate_pyspark_code(
            pipeline=st.session_state.pipeline,
            sources=st.session_state.sources,
        )
        st.code(code, language="python")

# ============================================================
# EXPORT
# ============================================================
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
