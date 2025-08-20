#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_fk_patch_v2.py

Patch otomatis FK yang masih meleset berdasarkan hasil validate_fk:
- kehadiran_pegawai.pegawai_id -> karyawan
- kontrak.pegawai_id           -> karyawan
- payroll.pegawai_id           -> karyawan
- penilaian_kinerja.pegawai_id -> karyawan
- kelas.wali_kelas_id          -> guru
- scholarship.penerima_id      -> siswa

Fitur:
- Dukungan YAML multi-document (---)
- Pencarian rekursif di seluruh struktur (fields/columns di root atau di dalam schema/*)
- Backup .bak sebelum tulis
- Fallback: jika field di file target tidak ditemukan, pindai semua YAML di struktur_data/

Cara pakai:
    python3 apply_fk_patch_v2.py
Opsional:
    python3 apply_fk_patch_v2.py --root struktur_data
"""

from __future__ import annotations
import argparse
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).parent

# Target patch yang diminta user
TARGETS: List[Tuple[str, str, str]] = [
    ("struktur_data/kehadiran_pegawai.yaml", "pegawai_id", "karyawan"),
    ("struktur_data/kontrak.yaml",           "pegawai_id", "karyawan"),
    ("struktur_data/payroll.yaml",           "pegawai_id", "karyawan"),
    ("struktur_data/penilaian_kinerja.yaml", "pegawai_id", "karyawan"),
    ("struktur_data/kelas.yaml",             "wali_kelas_id", "guru"),
    ("struktur_data/scholarship.yaml",       "penerima_id", "siswa"),
]

def load_yaml_all(p: Path) -> List[Any]:
    text = p.read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(text))
    # PyYAML bisa mengembalikan [None] untuk dok kosong — normalisasi ke []
    return [d if d is not None else {} for d in docs]

def dump_yaml_all(p: Path, docs: List[Any]) -> None:
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump_all(
            docs,
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            explicit_start=True,  # tulis '---' untuk tiap dok
        )

def ensure_backup(p: Path) -> None:
    bak = p.with_suffix(p.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(p, bak)

def is_field_dict(d: Any) -> bool:
    """Heuristik: dict yang tampak seperti definisi field."""
    return isinstance(d, dict) and "name" in d and isinstance(d.get("name"), str)

def patch_field_in_node(node: Any, field_name: str, ref_table: str) -> int:
    """
    Rekursif: cari semua dict field bernama `field_name` dan set "ref_table".
    Return jumlah perubahan.
    """
    changed = 0
    if isinstance(node, dict):
        # Jika node sendiri adalah field
        if is_field_dict(node) and node.get("name") == field_name:
            if node.get("ref_table") != ref_table:
                node["ref_table"] = ref_table
                changed += 1
        # Lanjut ke anak-anak
        for k, v in list(node.items()):
            changed += patch_field_in_node(v, field_name, ref_table)
    elif isinstance(node, list):
        for item in node:
            changed += patch_field_in_node(item, field_name, ref_table)
    # tipe lain: abaikan
    return changed

def patch_file(p: Path, field_name: str, ref_table: str) -> int:
    """
    Patch satu file YAML (semua dokumen di dalamnya).
    Return jumlah perubahan di file tersebut.
    """
    docs = load_yaml_all(p)
    before = yaml.safe_dump_all(docs)
    total_changes = 0
    for i in range(len(docs)):
        total_changes += patch_field_in_node(docs[i], field_name, ref_table)
    after = yaml.safe_dump_all(docs)
    if total_changes > 0 and before != after:
        ensure_backup(p)
        dump_yaml_all(p, docs)
    return total_changes

def scan_all_yaml(root: Path, patterns: List[str]) -> List[Path]:
    files: List[Path] = []
    for ext in patterns:
        files.extend(root.rglob(f"*{ext}"))
    # Hilangkan duplikat dan sort
    return sorted(set(files))

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="struktur_data", help="Folder akar YAML (default: struktur_data)")
    args = ap.parse_args()

    sdir = ROOT / args.root
    if not sdir.is_dir():
        print(f"[ERR] Folder tidak ditemukan: {sdir.resolve()}")
        return 2

    total_files_changed = 0
    total_fields_patched = 0
    not_found: List[Tuple[str, str, str]] = []  # (file_rel, field, ref)

    # Langkah 1: coba patch di file target masing-masing
    print("== Langkah 1: Patch sesuai file target ==")
    for rel, fname, ref in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"[SKIP] File target tidak ada: {rel}")
            not_found.append((rel, fname, ref))
            continue
        changes = patch_file(p, fname, ref)
        if changes > 0:
            print(f"[OK] {rel}: set {fname}.ref_table = {ref} (perubahan: {changes})")
            total_files_changed += 1
            total_fields_patched += changes
        else:
            print(f"[WARN] {rel}: field '{fname}' tidak ditemukan / tidak berubah")
            not_found.append((rel, fname, ref))

    # Langkah 2 (fallback): cari field yang belum ketemu di seluruh repo struktur_data
    if not_found:
        print("\n== Langkah 2 (fallback): Pindai seluruh struktur_data untuk field yang belum ketemu ==")
        all_yaml = scan_all_yaml(sdir, [".yaml", ".yml"])
        for rel, fname, ref in not_found:
            found_any = 0
            for f in all_yaml:
                try:
                    changes = patch_file(f, fname, ref)
                except Exception as e:
                    print(f"[ERR] Gagal parse {f}: {e}")
                    continue
                if changes > 0:
                    print(f"[OK] (fallback) {f.relative_to(ROOT)}: set {fname}.ref_table = {ref} (perubahan: {changes})")
                    total_files_changed += 1
                    total_fields_patched += changes
                    found_any += changes
                    # Jangan break: biarkan jika field yang sama muncul di beberapa file (aman)
            if found_any == 0:
                print(f"[FAIL] Field '{fname}' tidak ditemukan di repo. Tolong cek nama field/file untuk kasus: {rel}")

    print("\n== Ringkasan ==")
    print(f"File diubah            : {total_files_changed}")
    print(f"Total field dipatch    : {total_fields_patched}")
    print("Selesai. Sekarang jalankan kembali:")
    print("  python3 validate_fk.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
