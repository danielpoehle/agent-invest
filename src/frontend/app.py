import streamlit as st
import sqlite3
import sys
import os
import subprocess
from datetime import datetime

# Wir fügen den src-Ordner zum Pfad hinzu, um die Datenbank importieren zu können
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.database import DatabaseManager

# ==========================================
# SEITEN-KONFIGURATION
# ==========================================
st.set_page_config(
    page_title="KI Investment Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# DATENBANK VERBINDUNG
# ==========================================
# Wir suchen den Pfad zur SQLite DB relativ zu diesem Skript
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
db_path = os.path.join(base_dir, 'data', 'investment_system.db')

@st.cache_resource
def get_db():
    return DatabaseManager(db_path=db_path)

db = get_db()

# ==========================================
# UI: SEITENLEISTE (Sidebar)
# ==========================================
st.sidebar.title("🤖 Agenten-Steuerung")
st.sidebar.markdown("---")

# Kalender-Auswahl für Berichte
selected_date = st.sidebar.date_input("🗓️ Berichtsdatum auswählen", datetime.today())
selected_date_str = selected_date.strftime('%Y-%m-%d')
today_str = datetime.today().strftime('%Y-%m-%d')

st.sidebar.markdown("---")
# Kleines Info-Panel zum Portfolio in der Sidebar
portfolio = db.get_portfolio_for_agent()
st.sidebar.subheader("💼 Aktuelles Portfolio")
st.sidebar.write(f"**Gesamtwert:** {portfolio['total_value']:,.2f} €")
st.sidebar.write(f"**Cash:** {portfolio['cash']:,.2f} €")

# ==========================================
# UI: HAUPTBEREICH
# ==========================================
st.title(f"Tagesbericht: {selected_date.strftime('%d.%m.%Y')}")

# Versuche den Bericht für das gewählte Datum aus der DB zu laden
db.cursor.execute("SELECT markdown_text, raw_json_data FROM daily_reports WHERE date = ?", (selected_date_str,))
row = db.cursor.fetchone()

if row:
    # 1. BERICHT GEFUNDEN -> ANZEIGEN
    markdown_text = row[0]
    raw_json = row[1]
    
    st.success(f"Bericht aus der Datenbank geladen.")
    
    # Den Markdown-Text des Lead Agents wunderschön rendern
    st.markdown(markdown_text)
    
    # Als Bonus: Die rohen Agenten-Daten ausklappbar machen
    with st.expander("🛠️ Rohe Agenten-Daten (JSON) einsehen"):
        st.json(raw_json)
        
else:
    # 2. KEIN BERICHT GEFUNDEN
    st.warning(f"Für das Datum **{selected_date.strftime('%d.%m.%Y')}** liegt kein Bericht vor.")
    
    # 3. BONUS: WENN DAS DATUM HEUTE IST -> GENERIEREN ERLAUBEN
    if selected_date_str == today_str:
        st.info("Möchtest du deine KI-Agenten jetzt aufwecken und den heutigen Bericht generieren lassen?")
        
        if st.button("🚀 Agenten-Crew starten (Bericht generieren)", use_container_width=True):
            
            # Zeigt einen Ladekreis an, während das Backend rechnet
            with st.spinner("Die Agenten analysieren den Markt. Das kann ca. 1-2 Minuten dauern..."):
                try:
                    # Wir rufen unsere main.py als separaten Prozess auf
                    main_script_path = os.path.join(base_dir, 'src', 'main.py')
                    
                    # Führt das Skript im Hintergrund aus
                    result = subprocess.run(
                        [sys.executable, main_script_path], 
                        capture_output=True, 
                        text=True, 
                        check=True
                    )
                    
                    st.success("✅ Der Bericht wurde erfolgreich generiert!")
                    # Lädt die Seite neu, damit der Bericht aus der DB angezeigt wird
                    st.rerun()
                    
                except subprocess.CalledProcessError as e:
                    st.error("❌ Es gab einen Fehler bei der Ausführung der Agenten.")
                    with st.expander("Fehlerdetails ansehen"):
                        st.code(e.stderr or e.stdout)