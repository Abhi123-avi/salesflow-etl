# SalesFlow — Sales ETL & Reporting Dashboard

A Python and SQLite project that validates sales CSV data,
generates daily SQL reports, and displays an interactive dashboard.

## Live Demo
[Open the SalesFlow Dashboard](https://abhi123-avi.github.io/salesflow-etl/)

Interactive demo using sample data. Includes date filtering,
sales sorting, and light/dark mode.

## Features
- Detects duplicate rows and missing quantities.
- Validates dates, required fields, quantities, and prices.
- Records excluded rows with reasons.
- Stores cleaned records in SQLite.
- Calculates daily sales using SQL.
- Checks report totals against cleaned data.
- Includes date filters, sorting, and light/dark mode.
- Records successful runs and logs failures.

## Technologies
Python, SQLite, SQL, HTML, CSS, and JavaScript.
No third-party Python packages required.

## Run locally
From the project folder:

python3 etl.py

Open dashboard.html in your web browser by double-clicking it.
This works on both macOS and Windows.

To view daily sales in the terminal:

python3 query_sales.py

## Sample results
The included sample contains 7 rows:
- 6 accepted records
- 1 duplicate excluded
- Total sales: INR 21,200.00

## How updates work
Edit sales.csv, rerun etl.py, and refresh the dashboard.

## Scope
This is a local learning project using sample data.
The dashboard displays a generated snapshot.
Runs are started manually; scheduling is not configured.