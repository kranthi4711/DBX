"""Unity Catalog browser.

Runs inside Databricks with `spark`. Falls back to demo values locally.
"""

from typing import List

class UCBrowser:
    def __init__(self):
        try:
            from pyspark.sql import SparkSession  # noqa
            self.spark = SparkSession.builder.getOrCreate()
            self._demo = False
        except Exception:
            self.spark = None
            self._demo = True

    def catalogs(self) -> List[str]:
        if self._demo:
            return ["main", "hive_metastore"]
        return [r[0] for r in self.spark.sql("SHOW CATALOGS").collect()]

    def schemas(self, catalog: str) -> List[str]:
        if not catalog:
            return []
        if self._demo:
            return ["default", "sales", "marketing"]
        return [r[0] for r in self.spark.sql(f"SHOW SCHEMAS IN {catalog}").collect()]

    def tables(self, catalog: str, schema: str) -> List[str]:
        if not (catalog and schema):
            return []
        if self._demo:
            return ["customers", "orders", "products"]
        rows = self.spark.sql(f"SHOW TABLES IN {catalog}.{schema}").collect()
        # best-effort extraction
        out = []
        for r in rows:
            for v in list(r)[::-1]:
                if isinstance(v, str):
                    out.append(v)
                    break
        return sorted(list(set(out)))

    def columns_from_fullname(self, full_name: str) -> List[str]:
        if not full_name or full_name.count(".") != 2:
            return []
        if self._demo:
            return ["id", "name", "amount", "date"]
        return self.spark.table(full_name).columns
