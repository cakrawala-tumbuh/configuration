#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_fk.py
Pemeriksa referensi Foreign Key (FK) antartabel berdasarkan berkas YAML di folder `struktur_data`.

Cara pakai:
    python3 validate_fk.py
    python3 validate_fk.py --dir struktur_data
    python3 validate_fk.py --ext .yaml .yml

Keluaran:
- Ringkasan di terminal
- Laporan detail ke fk_report.txt
- Kode keluar 0 jika semua OK; 1 jika ada referensi FK yang hilang target tabelnya; 2 jika ada kesalahan umum

Prasyarat:
- pip install pyyaml
"""
from __future__ import annotations

import argparse
import sys
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any

# --------------------------
# Utilities
# --------------------------

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def load_yaml(path: Path) -> Any:
    try:
        import yaml  # import di sini agar error message lebih jelas bila pyyaml belum terpasang
    except Exception:
        eprint("Modul 'pyyaml' belum terpasang. Instal dahulu: pip install pyyaml")
        sys.exit(2)
    try:
        text = path.read_text(encoding="utf-8")
        return yaml.safe_load(text) or {}
    except Exception as exc:
        return {"__parse_error__": f"{exc}"}

def infer_table_name(doc: Any, fallback: str) -> str:
    """
    Heuristik nama tabel:
    1) Gunakan doc['name'] jika string dan tidak kosong
    2) Jika ada doc['table'] string, pakai itu
    3) Fallback ke nama file (tanpa ekstensi)
    """
    if isinstance(doc, dict):
        n = doc.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
        t = doc.get("table")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return fallback

def iter_fields(doc: Any) -> List[Dict[str, Any]]:
    """
    Ambil daftar field dari beberapa kemungkinan struktur:
    - doc["fields"]: list of dict
    - doc["columns"]: list of dict
    - doc["schema"]["fields"]: list of dict
    - doc["schema"]["columns"]: list of dict
    Jika tidak ditemukan, kembalikan list kosong.
    """
    if not isinstance(doc, dict):
        return []

    candidates = []
    for key in ("fields", "columns"):
        val = doc.get(key)
        if isinstance(val, list):
            candidates = [x for x in val if isinstance(x, dict)]
            if candidates:
                return candidates

    schema = doc.get("schema")
    if isinstance(schema, dict):
        for key in ("fields", "columns"):
            val = schema.get(key)
            if isinstance(val, list):
                candidates = [x for x in val if isinstance(x, dict)]
                if candidates:
                    return candidates

    return []

def parse_ref_target(ref_str: str) -> str:
    """
    Ambil nama tabel dari string referensi:
    - "table"              -> table
    - "table.id"           -> table
    - "schema.table"       -> schema.table (dianggap fully-qualified)
    - "schema.table.id"    -> schema.table
    """
    s = ref_str.strip()
    if not s:
        return ""
    parts = s.split(".")
    if len(parts) == 1:
        return parts[0]
    # Jika banyak komponen, buang komponen terakhir jika diasumsikan kolom
    # Contoh: "student.id" -> "student"; "school.student.id" -> "school.student"
    return ".".join(parts[:-1])

def find_fk_targets(fields: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Deteksi kandidat FK dari beberapa pola umum. Kembalikan list (field_name, target_table).

    Pola yang didukung:
    - Nama field berakhiran _id  => target "xxx" (tanpa _id)
    - Kunci ref_table: "<tabel>"
    - Kunci references / foreign_key: "<tabel>.<kolom>" atau "<tabel>"
    - type: fk/foreign_key/reference + ref/reference/target: "<tabel>[.<kolom>]"
    - domain relational ala ORM (opsional umum):
        - relation: "<tabel>"
        - many2one: { comodel: "<tabel>" } atau { model: "<tabel>" }
    """
    fks: List[Tuple[str, str]] = []

    for f in fields:
        name = str(f.get("name", "")).strip()

        # Pola 1: xxx_id -> xxx
        if name.endswith("_id") and len(name) > 3:
            fks.append((name, name[:-3]))

        # Pola 2: ref_table
        ref_table = f.get("ref_table")
        if isinstance(ref_table, str) and ref_table.strip():
            fks.append((name or "(unnamed)", ref_table.strip()))

        # Pola 3: references / foreign_key
        for key in ("references", "foreign_key"):
            v = f.get(key)
            if isinstance(v, str) and v.strip():
                fks.append((name or f"({key})", parse_ref_target(v)))

        # Pola 4: type: fk/reference + ref/reference/target
        ftype = str(f.get("type", "")).lower()
        if ftype in ("fk", "foreign_key", "reference", "many2one"):
            for k in ("ref", "reference", "target", "comodel", "model"):
                rv = f.get(k)
                if isinstance(rv, str) and rv.strip():
                    fks.append((name or f"({ftype})", parse_ref_target(rv)))

        # Pola 5: relation ala ORM
        rel = f.get("relation")
        if isinstance(rel, str) and rel.strip():
            fks.append((name or "(relation)", rel.strip()))

        # Pola 6: nested mapping many2one: { comodel: "..."} / { model: "..." }
        if isinstance(f.get("many2one"), dict):
            for k in ("comodel", "model", "table"):
                rv = f["many2one"].get(k)
                if isinstance(rv, str) and rv.strip():
                    fks.append((name or "(many2one)", parse_ref_target(rv)))

    # Normalisasi sederhana (strip spasi)
    fks = [(fname, t.strip()) for fname, t in fks if isinstance(t, str) and t.strip()]
    return fks

# --------------------------
# Laporan
# --------------------------

def write_report(
    path: Path,
    tables: Set[str],
    all_fk: List[Tuple[str, str, str]],
    missing: List[Tuple[str, str, str, str]],
    parse_errors: List[Tuple[str, str]],
) -> None:
    """
    Tulis laporan ke path (fk_report.txt)
    - tables: set nama tabel
    - all_fk: list (table_name, field_name, target_table)
    - missing: list (table_name, file_path, field_name, target_table)
    - parse_errors: list (file_path, error_message)
    """
    with path.open("w", encoding="utf-8") as f:
        f.write("FK REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total tables detected : {len(tables)}\n")
        f.write(f"Total FK candidates   : {len(all_fk)}\n")
        f.write(f"Missing FK targets    : {len(missing)}\n")
        f.write("=" * 80 + "\n\n")

        if parse_errors:
            f.write("YAML Parse Errors:\n")
            for p, msg in parse_errors:
                f.write(f" - {p}: {msg}\n")
            f.write("\n")

        if not all_fk:
            f.write("No FK candidates detected.\n\n")

        if missing:
            f.write("Missing targets detail:\n")
            for i, (tbl, file, field, target) in enumerate(missing, 1):
                f.write(f"{i:3d}. [{tbl}] {field} -> {target} (file: {file})\n")
            f.write("\n")
        else:
            f.write("All FK targets exist. ✅\n\n")

        # Ringkasan tabel
        f.write("Tables (sorted):\n")
        for t in sorted(tables):
            f.write(f" - {t}\n")

# --------------------------
# Main
# --------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Validasi referensi FK dari YAML di folder struktur_data")
    parser.add_argument(
        "--dir",
        default="struktur_data",
        help="Folder berisi berkas YAML (default: struktur_data)",
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        default=[".yml", ".yaml"],
        help="Ekstensi file YAML yang dipindai (default: .yml .yaml)",
    )
    args = parser.parse_args()

    sdir = Path(args.dir)
    if not sdir.is_dir():
        eprint(f"Folder tidak ditemukan: {sdir.resolve()}")
        return 2

    # Kumpulkan semua file YAML
    yaml_files: List[Path] = []
    for ext in args.ext:
        yaml_files.extend(sdir.rglob(f"*{ext}"))
    yaml_files = sorted(set(yaml_files))

    if not yaml_files:
        eprint("Tidak ada berkas YAML ditemukan.")
        return 2

    # Muat semua & petakan nama tabel
    tables: Set[str] = set()
    docs: Dict[str, Any] = {}
    table_of_file: Dict[str, str] = {}
    parse_errors: List[Tuple[str, str]] = []

    for p in yaml_files:
        doc = load_yaml(p)
        docs[str(p)] = doc
        if isinstance(doc, dict) and "__parse_error__" in doc:
            parse_errors.append((str(p), doc["__parse_error__"]))
            # Tetap lanjut agar berkas lain tetap divalidasi
            continue
        table_name = infer_table_name(doc, p.stem)
        tables.add(table_name)
        table_of_file[table_name] = str(p)

    # Periksa FK
    all_fk: List[Tuple[str, str, str]] = []  # (table, field, target_table)
    missing: List[Tuple[str, str, str, str]] = []  # (table, file, field, target_table)

    for p_str, doc in docs.items():
        if isinstance(doc, dict) and "__parse_error__" in doc:
            # sudah dicatat di parse_errors
            continue
        table_name = infer_table_name(doc, Path(p_str).stem)
        fields = iter_fields(doc)
        fks = find_fk_targets(fields)
        for field_name, target_table in fks:
            all_fk.append((table_name, field_name, target_table))
            if target_table not in tables:
                missing.append((table_name, p_str, field_name, target_table))

    # Cetak ringkasan ke terminal
    print("=" * 80)
    print(f"Jumlah tabel terdeteksi : {len(tables)}")
    if tables:
        sample = ", ".join(sorted(list(tables))[:10])
        print(f"Contoh tabel            : {sample}")
    print(f"Kandidat FK terdeteksi  : {len(all_fk)}")
    print(f"FK target hilang        : {len(missing)}")
    print("=" * 80)

    if parse_errors:
        print("Ada berkas yang gagal diparse YAML (lihat fk_report.txt untuk detail).")

    if not all_fk:
        print("Tidak ada kandidat FK yang terdeteksi dari pola umum.")
    if not missing:
        print("✅ Semua target FK memiliki tabel referensi yang ditemukan.")

    # Tulis laporan
    report_path = Path("fk_report.txt")
    write_report(report_path, tables, all_fk, missing, parse_errors)
    print(f"Laporan ditulis ke: {report_path.resolve()}")

    # Exit code: 0 jika tidak ada missing; 1 jika ada missing; 2 untuk error umum
    return 0 if not missing and not parse_errors else (1 if missing else 0)

if __name__ == "__main__":
    sys.exit(main())
