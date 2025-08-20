#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generator SQL dari YAML sesuai panduan_struktur_data.md
"""

import argparse
import os
import re
import sys
import yaml
from typing import Any, Dict, List

SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

VALID_TYPES = {
    "text": "text",
    "varchar": "varchar",
    "char": "char",
    "integer": "integer",
    "bigint": "bigint",
    "smallint": "smallint",
    "numeric": "numeric",
    "decimal": "decimal",
    "real": "real",
    "double": "double precision",
    "timestamp": "timestamp",
    "timestamptz": "timestamp with time zone",
    "date": "date",
    "boolean": "boolean",
    "uuid": "uuid",
}

def fail(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def is_snake_case(name: str) -> bool:
    return bool(SNAKE_CASE_RE.match(name))

def load_yaml_files(src: str) -> List[Dict[str, Any]]:
    items = []
    for root, _, files in os.walk(src):
        for fn in sorted(files):
            if fn.endswith((".yml", ".yaml")):
                path = os.path.join(root, fn)
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    fail(f"File YAML harus mapping: {path}")
                data["_path"] = path
                items.append(data)
    return items

def sql_literal(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    return "'" + str(val).replace("'", "''") + "'"

def render_table(data: Dict[str, Any], args) -> str:
    entity = data.get("entity", {})
    name = entity.get("technical_name")
    if not name or not is_snake_case(name):
        fail(f"[{data['_path']}] entity.technical_name wajib snake_case")

    fields = data.get("fields", [])
    if not fields:
        fail(f"[{data['_path']}] harus ada fields")

    pk_cols = [f["name"] for f in fields if f.get("pk")]
    if len(pk_cols) != 1:
        fail(f"[{data['_path']}] harus ada tepat satu pk: true")

    schema = args.schema
    fqtn = f'"{schema}"."{name}"'
    lines = []

    # CREATE EXTENSIONS
    stmts = []
    if args.create_extensions:
        for ext in args.create_extensions.split(","):
            ext = ext.strip()
            if ext:
                stmts.append(f"CREATE EXTENSION IF NOT EXISTS {ext};")

    # DROP
    if args.with_drop.lower() == "true":
        stmts.append(f"DROP TABLE IF EXISTS {fqtn} CASCADE;")

    # CREATE TABLE
    col_defs = []
    comments = []
    for f in fields:
        col = f["name"]
        if not is_snake_case(col):
            fail(f"[{data['_path']}] nama kolom harus snake_case: {col}")
        t = f.get("type")
        if t not in VALID_TYPES:
            fail(f"[{data['_path']}] tipe tidak valid: {t}")
        sqlt = VALID_TYPES[t]

        if t in ("varchar", "char"):
            length = f.get("length")
            if not length:
                length = args.default_varchar_length
            sqlt += f"({length})"

        coldef = f'"{col}" {sqlt}'

        if f.get("generated") == "uuid_v4" and t == "uuid":
            coldef += " DEFAULT gen_random_uuid()"
        elif f.get("generated") == "identity" and t in ("integer", "bigint", "smallint"):
            coldef += " GENERATED ALWAYS AS IDENTITY"

        if f.get("default") is not None:
            coldef += f" DEFAULT {sql_literal(f['default'])}"

        if not f.get("nullable", True):
            coldef += " NOT NULL"

        col_defs.append(coldef)

        if "comment" in f:
            cmt = sql_literal(f["comment"])
            comments.append(f'COMMENT ON COLUMN {fqtn}."{col}" IS {cmt};')
