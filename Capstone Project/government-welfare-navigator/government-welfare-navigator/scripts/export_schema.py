"""Generate database_schema.sql (MySQL DDL) from the SQLAlchemy models.

Usage:  python scripts/export_schema.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.extensions import db
import app.models  # noqa: F401  (registers tables)

out = ["-- Generated from SQLAlchemy models. MySQL 8 / utf8mb4.",
       "CREATE DATABASE IF NOT EXISTS welfare_navigator CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
       "USE welfare_navigator;", ""]
for table in db.metadata.sorted_tables:
    out.append(str(CreateTable(table).compile(dialect=mysql.dialect())).strip() + ";")
    for idx in sorted(table.indexes, key=lambda i: i.name or ""):
        out.append(str(CreateIndex(idx).compile(dialect=mysql.dialect())).strip() + ";")
    out.append("")
path = os.path.join(os.path.dirname(__file__), "..", "database_schema.sql")
with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("Wrote", os.path.abspath(path))
