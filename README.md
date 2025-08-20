
---

## 🌐 Services Overview

- **🔄 n8n** → Mengelola workflow otomatis dari dokumen ke database.  
- **🐘 PostgreSQL** → Menyimpan data project (satu project = satu database).  
- **📊 Superset** → Membuat dashboard & chart berbasis materialized view.  
- **🛠️ Portainer** → Mempermudah manajemen container.  
- **🌐 Traefik** → Menyediakan reverse proxy untuk semua service.  
- **☁️ Object Store** → Menyimpan dokumen/arsip terpusat.  

---

## 🔄 Orchestration with n8n

Peran utama **n8n** dalam project ini:  

1. 📑 Membaca dokumen dari sumber (misalnya hasil baseline study).  
2. 🏷️ Mengidentifikasi entitas berdasarkan `struktur_data`.  
3. ⏸️ Menampilkan hasil ekstraksi di **staging** untuk validasi user.  
4. ✅ Jika di-approve → insert data ke PostgreSQL.  
5. 📊 Data digunakan oleh Superset untuk analitik & dashboard.  

**Best practices**:  
- Workflow harus reusable.  
- Gunakan katalog `struktur_data` sebagai referensi.  
- Simpan versi workflow di repository untuk menjaga histori.  

---

## 📊 Data & Analytics

- **`struktur_data/`** → mendefinisikan entitas & atribut database.  
- **`materialized_view/`** → mempercepat analitik dengan view terstruktur.  
- **`charts/`** → konfigurasi chart Superset untuk visualisasi insight.  

---

## 🛠️ Development Workflow

- 🧹 **Pre-commit hooks** → memastikan YAML & struktur tetap konsisten.  
- ✅ **GitHub Actions** → validasi otomatis (linting & simulasi struktur_data).  
- 🔀 **Version Control** → workflow n8n dan konfigurasi disimpan dalam Git agar mudah di-review & di-rollback.  

---

## 📜 License & Attribution

- **Copyright** © PT. Cakrawala Tumbuh  
- **Contributor:** Andhitia Rama <andhitia.r@gmail.com>  

---

## 🔀 End-to-End Flow Baseline Study

Alur implementasi orkestrasi di Cantum mengikuti langkah-langkah berikut:

1. **Pilih Analisa dari Daftar Jasa**  
   Dari setiap project baseline studi, Cantum menentukan analisa apa saja yang akan diberikan kepada klien.  
   - Sumber referensi: `daftar_jasa.yaml`.

2. **Provision Database di PostgreSQL**  
   Orkestrasi otomatis membuat satu database khusus di PostgreSQL untuk setiap project.  
   - Struktur tabel dihasilkan dari `struktur_data/`.

3. **Generate Tampilan di Appsmith**  
   Secara otomatis dibuat tampilan di Appsmith yang terhubung ke database project yang baru.

4. **Bangun Materialized View**  
   Materialized View dibuat berdasarkan informasi `materialized_view/`.  
   - Definisi SQL MV ada pada direktori `/materialized_view`.

5. **Generate Chart di Superset**  
   Chart BI dibuat di Superset berdasarkan MV yang tersedia.  
   - Definisi chart dapat dilihat di direktori `/charts`.

Dengan alur ini, setiap project baseline studi dapat dengan cepat diproyeksikan menjadi sistem analitik lengkap: dari data mentah → database → MV → dashboard.
