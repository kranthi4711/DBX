"""Operation registry for dropdown-driven Databricks pipeline design.

Design goal: cover a broad, client-friendly set of **common** PySpark DataFrame transformations
and preview actions. The UI collects parameters (dropdowns/text) and we generate PySpark code.

Note: "All possible transformations" in PySpark is effectively unlimited. This registry includes
widely used operations and provides an easy extension pattern.
"""

import streamlit as st

# ---------------- UI builders ----------------

def select_columns_ui(cols1, cols2=None):
    return {"columns": st.multiselect("Columns", cols1, default=cols1[: min(10, len(cols1))])}


def filter_ui(cols1, cols2=None):
    c, o, v = st.columns([3, 2, 3])
    with c:
        col = st.selectbox("Column", cols1)
    with o:
        op = st.selectbox("Operator", ["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "LIKE", "RLIKE", "IS NULL", "IS NOT NULL"])
    with v:
        if op in ["IS NULL", "IS NOT NULL"]:
            st.text_input("Value", value="(not required)", disabled=True)
            val = None
        elif op in ["IN", "NOT IN"]:
            val = st.text_input("Values (comma separated)", placeholder="A,B,C")
        else:
            val = st.text_input("Value")
    return {"column": col, "operator": op, "value": val}


def sql_where_ui(cols1, cols2=None):
    st.caption("SQL WHERE condition, e.g. `amount > 1000 AND status = 'A'`")
    return {"condition": st.text_input("Condition")}


def join_ui(cols1, cols2):
    how = st.selectbox("Join type", ["inner", "left", "right", "full", "left_semi", "left_anti", "cross"])
    common = sorted(list(set(cols1).intersection(set(cols2))))
    keys = st.multiselect("Join keys", common if common else cols1)
    map_keys = st.toggle("Map keys when names differ", value=False)
    mapping = []
    if map_keys and keys:
        for k in keys:
            mapping.append({"s1": k, "s2": st.selectbox(f"Source2 column for {k}", cols2, key=f"map_{k}")})
    return {"how": how, "keys": keys, "map_keys": map_keys, "key_mapping": mapping}


def union_ui(cols1, cols2=None):
    return {"by_name": st.toggle("Union by name", value=True),
            "allow_missing_columns": st.toggle("Allow missing columns", value=False)}


def aggregate_ui(cols1, cols2=None):
    group_by = st.multiselect("Group by", cols1)
    st.caption("Add aggregations")
    if "_aggs" not in st.session_state:
        st.session_state._aggs = []

    a1, a2, a3 = st.columns([3, 2, 2])
    with a1:
        col = st.selectbox("Agg column", cols1, key="agg_col")
    with a2:
        func = st.selectbox("Function", ["count", "sum", "avg", "min", "max", "countDistinct"], key="agg_func")
    with a3:
        alias = st.text_input("Alias", value=f"{func}_{col}")

    if st.button("Add aggregation"):
        st.session_state._aggs.append({"column": col, "func": func, "alias": alias})

    if st.session_state._aggs:
        st.write(st.session_state._aggs)

    return {"group_by": group_by, "aggs": st.session_state._aggs}


def pivot_ui(cols1, cols2=None):
    gb = st.multiselect("Group by", cols1)
    pivot_col = st.selectbox("Pivot column", cols1)
    values_col = st.selectbox("Values column", cols1)
    agg = st.selectbox("Agg", ["sum", "avg", "max", "min", "count"])
    return {"group_by": gb, "pivot_col": pivot_col, "values_col": values_col, "agg": agg}


def withcolumn_ui(cols1, cols2=None):
    new_col = st.text_input("New/Existing column name")
    mode = st.selectbox("Builder", ["Simple", "Case When", "Concat", "Math", "SQL Expression"])

    p = {"new_column": new_col, "expr_mode": mode}

    if mode == "Simple":
        p["source_col"] = st.selectbox("Source column", cols1)
        p["simple_op"] = st.selectbox("Operation", ["copy", "upper", "lower", "trim", "length"])

    elif mode == "Concat":
        p["concat_cols"] = st.multiselect("Columns", cols1)
        p["delimiter"] = st.text_input("Delimiter", value="_")

    elif mode == "Math":
        p["left_col"] = st.selectbox("Left column", cols1)
        p["math_op"] = st.selectbox("Operator", ["+", "-", "*", "/", "%"])
        p["right_value"] = st.text_input("Right (number or column)")

    elif mode == "Case When":
        p["when_col"] = st.selectbox("When column", cols1)
        p["when_op"] = st.selectbox("When operator", ["=", "!=", ">", ">=", "<", "<=", "LIKE", "IN", "RLIKE"])
        p["when_val"] = st.text_input("When value")
        p["then_val"] = st.text_input("Then value")
        p["else_val"] = st.text_input("Else value")

    elif mode == "SQL Expression":
        st.caption("Spark SQL expression, e.g. `amount * 1.2` or `coalesce(colA, 'x')`")
        p["sql_expr"] = st.text_input("Expression")

    return p


def rename_ui(cols1, cols2=None):
    st.caption("Add rename mappings")
    if "_renames" not in st.session_state:
        st.session_state._renames = []

    c1, c2 = st.columns(2)
    with c1:
        old = st.selectbox("From", cols1, key="rn_old")
    with c2:
        new = st.text_input("To", key="rn_new")

    if st.button("Add rename"):
        if new:
            st.session_state._renames.append({"from": old, "to": new})

    st.write(st.session_state._renames)
    return {"mappings": st.session_state._renames}


def cast_ui(cols1, cols2=None):
    col = st.selectbox("Column", cols1)
    dtype = st.selectbox("Type", ["string", "int", "bigint", "double", "decimal(18,2)", "boolean", "date", "timestamp"])
    return {"column": col, "type": dtype}


def drop_ui(cols1, cols2=None):
    return {"columns": st.multiselect("Columns to drop", cols1)}


def fillna_ui(cols1, cols2=None):
    mode = st.selectbox("Fill mode", ["Single value", "Per-column"])
    if mode == "Single value":
        val = st.text_input("Value")
        subset = st.multiselect("Subset (optional)", cols1)
        return {"mode": mode, "value": val, "subset": subset}

    if "_fills" not in st.session_state:
        st.session_state._fills = []
    c1, c2 = st.columns(2)
    with c1:
        col = st.selectbox("Column", cols1, key="fill_col")
    with c2:
        val = st.text_input("Value", key="fill_val")

    if st.button("Add fill"):
        st.session_state._fills.append({"column": col, "value": val})
    st.write(st.session_state._fills)
    return {"mode": mode, "fills": st.session_state._fills}


def dropna_ui(cols1, cols2=None):
    how = st.selectbox("How", ["any", "all"])
    subset = st.multiselect("Subset", cols1)
    thresh = st.number_input("Threshold (optional)", min_value=0, value=0)
    return {"how": how, "subset": subset, "thresh": int(thresh)}


def dedup_ui(cols1, cols2=None):
    subset = st.multiselect("Subset (optional)", cols1)
    return {"subset": subset}


def distinct_ui(cols1, cols2=None):
    return {}


def limit_ui(cols1, cols2=None):
    return {"n": int(st.number_input("Rows", min_value=1, value=100))}


def orderby_ui(cols1, cols2=None):
    return {"columns": st.multiselect("Columns", cols1),
            "direction": st.selectbox("Direction", ["asc", "desc"])}


def sample_ui(cols1, cols2=None):
    frac = st.slider("Fraction", min_value=0.0, max_value=1.0, value=0.1)
    seed = st.number_input("Seed", min_value=0, value=42)
    return {"fraction": float(frac), "seed": int(seed)}


def repartition_ui(cols1, cols2=None):
    n = st.number_input("Partitions", min_value=1, value=200)
    cols = st.multiselect("Partition columns (optional)", cols1)
    return {"n": int(n), "columns": cols}


def coalesce_ui(cols1, cols2=None):
    return {"n": int(st.number_input("Partitions", min_value=1, value=50))}


def explode_ui(cols1, cols2=None):
    col = st.selectbox("Array/Map column", cols1)
    out = st.text_input("Output column", value="exploded")
    return {"column": col, "out": out}


def split_ui(cols1, cols2=None):
    col = st.selectbox("Column", cols1)
    pattern = st.text_input("Pattern", value=",")
    out = st.text_input("Output column", value=f"{col}_arr")
    return {"column": col, "pattern": pattern, "out": out}


def regexp_replace_ui(cols1, cols2=None):
    col = st.selectbox("Column", cols1)
    pattern = st.text_input("Regex pattern")
    repl = st.text_input("Replacement", value="")
    out = st.text_input("Output column", value=col)
    return {"column": col, "pattern": pattern, "replacement": repl, "out": out}


def date_add_ui(cols1, cols2=None):
    col = st.selectbox("Date column", cols1)
    days = st.number_input("Days", value=1)
    out = st.text_input("Output column", value=f"{col}_plus_days")
    return {"column": col, "days": int(days), "out": out}


def window_rank_ui(cols1, cols2=None):
    part = st.multiselect("Partition by", cols1)
    order = st.multiselect("Order by", cols1)
    func = st.selectbox("Window function", ["row_number", "rank", "dense_rank"])
    out = st.text_input("Output column", value=func)
    return {"partition_by": part, "order_by": order, "func": func, "out": out}


def sql_select_ui(cols1, cols2=None):
    st.caption("SQL SELECT expression list for selectExpr, e.g. `id, upper(name) as name_u`")
    return {"exprs": st.text_area("Select expressions", height=90)}


# ---------------- registry ----------------

OP_REGISTRY = {
    # Projection
    "Select Columns": {"category": "Projection", "needs_second_input": False, "ui": select_columns_ui},

    # Row operations
    "Filter": {"category": "Row", "needs_second_input": False, "ui": filter_ui},
    "SQL Where": {"category": "Row", "needs_second_input": False, "ui": sql_where_ui},
    "Distinct": {"category": "Row", "needs_second_input": False, "ui": distinct_ui},
    "Limit": {"category": "Row", "needs_second_input": False, "ui": limit_ui},
    "Order By": {"category": "Row", "needs_second_input": False, "ui": orderby_ui},
    "Sample": {"category": "Row", "needs_second_input": False, "ui": sample_ui},

    # Combine
    "Join": {"category": "Combine", "needs_second_input": True, "ui": join_ui},
    "Union": {"category": "Combine", "needs_second_input": True, "ui": union_ui},

    # Aggregations
    "Aggregate": {"category": "Aggregate", "needs_second_input": False, "ui": aggregate_ui},
    "Pivot": {"category": "Aggregate", "needs_second_input": False, "ui": pivot_ui},

    # Column operations
    "Create/Update Column": {"category": "Column", "needs_second_input": False, "ui": withcolumn_ui},
    "Rename Columns": {"category": "Column", "needs_second_input": False, "ui": rename_ui},
    "Cast Column": {"category": "Column", "needs_second_input": False, "ui": cast_ui},
    "Drop Columns": {"category": "Column", "needs_second_input": False, "ui": drop_ui},

    # Data quality
    "Fill Nulls": {"category": "Data Quality", "needs_second_input": False, "ui": fillna_ui},
    "Drop Nulls": {"category": "Data Quality", "needs_second_input": False, "ui": dropna_ui},
    "Drop Duplicates": {"category": "Data Quality", "needs_second_input": False, "ui": dedup_ui},

    # Performance
    "Repartition": {"category": "Performance", "needs_second_input": False, "ui": repartition_ui},
    "Coalesce": {"category": "Performance", "needs_second_input": False, "ui": coalesce_ui},

    # Complex types / Strings / Dates / Windows
    "Explode": {"category": "Complex Types", "needs_second_input": False, "ui": explode_ui},
    "Split": {"category": "Complex Types", "needs_second_input": False, "ui": split_ui},
    "Regexp Replace": {"category": "String", "needs_second_input": False, "ui": regexp_replace_ui},
    "Date Add": {"category": "Date/Time", "needs_second_input": False, "ui": date_add_ui},
    "Window Rank": {"category": "Window", "needs_second_input": False, "ui": window_rank_ui},

    # Advanced
    "SQL Select": {"category": "Advanced", "needs_second_input": False, "ui": sql_select_ui},
}


def list_operations():
    return [f"{d['category']} • {op}" for op, d in OP_REGISTRY.items()]


def resolve_operation(label: str) -> str:
    return label.split("•", 1)[1].strip() if "•" in label else label
