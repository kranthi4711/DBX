"""Operation registry for dropdown-driven Databricks pipeline design.

Each operation exposes a UI builder that supports defaults (for editing) and a key prefix
(to prevent Streamlit widget key collisions).
"""

import streamlit as st


def _idx(options, value):
    try:
        return max(0, options.index(value))
    except Exception:
        return 0


def select_columns_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    default_cols = defaults.get("columns") or cols1[: min(10, len(cols1))]
    return {"columns": st.multiselect("Columns", cols1, default=default_cols, key=f"{key_prefix}sel_cols")}


def filter_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    c, o, v = st.columns([3, 2, 3])
    with c:
        col_default = defaults.get("column") or (cols1[0] if cols1 else "")
        col = st.selectbox("Column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}flt_col")
    with o:
        ops = ["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "LIKE", "RLIKE", "IS NULL", "IS NOT NULL"]
        op_default = defaults.get("operator") or "="
        op = st.selectbox("Operator", ops, index=_idx(ops, op_default), key=f"{key_prefix}flt_op")
    with v:
        val_default = defaults.get("value")
        if op in ["IS NULL", "IS NOT NULL"]:
            st.text_input("Value", value="(not required)", disabled=True, key=f"{key_prefix}flt_val_disabled")
            val = None
        elif op in ["IN", "NOT IN"]:
            val = st.text_input("Values (comma separated)", value=val_default or "", placeholder="A,B,C", key=f"{key_prefix}flt_val_in")
        else:
            val = st.text_input("Value", value=val_default or "", key=f"{key_prefix}flt_val")
    return {"column": col, "operator": op, "value": val}


def sql_where_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    st.caption("SQL WHERE condition, e.g. `amount > 1000 AND status = 'A'`")
    return {"condition": st.text_input("Condition", value=defaults.get("condition", ""), key=f"{key_prefix}where")}


def join_ui(cols1, cols2, defaults=None, key_prefix=""):
    defaults = defaults or {}
    hows = ["inner", "left", "right", "full", "left_semi", "left_anti", "cross"]
    how_default = defaults.get("how") or "inner"
    how = st.selectbox("Join type", hows, index=_idx(hows, how_default), key=f"{key_prefix}join_how")

    common = sorted(list(set(cols1).intersection(set(cols2))))
    key_space = common if common else cols1
    default_keys = defaults.get("keys") or []
    keys = st.multiselect("Join keys", key_space, default=[k for k in default_keys if k in key_space], key=f"{key_prefix}join_keys")

    map_keys = st.toggle("Map keys when names differ", value=bool(defaults.get("map_keys", False)), key=f"{key_prefix}join_map")
    mapping = []
    if map_keys and keys:
        existing = {m.get("s1"): m.get("s2") for m in (defaults.get("key_mapping") or [])}
        for k in keys:
            s2_default = existing.get(k) or (cols2[0] if cols2 else "")
            mapping.append({"s1": k, "s2": st.selectbox(f"Source2 column for {k}", cols2, index=_idx(cols2, s2_default) if cols2 else 0, key=f"{key_prefix}map_{k}")})
    return {"how": how, "keys": keys, "map_keys": map_keys, "key_mapping": mapping}


def union_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    return {
        "by_name": st.toggle("Union by name", value=bool(defaults.get("by_name", True)), key=f"{key_prefix}un_by"),
        "allow_missing_columns": st.toggle("Allow missing columns", value=bool(defaults.get("allow_missing_columns", False)), key=f"{key_prefix}un_miss"),
    }


def aggregate_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    group_default = defaults.get("group_by") or []
    group_by = st.multiselect("Group by", cols1, default=[c for c in group_default if c in cols1], key=f"{key_prefix}gb")

    st.caption("Add aggregations")
    state_key = f"{key_prefix}aggs_state"
    if state_key not in st.session_state:
        st.session_state[state_key] = defaults.get("aggs") or []

    a1, a2, a3 = st.columns([3, 2, 2])
    with a1:
        col_default = (st.session_state[state_key][0]["column"] if st.session_state[state_key] else (cols1[0] if cols1 else ""))
        col = st.selectbox("Agg column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}agg_col")
    with a2:
        funcs = ["count", "sum", "avg", "min", "max", "countDistinct"]
        func_default = (st.session_state[state_key][0]["func"] if st.session_state[state_key] else "count")
        func = st.selectbox("Function", funcs, index=_idx(funcs, func_default), key=f"{key_prefix}agg_func")
    with a3:
        alias = st.text_input("Alias", value=f"{func}_{col}", key=f"{key_prefix}agg_alias")

    if st.button("Add aggregation", key=f"{key_prefix}agg_add"):
        st.session_state[state_key].append({"column": col, "func": func, "alias": alias})

    if st.session_state[state_key]:
        st.write(st.session_state[state_key])

    return {"group_by": group_by, "aggs": st.session_state[state_key]}


def pivot_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    gb_default = defaults.get("group_by") or []
    gb = st.multiselect("Group by", cols1, default=[c for c in gb_default if c in cols1], key=f"{key_prefix}pv_gb")

    pivot_default = defaults.get("pivot_col") or (cols1[0] if cols1 else "")
    values_default = defaults.get("values_col") or (cols1[0] if cols1 else "")

    pivot_col = st.selectbox("Pivot column", cols1, index=_idx(cols1, pivot_default) if cols1 else 0, key=f"{key_prefix}pv_col")
    values_col = st.selectbox("Values column", cols1, index=_idx(cols1, values_default) if cols1 else 0, key=f"{key_prefix}pv_val")

    aggs = ["sum", "avg", "max", "min", "count"]
    agg_default = defaults.get("agg") or "sum"
    agg = st.selectbox("Agg", aggs, index=_idx(aggs, agg_default), key=f"{key_prefix}pv_agg")
    return {"group_by": gb, "pivot_col": pivot_col, "values_col": values_col, "agg": agg}


def withcolumn_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    new_col = st.text_input("New/Existing column name", value=defaults.get("new_column", ""), key=f"{key_prefix}wc_new")
    modes = ["Simple", "Case When", "Concat", "Math", "SQL Expression"]
    mode_default = defaults.get("expr_mode") or "Simple"
    mode = st.selectbox("Builder", modes, index=_idx(modes, mode_default), key=f"{key_prefix}wc_mode")

    p = {"new_column": new_col, "expr_mode": mode}

    if mode == "Simple":
        src_default = defaults.get("source_col") or (cols1[0] if cols1 else "")
        p["source_col"] = st.selectbox("Source column", cols1, index=_idx(cols1, src_default) if cols1 else 0, key=f"{key_prefix}wc_src")
        ops = ["copy", "upper", "lower", "trim", "length"]
        op_default = defaults.get("simple_op") or "copy"
        p["simple_op"] = st.selectbox("Operation", ops, index=_idx(ops, op_default), key=f"{key_prefix}wc_sop")

    elif mode == "Concat":
        default_cols = defaults.get("concat_cols") or []
        p["concat_cols"] = st.multiselect("Columns", cols1, default=[c for c in default_cols if c in cols1], key=f"{key_prefix}wc_concols")
        p["delimiter"] = st.text_input("Delimiter", value=defaults.get("delimiter", "_"), key=f"{key_prefix}wc_delim")

    elif mode == "Math":
        left_default = defaults.get("left_col") or (cols1[0] if cols1 else "")
        p["left_col"] = st.selectbox("Left column", cols1, index=_idx(cols1, left_default) if cols1 else 0, key=f"{key_prefix}wc_l")
        ops = ["+", "-", "*", "/", "%"]
        op_default = defaults.get("math_op") or "+"
        p["math_op"] = st.selectbox("Operator", ops, index=_idx(ops, op_default), key=f"{key_prefix}wc_mop")
        p["right_value"] = st.text_input("Right (number or column)", value=defaults.get("right_value", ""), key=f"{key_prefix}wc_r")

    elif mode == "Case When":
        when_default = defaults.get("when_col") or (cols1[0] if cols1 else "")
        p["when_col"] = st.selectbox("When column", cols1, index=_idx(cols1, when_default) if cols1 else 0, key=f"{key_prefix}wc_wcol")
        ops = ["=", "!=", ">", ">=", "<", "<=", "LIKE", "IN", "RLIKE"]
        op_default = defaults.get("when_op") or "="
        p["when_op"] = st.selectbox("When operator", ops, index=_idx(ops, op_default), key=f"{key_prefix}wc_wop")
        p["when_val"] = st.text_input("When value", value=defaults.get("when_val", ""), key=f"{key_prefix}wc_wval")
        p["then_val"] = st.text_input("Then value", value=defaults.get("then_val", ""), key=f"{key_prefix}wc_then")
        p["else_val"] = st.text_input("Else value", value=defaults.get("else_val", ""), key=f"{key_prefix}wc_else")

    elif mode == "SQL Expression":
        st.caption("Spark SQL expression, e.g. `amount * 1.2` or `coalesce(colA, 'x')`")
        p["sql_expr"] = st.text_input("Expression", value=defaults.get("sql_expr", ""), key=f"{key_prefix}wc_sql")

    return p


def rename_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    st.caption("Add rename mappings")
    state_key = f"{key_prefix}ren_state"
    if state_key not in st.session_state:
        st.session_state[state_key] = defaults.get("mappings") or []

    c1, c2 = st.columns(2)
    with c1:
        old_default = (st.session_state[state_key][0]["from"] if st.session_state[state_key] else (cols1[0] if cols1 else ""))
        old = st.selectbox("From", cols1, index=_idx(cols1, old_default) if cols1 else 0, key=f"{key_prefix}rn_old")
    with c2:
        new = st.text_input("To", value="", key=f"{key_prefix}rn_new")

    if st.button("Add rename", key=f"{key_prefix}rn_add"):
        if new:
            st.session_state[state_key].append({"from": old, "to": new})

    st.write(st.session_state[state_key])
    return {"mappings": st.session_state[state_key]}


def cast_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    col_default = defaults.get("column") or (cols1[0] if cols1 else "")
    col = st.selectbox("Column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}cast_col")
    dtypes = ["string", "int", "bigint", "double", "decimal(18,2)", "boolean", "date", "timestamp"]
    dtype_default = defaults.get("type") or "string"
    dtype = st.selectbox("Type", dtypes, index=_idx(dtypes, dtype_default), key=f"{key_prefix}cast_type")
    return {"column": col, "type": dtype}


def drop_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    default_cols = defaults.get("columns") or []
    return {"columns": st.multiselect("Columns to drop", cols1, default=[c for c in default_cols if c in cols1], key=f"{key_prefix}drop")}


def fillna_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    modes = ["Single value", "Per-column"]
    mode_default = defaults.get("mode") or "Single value"
    mode = st.selectbox("Fill mode", modes, index=_idx(modes, mode_default), key=f"{key_prefix}fill_mode")

    if mode == "Single value":
        val = st.text_input("Value", value=defaults.get("value", ""), key=f"{key_prefix}fill_val")
        subset_default = defaults.get("subset") or []
        subset = st.multiselect("Subset (optional)", cols1, default=[c for c in subset_default if c in cols1], key=f"{key_prefix}fill_subset")
        return {"mode": mode, "value": val, "subset": subset}

    state_key = f"{key_prefix}fills_state"
    if state_key not in st.session_state:
        st.session_state[state_key] = defaults.get("fills") or []

    c1, c2 = st.columns(2)
    with c1:
        col_default = (st.session_state[state_key][0]["column"] if st.session_state[state_key] else (cols1[0] if cols1 else ""))
        col = st.selectbox("Column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}fill_col")
    with c2:
        val = st.text_input("Value", value="", key=f"{key_prefix}fill_val2")

    if st.button("Add fill", key=f"{key_prefix}fill_add"):
        st.session_state[state_key].append({"column": col, "value": val})

    st.write(st.session_state[state_key])
    return {"mode": mode, "fills": st.session_state[state_key]}


def dropna_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    hows = ["any", "all"]
    how_default = defaults.get("how") or "any"
    how = st.selectbox("How", hows, index=_idx(hows, how_default), key=f"{key_prefix}dropna_how")
    subset_default = defaults.get("subset") or []
    subset = st.multiselect("Subset", cols1, default=[c for c in subset_default if c in cols1], key=f"{key_prefix}dropna_subset")
    thresh = st.number_input("Threshold (optional)", min_value=0, value=int(defaults.get("thresh") or 0), key=f"{key_prefix}dropna_thr")
    return {"how": how, "subset": subset, "thresh": int(thresh)}


def dedup_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    subset_default = defaults.get("subset") or []
    subset = st.multiselect("Subset (optional)", cols1, default=[c for c in subset_default if c in cols1], key=f"{key_prefix}dedup")
    return {"subset": subset}


def distinct_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    return {}


def limit_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    return {"n": int(st.number_input("Rows", min_value=1, value=int(defaults.get("n") or 100), key=f"{key_prefix}limit"))}


def orderby_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    cols_default = defaults.get("columns") or []
    direction_default = defaults.get("direction") or "asc"
    direction_opts = ["asc", "desc"]
    return {
        "columns": st.multiselect("Columns", cols1, default=[c for c in cols_default if c in cols1], key=f"{key_prefix}ob_cols"),
        "direction": st.selectbox("Direction", direction_opts, index=_idx(direction_opts, direction_default), key=f"{key_prefix}ob_dir"),
    }


def sample_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    frac = float(defaults.get("fraction") or 0.1)
    seed = int(defaults.get("seed") or 42)
    frac = st.slider("Fraction", min_value=0.0, max_value=1.0, value=frac, key=f"{key_prefix}samp_frac")
    seed = st.number_input("Seed", min_value=0, value=seed, key=f"{key_prefix}samp_seed")
    return {"fraction": float(frac), "seed": int(seed)}


def repartition_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    n = st.number_input("Partitions", min_value=1, value=int(defaults.get("n") or 200), key=f"{key_prefix}rep_n")
    cols_default = defaults.get("columns") or []
    cols = st.multiselect("Partition columns (optional)", cols1, default=[c for c in cols_default if c in cols1], key=f"{key_prefix}rep_cols")
    return {"n": int(n), "columns": cols}


def coalesce_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    return {"n": int(st.number_input("Partitions", min_value=1, value=int(defaults.get("n") or 50), key=f"{key_prefix}coal"))}


def explode_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    col_default = defaults.get("column") or (cols1[0] if cols1 else "")
    col = st.selectbox("Array/Map column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}ex_col")
    out = st.text_input("Output column", value=defaults.get("out", "exploded"), key=f"{key_prefix}ex_out")
    return {"column": col, "out": out}


def split_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    col_default = defaults.get("column") or (cols1[0] if cols1 else "")
    col = st.selectbox("Column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}sp_col")
    pattern = st.text_input("Pattern", value=defaults.get("pattern", ","), key=f"{key_prefix}sp_pat")
    out = st.text_input("Output column", value=defaults.get("out", f"{col}_arr"), key=f"{key_prefix}sp_out")
    return {"column": col, "pattern": pattern, "out": out}


def regexp_replace_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    col_default = defaults.get("column") or (cols1[0] if cols1 else "")
    col = st.selectbox("Column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}rr_col")
    pattern = st.text_input("Regex pattern", value=defaults.get("pattern", ""), key=f"{key_prefix}rr_pat")
    repl = st.text_input("Replacement", value=defaults.get("replacement", ""), key=f"{key_prefix}rr_repl")
    out = st.text_input("Output column", value=defaults.get("out", col), key=f"{key_prefix}rr_out")
    return {"column": col, "pattern": pattern, "replacement": repl, "out": out}


def date_add_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    col_default = defaults.get("column") or (cols1[0] if cols1 else "")
    col = st.selectbox("Date column", cols1, index=_idx(cols1, col_default) if cols1 else 0, key=f"{key_prefix}da_col")
    days = st.number_input("Days", value=int(defaults.get("days") or 1), key=f"{key_prefix}da_days")
    out = st.text_input("Output column", value=defaults.get("out", f"{col}_plus_days"), key=f"{key_prefix}da_out")
    return {"column": col, "days": int(days), "out": out}


def window_rank_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    part_default = defaults.get("partition_by") or []
    order_default = defaults.get("order_by") or []
    funcs = ["row_number", "rank", "dense_rank"]
    func_default = defaults.get("func") or "row_number"
    part = st.multiselect("Partition by", cols1, default=[c for c in part_default if c in cols1], key=f"{key_prefix}w_part")
    order = st.multiselect("Order by", cols1, default=[c for c in order_default if c in cols1], key=f"{key_prefix}w_ord")
    func = st.selectbox("Window function", funcs, index=_idx(funcs, func_default), key=f"{key_prefix}w_func")
    out = st.text_input("Output column", value=defaults.get("out", func), key=f"{key_prefix}w_out")
    return {"partition_by": part, "order_by": order, "func": func, "out": out}


def sql_select_ui(cols1, cols2=None, defaults=None, key_prefix=""):
    defaults = defaults or {}
    st.caption("SQL SELECT expression list for selectExpr, e.g. `id, upper(name) as name_u`")
    return {"exprs": st.text_area("Select expressions", value=defaults.get("exprs", ""), height=90, key=f"{key_prefix}sel_exprs")}


OP_REGISTRY = {
    "Select Columns": {"category": "Projection", "needs_second_input": False, "ui": select_columns_ui},

    "Filter": {"category": "Row", "needs_second_input": False, "ui": filter_ui},
    "SQL Where": {"category": "Row", "needs_second_input": False, "ui": sql_where_ui},
    "Distinct": {"category": "Row", "needs_second_input": False, "ui": distinct_ui},
    "Limit": {"category": "Row", "needs_second_input": False, "ui": limit_ui},
    "Order By": {"category": "Row", "needs_second_input": False, "ui": orderby_ui},
    "Sample": {"category": "Row", "needs_second_input": False, "ui": sample_ui},

    "Join": {"category": "Combine", "needs_second_input": True, "ui": join_ui},
    "Union": {"category": "Combine", "needs_second_input": True, "ui": union_ui},

    "Aggregate": {"category": "Aggregate", "needs_second_input": False, "ui": aggregate_ui},
    "Pivot": {"category": "Aggregate", "needs_second_input": False, "ui": pivot_ui},

    "Create/Update Column": {"category": "Column", "needs_second_input": False, "ui": withcolumn_ui},
    "Rename Columns": {"category": "Column", "needs_second_input": False, "ui": rename_ui},
    "Cast Column": {"category": "Column", "needs_second_input": False, "ui": cast_ui},
    "Drop Columns": {"category": "Column", "needs_second_input": False, "ui": drop_ui},

    "Fill Nulls": {"category": "Data Quality", "needs_second_input": False, "ui": fillna_ui},
    "Drop Nulls": {"category": "Data Quality", "needs_second_input": False, "ui": dropna_ui},
    "Drop Duplicates": {"category": "Data Quality", "needs_second_input": False, "ui": dedup_ui},

    "Repartition": {"category": "Performance", "needs_second_input": False, "ui": repartition_ui},
    "Coalesce": {"category": "Performance", "needs_second_input": False, "ui": coalesce_ui},

    "Explode": {"category": "Complex Types", "needs_second_input": False, "ui": explode_ui},
    "Split": {"category": "Complex Types", "needs_second_input": False, "ui": split_ui},
    "Regexp Replace": {"category": "String", "needs_second_input": False, "ui": regexp_replace_ui},
    "Date Add": {"category": "Date/Time", "needs_second_input": False, "ui": date_add_ui},
    "Window Rank": {"category": "Window", "needs_second_input": False, "ui": window_rank_ui},

    "SQL Select": {"category": "Advanced", "needs_second_input": False, "ui": sql_select_ui},
}


def list_operations():
    return [f"{d['category']} • {op}" for op, d in OP_REGISTRY.items()]


def resolve_operation(label: str) -> str:
    return label.split("•", 1)[1].strip() if "•" in label else label
