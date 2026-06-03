from io import BytesIO

from openpyxl import Workbook


def build_default_demo_excel_bytes() -> bytes:
    """Build a small Unity Catalog-style Excel workbook for demo mode."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "UC"

    headers = [
        "CatalogName",
        "SchemaName",
        "TableName",
        "ColumnName1",
        "ColumnName2",
        "ColumnName3",
        "ColumnName4",
        "ColumnName5",
        "ColumnName6",
    ]
    worksheet.append(headers)

    rows = [
        ["main", "sales", "customers", "customer_id", "customer_name", "email", "phone", "city", "state"],
        ["main", "sales", "products", "product_id", "product_name", "category", "unit_price", "is_active", "created_at"],
        ["main", "sales", "orders", "order_id", "customer_id", "order_date", "order_status", "order_total", "channel"],
        ["main", "sales", "order_items", "order_item_id", "order_id", "product_id", "quantity", "unit_price", "line_total"],
    ]

    for row in rows:
        worksheet.append(row)

    samples = {
        "Customers_Data": [
            ["customer_id", "customer_name", "email", "phone", "city", "state"],
            [1, "Ava Johnson", "ava.johnson@example.com", "555-0101", "Dallas", "TX"],
            [2, "Noah Smith", "noah.smith@example.com", "555-0102", "Austin", "TX"],
            [3, "Mia Patel", "mia.patel@example.com", "555-0103", "Chicago", "IL"],
        ],
        "Products_Data": [
            ["product_id", "product_name", "category", "unit_price", "is_active", "created_at"],
            [101, "Laptop Stand", "Accessories", 29.99, True, "2026-01-08"],
            [102, "Wireless Mouse", "Accessories", 24.5, True, "2026-01-10"],
            [103, "USB-C Hub", "Accessories", 39.0, True, "2026-01-12"],
        ],
        "Orders_Data": [
            ["order_id", "customer_id", "order_date", "order_status", "order_total", "channel"],
            [5001, 1, "2026-02-01", "Shipped", 159.49, "Online"],
            [5002, 2, "2026-02-03", "Processing", 24.5, "Store"],
            [5003, 3, "2026-02-05", "Delivered", 68.99, "Online"],
        ],
        "Order_Items_Data": [
            ["order_item_id", "order_id", "product_id", "quantity", "unit_price", "line_total"],
            [9001, 5001, 101, 1, 29.99, 29.99],
            [9002, 5001, 102, 2, 24.5, 49.0],
            [9003, 5002, 103, 1, 39.0, 39.0],
        ],
    }

    for sheet_name, sheet_rows in samples.items():
        sample_sheet = workbook.create_sheet(title=sheet_name)
        for row in sheet_rows:
            sample_sheet.append(row)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()