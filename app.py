import streamlit as st
import sqlite3
import tempfile
import subprocess
import os
import pandas as pd

st.set_page_config(page_title="WordPress SQL Viewer", layout="wide")
st.title("📚 WordPress SQL Dump Viewer")

st.write("Upload een `.sql` bestand van een oude WordPress-site om posts en pagina’s te bekijken.")

uploaded_file = st.file_uploader("Upload SQL-bestand", type=["sql"])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".sql") as tmp_sql:
        tmp_sql.write(uploaded_file.read())
        tmp_sql_path = tmp_sql.name

    db_path = os.path.join(tempfile.gettempdir(), "wp_temp.db")

    # Lege database aanmaken
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.close()

    try:
        # SQL-bestand importeren in SQLite
        result = subprocess.run(["sqlite3", db_path, f".read {tmp_sql_path}"], capture_output=True, text=True, shell=True)
        if result.stderr:
            st.warning("⚠️ Waarschuwing tijdens import: sommige MySQL-syntaxis werkt mogelijk niet direct in SQLite.")
    except Exception as e:
        st.error(f"Import mislukt: {e}")
        st.stop()

    st.success("✅ SQL-bestand geïmporteerd!")

    # Ophalen van posts/pagina's
    try:
        conn = sqlite3.connect(db_path)
        query = """
        SELECT ID, post_title, post_type, post_status, post_date
        FROM wp_posts
        WHERE post_type IN ('post','page')
        ORDER BY post_date DESC
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        st.subheader("📄 Posts & Pagina’s")
        st.dataframe(df[["ID","post_title","post_type","post_status","post_date"]])

        selected_id = st.selectbox("Selecteer een post om de inhoud te bekijken:", df["ID"])

        if selected_id:
            conn = sqlite3.connect(db_path)
            content_df = pd.read_sql_query(f"SELECT post_title, post_content FROM wp_posts WHERE ID={selected_id}", conn)
            conn.close()

            if not content_df.empty:
                st.markdown(f"### 📝 {content_df.iloc[0]['post_title']}")
                st.markdown(content_df.iloc[0]['post_content'], unsafe_allow_html=True)
            else:
                st.warning("Geen content gevonden voor deze post.")
    except Exception as e:
        st.error(f"Kon data niet uitlezen: {e}")
else:
    st.info("⬆️ Upload een WordPress .sql dump om te beginnen.")
