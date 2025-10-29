#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard v4.2 — Emails:
- Mantiene todo lo de v4.1 (KPIs, gráficas, tabla)
- Nuevo filtro: rango Check-in/Check-out (ambos rangos deben cumplirse)
"""

import duckdb
import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

DETAIL_FULL = "data/data_full.parquet"

# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def _in_clause(values):
    """Convierte lista o valor en un IN SQL compatible."""
    if values is None or values == "":
        return None
    if isinstance(values, list):
        vals = [v for v in values if v not in (None, "")]
        if not vals:
            return None
        return "(" + ",".join(f"'{v}'" for v in vals) + ")"
    return f"('{values}')"


def build_where(
    start_date, end_date,
    checkin_start=None, checkout_end=None,
    agency=None, dest=None, cond=None, loc=None
):
    filters = [f"Fecha_de_creacion BETWEEN DATE '{start_date}' AND DATE '{end_date}'"]

    # 🔹 Nuevo: exigir que el periodo de la estancia también esté dentro del rango dado
    # Nota: nombres exactamente como en MySQL/Parquet (C mayúscula)
    if checkin_start and checkout_end:
        filters.append(
            f"Check_in_date >= DATE '{checkin_start}' AND Check_out_date <= DATE '{checkout_end}'"
        )

    for col, val in [
        ("agency", agency),
        ("Destination", dest),
        ("condactivacion", cond),
        ("Localizador", loc),
    ]:
        clause_vals = _in_clause(val)
        if clause_vals:
            filters.append(f"{col} IN {clause_vals}")
    return "WHERE " + " AND ".join(filters)


def query_filter_options(start_date, end_date, checkin_start=None, checkout_end=None):
    where = build_where(start_date, end_date, checkin_start, checkout_end)
    sql = f"""
        SELECT DISTINCT agency, Destination, condactivacion, Localizador
        FROM read_parquet('{DETAIL_FULL}')
        {where}
        LIMIT 10000
    """
    with duckdb.connect() as con:
        df = con.execute(sql).fetchdf()
    return {
        "agency": sorted(df["agency"].dropna().unique().tolist()),
        "Destination": sorted(df["Destination"].dropna().unique().tolist()),
        "condactivacion": sorted(df["condactivacion"].dropna().unique().tolist()),
        "Localizador": sorted(df["Localizador"].dropna().unique().tolist()),
    }


def query_totals(start_date, end_date, checkin_start, checkout_end,
                 agency=None, dest=None, cond=None, loc=None):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    regex = r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
    sql = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN Email IS NOT NULL AND TRIM(Email) <> '' THEN 1 ELSE 0 END) AS con_email,
            SUM(CASE WHEN Email IS NULL OR TRIM(Email) = '' THEN 1 ELSE 0 END) AS vacios,
            SUM(
                CASE
                    WHEN Email IS NOT NULL AND TRIM(Email) <> ''
                    AND REGEXP_MATCHES(LOWER(TRIM(Email)), '{regex}')
                THEN 1 ELSE 0 END
            ) AS validos
        FROM read_parquet('{DETAIL_FULL}')
        {where}
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf().iloc[0].to_dict()


def query_dups_and_sendables(start_date, end_date, checkin_start, checkout_end,
                             agency=None, dest=None, cond=None, loc=None):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    regex = r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
    sql = f"""
        WITH base AS (
          SELECT LOWER(TRIM(Email)) AS em
          FROM read_parquet('{DETAIL_FULL}')
          {where}
          AND Email IS NOT NULL AND TRIM(Email) <> ''
          AND REGEXP_MATCHES(LOWER(TRIM(Email)), '{regex}')
        )
        SELECT
          COUNT(*) AS valid_rows,
          COUNT(DISTINCT em) AS unique_valid,
          COUNT(*) - COUNT(DISTINCT em) AS duplicates_rows
        FROM base
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf().iloc[0].to_dict()


def query_vacios_detalle(start_date, end_date, checkin_start, checkout_end,
                         agency=None, dest=None, cond=None, loc=None):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    sql = f"""
        SELECT
            CAST(Fecha_de_creacion AS DATE) AS fecha,
            COALESCE(Destination, 'Sin destino') AS destino,
            COALESCE(condactivacion, 'Sin condactivacion') AS flujo,
            COALESCE(agency, 'Sin agency') AS agency,
            COUNT(*) AS vacios
        FROM read_parquet('{DETAIL_FULL}')
        {where}
        AND (Email IS NULL OR TRIM(Email) = '')
        GROUP BY ALL
        ORDER BY fecha
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf()


def query_invalid_emails(start_date, end_date, checkin_start, checkout_end,
                         agency=None, dest=None, cond=None, loc=None, limit=20):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    regex = r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
    sql = f"""
        SELECT Id, Localizador, Email
        FROM read_parquet('{DETAIL_FULL}')
        {where}
        AND Email IS NOT NULL AND TRIM(Email) <> ''
        AND NOT REGEXP_MATCHES(LOWER(TRIM(Email)), '{regex}')
        LIMIT {limit}
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf()


def query_top_domains_valid(start_date, end_date, checkin_start, checkout_end,
                            agency=None, dest=None, cond=None, loc=None, limit=10):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    regex = r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
    sql = f"""
        SELECT domain, COUNT(*) AS cnt
        FROM (
          SELECT
            CASE
              WHEN position('@' IN LOWER(TRIM(Email))) > 0
              THEN substring(LOWER(TRIM(Email)) FROM position('@' IN LOWER(TRIM(Email))) + 1)
              ELSE NULL
            END AS domain
          FROM read_parquet('{DETAIL_FULL}')
          {where}
          AND Email IS NOT NULL AND TRIM(Email) <> ''
          AND REGEXP_MATCHES(LOWER(TRIM(Email)), '{regex}')
        )
        WHERE domain IS NOT NULL
        GROUP BY domain
        ORDER BY cnt DESC
        LIMIT {limit}
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf()


def query_top_duplicated_emails(start_date, end_date, checkin_start, checkout_end,
                                agency=None, dest=None, cond=None, loc=None, limit=20):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    regex = r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
    sql = f"""
        SELECT em AS Email, COUNT(*) AS occurrences
        FROM (
          SELECT LOWER(TRIM(Email)) AS em
          FROM read_parquet('{DETAIL_FULL}')
          {where}
          AND Email IS NOT NULL AND TRIM(Email) <> ''
          AND REGEXP_MATCHES(LOWER(TRIM(Email)), '{regex}')
        )
        GROUP BY em
        HAVING COUNT(*) > 1
        ORDER BY occurrences DESC
        LIMIT {limit}
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf()


def query_enviables_por_dia(start_date, end_date, checkin_start, checkout_end,
                            agency=None, dest=None, cond=None, loc=None):
    where = build_where(start_date, end_date, checkin_start, checkout_end, agency, dest, cond, loc)
    regex = r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
    sql = f"""
        SELECT
            CAST(Fecha_de_creacion AS DATE) AS fecha,
            COALESCE(agency, 'Sin agency') AS agency,
            COALESCE(condactivacion, 'Sin condactivacion') AS flujo,
            COUNT(DISTINCT LOWER(TRIM(Email))) AS enviables
        FROM read_parquet('{DETAIL_FULL}')
        {where}
        AND Email IS NOT NULL AND TRIM(Email) <> ''
        AND REGEXP_MATCHES(LOWER(TRIM(Email)), '{regex}')
        GROUP BY ALL
        ORDER BY fecha
    """
    with duckdb.connect() as con:
        return con.execute(sql).fetchdf()


def kpi_card(value, title, color="primary"):
    return dbc.Card(
        dbc.CardBody([
            html.Small(title, className="d-block mb-1"),
            html.H3(f"{int(value):,}", className="mb-0")
        ]),
        className=f"bg-{color} text-light border-0 rounded-3 shadow-sm text-center"
    )

# =========================================================
# APP
# =========================================================
# ==========================
# Obtener rangos de fechas
# ==========================
with duckdb.connect() as con:
    # Rango de creación (Fecha_de_creacion)
    min_date, max_date = con.execute("""
        SELECT min(Fecha_de_creacion), max(Fecha_de_creacion)
        FROM read_parquet(?)
    """, [DETAIL_FULL]).fetchone()

    # Rango real de Check-in / Check-out
    ci_min, ci_max, co_min, co_max = con.execute("""
        SELECT 
            min(Check_in_date), max(Check_in_date),
            min(Check_out_date), max(Check_out_date)
        FROM read_parquet(?)
    """, [DETAIL_FULL]).fetchone()

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.COSMO])
app.title = "Dashboard Completo — Emails (v4.2)"

# Opciones iniciales sin restringir por check-in/out
_init_opts = query_filter_options(min_date, max_date)

app.layout = dbc.Container([
    html.H2("📊 Dashboard Completo de Métricas de Emails", className="text-center my-4"),
    html.Div(f"📅 Datos actualizados hasta: {max_date}", className="text-center text-secondary mb-4"),

    # FILTROS DE FECHA
    dbc.Row([
        dbc.Col([
            html.Label("Rango de creación"),
            dcc.DatePickerRange(
                id="f-fechas",
                min_date_allowed=min_date,
                max_date_allowed=max_date,
                start_date=min_date,
                end_date=max_date,
                display_format="YYYY-MM-DD"
            ),
        ], md=3),
        dbc.Col([
            html.Label("Rango de Check-in / Check-out"),
            dcc.DatePickerRange(
                id="f-ckin-ckout",
                min_date_allowed=min(ci_min, co_min),
                max_date_allowed=max(ci_max, co_max),
                start_date=ci_min,
                end_date=co_max,
                display_format="YYYY-MM-DD"
            ),
            html.Small(f"📆 Rango disponible: {ci_min} → {co_max}",
                       className="text-muted"),
        ], md=3),
        dbc.Col([
            html.Br(),
            dbc.Button("Aplicar filtros", id="btn-aplicar", color="primary", className="w-100")
        ], md=2),
    ], className="mb-4"),

    # DEMÁS FILTROS
    dbc.Row([
        dbc.Col([
            html.Label("Agency"),
            dcc.Dropdown(
                id="f-agency",
                options=[{"label": v, "value": v} for v in _init_opts["agency"]],
                multi=True, placeholder="Selecciona agency"
            )
        ], md=3),
        dbc.Col([
            html.Label("Destination"),
            dcc.Dropdown(
                id="f-dest",
                options=[{"label": v, "value": v} for v in _init_opts["Destination"]],
                multi=True, placeholder="Selecciona destino"
            )
        ], md=3),
        dbc.Col([
            html.Label("Condactivacion"),
            dcc.Dropdown(
                id="f-cond",
                options=[{"label": v, "value": v} for v in _init_opts["condactivacion"]],
                multi=True, placeholder="Selecciona flujo"
            )
        ], md=3),
        dbc.Col([
            html.Label("Localizador"),
            dcc.Dropdown(
                id="f-loc",
                options=[{"label": v, "value": v} for v in _init_opts["Localizador"]],
                multi=True, placeholder="Selecciona localizador"
            )
        ], md=3),
    ], className="mb-3"),

    # KPIs
    dbc.Row([
        dbc.Col(id="kpi-total", md=2),
        dbc.Col(id="kpi-email", md=2),
        dbc.Col(id="kpi-vacios", md=2),
        dbc.Col(id="kpi-validos", md=2),
        dbc.Col(id="kpi-duplicados", md=2),
        dbc.Col(id="kpi-enviables", md=2),
    ]),
    html.Hr(),

    dcc.Graph(id="graf-bar"),
    dcc.Graph(id="graf-vacios-dia"),

    dbc.Row([
        dbc.Col(dcc.Graph(id="graf-top-dominios"), md=6),
        dbc.Col(dcc.Graph(id="graf-top-duplicados"), md=6),
    ]),

    html.H4("📈 Enviables por día (por Agency y Condactivación)", className="mt-4"),
    dcc.Graph(id="graf-enviables-dia"),

    html.H4("📬 Ejemplos de correos inválidos (regex avanzado)", className="mt-4"),
    dash_table.DataTable(
        id="tbl-invalidos",
        columns=[{"name": c, "id": c} for c in ["Id", "Localizador", "Email"]],
        style_table={"overflowX": "auto"},
        style_cell={"fontSize": "12px", "padding": "5px"},
        style_header={"fontWeight": "bold"},
        page_size=20,
        sort_action="native",
        filter_action="native"
    )
], fluid=True)


# =========================================================
# CALLBACKS
# =========================================================

@app.callback(
    Output("f-agency", "options"),
    Output("f-dest", "options"),
    Output("f-cond", "options"),
    Output("f-loc", "options"),
    Input("f-fechas", "start_date"),
    Input("f-fechas", "end_date"),
    Input("f-ckin-ckout", "start_date"),
    Input("f-ckin-ckout", "end_date"),
)
def actualizar_opciones_por_fecha(start_date, end_date, ckin_start, ckout_end):
    opts = query_filter_options(start_date, end_date, ckin_start, ckout_end)
    return (
        [{"label": v, "value": v} for v in opts["agency"]],
        [{"label": v, "value": v} for v in opts["Destination"]],
        [{"label": v, "value": v} for v in opts["condactivacion"]],
        [{"label": v, "value": v} for v in opts["Localizador"]],
    )


@app.callback(
    Output("kpi-total", "children"),
    Output("kpi-email", "children"),
    Output("kpi-vacios", "children"),
    Output("kpi-validos", "children"),
    Output("kpi-duplicados", "children"),
    Output("kpi-enviables", "children"),
    Output("graf-bar", "figure"),
    Output("graf-vacios-dia", "figure"),
    Output("tbl-invalidos", "data"),
    Output("graf-top-dominios", "figure"),
    Output("graf-top-duplicados", "figure"),
    Output("graf-enviables-dia", "figure"),
    Input("btn-aplicar", "n_clicks"),
    State("f-fechas", "start_date"),
    State("f-fechas", "end_date"),
    State("f-ckin-ckout", "start_date"),
    State("f-ckin-ckout", "end_date"),
    State("f-agency", "value"),
    State("f-dest", "value"),
    State("f-cond", "value"),
    State("f-loc", "value"),
)
def actualizar_dashboard(n, start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc):
    if not n:
        raise dash.exceptions.PreventUpdate

    r = query_totals(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    total, con_em, vacios, validos = int(r["total"] or 0), int(r["con_email"] or 0), int(r["vacios"] or 0), int(r["validos"] or 0)

    d = query_dups_and_sendables(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    dups, enviables = int(d["duplicates_rows"] or 0), int(d["unique_valid"] or 0)

    fig_tot = px.bar(
        x=["Total", "Con email", "Válidos", "Vacíos", "Duplicados", "Enviables"],
        y=[total, con_em, validos, vacios, dups, enviables],
        text=[f"{v:,}" for v in [total, con_em, validos, vacios, dups, enviables]],
        title=f"Totales ({start_date} a {end_date}) | Check-in/out: {ckin_start} → {ckout_end}"
    )
    fig_tot.update_traces(textposition="outside")

    df_vacios = query_vacios_detalle(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    fig_vacios = px.bar(title="Sin vacíos en el rango seleccionado") if df_vacios.empty else \
        px.bar(df_vacios, x="fecha", y="vacios", color="destino", hover_data=["flujo", "agency"], title=f"Vacíos por día")

    invalids = query_invalid_emails(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    tbl = invalids.to_dict("records")

    dom = query_top_domains_valid(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    fig_dom = px.bar(dom, x="domain", y="cnt", title="Top dominios (emails válidos)")

    dup = query_top_duplicated_emails(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    fig_dup = px.bar(dup.sort_values("occurrences"), x="occurrences", y="Email", orientation="h", title="Top emails duplicados (válidos)")

    df_env = query_enviables_por_dia(start_date, end_date, ckin_start, ckout_end, agency, dest, cond, loc)
    fig_env = px.bar(title="Sin datos de enviables en el rango seleccionado") if df_env.empty else \
        px.line(df_env, x="fecha", y="enviables", color="agency", line_dash="flujo",
                title="Enviables por día (por Agency y Condactivación)", markers=True)

    fig_env.update_layout(xaxis_title=None, yaxis_title="Emails únicos válidos")

    return (
        kpi_card(total, "Total", "secondary"),
        kpi_card(con_em, "Con email", "info"),
        kpi_card(vacios, "Vacíos", "warning"),
        kpi_card(validos, "Válidos", "success"),
        kpi_card(dups, "Duplicados", "danger"),
        kpi_card(enviables, "Enviables", "dark"),
        fig_tot, fig_vacios, tbl, fig_dom, fig_dup, fig_env
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=True)
