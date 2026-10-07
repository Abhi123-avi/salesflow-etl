import sqlite3
from pathlib import Path
from decimal import Decimal

database_path = Path(__file__).parent / "sales.db"

if not database_path.exists():
    raise FileNotFoundError("Run etl.py first to create sales.db.")

connection = sqlite3.connect(database_path)

try:
    results = connection.execute("""
        SELECT sale_date, SUM(sales_amount_paise)
        FROM sales
        GROUP BY sale_date
        ORDER BY sale_date
    """).fetchall()
finally:
    connection.close()

print("Daily sales from the database:\n")

for date, total_paise in results:
    amount = Decimal(total_paise) / 100
    print(f"{date}: INR {amount:,.2f}")