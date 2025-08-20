# 📘 Cantum Configuration

🚀 **Cantum Configuration** adalah project referensi untuk implementasi orkestrasi menggunakan **n8n**.  
Project ini digunakan sebagai acuan dalam mengelola data, workflow otomatis, dan analitik untuk jasa konsultasi pendidikan.

---

## 🧩 Technology Stack

Project ini menggunakan kombinasi teknologi open-source dan layanan cloud:

| Teknologi       | Fungsi Utama                                      |
|-----------------|--------------------------------------------------|
| 🐘 PostgreSQL   | Basis data per project                            |
| 🔄 n8n          | Orkestrasi workflow & otomasi integrasi           |
| 🌐 Traefik      | Reverse proxy & routing service                   |
| 📊 Superset     | Business Intelligence & visualisasi data          |
| 🛠️ Portainer    | Manajemen container                               |
| ☁️ Object Store | Penyimpanan dokumen (Biznet Object Storage/MinIO) |

---

## 📂 Project Structure

Struktur direktori utama:

```
.
├── struktur_data/      # Definisi skema database per entitas
├── charts/             # Konfigurasi chart Superset
├── materialized_view/  # View analitik untuk BI
└── README.md
```

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
