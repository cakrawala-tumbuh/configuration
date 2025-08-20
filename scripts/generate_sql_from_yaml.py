#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generator SQL PostgreSQL dari YAML struktur_data yang mengikuti panduan_struktur_data.md.

Skema YAML (ringkas):
- spec_version: "1.x" (opsional)
- entity:
    name: "Guru"                         # Nama human readable
    technical_name: "guru"               # snake_case; default dari nama file
    schema: "public"                     # override schema (opsional)
    comment: "..."                       # komentar tabel (opsional)
- fields:                                # Wajib: list
  - name: "Nama Lengkap"                 # label human
    technical_name: "name"               # snake_case kolom; wajib
    type: "text|uuid|integer|varchar|..."# wajib; 'serial' dilarang
    length: 255                          # opsional untuk varchar/char
    not_null: true|false                 # default false
    unique: true|false                   # default false
    pk: true|false                       # maks 1 kolom pk atau gunakan 'primary_key' root (opsional)
    default: "..."                       # literal default
    generated: "uuid_v4"                 # jika uuid otomatis
    fk:                                  # opsional (untuk *_id disarankan)
      ref_table: "siswa"                 # wajib untuk fk
      ref_field: "id"                    # default "id"
      on_delete: "cascade|restrict|set null|no action|set default"
      on_update: "cascade|restrict|no action|set null|set default"
      deferrable: "deferrable initially deferred|deferrable|not deferrable"
    comment: "..."                       # komentar kolom
- constraints:                           # opsional
  - name: "ck_positive"
    expression: "check (nilai >= 0)"
- indexes:                               # opsional
  - name: "idx_guru_name"
    columns: ["name"]
    unique: false
    method: "btree"                      # btree/hash/gin/gist/brin
    where: "..."                         # partial index
"""

import argparse
import sys
import os
import glob
from typing import Any, Dict, List, Optional

import yaml

ALLOWED_TYPES = {
    "integer","bigint","smallint",
    "uuid",
    "text","varchar","char",
    "date","timestamp","timestamptz","time","timetz",
    "boolean",
    "numeric","decimal","float","double","real",
    "json","jsonb",
}

def snake(s: str) -> str:
    return s

def to_bool(v: Any, default: bool=False) -> bool:
    if v is None: return default
    if isinstance(v, bool): return v
    s = str(v).strip().lower()
    return s in {"1","true","yes","y","on"}

def qident(name: str) -> str:
    # quote identifier if needed
    if not name:
        return name
    if not name.isidentifier() or any(c in name for c in ('-', ' ', '.')):
        return f'"{name}"'
    return name

def qliteral(val: Any) -> str:
    if val is None: return "NULL"
    if isinstance(val, bool): return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)): return str(val)
    s = str(val).replace("'", "''")
    return f"'{s}'"

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def detect_table_name(yaml_path: str, entity_block: Dict[str, Any]) -> str:
    # technical_name > file stem
    tech = (entity_block or {}).get("technical_name")
    if isinstance(tech, str) and tech.strip():
        return tech.strip()
    return os.path.splitext(os.path.basename(yaml_path))[0]

def uuid_default_function(extensions: List[str]) -> str:
    # Pilih fungsi default UUID berdasar ekstensi
    ext = [e.strip().lower() for e in (extensions or [])]
    if "uuid-ossp" in ext:
        return "uuid_generate_v4()"
    # default ke pgcrypto jika ada
    return "gen_random_uuid()"

def render_column(col: Dict[str, Any], default_varchar_len: int, uuid_func: str) -> Dict[str, Any]:
    name = col.get("technical_name") or col.get("name")
    if not name:
        raise ValueError("Field tanpa technical_name/name")
    typ = (col.get("type") or "").lower()
    if not typ:
        raise ValueError(f"Field {name}: 'type' wajib diisi")
    if typ == "serial":
        raise ValueError(f"Field {name}: 'serial' tidak diperbolehkan")
    if typ not in ALLOWED_TYPES:
        # izinkan varchar(N)/char(N)
        if typ.startswith("varchar") or typ.startswith("char"):
            pass
        else:
            raise ValueError(f"Field {name}: tipe '{typ}' tidak dikenal")

    pieces = []
    # length handling
    length = col.get("length")
    if typ in {"varchar","char"}:
        n = int(length) if length is not None else int(default_varchar_len)
        type_sql = f"{typ}({n})"
    else:
        type_sql = typ

    pieces.append(f"{qident(name)} {type_sql}")

    # generated uuid
    gen = (col.get("generated") or "").lower()
    if gen == "uuid_v4":
        pieces.append(f"DEFAULT {uuid_func}")

    # default literal
    if col.get("default") is not None and not gen:
        pieces.append(f"DEFAULT {qliteral(col['default'])}")

    if to_bool(col.get("not_null")):
        pieces.append("NOT NULL")
    if to_bool(col.get("unique")):
        pieces.append("UNIQUE")

    return {
        "name": name,
        "sql": " ".join(pieces),
        "pk": to_bool(col.get("pk")),
        "fk": col.get("fk"),
        "comment": col.get("comment"),
    }

def build_table_sql(doc: Dict[str, Any], yaml_path: str, schema: str, owner: Optional[str],
                    default_varchar_len: int, tablespace: Optional[str], extensions: List[str]) -> List[str]:
    entity = doc.get("entity") or {}
    fields = doc.get("fields") or []
    constraints = doc.get("constraints") or []
    indexes = doc.get("indexes") or []

    if not isinstance(fields, list) or not fields:
        raise ValueError("List 'fields' wajib dan tidak boleh kosong")

    table_schema = entity.get("schema") or schema
    table_name = detect_table_name(yaml_path, entity)
    table_comment = entity.get("comment")

    uuid_func = uuid_default_function(extensions)

    # columns
    col_defs = []
    primary_cols = []
    fk_defs = []
    col_comments = {}

    for f in fields:
        rendered = render_column(f, default_varchar_len, uuid_func)
        col_defs.append(rendered["sql"])
        if rendered["pk"]:
            primary_cols.append(rendered["name"])
        if rendered["fk"]:
            fk = rendered["fk"] or {}
            ref_table = fk.get("ref_table")
            ref_field = fk.get("ref_field", "id")
            if not ref_table:
                raise ValueError(f"Field {rendered['name']}: fk.ref_table wajib")
            fk_sql = f"FOREIGN KEY ({qident(rendered['name'])}) REFERENCES {qident(ref_table)}({qident(ref_field)})"
            if fk.get("on_delete"):
                fk_sql += f" ON DELETE {fk['on_delete'].upper()}"
            if fk.get("on_update"):
                fk_sql += f" ON UPDATE {fk['on_update'].upper()}"
            if fk.get("deferrable"):
                fk_sql += f" {fk['deferrable'].upper()}"
            fk_defs.append(fk_sql)
        if rendered["comment"]:
            col_comments[rendered["name"]] = rendered["comment"]

    if len(primary_cols) > 1:
        raise ValueError(f"PK lebih dari satu kolom: {primary_cols}")

    # Table DDL
    lines = []
    # Extensions
    if extensions:
        for ext in extensions:
            ext = ext.strip()
            if ext:
                lines.append(f"CREATE EXTENSION IF NOT EXISTS {qident(ext)};")

    # DROP
    lines.append(f"DROP TABLE IF EXISTS {qident(table_schema)}.{qident(table_name)} CASCADE;")

    # CREATE
    ddl_cols = []
    ddl_cols.extend(col_defs)
    if primary_cols:
        cols = ", ".join(qident(c) for c in primary_cols)
        ddl_cols.append(f"PRIMARY KEY ({cols})")
    ddl_cols.extend(fk_defs)

    tbl = f"CREATE TABLE {qident(table_schema)}.{qident(table_name)} (\n    " + ",\n    ".join(ddl_cols) + "\n);"
    lines.append(tbl)

    if tablespace:
        lines.append(f"ALTER TABLE {qident(table_schema)}.{qident(table_name)} SET TABLESPACE {qident(tablespace)};")

    if owner:
        lines.append(f"ALTER TABLE {qident(table_schema)}.{qident(table_name)} OWNER TO {qident(owner)};")

    # constraints (raw)
    for c in constraints:
        cname = c.get("name")
        expr = c.get("expression")
        if cname and expr:
            lines.append(f"ALTER TABLE {qident(table_schema)}.{qident(table_name)} ADD CONSTRAINT {qident(cname)} {expr};")

    # indexes
    for idx in indexes:
        iname = idx.get("name")
        cols = idx.get("columns") or []
        unique = to_bool(idx.get("unique"))
        method = idx.get("method")
        where = idx.get("where")
        if not iname or not cols:
            continue
        uniq = "UNIQUE " if unique else ""
        meth = f"USING {method.upper()} " if method else ""
        col_list = ", ".join(qident(c) for c in cols)
        where_sql = f" WHERE {where}" if where else ""
        lines.append(f"CREATE {uniq}INDEX {qident(iname)} ON {qident(table_schema)}.{qident(table_name)} {meth}({col_list}){where_sql};")

    # comments
    if table_comment:
        lines.append(f"COMMENT ON TABLE {qident(table_schema)}.{qident(table_name)} IS {qliteral(table_comment)};")
    for cname, cmt in col_comments.items():
        lines.append(f"COMMENT ON COLUMN {qident(table_schema)}.{qident(table_name)}.{qident(cname)} IS {qliteral(cmt)};")

    return lines

def main():
    ap = argparse.ArgumentParser(description="Generate SQL dari struktur_data (panduan_struktur_data.md)")
    ap.add_argument("--struktur-dir", default="struktur_data")
    ap.add_argument("--out", default="build.sql")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--owner", default="")
    ap.add_argument("--with-drop", default="false")
    ap.add_argument("--default-varchar-length", default="255")
    ap.add_argument("--tablespace", default="")
    ap.add_argument("--create-extensions", default="")
    ap.add_argument("--strict", action="store_true", help="Stop saat ada kesalahan")
    args = ap.parse_args()

    struktur_dir = args.struktur_dir
    out_path = args.out
    schema = args.schema or "public"
    owner = args.owner or None
    with_drop = to_bool(args.with_drop)
    default_varchar_len = int(args.default_varchar_length)
    tablespace = args.tablespace or None
    extensions = [x.strip() for x in (args.create_extensions.split(",") if args.create_extensions else []) if x.strip()]

    yaml_paths = sorted(glob.glob(os.path.join(struktur_dir, "*.yml")) + glob.glob(os.path.join(struktur_dir, "*.yaml")))
    if not yaml_paths:
        print(f"Tidak ada file YAML di {struktur_dir}", file=sys.stderr)
        sys.exit(1)

    all_lines: List[str] = []

    for yp in yaml_paths:
        try:
            doc = load_yaml(yp)
            # transisi: dukung format lama -> map ke format panduan minimal
            if "entity" not in doc and "fields" not in doc and "columns" in doc:
                # konversi kasar
                entity_block = {
                    "technical_name": doc.get("table") or os.path.splitext(os.path.basename(yp))[0],
                    "comment": doc.get("description",""),
                }
                new_fields = []
                for col in doc.get("columns") or []:
                    f = {
                        "name": col.get("label") or col.get("name"),
                        "technical_name": col.get("name"),
                        "type": str(col.get("type","")).lower(),
                        "not_null": not bool(col.get("nullable", True)),
                        "unique": bool(col.get("unique", False)),
                        "pk": bool(col.get("primary_key", False)),
                        "default": col.get("default"),
                        "comment": col.get("comment"),
                    }
                    # map FK dari constraints/foreign key sederhana jika tersedia
                    # dan/atau ref_table pada format lain
                    if "ref_table" in col:
                        f["fk"] = {"ref_table": col["ref_table"], "ref_field": col.get("ref_field","id")}
                    new_fields.append(f)
                doc = {
                    "entity": entity_block,
                    "fields": new_fields,
                    "constraints": doc.get("constraints") or [],
                    "indexes": [],
                }

            lines = build_table_sql(doc, yp, schema=schema, owner=owner,
                                    default_varchar_len=default_varchar_len,
                                    tablespace=tablespace, extensions=extensions)

            # with_drop is already applied inside build_table_sql by default; if user disabled, we can strip it
            if not with_drop:
                lines = [ln for ln in lines if not ln.startswith("DROP TABLE IF EXISTS ")]

            all_lines.extend(lines)
            all_lines.append("")

        except Exception as e:
            print(f"[ERROR] {os.path.basename(yp)}: {e}", file=sys.stderr)
            if args.strict:
                sys.exit(1)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines).rstrip() + "\n")

    print(f"Selesai. SQL ditulis ke {out_path} (total baris: {sum(1 for _ in open(out_path,'r',encoding='utf-8'))}).")

if __name__ == "__main__":
    main()
