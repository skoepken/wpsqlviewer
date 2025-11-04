import streamlit as st
import sqlite3, tempfile, os, re, pandas as pd

st.set_page_config(page_title="WordPress Dump Viewer", layout="wide")
st.title("📚 WordPress Dump Viewer – wp_posts Extractor")

st.write("Upload je volledige `.sql` export (uit phpMyAdmin). De app haalt automatisch **alleen de wp_posts** eruit en toont de inhoud.")

uploaded = st.file_uploader("Upload SQL-bestand", type=["sql"])

def extract_wp_posts_section(sql_text:str) -> str:
    """Haal alleen de CREATE + INSERTS van wp_posts uit het dumpbestand."""
    lines = sql_text.splitlines()
    keep = False
    extracted = []
    for line in lines:
        # Start van wp_posts structuur
        if re.search(r"CREATE TABLE [`'\"]?wp_posts[`'\"]?", line):
            keep = True
        elif keep and re.search(r"CREATE TABLE [`'\"]?wp_", line) and "wp_posts" not in line:
            # stop bij volgende tabel
            keep = False
        if keep:
            extracted.append(line)
        # Altijd inserts meenemen
        if re.search(r"INSERT INTO [`'\"]?wp_posts[`'\"]?", line):
            extracted.append(line)
    return "\n".join(extracted)

def make_sqlite_friendly(sql_text:str) -> str:
    sql_text = sql_text.replace("`", '"')
    sql_text = re.sub(r"AUTO_INCREMENT=\d+", "", sql_text)
    sql_text = re.sub(r"ENGINE=.*?;", ";", sql_text)
    sql_text = re.sub(r"DEFAULT CHARSET=.*?;", ";", sql_text)
    sql_text = re.sub(r"COLLATE [^\s;]+", "", sql_text)
    sql_text = re.sub(r"bigint\(20\) unsigned", "INTEGER", sql_text)
    sql_text = re.sub(r"int\(11\)", "INTEGER", sql_text)
    sql_text = re.sub(r"varchar\(\d+\)", "TEXT", sql_text)
    sql_text = re.sub(r"longtext", "TEXT", sql_text)
    sql_text = re.sub(r"datetime", "TEXT", sql_text)
    sql_text = re.sub(r"\(\d+\)", "", sql_text)
    return sql_text

if uploaded:
    raw = uploaded.read().decode("utf-8", errors="ignore")
    wp_sql = extract_wp_posts_section(raw)
    if not wp_sql:
        st.error("Geen wp_posts sectie gevonden in dit bestand.")
        st.stop()

    converted = make_sqlite_friendly(wp_sql)

    db = os.path.join(tempfile.gettempdir(), "wp_temp.db")
    if os.path.exists(db):
        os.remove(db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    # maak tabellen en vul data
    for stmt in converted.split(";"):
        s = stmt.strip()
        if not s:
            continue
        try:
            cur.execute(s)
        except Exception:
            pass
    conn.commit()

    # check wp_posts
    try:
        df = pd.read_sql_query(
            """SELECT ID, post_title, post_type, post_status, post_date 
               FROM wp_posts 
               WHERE post_type IN ('post','page') 
               ORDER BY post_date DESC""",
            conn
        )
        if df.empty:
            st.warning("Geen zichtbare posts/pagina’s gevonden (mogelijk geen data in dump).")
        else:
            st.dataframe(df)
            sel = st.selectbox("Kies een post om te bekijken:", df["ID"])
            if sel:
                content = pd.read_sql_query(
                    f"SELECT post_title, post_content FROM wp_posts WHERE ID={sel}", conn
                )
                st.markdown(f"### {content.iloc[0]['post_title']}")
                st.markdown(content.iloc[0]['post_content'], unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Fout bij uitlezen: {e}")
    finally:
        conn.close()
else:
    st.info("⬆️ Upload een phpMyAdmin-export om te beginnen.")
