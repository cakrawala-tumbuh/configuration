#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import glob
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def to_bool(val: Any, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}

def qident(name: str) -> str:
    """
    Quote identifier if needed; keep simple to avoid edge cases.
    """
    if re.fullmatch(r"[a-z_][a-z0-9_]*", name or ""):
        return name
    return '"' + name.replace('"', '""') + '"'

def qliteral(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    return "'" + s.replace("'", "''") + "'"

def normalize_pg_type(col: Dict[str, Any], default_varchar_len: int) -> str:
    """
    Normalize YAML type declarations to PostgreSQL SQL types.
    Supports:
      - "varchar", optional "length"
      - "text", "uuid", "int"/"integer", "bigint", "numeric", "boolean"/"bool",
        "date", "timestamp", "timestamptz"
      - enum:<name>  (handled as "enum::<name>" marker; actual CREATE TYPE generated elsewhere)
      - json, jsonb
    """
    t = (col.get("type") or "").strip().lower()

    if t.startswith("enum:"):
        enum_name = t.split(":", 1)[1].strip()
        return f"enum::{enum_name}"

    if t in {"varchar", "character varying"}:
        length = col.get("length")
        if isinstance(length, int) and length > 0:
            return f"varchar({length})"
        return f"varchar({default_varchar_len})"
    if t in {"text"}:
        return "text"
    if t in {"uuid"}:
        return "uuid"
    if t in {"int", "integer"}:
        return "integer"
    if t in {"bigint"}:
        return "bigint"
    if t in {"numeric", "decimal"}:
        precision = col.get("precision")
        scale = col.get("scale")
        if isinstance(precision, int) and isinstance(scale, int):
            return f"numeric({precision},{scale})"
        return "numeric"
    if t in {"boolean", "bool"}:
        return "boolean"
    if t in {"date"}:
        return "date"
    if t in {"timestamp"}:
        return "timestamp"
    if t in {"timestamptz", "timestamp with time zone"}:
        return "timestamptz"
    if t in {"jsonb"}:
        return "jsonb"
    if t in {"json"}:
        return "json"

    # fallback: return as-is
    return t or f"varchar({default_varchar_len})"

def parse_yaml_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def collect_yaml_files(root: str) -> List[str]:
    files = []
    for ext in ("*.yaml", "*.yml"):
        files.extend(glob.glob(os.path.join(root, "**", ext), recursive=True))
    return sorted(files)

# ---------------------------------------------------------------------------
# SQL generators
# ---------------------------------------------------------------------------

def gen_drop_stmt(object_type: str, fqname: str) -> str:
    return f"DROP {object_type} IF EXISTS {fqname} CASCADE;"

def gen_create_enum(enum_name: str, values: List[str], with_drop: bool, schema: str, owner: Optional[str]) -> str:
    fqname = f"{qident(schema)}.{qident(enum_name)}"
    stmts = []
    if with_drop:
        stmts.append(gen_drop_stmt("TYPE", fqname))
    vals = ", ".join(qliteral(v) for v in values)
    stmts.append(f"CREATE TYPE {fqname} AS ENUM ({vals});")
    if owner:
        stmts.append(f"ALTER TYPE {fqname} OWNER TO {qident(owner)};")
    return "\n".join(stmts)

def column_line(col: Dict[str, Any], default_varchar_len: int) -> Tuple[str, Optional[str]]:
    """
    Return (column_ddl, generated_constraint) where generated_constraint may be inline (None if not).
    """
    name = col.get("name")
    if not name:
        raise ValueError("Kolom tanpa 'name' terdeteksi.")
    t = normalize_pg_type(col, default_varchar_len)
    nullable = col.get("nullable", True)
    default = col.get("default")
    comment = col.get("comment")

    line = f"{qident(name)} "

    if t.startswith("enum::"):
        # Refer to enum type in schema-qualified form later; placeholder type name will be replaced upstream.
        enum_name = t.split("::", 1)[1]
        line += f"{qident(enum_name)}"
    else:
        line += t

    if not nullable:
        line += " NOT NULL"

    if default is not None:
        # allow raw function default with marker :raw (e.g. {default: "now():raw"})
        sdef = str(default)
        if sdef.endswith(":raw"):
            line += f" DEFAULT {sdef[:-4]}"
        else:
            line += f" DEFAULT {qliteral(default)}"

    return line, comment

def gen_table_sql(obj: Dict[str, Any], schema: str, owner: Optional[str], with_drop: bool,
                  default_varchar_len: int, tablespace: Optional[str]) -> Tuple[str, List[str]]:
    """
    Returns (SQL, enum_decls_needed) for a table object.
    Expected keys in obj:
      - name (str)  -> table name
      - schema (str, optional)
      - columns (list of {name, type, ...})
      - primary_key (list of column names) OR per-column primary_key: true
      - uniques (list of list-of-cols OR list of names)
      - indexes (list of {name?, columns, using?, unique?})
      - checks (list of raw check expressions)
      - references / foreign_keys: list of {columns, ref_table, ref_columns?, on_delete?, on_update?, deferrable?, initially_deferred?}
      - comment (str)
    """
    enum_needed: List[str] = []

    # Resolve schema
    sch = (obj.get("schema") or schema).strip()
    tname = obj.get("name")
    if not tname:
        raise ValueError("Objek table tanpa 'name'.")

    fqname = f"{qident(sch)}.{qident(tname)}"
    columns = obj.get("columns") or []
    if not isinstance(columns, list) or not columns:
        raise ValueError(f"Tabel {tname}: 'columns' kosong atau tidak valid.")

    # Collect enum usage and build column lines
    col_lines: List[str] = []
    col_comments: List[Tuple[str, str]] = []
    for c in columns:
        line, comment = column_line(c, default_varchar_len)
        # If enum::<name> appears, ensure we record it and replace with schema-qualified name:
        if "enum::" in line:
            m = re.search(r"enum::([a-zA-Z0-9_]+)", line)
            if m:
                enum_name = m.group(1)
                enum_needed.append(enum_name)
                # Replace placeholder with schema-qualified enum
                line = line.replace(f"enum::{enum_name}", f"{qident(sch)}.{qident(enum_name)}")
        col_lines.append(line)
        if comment:
            col_comments.append((c.get("name", ""), comment))

    # Primary key
    pk_cols = []
    explicit_pk = obj.get("primary_key")
    if explicit_pk:
        if isinstance(explicit_pk, list):
            pk_cols = explicit_pk
        else:
            raise ValueError(f"Tabel {tname}: 'primary_key' harus list.")
    else:
        # per-column pk
        for c in columns:
            if to_bool(c.get("primary_key", False), False):
                pk_cols.append(c["name"])

    # Uniques
    uniques = obj.get("uniques") or []
    unique_groups: List[List[str]] = []
    for u in uniques:
        if isinstance(u, list):
            unique_groups.append(u)
        elif isinstance(u, str):
            unique_groups.append([u])
        else:
            raise ValueError(f"Tabel {tname}: elemen 'uniques' tidak valid.")

    # Checks
    checks = obj.get("checks") or []
    check_lines: List[str] = []
    for ch in checks:
        # raw SQL expression for CHECK
        check_lines.append(f"CHECK ({ch})")

    # Foreign keys
    fks = obj.get("foreign_keys") or obj.get("references") or []
    fk_lines: List[str] = []
    for idx, fk in enumerate(fks, start=1):
        cols = fk.get("columns") or []
        ref_table = fk.get("ref_table")
        ref_cols = fk.get("ref_columns") or []
        if not cols or not ref_table:
            raise ValueError(f"Tabel {tname}: foreign key ke-{idx} tidak valid (butuh 'columns' dan 'ref_table').")
        ref_schema = fk.get("ref_schema") or sch  # default sama schema
        line = f"FOREIGN KEY ({', '.join(qident(c) for c in cols)}) REFERENCES {qident(ref_schema)}.{qident(ref_table)}"
        if ref_cols:
            line += f" ({', '.join(qident(c) for c in ref_cols)})"
        on_delete = fk.get("on_delete")
        on_update = fk.get("on_update")
        if on_delete:
            line += f" ON DELETE {on_delete.upper()}"
        if on_update:
            line += f" ON UPDATE {on_update.upper()}"
        if to_bool(fk.get("deferrable", False), False):
            line += " DEFERRABLE"
            if to_bool(fk.get("initially_deferred", False), False):
                line += " INITIALLY DEFERRED"
        fk_lines.append(line)

    # Compose CREATE TABLE
    pre = []
    if with_drop:
        pre.append(gen_drop_stmt("TABLE", fqname))

    body_parts: List[str] = []
    body_parts.extend(col_lines)

    if pk_cols:
        body_parts.append(f"PRIMARY KEY ({', '.join(qident(c) for c in pk_cols)})")

    for ug in unique_groups:
        body_parts.append(f"UNIQUE ({', '.join(qident(c) for c in ug)})")

    body_parts.extend(check_lines)
    body_parts.extend(fk_lines)

    create_line = f"CREATE TABLE {fqname} (\n    " + ",\n    ".join(body_parts) + "\n)"
    if tablespace:
        create_line += f" TABLESPACE {qident(tablespace)}"
    create_line += ";"

    stmts: List[str] = []
    stmts.extend(pre)
    stmts.append(create_line)

    # Comments
    t_comment = obj.get("comment")
    if t_comment:
        stmts.append(f"COMMENT ON TABLE {fqname} IS {qliteral(t_comment)};")
    for col_name, cmt in col_comments:
        stmts.append(f"COMMENT ON COLUMN {fqname}.{qident(col_name)} IS {qliteral(cmt)};")

    # Indexes
    indexes = obj.get("indexes") or []
    for i, idx in enumerate(indexes, start=1):
        cols = idx.get("columns") or []
        if not cols:
            continue
        iname = idx.get("name") or f"{tname}_{i}_idx"
        using = idx.get("using")
        unique = to_bool(idx.get("unique", False), False)
        line = "CREATE "
        if unique:
            line += "UNIQUE "
        line += f"INDEX {qident(iname)} ON {fqname}"
        if using:
            line += f" USING {using}"
        line += f" ({', '.join(qident(c) for c in cols)});"
        if tablespace:
            line = line[:-1] + f" TABLESPACE {qident(tablespace)};"
        stmts.append(line)

    # Owner
    if owner:
        stmts.append(f"ALTER TABLE {fqname} OWNER TO {qident(owner)};")

    return "\n".join(stmts), enum_needed

def gen_view_sql(obj: Dict[str, Any], schema: str, owner: Optional[str], with_drop: bool, materialized: bool) -> str:
    sch = (obj.get("schema") or schema).strip()
    name = obj.get("name")
    if not name:
        raise ValueError("Objek view tanpa 'name'.")
    fqname = f"{qident(sch)}.{qident(name)}"
    sql_text = obj.get("sql") or obj.get("definition")
    if not sql_text:
        raise ValueError(f"View {name}: butuh field 'sql' atau 'definition'.")

    pre = []
    if with_drop:
        drop_kw = "MATERIALIZED VIEW" if materialized else "VIEW"
        pre.append(gen_drop_stmt(drop_kw, fqname))

    create_kw = "CREATE MATERIALIZED VIEW" if materialized else "CREATE VIEW"
    stmt = f"{create_kw} {fqname} AS\n{sql_text.strip()};"

    post = []
    if owner:
        if materialized:
            post.append(f"ALTER MATERIALIZED VIEW {fqname} OWNER TO {qident(owner)};")
        else:
            post.append(f"ALTER VIEW {fqname} OWNER TO {qident(owner)};")

    comment = obj.get("comment")
    if comment:
        target = "MATERIALIZED VIEW" if materialized else "VIEW"
        post.append(f"COMMENT ON {target} {fqname} IS {qliteral(comment)};")

    return "\n".join(pre + [stmt] + post)

# ---------------------------------------------------------------------------
# Main compiler
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate build.sql from struktur_data YAML")
    parser.add_argument("--struktur-dir", required=True, help="Direktori akar struktur_data")
    parser.add_argument("--out", required=True, help="Output SQL file path (build.sql)")
    parser.add_argument("--schema", default="public", help="Schema default")
    parser.add_argument("--owner", default="", help="Owner default (opsional)")
    parser.add_argument("--with-drop", default="true", help="Sertakan DROP IF EXISTS")
    parser.add_argument("--default-varchar-length", default="255", help="Panjang default varchar")
    parser.add_argument("--tablespace", default="", help="Tablespace default (opsional)")
    parser.add_argument("--create-extensions", default="", help="Daftar ekstensi yang perlu dibuat (comma-separated)")
    parser.add_argument("--strict", default="false", help="Jika true, error YAML akan menghentikan proses")

    args = parser.parse_args()

    struktur_dir = args.struktur_dir
    out_path = args.out
    default_schema = args.schema.strip() or "public"
    owner = args.owner.strip() or None
    with_drop = to_bool(args.with_drop, True)
    try:
        default_varchar_len = int(args.default_varchar_length)
    except Exception:
        default_varchar_len = 255
    tablespace = args.tablespace.strip() or None
    create_extensions = [x.strip() for x in (args.create_extensions or "").split(",") if x.strip()]
    strict_mode = to_bool(args.strict, False)

    files = collect_yaml_files(struktur_dir)
    if not files:
        print(f"Tidak ditemukan file YAML di {struktur_dir}", file=sys.stderr)
        if strict_mode:
            sys.exit(1)

    # Accumulate
    enum_registry: Dict[str, List[str]] = {}  # enum_name -> values
    table_objs: List[Dict[str, Any]] = []
    view_objs: List[Tuple[Dict[str, Any], bool]] = []  # (obj, is_materialized)

    errors: List[str] = []

    for path in files:
        try:
            data = parse_yaml_file(path)
            if not isinstance(data, dict):
                raise ValueError("YAML harus berupa mapping/object.")

            kind = (data.get("kind") or data.get("type") or "table").strip().lower()
            # Normalisasi penamaan bidang umum
            if kind in {"table", "tabel"}:
                table_objs.append(data)
            elif kind in {"view"}:
                view_objs.append((data, False))
            elif kind in {"materialized_view", "mview", "mv"}:
                view_objs.append((data, True))
            elif kind in {"enum"}:
                ename = data.get("name")
                evals = data.get("values") or data.get("items")
                if not ename or not isinstance(evals, list) or not evals:
                    raise ValueError(f"Enum di {path} tidak valid (butuh 'name' dan 'values').")
                enum_registry[ename] = [str(v) for v in evals]
            else:
                # Jika ada skema lain, abaikan (tidak fatal)
                pass

        except Exception as e:
            msg = f"[ERROR] {path}: {e}"
            errors.append(msg)

    if errors:
        for m in errors:
            print(m, file=sys.stderr)
        if strict_mode:
            sys.exit(1)

    # Build SQL
    output: List[str] = []
    output.append("-- Auto-generated by scripts/generate_sql_from_yaml.py")
    output.append("-- Do not edit manually.")
    output.append("SET client_min_messages = WARNING;")
    output.append("")

    # CREATE EXTENSIONS (idempotent)
    for ext in create_extensions:
        output.append(f"CREATE EXTENSION IF NOT EXISTS {qident(ext)};")

    # Ensure default schema exists
    output.append(f"CREATE SCHEMA IF NOT EXISTS {qident(default_schema)};")
    if owner:
        output.append(f"ALTER SCHEMA {qident(default_schema)} OWNER TO {qident(owner)};")
    output.append("")

    # Enums from registry
    if enum_registry:
        for ename, vals in enum_registry.items():
            output.append(gen_create_enum(ename, vals, with_drop, default_schema, owner))
            output.append("")

    # Tables
    # Note: if a table uses enum::<name> that is NOT defined in registry, we still proceed,
    # assuming the enum exists or is defined elsewhere; strict mode would have already failed earlier if desired.
    for obj in table_objs:
        try:
            sql, _ = gen_table_sql(
                obj=obj,
                schema=default_schema,
                owner=owner,
                with_drop=with_drop,
                default_varchar_len=default_varchar_len,
                tablespace=tablespace,
            )
            output.append(sql)
            output.append("")
        except Exception as e:
            msg = f"[TABLE ERROR] {obj.get('name','<unknown>')}: {e}"
            print(msg, file=sys.stderr)
            if strict_mode:
                sys.exit(1)

    # Views & Materialized Views
    for obj, is_mv in view_objs:
        try:
            v_sql = gen_view_sql(
                obj=obj,
                schema=default_schema,
                owner=owner,
                with_drop=with_drop,
                materialized=is_mv,
            )
            output.append(v_sql)
            output.append("")
        except Exception as e:
            msg = f"[VIEW ERROR] {obj.get('name','<unknown>')}: {e}"
            print(msg, file=sys.stderr)
            if strict_mode:
                sys.exit(1)

    # Write out
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output).strip() + "\n")

    print(f"Selesai. SQL ditulis ke {out_path} (total baris: {sum(1 for _ in open(out_path,'r',encoding='utf-8'))}).")

if __name__ == "__main__":
    main()
