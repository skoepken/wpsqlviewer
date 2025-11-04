import streamlit as st
import sqlite3, tempfile, os, re, pandas as pd

st.set_page_config(page_title="WordPress SQL Viewer", layout="wide")
st.title("📚 WordPress SQL Dump Viewer – wp_posts Extractor")

st.write("""
Upload een volledige `.sql` export uit phpMyAdmin of MariaDB.  
De app haalt automatisch alleen de **wp_posts**-tabel (structuur + data) eruit,  
maakt ze SQLite-compatibel en toont je posts en pagina’s.
""")

uploaded = st.file_uploader("Upload SQL-bestand", type=["sql"])

# ---------- hulpfuncties ----------

CREATE_FALLBACK = """
CREATE TABLE IF NOT EXISTS wp_posts (
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
"""

def strip_mysql_comments(sql_text: str) -> str:
    """Verwijder MySQL-specifieke /*!...*/ comments en LOCK/UNLOCK statements."""
    s = re.sub(r"/\*![0-9]+.*?\*/;", "", sql_text, flags=re.DOTALL)
    s = re.sub(r"LOCK TABLES .*?;", "", s, flags=re.IGNORECASE)
    s = re.sub(r"UNLOCK TABLES;", "", s, flags=re.IGNORECASE)
    return s

def extract_wp_posts_block(sql_text: str) -> str:
    """Neem de DROP/CREATE/INSERT stukken die specifiek op wp_posts slaan."""
    blocks = []
    # DROP
    drop_matches = re.findall(r"(?im)^DROP\s+TABLE\s+IF\s+EXISTS\s+[`'\"]?wp_posts[`'\"]?\s*;\s*", sql_text)
    blocks += drop_matches
    # CREATE
    create_match = re.search(
        r'(?is)CREATE\s+TABLE\s+[`\'"]?wp_posts[`\'"]?\s*\((.*?)\)\s*[^;]*;',
        sql_text
    )
    if create_match:
        blocks.append(create_match.group(0))
    # INSERTS
    insert_matches = re.findall(
        r'(?is)INSERT\s+INTO\s+[`\'"]?wp_posts[`\'"]?.*?;',
        sql_text
    )
    blocks += insert_matches
    return "\n".join(blocks)

def mysql_create_to_sqlite(create_sql: str) -> str:
    """Maak MySQL CREATE wp_posts compatibel met SQLite."""
    if not create_sql:
        return ""
    s = create_sql.replace("`", '"')
    s = re.sub(r"ENGINE\s*=\s*[^;]*;", ";", s, flags=re.IGNORECASE)
    s = re.sub(r"DEFAULT\s+CHARSET\s*=\s*[^;]*;", ";", s, flags=re.IGNORECASE)
    s = re.sub(r"COLLATE\s+[^\s;]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"AUTO_INCREMENT\s*=\s*\d+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"COMMENT\s+'[^']*'", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bbigint\s*\(\s*\d+\s*\)\s*unsigned", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\bint\s*\(\s*\d+\s*\)", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\btinyint\s*\(\s*\d+\s*\)\s*unsigned", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\bvarchar\s*\(\s*\d+\s*\)", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\blongtext\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\btext\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bdatetime\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bunsigned\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?im)^\s*(UNIQUE\s+)?KEY\s+.*?,\s*$", "", s)
    s = re.sub(r",\s*(\)|PRIMARY|$)", r"\1", s)
    if not s.strip().endswith(";"):
        s = s.rstrip() + ";"
    s = re.sub(r'CREATE\s+TABLE\s+"wp_posts"', 'CREATE TABLE wp_posts', s, flags=re.IGNORECASE)
    s = s.replace("AUTO_INCREMENT", "")
    return s

def normalize_inserts(s: str) -> str:
    """Maak INSERTS iets veiliger voor SQLite."""
    s = s.replace("`", '"')
    s = re.sub(r"ON\s+DUPLICATE\s+KEY\s+UPDATE.*?;", ";", s, flags=re.IGNORECASE|re.DOTALL)
    s = strip_mysql_comments(s)
    return s

# ---------- main ----------
if uploaded:
    raw = uploaded.read().decode("utf-8", errors="ignore")
    wp_block = extract_wp_posts_block(raw)
    if not wp_block:
        st.error("Kon geen wp_posts-sectie vinden in dit bestand.")
        st.stop()

    create_match = re.search(r'(?is)CREATE\s+TABLE\s+[`\'"]?wp_posts[`\'"]?\s*\(.*?\)\s*[^;]*;', wp_block)
    create_sql_mysql = create_match.group(0) if create_match else ""
    insert_sql_mysql = "\n".join(
        re.findall(r'(?is)INSERT\s+INTO\s+[`\'"]?wp_posts[`\'"]?.*?;', wp_block)
    )

    create_sql_sqlite = mysql_create_to_sqlite(create_sql_mysql)
    insert_sql_sqlite = normalize_inserts(insert_sql_mysql)

    db = os.path.join(tempfile.gettempdir(), "wp_temp.db")
    if os.path.exists(db):
        os.remove(db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    cur.executescript(CREATE_FALLBACK)
    conn.commit()

    if create_sql_sqlite.strip():
        try:
            cur.executescript(create_sql_sqlite)
            conn.commit()
        except Exception:
            pass  # fallback bestaat al

    # --- multi-row inserts correct uitvoeren ---
    inserted_ok = 0
    if insert_sql_sqlite.strip():
        inserts = re.findall(r'(?is)(INSERT\s+INTO\s+["\']?wp_posts["\']?.*?;)', insert_sql_sqlite)
        for ins in inserts:
            stmt = ins.strip()
            if not stmt:
                continue
            try:
                cur.executescript(stmt)
                conn.commit()
                inserted_ok = 1
            except Exception:
                stmt2 = stmt.replace("\\n", " ").replace("\\r", " ")
                try:
                    cur.executescript(stmt2)
                    conn.commit()
                    inserted_ok = 1
                except Exception:
                    pass

    # --- debug: tabellen en rijen ---
    tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;", conn)
    st.caption("📋 Tabellen gevonden:")
    st.dataframe(tables)

    try:
        count_df = pd.read_sql_query("SELECT COUNT(*) AS n FROM wp_posts;", conn)
        st.caption(f"🧮 Aantal rijen in wp_posts: {int(count_df.iloc[0]['n'])}")
    except Exception:
        st.warning("wp_posts bestaat nog steeds niet.")

    # --- toon posts/pagina's ---
    try:
        df = pd.read_sql_query(
            """
            SELECT ID, post_title, post_type, post_status, post_date
            FROM wp_posts
            WHERE post_type IN ('post','page')
            ORDER BY post_date DESC
            """,
            conn
        )
        if df.empty:
            if inserted_ok == 0:
                st.warning("Geen INSERTS uitgevoerd (dump bevatte mogelijk geen data).")
            else:
                st.warning("Geen posts/pagina’s gevonden (mogelijk andere post_types).")
        else:
            st.subheader("📄 Posts & Pagina’s")
            st.dataframe(df)
            sel = st.selectbox("Kies een post:", df["ID"])
            if sel:
                content = pd.read_sql_query(
                    "SELECT post_title, post_content FROM wp_posts WHERE ID = ?",
                    conn, params=(int(sel),)
                )
                if not content.empty:
                    st.markdown(f"### {content.iloc[0]['post_title']}")
                    st.markdown(content.iloc[0]['post_content'], unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Fout bij uitlezen: {e}")
    finally:
        conn.close()
else:
    st.info("⬆️ Upload een phpMyAdmin-export (.sql) om te beginnen.")
