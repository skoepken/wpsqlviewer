import streamlit as st
import sqlite3
import tempfile
import os
import pandas as pd
import re

st.set_page_config(page_title="WordPress SQL Viewer", layout="wide")
st.title("📚 WordPress SQL Dump Viewer (MySQL → SQLite converter)")

st.write("Upload een `.sql` bestand (zoals geëxporteerd uit phpMyAdmin) om je WordPress posts en pagina’s te bekijken.")

uploaded_file = st.file_uploader("Upload SQL-bestand", type=["sql"])

def convert_mysql_to_sqlite(sql_text: str) -> str:
    """
    Zet MySQL SQL dump om naar SQLite-compatibel SQL.
    """
    # Vervang backticks door dubbele aanhalingstekens
    sql_text = sql_text.replace('`', '"')

    # Verwijder ENGINE, AUTO_INCREMENT, DEFAULT CHARSET, COLLATE, etc.
    sql_text = re.sub(r'ENGINE=.*?;', ';', sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r'AUTO_INCREMENT=\d+', '', sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r'DEFAULT CHARSET=.*?;', ';', sql_text, flags=re.IGNORECASE)
    sql_text = re.sub(r'COLLATE [^\s;]+', '', sql_text, flags=re.IGNORECASE)

    # MySQL booleans → SQLite
    sql_text = sql_text.replace('tinyint(1)', 'INTEGER')

    # Unsigned → verwijderen (SQLite kent dat niet)
    sql_text = sql_text.replace('unsigned', '')

    # ON UPDATE CURRENT_TIMESTAMP → verwijderen
    sql_text = re.sub(r'ON UPDATE CURRENT_TIMESTAMP', '', sql_text, flags=re.IGNORECASE)

    # COMMENTs verwijderen
    sql_text = re.sub(r'COMMENT\s+\'[^\']*\'', '', sql_text, flags=re.IGNORECASE)

    return sql_text

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".sql") as tmp_sql:
        raw_sql = uploaded_file.read().decode("utf-8", errors="ignore")
        converted_sql = convert_mysql_to_sqlite(raw_sql)
        tmp_sql.write(converted_sql.encode("utf-8"))
        tmp_sql_path = tmp_sql.name

    db_path = os.path.join(tempfile.gettempdir(), "wp_temp.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Splitsen op puntkomma’s om SQL-statement per stuk uit te voeren
        for statement in converted_sql.split(';'):
            stmt = statement.strip()
            if stmt:
                try:
                    cursor.execute(stmt)
                except Exception:
                    # Veel dumps hebben INSERT’s met rare tekens → overslaan
                    pass
        conn.commit()
        st.success("✅ SQL-bestand succesvol geconverteerd en geïmporteerd!")
    except Exception as e:
        st.error(f"Import mislukt: {e}")
        st.stop()

    # Ophalen van posts/pagina's
    try:
        query = """
        SELECT ID, post_title, post_type, post_status, post_date
        FROM wp_posts
        WHERE post_type IN ('post','page')
        ORDER BY post_date DESC
        """
        df = pd.read_sql_query(query, conn)

        if df.empty:
            st.warning("Geen posts/pagina’s gevonden. Controleer of je dump de tabel `wp_posts` bevat.")
        else:
            st.subheader("📄 Posts & Pagina’s")
            st.dataframe(df[["ID","post_title","post_type","post_status","post_date"]])

            selected_id = st.selectbox("Selecteer een post om de inhoud te bekijken:", df["ID"])

            if selected_id:
                content_df = pd.read_sql_query(
                    f"SELECT post_title, post_content FROM wp_posts WHERE ID={selected_id}", conn
                )
                if not content_df.empty:
                    st.markdown(f"### 📝 {content_df.iloc[0]['post_title']}")
                    st.markdown(content_df.iloc[0]['post_content'], unsafe_allow_html=True)
                else:
                    st.warning("Geen content gevonden voor deze post.")
    except Exception as e:
        st.error(f"Kon data niet uitlezen: {e}")
    finally:
        conn.close()
else:
    st.info("⬆️ Upload een WordPress .sql export uit phpMyAdmin om te beginnen.")
