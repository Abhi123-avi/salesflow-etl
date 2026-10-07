"""SalesFlow: CSV validation, SQLite reporting, and a local dashboard.
Run: python etl.py
Uses only Python's standard library. Outputs are latest-run snapshots;
run_history.csv is appended only after all processing succeeds.
"""
import csv
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
import sqlite3

BASE = Path(__file__).resolve().parent
FIELDS = ["order_id", "date", "product", "quantity", "unit_price"]
# Keep totals within JavaScript's exact integer range (amounts use paise).
MAX_PAISE = 2**53 - 1


def money(paise):
    return f"{Decimal(paise) / 100:.2f}"


def write_csv(path, columns, rows):
    """Write to a temporary file before replacing this individual output."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_and_clean():
    clean = []
    rejected = []
    seen = set()
    counts = dict(input=0, duplicates=0, missing=0, invalid=0, invalid_fields=0)
    with (BASE / "sales.csv").open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, strict=True)
        if reader.fieldnames != FIELDS:
            raise ValueError("sales.csv must have these headers in order: " + ",".join(FIELDS))
        for row in reader:
            counts["input"] += 1
            reason = ""
            category = ""
            if None in row or any(value is None for value in row.values()):
                category, reason = "invalid_fields", "Incorrect number of CSV columns"
            else:
                row = {key: value.strip() for key, value in row.items()}
                key = tuple(row[field] for field in FIELDS)
                if key in seen:
                    category, reason = "duplicates", "Duplicate row"
                else:
                    seen.add(key)
                    if not row["quantity"]:
                        category, reason = "missing", "Missing quantity"
                    else:
                        try:
                            if not row["order_id"] or not row["product"]:
                                raise ValueError("Missing order ID or product")
                            parsed_date = date.fromisoformat(row["date"])
                            if parsed_date.isoformat() != row["date"]:
                                raise ValueError("Use YYYY-MM-DD dates")
                        except ValueError:
                            category, reason = "invalid_fields", "Missing ID/product or invalid YYYY-MM-DD date"
                        if not reason:
                            try:
                                quantity = int(row["quantity"])
                                price = Decimal(row["unit_price"])
                                if quantity <= 0 or quantity > MAX_PAISE:
                                    raise ValueError()
                                if not price.is_finite() or price < 0 or price > Decimal(MAX_PAISE) / 100:
                                    raise ValueError()
                                paise = price * 100
                                if paise != paise.to_integral_value():
                                    raise ValueError()
                                unit = int(paise)
                                amount = quantity * unit
                                if amount > MAX_PAISE:
                                    raise ValueError()
                            except (ValueError, InvalidOperation):
                                category, reason = "invalid", "Invalid quantity/price, fractional paise, or amount too large"
            if reason:
                counts[category] += 1
                rejected.append({
                    "source_line": reader.line_num,
                    **{field: row.get(field) or "" for field in FIELDS},
                    "reason": reason,
                })
            else:
                clean.append({
                    **row, "quantity": quantity,
                    "unit_price": money(unit), "sales_amount": money(amount),
                    "unit_price_paise": unit, "sales_amount_paise": amount,
                })
    total = sum(row["sales_amount_paise"] for row in clean)
    if total > MAX_PAISE:
        raise ValueError("Total exceeds the dashboard's supported exact-money range.")
    if not clean:
        raise ValueError("No valid sales records. Check sales.csv; previous outputs are retained.")
    if counts["input"] != len(clean) + len(rejected):
        raise ValueError("Input row reconciliation failed.")
    return clean, rejected, counts, total


def load_database(clean, expected_total):
    connection = sqlite3.connect(BASE / "sales.db")
    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sales (
                    order_id TEXT, sale_date TEXT, product TEXT,
                    quantity INTEGER, unit_price_paise INTEGER,
                    sales_amount_paise INTEGER
                )
            """)
            connection.execute("DELETE FROM sales")
            connection.executemany("""
                INSERT INTO sales
                (order_id, sale_date, product, quantity, unit_price_paise, sales_amount_paise)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (r["order_id"], r["date"], r["product"], r["quantity"],
                 r["unit_price_paise"], r["sales_amount_paise"])
                for r in clean
            ])
            count, total = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(sales_amount_paise), 0) FROM sales"
            ).fetchone()
            daily = connection.execute("""
                SELECT sale_date, SUM(sales_amount_paise)
                FROM sales GROUP BY sale_date ORDER BY sale_date
            """).fetchall()
            if count != len(clean) or total != expected_total or sum(n for _, n in daily) != total:
                raise ValueError("SQL reconciliation failed.")
        return count, total, daily
    finally:
        connection.close()


def build_dashboard(data):
    page = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SalesFlow | Sales Dashboard</title>
    <style>
        :root {
            --bg: #f3f6fb;
            --card: #ffffff;
            --text: #17243b;
            --muted: #61718b;
            --border: #e0e7f0;
            --accent: #4255e7;
        }
        body.dark {
            color-scheme: dark;
            --bg: #0e1628;
            --card: #19243a;
            --text: #f1f5ff;
            --muted: #abbad1;
            --border: #33415b;
            --accent: #a4b0ff;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        main { max-width: 1100px; margin: auto; padding: 32px 24px; }
        header, .toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            flex-wrap: wrap;
        }
        .brand { font-size: 22px; font-weight: 800; color: var(--accent); }
        .muted { color: var(--muted); font-size: 14px; }
        .hero {
            margin: 28px 0;
            padding: 32px;
            border-radius: 22px;
            background: linear-gradient(120deg, #263aa6, #6556dc);
            color: white;
        }
        .hero h1 { margin: 0 0 10px; font-size: clamp(26px, 4vw, 38px); }
        .hero p { margin: 0; line-height: 1.6; }
        .cards {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
        }
        .card, .panel {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 22px;
        }
        .card h2 {
            margin: 0;
            font-size: 14px;
            font-weight: 500;
            color: var(--muted);
        }
        .metric { margin: 14px 0 6px; font-size: 28px; font-weight: 750; }
        .panel { margin-top: 22px; }
        .panel h2 { margin-top: 0; font-size: 19px; }
        button, input, select {
            padding: 10px 13px;
            border: 1px solid var(--border);
            border-radius: 9px;
            background: var(--card);
            color: var(--text);
            font: inherit;
        }
        button { cursor: pointer; }
        button:hover { border-color: var(--accent); }
        button:focus-visible, input:focus-visible, select:focus-visible {
            outline: 3px solid var(--accent);
            outline-offset: 3px;
        }
        .filters { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
        label { display: grid; gap: 6px; font-size: 13px; }
        .bar-row {
            display: grid;
            grid-template-columns: 100px 1fr 125px;
            gap: 14px;
            align-items: center;
            margin: 20px 0;
            font-size: 14px;
        }
        .track { background: var(--bg); border-radius: 8px; height: 22px; }
        .bar {
            background: linear-gradient(90deg, #4967ed, #9b72ed);
            height: 100%;
            border-radius: 8px;
        }
        .amount { text-align: right; }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 15px 10px; text-align: left; border-bottom: 1px solid var(--border); }
        th { color: var(--muted); font-size: 13px; }
        tbody tr:hover { background: var(--bg); }
        .status { color: var(--accent); font-weight: 600; }
        footer { padding: 24px 0; line-height: 1.7; }
        @media (max-width: 750px) {
            .cards { grid-template-columns: repeat(2, 1fr); }
            .bar-row { grid-template-columns: 85px 1fr; }
            .amount { grid-column: 2; }
        }
        @media (max-width: 420px) {
            .cards { grid-template-columns: 1fr; }
            main { padding: 20px 14px; }
        }
    </style>
    </head>
    <body>
    <main>
        <header>
            <div class="brand">SalesFlow<span class="muted"> / Analytics</span></div>
            <button id="theme" type="button" aria-pressed="false">Dark mode</button>
        </header>

        <section class="hero">
            <h1>Your sales, clearly explained.</h1>
            <p>Sample data · Daily revenue and data quality overview.</p>
        </section>

        <section class="cards" aria-label="Sales and data quality summary">
            <article class="card">
                <h2>Filtered sales</h2>
                <p class="metric" id="revenue"></p>
                <span class="muted">Selected date range</span>
            </article>
            <article class="card">
                <h2>Clean records</h2>
                <p class="metric" id="clean"></p>
                <span class="muted">Entire processing run</span>
            </article>
            <article class="card">
                <h2>Excluded records</h2>
                <p class="metric" id="excluded"></p>
                <span class="muted">Duplicates or invalid values</span>
            </article>
            <article class="card">
                <h2>Days with sales</h2>
                <p class="metric" id="days"></p>
                <span class="muted">Selected date range</span>
            </article>
        </section>

        <section class="panel">
            <div class="toolbar">
                <h2>Explore daily sales</h2>
                <div class="filters">
                    <label>From<input id="start" type="date"></label>
                    <label>To<input id="end" type="date"></label>
                    <button id="reset" type="button">Reset</button>
                </div>
            </div>
            <p id="message" class="muted" role="status" aria-live="polite"></p>
            <div id="chart" aria-label="Daily sales bar chart"></div>
        </section>

        <section class="panel">
            <div class="toolbar">
                <h2>Sales breakdown</h2>
                <label>Sort by
                    <select id="sort">
                        <option value="date">Date: oldest first</option>
                        <option value="high">Sales: highest first</option>
                        <option value="low">Sales: lowest first</option>
                    </select>
                </label>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th scope="col">Date</th><th scope="col">Revenue</th></tr></thead>
                    <tbody id="rows"></tbody>
                </table>
            </div>
        </section>

        <section class="panel">
            <h2>Processing summary</h2>
            <p class="status">SQL report total matches cleaned sales.</p>
            <p id="quality" class="muted"></p>
            <p class="muted">This check confirms matching totals, not complete data accuracy.</p>
        </section>

        <footer class="muted">
            <div id="updated"></div>
            Snapshot dashboard: run python etl.py again and refresh this page to update results.
        </footer>
    </main>

    <script id="data" type="application/json">__DASHBOARD_DATA__</script>
    <script>
        const data = JSON.parse(document.getElementById("data").textContent);
        const $ = id => document.getElementById(id);
        const money = cents => new Intl.NumberFormat("en-IN", {
            style: "currency", currency: "INR"
        }).format(cents / 100);

        // Sum whole paise to avoid floating-point addition errors.
        const daily = data.daily.map(row => ({
            date: row.date,
            cents: row.paise
        }));

        $("clean").textContent = data.clean;
        $("excluded").textContent = data.duplicates + data.missing + data.invalid + data.invalid_fields;
        $("quality").textContent =
            `Input: ${data.input} | Duplicates: ${data.duplicates} | ` +
            `Missing quantity: ${data.missing} | Invalid numbers: ${data.invalid} | Invalid fields: ${data.invalid_fields}`;
        $("updated").textContent = `Generated: ${data.generated}`;

        function render() {
            const start = $("start").value;
            const end = $("end").value;
            const invalid = start && end && start > end;

            const filtered = invalid ? [] : daily.filter(row =>
                (!start || row.date >= start) && (!end || row.date <= end)
            );

            $("revenue").textContent = money(
                filtered.reduce((sum, row) => sum + row.cents, 0)
            );
            $("days").textContent = filtered.length;
            $("message").textContent = invalid
                ? "The From date must be on or before the To date."
                : filtered.length
                    ? `Showing ${filtered.length} days with sales.`
                    : "No sales found for this date range.";

            $("chart").replaceChildren();
            const maximum = filtered.reduce((largest, row) => Math.max(largest, row.cents), 1);

            filtered.forEach(row => {
                const line = document.createElement("div");
                line.className = "bar-row";

                const date = document.createElement("span");
                date.textContent = row.date;

                const track = document.createElement("div");
                track.className = "track";
                track.setAttribute("aria-hidden", "true");

                const bar = document.createElement("div");
                bar.className = "bar";
                bar.style.width = `${row.cents / maximum * 100}%`;
                track.append(bar);

                const amount = document.createElement("span");
                amount.className = "amount";
                amount.textContent = money(row.cents);

                line.append(date, track, amount);
                $("chart").append(line);
            });

            const sorted = [...filtered];
            if ($("sort").value === "high") sorted.sort((a, b) => b.cents - a.cents);
            if ($("sort").value === "low") sorted.sort((a, b) => a.cents - b.cents);

            $("rows").replaceChildren();
            sorted.forEach(row => {
                const tr = document.createElement("tr");
                const date = document.createElement("td");
                const amount = document.createElement("td");
                date.textContent = row.date;
                amount.textContent = money(row.cents);
                tr.append(date, amount);
                $("rows").append(tr);
            });
        }

        ["start", "end", "sort"].forEach(id =>
            $(id).addEventListener("change", render)
        );

        $("reset").addEventListener("click", () => {
            $("start").value = "";
            $("end").value = "";
            $("sort").value = "date";
            render();
        });

        $("theme").addEventListener("click", () => {
            const dark = document.body.classList.toggle("dark");
            $("theme").textContent = dark ? "Light mode" : "Dark mode";
            $("theme").setAttribute("aria-pressed", String(dark));
        });

        render();
    </script>
    </body>
    </html>
    """


    safe_data = json.dumps(data).replace("<", "\u003c")
    return page.replace("__DASHBOARD_DATA__", safe_data)


def main():
    clean, rejected, counts, expected_total = read_and_clean()
    count, total, daily = load_database(clean, expected_total)
    write_csv(BASE / "clean_sales.csv", FIELDS + ["sales_amount"], [
        {key: row[key] for key in FIELDS + ["sales_amount"]} for row in clean
    ])
    write_csv(BASE / "rejected_sales.csv", ["source_line"] + FIELDS + ["reason"], rejected)
    write_csv(BASE / "daily_sales.csv", ["date", "total_sales"], [
        {"date": day, "total_sales": money(amount)} for day, amount in daily
    ])
    with (BASE / "daily_sales.csv").open(newline="", encoding="utf-8") as file:
        saved = [(r["date"], Decimal(r["total_sales"])) for r in csv.DictReader(file)]
    if saved != [(day, Decimal(amount) / 100) for day, amount in daily]:
        raise ValueError("Saved daily report does not match SQL results.")

    completed = datetime.now().astimezone()
    data = {
        **counts, "clean": count, "total": money(total),
        "generated": completed.strftime("%d %b %Y, %H:%M:%S %Z"),
        "daily": [{"date": day, "paise": amount} for day, amount in daily],
    }
    dashboard = BASE / "dashboard.html"
    temporary = BASE / "dashboard.html.tmp"
    try:
        temporary.write_text(build_dashboard(data), encoding="utf-8")
        temporary.replace(dashboard)
    finally:
        temporary.unlink(missing_ok=True)

    # Keep the existing history format so earlier runs remain readable.
    history = BASE / "run_history.csv"
    columns = ["completed_at", "input_rows", "clean_rows", "duplicates",
               "missing_quantity", "invalid_numbers", "total_sales"]
    needs_header = not history.exists() or history.stat().st_size == 0
    if not needs_header:
        with history.open(newline="", encoding="utf-8") as file:
            if next(csv.reader(file), None) != columns:
                raise ValueError("Unexpected run_history.csv header; history was not changed.")
    with history.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if needs_header:
            writer.writerow(columns)
        writer.writerow([completed.isoformat(timespec="seconds"), counts["input"],
                         count, counts["duplicates"], counts["missing"],
                         counts["invalid"], money(total)])
    print(f"Database records: {count}")
    print(f"Database total: INR {Decimal(total) / 100:,.2f}")
    print("SQL checks passed. Dashboard updated from database results.")
    print(f"Excluded records: {len(rejected)} — see rejected_sales.csv")
    print("Successful run recorded in run_history.csv")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Failure details are separate from successful run history.
        logger = logging.getLogger("salesflow")
        logger.setLevel(logging.ERROR)
        try:
            handler = RotatingFileHandler(
                BASE / "errors.log", maxBytes=100_000, backupCount=2,
                encoding="utf-8"
            )
            logger.addHandler(handler)
            logger.exception("ETL failed; outputs may be from different runs. Fix the error and rerun.")
            handler.close()
        except OSError:
            pass
        print("Run failed. Check the error below and errors.log. Fix it and rerun.")
        raise
