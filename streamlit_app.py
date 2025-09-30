#!/usr/bin/env python3
"""
Point d'entrée Streamlit pour le déploiement (Cloud/local).
Déclenche l'UI principale définie dans tools/streamlit_ui.py
et ajoute un aperçu minimal des données collectées (CSV le plus récent).
"""
from pathlib import Path
from contextlib import closing
import glob
import sqlite3

import httpx
import pandas as pd
import streamlit as st

from tools.streamlit_ui import main as ui_main


@st.cache_data(show_spinner=False)
def load_latest_export(path: str = "exports/latest_export.csv") -> pd.DataFrame:
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def list_export_csvs(pattern: str = "exports/*.csv") -> list[str]:
    return sorted(glob.glob(pattern))


@st.cache_data(show_spinner=False)
def load_csv(path: str, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(path, nrows=nrows)


@st.cache_data(show_spinner=False)
def list_sqlite_dbs(pattern: str = "data/*.db") -> list[str]:
    return sorted(glob.glob(pattern))


@st.cache_data(show_spinner=False)
def list_sqlite_tables(db_path: str) -> list[str]:
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
            rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def preview_sqlite_table(db_path: str, table: str, limit: int = 500) -> pd.DataFrame:
    query = f"SELECT * FROM {table} LIMIT {int(limit)}"
    with closing(sqlite3.connect(db_path)) as conn:
        return pd.read_sql_query(query, conn)


@st.cache_data(show_spinner=False)
def fetch_coingecko_price(coin_id: str = "bitcoin", vs: str = "usd") -> dict:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={vs}"
    with httpx.Client(timeout=10) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


@st.cache_data(show_spinner=False)
def fetch_bybit_lsr(symbol: str = "BTCUSDT") -> dict | None:
    url = "https://api.bybit.com/v5/market/account-ratio"
    params = {"symbol": symbol, "category": "linear", "period": "24h"}
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


if __name__ == "__main__":
    # Page de configuration principale
    ui_main()

    # Aperçu minimal des données collectées (si le CSV existe)
    st.divider()
    st.header("Données collectées – aperçu rapide")
    csv = Path("exports/latest_export.csv")
    if csv.exists():
        df = load_latest_export(str(csv))
        st.dataframe(df, width='stretch')
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            st.line_chart(df[num_cols[: min(3, len(num_cols))]])
    else:
        st.info(
            "Fichier introuvable: exports/latest_export.csv. "
            "Lancez une collecte/export (ex: main.py) pour générer cet export."
        )

    st.divider()
    tab_csv, tab_db, tab_live = st.tabs(["Explorateur CSV", "SQLite", "Live APIs"])

    with tab_csv:
        csvs = list_export_csvs()
        if not csvs:
            st.info("Aucun CSV trouvé dans exports/.")
        else:
            col1, col2 = st.columns([3, 1])
            with col1:
                choice = st.selectbox("Fichier CSV", csvs, index=len(csvs) - 1)
            with col2:
                nrows = st.number_input("Aperçu (nrows)", min_value=50, max_value=5000, value=100, step=50)
            try:
                dfp = load_csv(choice, int(nrows))
                st.dataframe(dfp, width='stretch')
                num = dfp.select_dtypes(include=["number"]).columns
                if len(num) > 0:
                    st.area_chart(dfp[num])
            except Exception as e:
                st.error(f"Erreur de lecture: {e}")

    with tab_db:
        dbs = list_sqlite_dbs()
        if not dbs:
            st.info("Aucune base SQLite (data/*.db) trouvée.")
        else:
            db_choice = st.selectbox("Base SQLite", dbs, index=0)
            tables = list_sqlite_tables(db_choice)
            if not tables:
                st.warning("Aucune table détectée.")
            else:
                t_choice = st.selectbox("Table", tables, index=0)
                limit = st.slider("Limite", min_value=50, max_value=5000, value=500, step=50)
                try:
                    df_sql = preview_sqlite_table(db_choice, t_choice, int(limit))
                    st.dataframe(df_sql, width='stretch')
                except Exception as e:
                    st.error(f"Erreur SQL: {e}")

    with tab_live:
        st.subheader("Prix spot – CoinGecko")
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            coin = st.text_input("Coin ID", value="bitcoin")
        with c2:
            vs = st.text_input("Devise", value="usd")
        with c3:
            if st.button("Actualiser prix", use_container_width=True):
                st.cache_data.clear()
        try:
            price = fetch_coingecko_price(coin, vs)
            st.json(price)
        except Exception as e:
            st.error(f"CoinGecko erreur: {e}")

        st.divider()
        st.subheader("Bybit – Long/Short Ratio (24h)")
        colb1, colb2 = st.columns([3, 1])
        with colb1:
            sym = st.text_input("Symbole", value="BTCUSDT")
        with colb2:
            refresh = st.button("Actualiser LSR", use_container_width=True)
        if refresh:
            st.cache_data.clear()
        data = fetch_bybit_lsr(sym)
        if data is None:
            st.warning("Aucune donnée LSR (Bybit) disponible.")
        else:
            st.json(data)
