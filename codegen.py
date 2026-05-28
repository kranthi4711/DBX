from typing import List, Dict
from model import Pipeline, Source


def _q(s: str) -> str:
    return "'" + (s or "").replace("'", "\\'") + "'"


def _safe_alias(a: str) -> str:
    out = "".join([c if c.isalnum() or c == "_" else "_" for c in (a or "")])
    if out and out[0].isdigit():
        out = "_" + out
    return out or "df"


def _maybe_number(v: str):
    try:
        float(v)
        return v, True
    except Exception:
        return _q(v), False


def _filter_expr(p: Dict) -> str:
    col = p.get("column")
    op = p.get("operator")
    val = p.get("value")

    if op in ["IS NULL", "IS NOT NULL"]:
        return f"{col} {op}"

    if op in ["IN", "NOT IN"]:
        toks = [t.strip() for t in (val or "").split(",") if t.strip()]
        vals = ", ".join([_q(t) for t in toks])
        return f"{col} {op} ({vals})"

    if op in ["LIKE", "RLIKE"]:
        return f"{col} {op} {_q(val)}"

    v, _ = _maybe_number(val)
    return f"{col} {op} {v}"


def generate_pyspark_code(pipeline: Pipeline, sources: List[Source]) -> str:
    lines = []
    lines.append("from pyspark.sql import SparkSession")
    lines.append("from pyspark.sql import functions as F")
    lines.append("from pyspark.sql.window import Window")
    lines.append("")
    lines.append("spark = SparkSession.builder.getOrCreate()")
    lines.append("")

    for s in sources:
        v = _safe_alias(s.alias)
        lines.append(f"{v} = spark.table({_q(s.full_name)})")
    lines.append("")

    for i, step in enumerate(pipeline.steps, start=1):
        inp1 = _safe_alias(step.input1)
        inp2 = _safe_alias(step.input2) if step.input2 else ""
        out = _safe_alias(step.output_alias)
        op = step.operation
        p = step.params or {}

        lines.append(f"# --- Step {i}: {op} ---")

        if op == "Select Columns":
            cols = p.get("columns", [])
            if cols:
                sel = ", ".join([f"F.col('{c}')" for c in cols])
                lines.append(f"{out} = {inp1}.select({sel})")
            else:
                lines.append(f"{out} = {inp1}")

        elif op == "Filter":
            expr = _filter_expr(p)
            lines.append(f"{out} = {inp1}.filter(F.expr(\"{expr}\"))")

        elif op == "SQL Where":
            cond = p.get("condition", "")
            lines.append(f"{out} = {inp1}.filter(F.expr({_q(cond)}))")

        elif op == "Join":
            how = p.get("how", "inner")
            keys = p.get("keys", [])
            if p.get("map_keys") and p.get("key_mapping"):
                conds = []
                for m in p.get("key_mapping", []):
                    conds.append(f"{inp1}[{_q(m['s1'])}] == {inp2}[{_q(m['s2'])}]")
                on_expr = " & ".join(conds) if conds else "None"
                lines.append(f"{out} = {inp1}.join({inp2}, on=({on_expr}), how={_q(how)})")
            else:
                if keys:
                    on_list = "[" + ", ".join([_q(k) for k in keys]) + "]"
                else:
                    on_list = "None"
                lines.append(f"{out} = {inp1}.join({inp2}, on={on_list}, how={_q(how)})")

        elif op == "Union":
            by_name = bool(p.get("by_name", True))
            allow_missing = bool(p.get("allow_missing_columns", False))
            if by_name:
                lines.append(f"{out} = {inp1}.unionByName({inp2}, allowMissingColumns={allow_missing})")
            else:
                lines.append(f"{out} = {inp1}.union({inp2})")

        elif op == "Aggregate":
            gb = p.get("group_by", [])
            aggs = p.get("aggs", [])
            if gb:
                gb_expr = ", ".join([f"F.col('{c}')" for c in gb])
                lines.append(f"g{i} = {inp1}.groupBy({gb_expr})")
            else:
                lines.append(f"g{i} = {inp1}.groupBy()")

            agg_exprs = []
            for a in aggs:
                func = a.get("func")
                col = a.get("column")
                alias = a.get("alias")
                if func == "countDistinct":
                    agg_exprs.append(f"F.countDistinct('{col}').alias({_q(alias)})")
                elif func == "count":
                    agg_exprs.append(f"F.count(F.col('{col}')).alias({_q(alias)})")
                else:
                    agg_exprs.append(f"F.{func}(F.col('{col}')).alias({_q(alias)})")
            if agg_exprs:
                lines.append(f"{out} = g{i}.agg({', '.join(agg_exprs)})")
            else:
                lines.append(f"{out} = g{i}.count()")

        elif op == "Pivot":
            gb = p.get("group_by", [])
            pivot_col = p.get("pivot_col")
            values_col = p.get("values_col")
            agg = p.get("agg", "sum")
            gb_expr = ", ".join([f"F.col('{c}')" for c in gb]) if gb else ""
            if gb_expr:
                lines.append(f"{out} = {inp1}.groupBy({gb_expr}).pivot('{pivot_col}').agg(F.{agg}(F.col('{values_col}')))")
            else:
                lines.append(f"{out} = {inp1}.groupBy().pivot('{pivot_col}').agg(F.{agg}(F.col('{values_col}')))")

        elif op == "Create/Update Column":
            newc = p.get("new_column")
            mode = p.get("expr_mode")
            if mode == "Simple":
                src = p.get("source_col")
                sop = p.get("simple_op")
                if sop == "copy":
                    expr = f"F.col('{src}')"
                elif sop == "length":
                    expr = f"F.length(F.col('{src}'))"
                else:
                    expr = f"F.{sop}(F.col('{src}'))"
            elif mode == "Concat":
                cols = p.get("concat_cols", [])
                delim = p.get("delimiter", "_")
                args = ", ".join([f"F.col('{c}')" for c in cols]) if cols else ""
                expr = f"F.concat_ws({_q(delim)}, {args})" if args else "F.lit('')"
            elif mode == "Math":
                l = p.get("left_col")
                op2 = p.get("math_op")
                rv = p.get("right_value")
                try:
                    float(rv)
                    right = rv
                except Exception:
                    right = f"F.col('{rv}')"
                expr = f"(F.col('{l}') {op2} {right})"
            elif mode == "Case When":
                wcol = p.get("when_col")
                wop = p.get("when_op")
                wval = p.get("when_val")
                thenv = p.get("then_val")
                elsev = p.get("else_val")
                v, _ = _maybe_number(wval)
                expr = f"F.when(F.expr(\"{wcol} {wop} {v}\"), F.lit({_q(thenv)})).otherwise(F.lit({_q(elsev)}))"
            else:
                sql_expr = p.get("sql_expr", "")
                expr = f"F.expr({_q(sql_expr)})"

            lines.append(f"{out} = {inp1}.withColumn({_q(newc)}, {expr})")

        elif op == "Rename Columns":
            mappings = p.get("mappings", [])
            lines.append(f"{out} = {inp1}")
            for m in mappings:
                lines.append(f"{out} = {out}.withColumnRenamed({_q(m['from'])}, {_q(m['to'])})")

        elif op == "Cast Column":
            col = p.get("column")
            dtype = p.get("type")
            lines.append(f"{out} = {inp1}.withColumn({_q(col)}, F.col({_q(col)}).cast({_q(dtype)}))")

        elif op == "Drop Columns":
            cols = p.get("columns", [])
            if cols:
                args = ", ".join([_q(c) for c in cols])
                lines.append(f"{out} = {inp1}.drop({args})")
            else:
                lines.append(f"{out} = {inp1}")

        elif op == "Fill Nulls":
            if p.get("mode") == "Single value":
                val = p.get("value")
                subset = p.get("subset", [])
                if subset:
                    lines.append(f"{out} = {inp1}.fillna({_q(val)}, subset={[c for c in subset]!r})")
                else:
                    lines.append(f"{out} = {inp1}.fillna({_q(val)})")
            else:
                fills = p.get("fills", [])
                mp = {f["column"]: f["value"] for f in fills}
                lines.append(f"{out} = {inp1}.fillna({mp!r})")

        elif op == "Drop Nulls":
            how = p.get("how", "any")
            subset = p.get("subset", [])
            thresh = p.get("thresh", 0)
            args = []
            if how:
                args.append(f"how={_q(how)}")
            if subset:
                args.append(f"subset={[c for c in subset]!r}")
            if thresh:
                args.append(f"thresh={int(thresh)}")
            lines.append(f"{out} = {inp1}.dropna({', '.join(args)})")

        elif op == "Drop Duplicates":
            subset = p.get("subset", [])
            if subset:
                lines.append(f"{out} = {inp1}.dropDuplicates({[c for c in subset]!r})")
            else:
                lines.append(f"{out} = {inp1}.dropDuplicates()")

        elif op == "Distinct":
            lines.append(f"{out} = {inp1}.distinct()")

        elif op == "Limit":
            n = int(p.get("n", 100))
            lines.append(f"{out} = {inp1}.limit({n})")

        elif op == "Order By":
            cols = p.get("columns", [])
            direction = p.get("direction", "asc")
            if cols:
                if direction == "desc":
                    ords = ", ".join([f"F.col('{c}').desc()" for c in cols])
                else:
                    ords = ", ".join([f"F.col('{c}').asc()" for c in cols])
                lines.append(f"{out} = {inp1}.orderBy({ords})")
            else:
                lines.append(f"{out} = {inp1}")

        elif op == "Sample":
            frac = float(p.get("fraction", 0.1))
            seed = int(p.get("seed", 42))
            lines.append(f"{out} = {inp1}.sample(withReplacement=False, fraction={frac}, seed={seed})")

        elif op == "Repartition":
            n = int(p.get("n", 200))
            cols = p.get("columns", [])
            if cols:
                cols_expr = ", ".join([f"F.col('{c}')" for c in cols])
                lines.append(f"{out} = {inp1}.repartition({n}, {cols_expr})")
            else:
                lines.append(f"{out} = {inp1}.repartition({n})")

        elif op == "Coalesce":
            n = int(p.get("n", 50))
            lines.append(f"{out} = {inp1}.coalesce({n})")

        elif op == "Explode":
            col = p.get("column")
            outc = p.get("out", "exploded")
            lines.append(f"{out} = {inp1}.withColumn({_q(outc)}, F.explode(F.col({_q(col)})))")

        elif op == "Split":
            col = p.get("column")
            pat = p.get("pattern", ",")
            outc = p.get("out")
            lines.append(f"{out} = {inp1}.withColumn({_q(outc)}, F.split(F.col({_q(col)}), {_q(pat)}))")

        elif op == "Regexp Replace":
            col = p.get("column")
            pat = p.get("pattern")
            repl = p.get("replacement", "")
            outc = p.get("out", col)
            lines.append(f"{out} = {inp1}.withColumn({_q(outc)}, F.regexp_replace(F.col({_q(col)}), {_q(pat)}, {_q(repl)}))")

        elif op == "Date Add":
            col = p.get("column")
            days = int(p.get("days", 1))
            outc = p.get("out")
            lines.append(f"{out} = {inp1}.withColumn({_q(outc)}, F.date_add(F.col({_q(col)}), {days}))")

        elif op == "Window Rank":
            part = p.get("partition_by", [])
            order = p.get("order_by", [])
            func = p.get("func", "row_number")
            outc = p.get("out", func)
            w = []
            if part:
                w.append(".partitionBy(" + ", ".join([f"F.col('{c}')" for c in part]) + ")")
            if order:
                w.append(".orderBy(" + ", ".join([f"F.col('{c}').asc()" for c in order]) + ")")
            wspec = "Window" + "".join(w)
            if func == "row_number":
                expr = f"F.row_number().over({wspec})"
            elif func == "rank":
                expr = f"F.rank().over({wspec})"
            else:
                expr = f"F.dense_rank().over({wspec})"
            lines.append(f"{out} = {inp1}.withColumn({_q(outc)}, {expr})")

        elif op == "SQL Select":
            exprs = p.get("exprs", "")
            lines.append(f"{out} = {inp1}.selectExpr({exprs!r})")

        else:
            lines.append(f"{out} = {inp1}  # TODO: Operation not implemented")

        for act in (step.actions or []):
            if act == "printSchema":
                lines.append(f"{out}.printSchema()")
            elif act == "explain":
                lines.append(f"{out}.explain(True)")
            elif act.startswith("show"):
                try:
                    n = int(act.split("(")[1].split(")")[0])
                except Exception:
                    n = 20
                lines.append(f"{out}.show({n}, truncate=False)")
            elif act == "count":
                lines.append(f"print({out}.count())")

        lines.append("")

    if pipeline.outputs:
        lines.append("# --- Optional: write outputs to Unity Catalog tables (disabled by default) ---")
        for o in pipeline.outputs:
            tgt = o.full_name()
            if not tgt:
                continue
            src_alias = _safe_alias(o.from_alias)
            mode = o.mode or "overwrite"
            lines.append(f"# {src_alias}.write.format('delta').mode({_q(mode)}).saveAsTable({_q(tgt)})")

    return "\n".join(lines)
