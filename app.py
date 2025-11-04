import streamlit as st
import sqlite3
import tempfile
import os
import pandas as pd
import re

st.set_page_config(page_title="WordPress SQL Viewer", layout="wide")
st.title("📚 WordPress SQL Dump Viewer (auto-convert MySQL → SQLite)")

st.write("Upload een `.sql` export uit phpMyAdmin om de inhoud van `wp_posts` te bekijken.")

uploaded_file = st.file_uploader("Upload SQL-bestand", type=["sql"])

def convert_mysql_to_sqlite(sql_text: str) -> str:
    # Backticks → dubbele aanhalingstekens
    sql_text = sql_text.replace("`", '"')

    # MySQL-specifieke opties verwijderen
    sql_text = re.sub(r"AUTO_INCREMENT=\d+", "", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"ENGINE=.*?;", ";", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"DEFAULT CHARSET=.*?;", ";", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"COLLATE [^\s;]+", "", sql_text, flags=re.IGNORECASE)

    # MySQL types → SQLite types
    sql_text = re.sub(r"bigint\(20\) unsigned", "INTEGER", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"int\(11\)", "INTEGER", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"varchar\(\d+\)", "TEXT", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"longtext", "TEXT", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"text", "TEXT", sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r"datetime", "TEXT", sql_text, flags=re.IGNORECASE)

    # Verwijder indexlengtes: (191) → niets
    sql_text = re.sub(r"\(\d+\)", "", sql_text)

    # Drop statements die SQLite niet snapt
    sql_text = re.sub(r"\/\*![0-9]+.*?\*\/;", "", sql_text, flags=re.DOTALL)

    return sql_text


if uploaded_file:
    raw_sql = uploaded_file.read().decode("utf-8", errors="ignore")
    converted_sql = convert_mysql_to_sqlite(raw_sql)

    db_path = os.path.join(tempfile.gettempdir(), "wp_temp.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Probeer de CREATE TABLE ... zelf uit te voeren
        for stmt in converted_sql.split(";"):
            s = stmt.strip()
            if not s:
                continue
            try:
                cur.execute(s)
            except Exception:
                # negeer statements die SQLite niet begrijpt (zoals INSERT met rare syntax)
                pass
        conn.commit()

        # check of wp_posts bestaat; anders handmatig aanmaken
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wp_posts';")
        if not cur.fetchone():
            st.warning("`wp_posts` niet aangemaakt — handmatige tabelstructuur toegevoegd.")
            cur.executescript("""
                CREATE TABLE wp_posts (
                    ID INTEGER PRIMARY KEY,
                    post_author INTEGER,
                    post_date TEXT,
                    post_date_gmt TEXT,
                    post_content TEXT,
                    post_title TEXT,
                    post_excerpt TEXT,
                    post_status TEXT,
                    comment_status TEXT,
                    ping_status TEXT,
                    post_password TEXT,
                    post_name TEXT,
                    to_ping TEXT,
                    pinged TEXT,
                    post_modified TEXT,
                    post_modified_gmt TEXT,
                    post_content_filtered TEXT,
                    post_parent INTEGER,
                    guid TEXT,
                    menu_order INTEGER,
                    post_type TEXT,
                    post_mime_type TEXT,
                    comment_count INTEGER
                );
            """)
            conn.commit()

        st.success("✅ SQL-bestand geïmporteerd!")
    except Exception as e:
        st.error(f"Import mislukt: {e}")
        st.stop()

    # Toon tabellen voor debug
    tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", conn)
    st.write("📋 Tabellen gevonden:", tables)

    try:
        query = """
        SELECT ID, post_title, post_type, post_status, post_date
        FROM wp_posts
        WHERE post_type IN ('post','page')
        ORDER BY post_date DESC
        """
        df = pd.read_sql_query(query, conn)

        if df.empty:
            st.warning("Geen posts of pagina’s gevonden.")
        else:
            st.subheader("📄 Posts & Pagina’s")
            st.dataframe(df[["ID","post_title","post_type","post_status","post_date"]])

            selected_id = st.selectbox("Kies een post om te bekijken:", df["ID"])
            content_df = pd.read_sql_query(
                f"SELECT post_title, post_content FROM wp_posts WHERE ID={selected_id}", conn
            )
            if not content_df.empty:
                st.markdown(f"### 📝 {content_df.iloc[0]['post_title']}")
                st.markdown(content_df.iloc[0]['post_content'], unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Kon data niet uitlezen: {e}")
    finally:
        conn.close()
else:
    st.info("⬆️ Upload een WordPress `.sql` export uit phpMyAdmin om te beginnen.")
