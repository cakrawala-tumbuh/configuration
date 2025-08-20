# Panduan Penulisan **Struktur Data Entitas** (YAML)

Dokumen ini menjadi _single source of truth_ untuk menulis / mengubah berkas YAML di direktori `struktur_data/`. Formatnya dirancang agar mudah dibaca non-teknis namun cukup tegas untuk digenerasi menjadi **SQL (PostgreSQL)** secara otomatis.

## Aturan Utama
1. Nama file = nama entitas (snake_case), contoh: `siswa.yaml`.
2. Setiap file hanya memuat **1 entitas**.
3. Gunakan struktur standar: `entity`, `fields`, `constraints`, `indexes`, `comment`.
4. Kolom FK harus berakhiran `_id` dan menunjuk ke `ref_table`.
5. PK dianjurkan menggunakan `uuid` dengan `generated: uuid_v4`.

## Contoh Minimal
```yaml
spec_version: "1.0"
entity:
  name: "Guru"
  technical_name: "guru"
fields:
  - name: "ID"
    technical_name: "id"
    type: "uuid"
    pk: true
    generated: "uuid_v4"
    not_null: true
  - name: "Nama"
    technical_name: "name"
    type: "text"
    not_null: true
```

## Checklist Validasi
- [ ] Nama entitas unik dan snake_case.
- [ ] Tepat satu `pk: true`.
- [ ] Semua `_id` memiliki `fk.ref_table` yang valid.
- [ ] Tidak menggunakan `serial` baru.
- [ ] Ada `comment` untuk tabel penting.
