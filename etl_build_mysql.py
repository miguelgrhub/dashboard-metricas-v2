#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etl_update_or_rebuild.py
Versión automática del ETL:
- Detecta si MySQL tiene datos más recientes.
- Si hay nuevas fechas → agrega las nuevas filas al Parquet.
- Si no existe el Parquet → lo crea completo.
"""

import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime, date
import os, re

# ===============================
# CONFIGURACIÓN
# ===============================
DB_URL = "mysql+pymysql://admin:adminservidor123@nexusgrhub.cxnchtdj9k1t.us-east-2.rds.amazonaws.com:3306/ContactsDetail"
OUT_DIR = "data"
os.makedirs(OUT_DIR, exist_ok=True)
DATA_FILE = f"{OUT_DIR}/data_full.parquet"

EMAIL_REGEX = r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"

print("🚀 Conectando a MySQL…")
engine = create_engine(DB_URL)

# ===============================
# 1️⃣ OBTENER FECHA MÁXIMA EN MYSQL
# ===============================
max_mysql = pd.read_sql("SELECT MAX(Fecha_de_creacion) AS max_fecha FROM data WHERE Fecha_de_creacion IS NOT NULL;", engine)
max_mysql_date = pd.to_datetime(max_mysql["max_fecha"].iloc[0]).date()
print(f"🗓️  Última fecha en MySQL: {max_mysql_date}")

# ===============================
# 2️⃣ LEER PARQUET EXISTENTE (SI HAY)
# ===============================
if os.path.exists(DATA_FILE):
    df_local = pd.read_parquet(DATA_FILE, columns=["Fecha_de_creacion"])
    max_local_date = df_local["Fecha_de_creacion"].max()
    print(f"📦 Última fecha en Parquet: {max_local_date}")
else:
    df_local = None
    max_local_date = None
    print("⚠️  No existe Parquet previo. Se generará desde cero.")

# ===============================
# 3️⃣ DECISIÓN: ACTUALIZAR O REGENERAR
# ===============================
if max_local_date and max_local_date >= max_mysql_date:
    print("✅ El Parquet ya está actualizado. No se requiere acción.")
    exit(0)

if max_local_date:
    # Descargar SOLO filas nuevas
    query = f"""
        SELECT Id, Email, agency, Destination, condactivacion, Localizador, Fecha_de_creacion
        FROM data
        WHERE Fecha_de_creacion > '{max_local_date}'
    """
    mode = "append"
    print(f"🔄 Descargando filas nuevas posteriores a {max_local_date}…")
else:
    # Descargar todo
    query = """
        SELECT Id, Email, agency, Destination, condactivacion, Localizador, Fecha_de_creacion
        FROM data
        WHERE Fecha_de_creacion IS NOT NULL
    """
    mode = "full"
    print("🧱 Descargando tabla completa…")

df_new = pd.read_sql(query, engine)
print(f"📦 Filas descargadas desde MySQL: {len(df_new):,}")

if df_new.empty:
    print("✅ No hay datos nuevos para agregar.")
    exit(0)

# ===============================
# 4️⃣ LIMPIEZA Y NORMALIZACIÓN
# ===============================
df_new["Fecha_de_creacion"] = pd.to_datetime(
    df_new["Fecha_de_creacion"].astype(str).replace("0000-00-00 00:00:00", pd.NaT),
    errors="coerce"
).dt.date

df_new = df_new.dropna(subset=["Fecha_de_creacion"])
df_new["Email_clean"] = df_new["Email"].apply(
    lambda x: str(x).strip().lower() if pd.notna(x) and str(x).strip() != "" else None
)

df_new["has_email"] = df_new["Email_clean"].notna()
df_new["valid_email"] = df_new["Email_clean"].apply(lambda x: bool(re.match(EMAIL_REGEX, x)) if x else False)
df_new["empty_email"] = ~df_new["has_email"]

print(f"✅ Nuevos registros limpios: {len(df_new):,}")

# ===============================
# 5️⃣ COMBINAR SI EXISTE PARQUET
# ===============================
if mode == "append" and df_local is not None:
    df_old = pd.read_parquet(DATA_FILE)
    df = pd.concat([df_old, df_new], ignore_index=True)
    print(f"📈 Total combinado: {len(df):,} filas (antes {len(df_old):,} + nuevas {len(df_new):,})")
else:
    df = df_new

# ===============================
# 6️⃣ DUPLICADOS Y MÉTRICAS
# ===============================
df["is_duplicate"] = df.duplicated(subset=["Email_clean"], keep=False)
df["sendable"] = df["valid_email"] & ~df["is_duplicate"]

df.to_parquet(DATA_FILE, index=False)
print(f"🎯 data_full.parquet actualizado correctamente ({len(df):,} filas).")

# ===============================
# 7️⃣ ACTUALIZAR MÉTRICAS RESUMIDAS
# ===============================
metrics_daily = (
    df.groupby("Fecha_de_creacion")
    .agg(
        total=("Id", "count"),
        with_email=("has_email", "sum"),
        valid=("valid_email", "sum"),
        empty=("empty_email", "sum"),
        duplicates=("is_duplicate", "sum"),
        sendable=("sendable", "sum"),
    )
    .reset_index()
)
metrics_daily.to_parquet(f"{OUT_DIR}/metrics_daily.parquet")
print("✅ metrics_daily.parquet actualizado.")

metrics_top_domains = (
    df[df["valid_email"]]
    .assign(domain=lambda x: x["Email_clean"].str.split("@").str[-1])
    .groupby("domain").size().reset_index(name="count")
    .sort_values("count", ascending=False)
)
metrics_top_domains.to_parquet(f"{OUT_DIR}/metrics_top_domains_daily.parquet")
print("✅ metrics_top_domains_daily.parquet actualizado.")

repeated = (
    df[df["is_duplicate"]]
    .groupby("Email_clean")
    .agg(
        occurrences=("Email_clean", "size"),
        first_seen=("Fecha_de_creacion", "min"),
        last_seen=("Fecha_de_creacion", "max"),
    )
    .reset_index()
    .sort_values("occurrences", ascending=False)
)
repeated.to_parquet(f"{OUT_DIR}/metrics_repeated_emails.parquet")
print("✅ metrics_repeated_emails.parquet actualizado.")

# ===============================
# 8️⃣ RESUMEN
# ===============================
print("\n📊 Resumen global actualizado:")
print(f"   Con email     : {df['has_email'].sum():,}")
print(f"   Vacíos        : {df['empty_email'].sum():,}")
print(f"   Válidos       : {df['valid_email'].sum():,}")
print(f"   Duplicados    : {df['is_duplicate'].sum():,}")
print(f"   Enviables     : {df['sendable'].sum():,}")

print("\n✅ ETL completado con éxito.")
