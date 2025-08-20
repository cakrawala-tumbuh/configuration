#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generator SQL STRICT sesuai panduan_struktur_data.md dengan 5 fase output:

1) CREATE EXTENSION (unique, sekali di atas)
2) CREATE TABLE (semua tabel)
3) Non-FK constraints: PRIMARY KEY, UNIQUE, CHECK
4) FOREIGN KEY (setelah semua tabel ada)
5) INDEX, COMMENT, ALTER OWNER

Aturan STRICT (patuh panduan):
- Wajib keys: entity, fields (constraints?, indexes?, comment?)
- entity.technical_name: snake_case dan HARUS sama dengan nama file (tanpa .yaml)
- Tepat satu field dengan pk: true
- Setiap kolom yang berakhiran *_id WAJIB punya fk.ref_table (atau references.table/ref_table)
- Tipe kolom ditulis apa adanya (contoh: varchar(100), numeric(12,2), timestamp, uuid, bigint)
- Default khusus:
  - generated == "uuid_v4" & type == uuid  -> DEFAULT gen_random_uuid()
  - default == "generated always as identity" & type integer/bigint/smallint -> GENERATED ALWAYS AS IDENTITY

CLI:
  --src <dir>            : direktori struktur_data
  --schema <name>        : nama schema (default: public)
  --owner <name>         : owner tabel (opsional)
  --with-drop true|false : DROP TABLE IF EXISTS (default: false)
  --tablespace <name>    : TABLESPACE untuk index (opsional)
  --create-extensions    : daftar ekstensi, koma-sep (default: pgcrypto)
  --validate-only true|false : hanya validasi, tidak cetak SQL (default: false)
"""
import argparse, os, sys, re, yaml
from typing import Any, Dict, List, Optional, Tuple

SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

def is_snake_case(s: str) -> bool:
    return bool(SNAKE_CASE_RE.match(s))

def sql_literal(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    # izinkan fungsi/keyword umum
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(", s) or s.upper() in {"CURRENT_DATE", "CURRENT_TIMESTAMP"}:
        return s
    return "'" + s.replace("'", "''") + "'"

def load_yaml_files(src: str):
    items = []
    for root, _, files in os.walk(src):
        for fn in sorted(files):
            if fn.endswith((".yml", ".yaml")):
                path = os.path.join(root, fn)
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                items.append((path, data))
    return items

def extract_fk_info(f: Dict[str, Any]) -> Tuple[Optional[str], str, str]:
    """
    Kembalikan (ref_table, on_delete, on_update).
    Mencari di:
      - f["fk"].ref_table / f["fk"].table
      - f["ref_table"]
      - f["references"].table/ref_table
    """
    ref_table = None
    on_delete = "NO ACTION"
    on_update = "NO ACTION"
    if isinstance(f.get("fk"), dict):
        ref_table = f["fk"].get("ref_table") or f["fk"].get("table")
        on_delete = f["fk"].get("on_delete", on_delete)
        on_update = f["fk"].get("on_update", on_update)
    elif "ref_table" in f:
        ref_table = f.get("ref_table")
    elif isinstance(f.get("references"), dict):
        ref_table = f["references"].get("table") or f["references"].get("ref_table")
        on_delete = f["references"].get("on_delete", on_delete)
        on_update = f["references"].get("on_update", on_update)
    return ref_table, on_delete, on_update

def validate_model(path: str, data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not isinstance(data, dict):
        return ["Root harus mapping/dict."]
    if "entity" not in data or "fields" not in data:
        return ["Wajib ada key 'entity' dan 'fields' (STRICT)."]
    ent = data["entity"]
    if not isinstance(ent, dict):
        return ["'entity' harus mapping."]
    tname = ent.get("technical_name")
    if not tname or not is_snake_case(tname):
        errs.append("entity.technical_name wajib snake_case.")
    # Nama file harus sama dengan technical_name
    stem = os.path.splitext(os.path.basename(path))[0]
    if tname and stem != tname:
        errs.append(f"Nama file '{stem}' harus sama dengan entity.technical_name '{tname}'.")
    # Fields
    fields = data.get("fields")
    if not isinstance(fields, list) or not fields:
        errs.append("fields harus list dan minimal 1.")
        return errs
    pk_count = 0
    for f in fields:
        col = f.get("technical_name")
        if not col or not is_snake_case(col):
            errs.append(f"Kolom wajib snake_case: {col!r}")
        if "type" not in f:
            errs.append(f"{col}: field 'type' wajib.")
        if f.get("pk") is True:
            pk_count += 1
        # Kewajiban FK untuk *_id
        if col and col.endswith("_id"):
            ref_table, _, _ = extract_fk_info(f)
            if not ref_table:
                errs.append(f"{col}: wajib fk.ref_table (atau references.table/ref_table).")
    if pk_count != 1:
        errs.append(f"Tepat satu field pk:true diperlukan (sekarang {pk_count}).")
    return errs

def build_sql_fragments(path: str, data: Dict[str, Any], args):
    """Kembalikan dict berisi potongan SQL per fase untuk satu tabel."""
    schema = args.schema
    ent = data["entity"]
    tbl = ent["technical_name"]
    fqtn = f'"{schema}"."{tbl}"'

    fragments = {
        "drop": [],
        "create_table": [],
        "non_fk_constraints": [],
        "fks": [],
        "indexes": [],
        "comments": [],
        "owner": [],
    }

    # DROP
    if str(args.with_drop).lower() == "true":
        fragments["drop"].append(f"DROP TABLE IF EXISTS {fqtn} CASCADE;")

    # Kolom
    col_defs: List[str] = []
    for f in data["fields"]:
        col = f["technical_name"]
        typ = str(f["type"]).strip()
        coldef = f'"{col}" {typ}'

        # generated/default khusus
        gen = (f.get("generated") or "").strip().lower() if f.get("generated") is not None else ""
        default = f.get("default")
        if gen == "uuid_v4" and typ.lower().startswith("uuid"):
            coldef += " DEFAULT gen_random_uuid()"
        if isinstance(default, str) and default.strip().lower() == "generated always as identity":
            if any(typ.lower().startswith(x) for x in ("integer", "bigint", "smallint")):
                coldef += " GENERATED ALWAYS AS IDENTITY"
                default = None
        if default is not None:
            coldef += f" DEFAULT {sql_literal(default)}"
        if f.get("not_null") is True:
            coldef += " NOT NULL"

        col_defs.append(coldef)

    # CREATE TABLE (tanpa constraints)
    fragments["create_table"].append(f"CREATE TABLE {fqtn} (\n  " + ",\n  ".join(col_defs) + "\n);")

    # PRIMARY KEY
    pk_cols = [f["technical_name"] for f in data["fields"] if f.get("pk") is True]
    if pk_cols:
        pk = ", ".join(f'"{c}"' for c in pk_cols)
        fragments["non_fk_constraints"].append(f'ALTER TABLE {fqtn} ADD CONSTRAINT "{tbl}__pk" PRIMARY KEY ({pk});')

    # UNIQUE dari field.unique == true
    uq_i = 0
    for f in data["fields"]:
        if f.get("unique") is True:
            uq_i += 1
            fragments["non_fk_constraints"].append(
                f'ALTER TABLE {fqtn} ADD CONSTRAINT "{tbl}__uq_{uq_i}" UNIQUE ("{f["technical_name"]}");'
            )

    # CHECK constraints
    ck_i = 0
    for c in (data.get("constraints") or []):
        expr = c.get("expression") if isinstance(c, dict) else None
        if expr:
            ck_i += 1
            fragments["non_fk_constraints"].append(
                f'ALTER TABLE {fqtn} ADD CONSTRAINT "{tbl}__ck_{ck_i}" CHECK ({expr});'
            )

    # Foreign keys (disimpan untuk fase 4)
    for f in data["fields"]:
        col = f["technical_name"]
        ref_table, on_delete, on_update = extract_fk_info(f)
        if ref_table:
            fk_name = f'{tbl}__{col}__fk'
            fragments["fks"].append(
                f'ALTER TABLE {fqtn} ADD CONSTRAINT "{fk_name}" FOREIGN KEY ("{col}") '
                f'REFERENCES "{schema}"."{ref_table}" ("id") '
                f"ON DELETE {on_delete} ON UPDATE {on_update};"
            )

    # Indexes
    ix_i = 0
    for idx in (data.get("indexes") or []):
        cols = idx.get("columns")
        if isinstance(cols, list) and cols:
            ix_i += 1
            cols_str = ", ".join(f'"{c}"' for c in cols)
            method = f' USING {idx["method"]}' if idx.get("method") else ""
            where = f' WHERE {idx["where"]}' if idx.get("where") else ""
            ts = f' TABLESPACE {args.tablespace}' if args.tablespace else ""
            name = f'{tbl}__ix_{ix_i}'
            if idx.get("unique"):
                fragments["indexes"].append(
                    f'CREATE UNIQUE INDEX "{name}" ON {fqtn}{method} ({cols_str}){where}{ts};'
                )
            else:
                fragments["indexes"].append(
                    f'CREATE INDEX "{name}" ON {fqtn}{method} ({cols_str}){where}{ts};'
                )

    # Comments
    tcomment = data.get("comment") or ent.get("comment")
    if tcomment:
        fragments["comments"].append(f"COMMENT ON TABLE {fqtn} IS {sql_literal(tcomment)};")
    for f in data["fields"]:
        if f.get("comment"):
            fragments["comments"].append(
                f'COMMENT ON COLUMN {fqtn}."{f["technical_name"]}" IS {sql_literal(f["comment"])};'
            )

    # Owner
    if args.owner:
        fragments["owner"].append(f"ALTER TABLE {fqtn} OWNER TO {args.owner};")

    return tbl, fragments

def main():
    p = argparse.ArgumentParser(description="Generate SQL STRICT (5 fase) dari struktur_data (patuh panduan_struktur_data.md)")
    p.add_argument("--src", required=True, help="Direktori struktur_data")
    p.add_argument("--schema", default="public")
    p.add_argument("--owner", default="")
    p.add_argument("--with-drop", default="false")
    p.add_argument("--tablespace", default="")
    p.add_argument("--create-extensions", default="pgcrypto")
    p.add_argument("--validate-only", default="false")
    args = p.parse_args()

    files = load_yaml_files(args.src)
    all_errs = {}
    for path, data in files:
        errs = validate_model(path, data)
        if errs:
            all_errs[path] = errs

    validating = str(args.validate_only).lower() == "true"

    if validating:
        if all_errs:
            for path, errs in all_errs.items():
                print(f"[INVALID] {os.path.relpath(path, args.src)}", file=sys.stderr)
                for e in errs:
                    print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("Validasi OK", file=sys.stderr)
            return

    # Generate hanya bila tidak ada error
    if all_errs:
        for path, errs in all_errs.items():
            print(f"[INVALID] {os.path.relpath(path, args.src)}", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Kumpulkan potongan per tabel
    drops, create_tables = [], []
    non_fk_constraints, fks = [], []
    indexes, comments, owners = [], [], []

    # Ekstensi (unique)
    extensions = []
    if args.create_extensions:
        for ext in str(args.create_extensions).split(","):
            ext = ext.strip()
            if ext and ext not in extensions:
                extensions.append(ext)

    table_names: List[str] = []

    for path, data in files:
        tbl, frags = build_sql_fragments(path, data, args)
        table_names.append(tbl)
        drops.extend(frags["drop"])
        create_tables.extend(frags["create_table"])
        non_fk_constraints.extend(frags["non_fk_constraints"])
        fks.extend(frags["fks"])
        indexes.extend(frags["indexes"])
        comments.extend(frags["comments"])
        owners.extend(frags["owner"])

    # Cetak dalam 5 fase
    # Header
    print("-- =================================================================")
    print("--  GENERATED BY generate_sql_from_yaml.py (STRICT, 5 PHASES)      ")
    print("-- =================================================================")
    print(f"--  Tables: {', '.join(sorted(table_names))}")
    print()

    # 1) Extensions
    for ext in extensions:
        print(f"CREATE EXTENSION IF NOT EXISTS {ext};")
    if extensions:
        print()

    # 2) CREATE TABLES (+ optional DROPs di atasnya agar jelas urutannya)
    for stmt in drops:
        print(stmt)
    if drops:
        print()
    for stmt in create_tables:
        print(stmt)
    if create_tables:
        print()

    # 3) NON-FK CONSTRAINTS
    for stmt in non_fk_constraints:
        print(stmt)
    if non_fk_constraints:
        print()

    # 4) FOREIGN KEYS
    for stmt in fks:
        print(stmt)
    if fks:
        print()

    # 5) INDEXES, COMMENTS, OWNERS
    for stmt in indexes:
        print(stmt)
    if indexes:
        print()
    for stmt in comments:
        print(stmt)
    if comments:
        print()
    for stmt in owners:
        print(stmt)

if __name__ == "__main__":
    main()
