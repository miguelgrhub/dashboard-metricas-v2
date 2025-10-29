#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_validacion_comparativa.py
Compara resultados del Parquet vs MySQL con los mismos filtros:
- Valida que ambos conjuntos devuelven la misma cantidad de registros y métricas.
"""

import pandas as pd
from sqlalchemy import create_engine, text

# ==============================
# ⚙️ CONFIGURACIÓN
# ==============================
DB_URI = "mysql+pymysql://admin:adminservidor123@nexusgrhub.cxnchtdj9k1t.us-east-2.rds.amazonaws.com:3306/ContactsDetail"
TABLE = "data"
PARQUET_PATH = "data/data_full.parquet"

# Filtros a comparar (ajusta según tu dashboard)
fecha_ini = "2025-01-01"
fecha_fin = "2025-10-26"
checkin_ini = "2025-10-20"
checkin_fin = "2025-10-20"
checkout_ini = "2024-06-18"
checkout_fin = "2026-10-09"

# ==============================
# 📦 DESCARGA DESDE MYSQL
# ==============================
print("🚀 Consultando directamente en MySQL...")
engine = create_engine(DB_URI)

sql = text(f"""
    SELECT 
        Id, Email, agency, Destination, condactivacion, Localizador,
        Fecha_de_creacion, Check_in_date, Check_out_date
    FROM {TABLE}
    WHERE Fecha_de_creacion BETWEEN :fecha_ini AND :fecha_fin
      AND (Check_in_date BETWEEN :checkin_ini AND :checkin_fin)
      AND (Check_out_date BETWEEN :checkout_ini AND :checkout_fin)
""")

params = {
    "fecha_ini": fecha_ini,
    "fecha_fin": fecha_fin,
    "checkin_ini": checkin_ini,
    "checkin_fin": checkin_fin,
    "checkout_ini": checkout_ini,
    "checkout_fin": checkout_fin,
}

df_mysql = pd.read_sql(sql, engine, params=params)
print(f"✅ Registros en MySQL con filtros: {len(df_mysql):,}")

# ==============================
# 📂 CARGA DESDE PARQUET
# ==============================
print("\n📁 Cargando Parquet local...")
df_parquet = pd.read_parquet(PARQUET_PATH)
print(f"✅ Registros totales en Parquet: {len(df_parquet):,}")

# Filtrado en Parquet con los mismos rangos
mask = (
    (df_parquet["Fecha_de_creacion"] >= pd.to_datetime(fecha_ini)) &
    (df_parquet["Fecha_de_creacion"] <= pd.to_datetime(fecha_fin)) &
    (df_parquet["Check_in_date"] >= pd.to_datetime(checkin_ini)) &
    (df_parquet["Check_in_date"] <= pd.to_datetime(checkin_fin)) &
    (df_parquet["Check_out_date"] >= pd.to_datetime(checkout_ini)) &
    (df_parquet["Check_out_date"] <= pd.to_datetime(checkout_fin))
)
df_local = df_parquet[mask]
print(f"✅ Registros filtrados en Parquet: {len(df_local):,}")

# ==============================
# 📊 COMPARACIÓN DE MÉTRICAS
# ==============================
def calc_metrics(df):
    df["Email_clean"] = df["Email"].astype(str).str.strip().str.lower()
    df["has_email"] = df["Email_clean"] != ""
    df["valid_email"] = df["Email_clean"].str.match(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$", na=False)
    df["duplicate"] = df.duplicated(subset=["Email_clean"], keep=False)
    df["sendable"] = df["valid_email"] & ~df["duplicate"]
    return {
        "total": len(df),
        "con_email": int(df["has_email"].sum()),
        "vacios": int((~df["has_email"]).sum()),
        "validos": int(df["valid_email"].sum()),
        "duplicados": int(df["duplicate"].sum()),
        "enviables": int(df["sendable"].sum()),
    }

metrics_mysql = calc_metrics(df_mysql)
metrics_local = calc_metrics(df_local)

# ==============================
# 🧮 RESULTADOS
# ==============================
print("\n📊 Comparativa de métricas (MySQL vs Parquet):\n")
for k in metrics_mysql.keys():
    val_mysql = metrics_mysql[k]
    val_local = metrics_local[k]
    diff = val_mysql - val_local
    print(f"  {k:<12}: MySQL={val_mysql:,} | Parquet={val_local:,} | Δ={diff:+,}")

print("\n🧾 Fechas detectadas en los resultados:")
print(f"  MySQL  → Fecha_creacion: {df_mysql['Fecha_de_creacion'].min()} → {df_mysql['Fecha_de_creacion'].max()}")
print(f"  Parquet → Fecha_creacion: {df_local['Fecha_de_creacion'].min()} → {df_local['Fecha_de_creacion'].max()}")

print("\n✅ Validación completada.")
