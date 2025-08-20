#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_fk_patch.py
Patch otomatis untuk memperbaiki target FK dan nama tabel sesuai keputusan:
- akun (bukan account)
- karyawan (bukan pegawai)
- penerima (scholarship.penerima_id) mengacu ke siswa
- wali_kelas_id mengacu ke guru

Cara pakai:
    python3 apply_fk_patch.py

Prasyarat:
    pip install pyyaml
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).parent
SDIR = ROOT / "struktur_data"

# File & field target yang akan dipatch
TABLE_NAME_PATCH = {
    # file_path: target_table_name
    "struktur_data/account.yaml": "akun",
}

FK_PATCHES = [
    # (file_path, field_name, ref_table)
    ("struktur_data/journal_entry.yaml",   "akun_id",        "akun"),
    ("struktur_data/kehadiran_pegawai.yaml", "pegawai_id",   "karyawan"),
    ("struktur_data/kontrak.yaml",         "pegawai_id",     "karyawan"),
    ("struktur_data/payroll.yaml",         "pegawai_id",     "karyawan"),
    ("struktur_data/penilaian_kinerja.yaml","pegawai_id",    "karyawan"),
    ("struktur_data/scholarship.yaml",     "penerima_id",    "siswa"),
    ("struktur_data/kelas.yaml",           "wali_kelas_id",  "guru"),
]

def load_yaml(p: Path) -> Any:
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data

def dump_yaml(p: Path, data: Any) -> None:
    # Simpan dengan gaya YAML standar
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

def ensure_backup(p: Path) -> None:
    bak = p.with_suffix(p.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(p, bak)

def get_fields_containers(doc: Any) -> List[List[Dict[str, Any]]]:
    """
    Mengembalikan list berisi referensi ke list 'fields' potensial yang ada.
    - doc["fields"] or doc["columns"]
    - doc["schema"]["fields"] or doc["schema"]["columns"]
    """
    containers: List[List[Dict[str, Any]]] = []
    if isinstance(doc, dict):
        for key in ("fields", "columns"):
            val = doc.get(key)
            if isinstance(val, list):
                # filter hanya dict
                arr = [x for x in val if isinstance(x, dict)]
                if arr is not val:
                    # kalau ada elemen non-dict, rebuild
                    doc[key] = arr
                containers.append(doc[key])

        schema = doc.get("schema")
        if isinstance(schema, dict):
            for key in ("fields", "columns"):
                val = schema.get(key)
                if isinstance(val, list):
                    arr = [x for x in val if isinstance(x, dict)]
                    if arr is not val:
                        schema[key] = arr
                    containers.append(schema[key])

    return containers

def set_table_name(p: Path, target_name: str) -> bool:
    """
    Set doc['name'] = target_name pada file p jika memungkinkan.
    Mengembalikan True jika ada perubahan, False jika tidak.
    """
    doc = load_yaml(p)
    if not isinstance(doc, dict):
        return False
    current = doc.get("name")
    if current != target_name:
        ensure_backup(p)
        doc["name"] = target_name
        dump_yaml(p, doc)
        return True
    return False

def set_field_ref_table(p: Path, field_name: str, ref_table: str) -> bool:
    """
    Menambahkan/menimpa ref_table pada field 'field_name' di file p.
    Mencari di beberapa kontainer fields/columns.
    Mengembalikan True jika ada perubahan, False jika tidak.
    """
    doc = load_yaml(p)
    changed = False

    containers = get_fields_containers(doc)
    if not containers:
        # tidak ada bidang fields/columns; tidak bisa mempatch
        return False

    for arr in containers:
        for f in arr:
            if isinstance(f, dict) and str(f.get("name", "")).strip() == field_name:
                if f.get("ref_table") != ref_table:
                    ensure_backup(p)
                    f["ref_table"] = ref_table
                    changed = True

    if changed:
        dump_yaml(p, doc)
    return changed

def main() -> int:
    if not SDIR.is_dir():
        print(f"Folder tidak ditemukan: {SDIR.resolve()}")
        return 2

    total_changes = 0

    # 1) Patch nama tabel account → akun
    for file_rel, target in TABLE_NAME_PATCH.items():
        p = ROOT / file_rel
        if p.exists():
            if set_table_name(p, target):
                print(f"[OK] Ubah name: {file_rel} → {target}")
                total_changes += 1
        else:
            print(f"[SKIP] File tidak ditemukan: {file_rel}")

    # 2) Patch FK ref_table
    for file_rel, field_name, ref_table in FK_PATCHES:
        p = ROOT / file_rel
        if p.exists():
            if set_field_ref_table(p, field_name, ref_table):
                print(f"[OK] Set {file_rel}: {field_name}.ref_table = {ref_table}")
                total_changes += 1
            else:
                print(f"[INFO] Tidak ada perubahan atau field tidak ditemukan: {file_rel}#{field_name}")
        else:
            print(f"[SKIP] File tidak ditemukan: {file_rel}")

    if total_changes == 0:
        print("Tidak ada perubahan yang diterapkan.")
    else:
        print(f"Selesai. Perubahan diterapkan: {total_changes}")

    print("\nTips verifikasi:")
    print("  1) Jalankan kembali validator: python3 validate_fk.py")
    print("  2) Pastikan FK target hilang = 0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
