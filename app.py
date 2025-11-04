import streamlit as st
import sqlite3
import tempfile
import os
import pandas as pd
import re

st.set_page_config(page_title="WordPress SQL Viewer", layout="wide")
st.title("📚 WordPress SQL Dump Viewer (inclusief data-import)")

st.write("Upload een `.sql` export uit phpMyAdmin om de inhoud van `wp_posts` te bekijken.")

uploaded_file = st.file_uploader("Upload SQL-bestand", type=["sql"])

def clean_mysql_schema(sql_text: str) -> str:
    # Maak CREATE TABLE compatibel
    sql_text = sql_text.replace("`", '"')
    sql_text = re.sub(r"AUTO_INCREMENT=\d+", "", sql_text)
    sql_text = re.sub(r"ENGINE=.*?;", ";", sql_text)
    sql_text = re.sub(r"DEFAULT CHARSET=.*?;", ";", sql_text)
    sql_text = re.sub(r"COLLATE [^\s;]+", "", sql_text)
    sql_text = re.sub(r"bigint\(20\) unsigned", "INTEGER", sql_text)
    sql_text = re.sub(r"int\(11\)", "INTEGER", sql_text)
    sql_text = re.sub(r"varchar\(\d+\)", "TEXT", sql_text)
    sql_text = re.sub(r"longtext", "TEXT", sql_text)
    sql_text = re.sub(r"text", "TEXT", sql_text)
    sql_text = re.sub(r"datetime", "TEXT", sql_text)
    sql_text = re.sub(r"\(\d+\)", "", sql_text)
    sql_text = re.sub(r"\/\*![0-9]+.*?\*\/;", "", sql_text, flags=re.DOTALL)
    return sql_text

def extract_inserts(sql_text: str):
    # Vind alle INSERT-statements specifiek voor wp_posts
    inserts = re.findall(r"INSERT INTO [`\"]?wp_posts[`\"]?.*?;", sql_text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = []
    for ins in inserts:
        ins = ins.replace("`", '"')
        ins = ins.replace("\\'", "''")
        ins = re.sub(r"ON DUPLICATE KEY.*", "", ins, flags=re.IGNORECASE)
        cleaned.append(ins.strip())
    return cleaned

if uploaded_file:
    raw_sql = uploaded_file.read().decode("utf-8", errors="ignore")
    schema_sql = clean_mysql_schema(raw_sql)
    inserts = extract_inserts(raw_sql)

    db_path = os.path.join(tempfile.gettempdir(), "wp_temp.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Probeer CREATE TABLEs uit te voeren
        for stmt in schema_sql.split(";"):
            s = stmt.strip()
            if s:
                try:
                    cur.execute(s)
                except Exception:
                    pass
        conn.commit()

        # Controleer wp_posts, anders handmatig aanmaken
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wp_posts';")
        if not cur.fetchone():
            st.warning("`wp_posts` niet aangemaakt — standaardstructuur toegevoegd.")
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

        # Voer alle INSERTS uit
        count = 0
        for ins in inserts:
            try:
                cur.execute(ins)
                count += 1
            except Exception:
                # Meerdere VALUES in één statement → splitsen
                match = re.search(r"VALUES\s*(\(.*\))", ins, flags=re.IGNORECASE | re.DOTALL)
                if match:
                    values_block = match.group(1)
                    tuples = re.findall(r"\((.*?)\)", values_block)
                    for t in tuples:
                        t_stmt = "INSERT INTO wp_posts VALUES (" + t + ");"
                        try:
                            cur.execute(t_stmt)
                            count += 1
                        except Exception:
                            pass
        conn.commit()

        st.success(f"✅ SQL-bestand geïmporteerd! ({count} inserts uitgevoerd)")
    except Exception as e:
        st.error(f"Import mislukt: {e}")
        st.stop()

    # Toon tabellen
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
            st.warning("Geen posts of pagina’s gevonden. (Mogelijk geen INSERT-data in dump.)")
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
