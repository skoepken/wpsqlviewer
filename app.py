import streamlit as st
import sqlite3, tempfile, os, re, pandas as pd

st.set_page_config(page_title="WordPress Dump Viewer", layout="wide")
st.title("📚 WordPress Dump Viewer – alleen wp_posts")

st.write("Upload je volledige `.sql` export (phpMyAdmin). De app haalt automatisch **alleen wp_posts** (CREATE + INSERTS) eruit, zet het om naar SQLite en toont je posts/pagina’s.")

uploaded = st.file_uploader("Upload SQL-bestand", type=["sql"])

# ---------- helpers ----------
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

def extract_wp_posts_block(sql_text: str) -> str:
    """
    Neem de DROP/CREATE/INSERT stukken die specifiek op wp_posts slaan.
    We laten alles als tekst en filteren puur op regels/blocks die wp_posts noemen.
    """
    # Verzamel alle regels die te maken hebben met wp_posts structuur + data
    blocks = []

    # 1) DROP TABLE IF EXISTS `wp_posts`;
    drop_matches = re.findall(r"(?im)^DROP\s+TABLE\s+IF\s+EXISTS\s+[`'\"]?wp_posts[`'\"]?\s*;\s*", sql_text)
    blocks += drop_matches

    # 2) CREATE TABLE `wp_posts` ( ... );
    create_match = re.search(
        r'(?is)CREATE\s+TABLE\s+[`\'"]?wp_posts[`\'"]?\s*\((.*?)\)\s*[^;]*;',
        sql_text
    )
    if create_match:
        create_body = create_match.group(0)  # volledige CREATE incl. trailing ;)
        blocks.append(create_body)

    # 3) Alle INSERTs in wp_posts (multi-line toegestaan, tot de volgende ;)
    insert_matches = re.findall(
        r'(?is)INSERT\s+INTO\s+[`\'"]?wp_posts[`\'"]?.*?;',
        sql_text
    )
    blocks += insert_matches

    return "\n".join(blocks)

def mysql_create_to_sqlite(create_sql: str) -> str:
    """
    Maak MySQL CREATE wp_posts compatibel met SQLite.
    We bewerken ALLEEN het CREATE-statement (niet de INSERTS).
    """
    if not create_sql:
        return ""

    s = create_sql

    # backticks -> dubbele quotes
    s = s.replace("`", '"')

    # ENGINE/CHARSET/COLLATE/COMMENT/AUTO_INCREMENT tail meenemen
    s = re.sub(r"ENGINE\s*=\s*[^;]*;", ";", s, flags=re.IGNORECASE)
    s = re.sub(r"DEFAULT\s+CHARSET\s*=\s*[^;]*;", ";", s, flags=re.IGNORECASE)
    s = re.sub(r"COLLATE\s+[^\s;]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"AUTO_INCREMENT\s*=\s*\d+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"COMMENT\s+'[^']*'", "", s, flags=re.IGNORECASE)

    # Datatypen versimpelen (alleen in de kolom-definities)
    # Let op: we wijzigen NIET de VALUES/INSERTs hier
    s = re.sub(r"\bbigint\s*\(\s*\d+\s*\)\s*unsigned", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\bint\s*\(\s*\d+\s*\)", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\btinyint\s*\(\s*\d+\s*\)\s*unsigned", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\bvarchar\s*\(\s*\d+\s*\)", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\blongtext\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\btext\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bdatetime\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bunsigned\b", "", s, flags=re.IGNORECASE)

    # KEY/INDEX regels die prefix-lengtes hebben -> simpeler of weg
    # (SQLite kan ze negeren; ze zijn niet nodig om data te tonen)
    # Verwijder volledige KEY/INDEX-regels
    s = re.sub(r"(?im)^\s*(UNIQUE\s+)?KEY\s+.*?,\s*$", "", s)

    # PRIMARY KEY laten we staan
    # Haal eventuele dubbele komma's op het einde weg
    s = re.sub(r",\s*(\)|PRIMARY|$)", r"\1", s)

    # Zorg dat het eindigt met puntkomma
    if not s.strip().endswith(";"):
        s = s.rstrip() + ";"

    # Herstel tabelnaam zonder quotes voor zekerheid
    s = re.sub(r'CREATE\s+TABLE\s+"wp_posts"', 'CREATE TABLE wp_posts', s, flags=re.IGNORECASE)

    # Maak van AUTO_INCREMENT op kolom-niveau gewoon PRIMARY KEY (al gedaan via types)
    s = s.replace("AUTO_INCREMENT", "")

    return s

def normalize_inserts(inserts_sql: str) -> str:
    """
    Inserts laten we grotendeels ongemoeid (best), maar:
    - backticks naar dubbele quotes
    - ON DUPLICATE KEY -> weg
    - NO_AUTO_VALUE_ON_ZERO is al elders, niet relevant hier
    """
    s = inserts_sql.replace("`", '"')
    s = re.sub(r"ON\s+DUPLICATE\s+KEY\s+UPDATE.*?;", ";", s, flags=re.IGNORECASE|re.DOTALL)
    return s

# ---------- main ----------
if uploaded:
    raw = uploaded.read().decode("utf-8", errors="ignore")

    # 1) haal wp_posts DROP/CREATE/INSERTS uit het hele bestand
    wp_block = extract_wp_posts_block(raw)
    if not wp_block:
        st.error("Kon de `wp_posts`-sectie niet vinden in dit bestand.")
        st.stop()

    # 2) splits CREATE en INSERTs
    create_match = re.search(r'(?is)CREATE\s+TABLE\s+[`\'"]?wp_posts[`\'"]?\s*\(.*?\)\s*[^;]*;', wp_block)
    create_sql_mysql = create_match.group(0) if create_match else ""

    insert_sql_mysql = "\n".join(
        re.findall(r'(?is)INSERT\s+INTO\s+[`\'"]?wp_posts[`\'"]?.*?;', wp_block)
    )

    # 3) zet CREATE om naar SQLite
    create_sql_sqlite = mysql_create_to_sqlite(create_sql_mysql)

    # 4) normaliseer INSERTs
    insert_sql_sqlite = normalize_inserts(insert_sql_mysql)

    # 5) maak tijdelijke sqlite db
    db = os.path.join(tempfile.gettempdir(), "wp_temp.db")
    if os.path.exists(db):
        os.remove(db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    # 6) zorg dat de tabel er ZEKER is
    cur.executescript(CREATE_FALLBACK)
    conn.commit()

    # 7) voer de (geconverteerde) CREATE uit bovenop fallback (overbodige errors negeren)
    if create_sql_sqlite.strip():
        try:
            cur.executescript(create_sql_sqlite)
            conn.commit()
        except Exception:
            pass  # maakt niet uit: fallback bestaat al

    # 8) voer alle INSERTS in één keer uit (executescript ondersteunt multi-row)
    inserted_ok = 0
    if insert_sql_sqlite.strip():
        try:
            cur.executescript(insert_sql_sqlite)
            conn.commit()
            inserted_ok = 1
        except Exception:
            # als multi-row stukloopt, probeer ruwer te splitsen per ;
            stmts = [s for s in insert_sql_sqlite.split(";") if s.strip()]
            for s in stmts:
                try:
                    cur.executescript(s + ";")
                    conn.commit()
                    inserted_ok = 1
                except Exception:
                    pass

    # 9) debug: lijst tabellen + aantal rows
    tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;", conn)
    st.caption("📋 Tabellen gevonden:")
    st.dataframe(tables)

    try:
        count_df = pd.read_sql_query("SELECT COUNT(*) AS n FROM wp_posts;", conn)
        st.caption(f"🧮 Aantal rijen in wp_posts: {int(count_df.iloc[0]['n'])}")
    except Exception:
        st.warning("wp_posts bestaat nog steeds niet. Dan ging CREATE of INSERT mis.")

    # 10) toon posts/pagina's
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
                st.warning("Geen inserts uitgevoerd (dump bevatte mogelijk geen `INSERT INTO wp_posts`).")
            else:
                st.warning("Geen posts/pagina’s gevonden (mogelijk alleen concepten of andere post_type). Probeer filter weg te halen.")
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
