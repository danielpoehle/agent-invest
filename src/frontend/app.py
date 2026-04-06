import streamlit as st
import sqlite3
import sys
import os
import subprocess
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

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
inception_date_str = db.get_system_config('inception_date') or "Unbekannt"

st.sidebar.subheader("💼 Aktuelles Portfolio")
st.sidebar.write(f"**Gesamtwert:** {portfolio['total_value']:,.2f} €")
st.sidebar.write(f"**Cash:** {portfolio['cash']:,.2f} €")

# Ein Expander, der dir deine genauen Positionen anzeigt
with st.sidebar.expander("📊 Portfolio-Details ansehen"):
    if portfolio['equities']:
        import pandas as pd
        df = pd.DataFrame(portfolio['equities'])
        # Wir blenden irrelevante Spalten für die Schnellansicht aus
        st.dataframe(df[['ticker', 'shares', 'avg_price', 'value']], hide_index=True)
    else:
        st.write("Dein Depot ist aktuell leer (100% Cash).")

st.sidebar.markdown("---")
# Das Formular zur Trade-Erfassung
st.sidebar.subheader("📝 Trade erfassen")
with st.sidebar.form("trade_form", clear_on_submit=True):
    t_date = st.date_input("Transaktions-Datum", datetime.today())
    
    col1, col2 = st.columns(2)
    with col1:
        t_type = st.selectbox("Aktion", ["BUY", "SELL"])
    with col2:
        t_ticker = st.text_input("Ticker (z.B. NVDA)")
        
    t_shares = st.number_input("Anzahl Stücke / Anteile", min_value=0.0001, step=1.0, format="%.4f")
    t_price = st.number_input("Preis pro Anteil (€)", min_value=0.01, step=1.0, format="%.2f")
    
    col3, col4 = st.columns(2)
    with col3:
        t_fee = st.number_input("Gebühren (€)", min_value=0.0, step=1.0, format="%.2f")
    with col4:
        t_tax = st.number_input("Steuern (€)", min_value=0.0, step=1.0, format="%.2f", help="Wird nur bei SELL berechnet")
        
    submit_trade = st.form_submit_button("💾 Trade in DB speichern", use_container_width=True)
    
    if submit_trade:
        if not t_ticker:
            st.error("Bitte einen Ticker eingeben.")
        else:
            try:
                db.log_trade(
                    date_str=t_date.strftime('%Y-%m-%d'),
                    trade_type=t_type,
                    ticker=t_ticker.upper(),
                    shares=t_shares,
                    price=t_price,
                    fee=t_fee,
                    tax=t_tax
                )
                st.success(f"{t_type} erfolgreich: {t_shares}x {t_ticker.upper()} gespeichert!")
                st.rerun() # Lädt die Seite neu, damit oben der Cash-Bestand aktualisiert wird
            except Exception as e:
                st.error(f"Fehler: {e}")

st.sidebar.markdown("---")
# Der Urknall (System Reset)
st.sidebar.subheader("⚠️ Admin-Bereich")
with st.sidebar.expander("🧨 System-Reset (Urknall)"):
    st.warning("ACHTUNG: Dies löscht ALLE Trades, das Portfolio und alle Berichte unwiderruflich!")
    
    reset_date = st.date_input("Neues Startdatum (Inception Date)", datetime.today())
    reset_balance = st.number_input("Neues Startkapital (€)", min_value=100.0, value=100000.0, step=1000.0)
    
    confirm_reset = st.checkbox("Ich bin mir absolut sicher.")
    
    if st.button("🚨 PORTFOLIO ZURÜCKSETZEN", type="primary", use_container_width=True):
        if confirm_reset:
            db.reset_database(reset_date.strftime('%Y-%m-%d'), reset_balance)
            st.success("💥 Urknall ausgeführt! Das System wurde auf Null gesetzt.")
            st.rerun()
        else:
            st.error("Bitte bestätige die Checkbox, um den Reset auszuführen.")

# Historie manuell nachladen
with st.sidebar.expander("⏳ Historie nachladen"):
    st.info("Lädt fehlende Performance-Daten für vergangene Tage nach. Rekonstruiert das Portfolio anhand der Trade-Historie.")
    backfill_date = st.date_input("Fehlendes Datum auswählen", datetime.today() - timedelta(days=1))
    
    if st.button("🔄 Daten nachladen", use_container_width=True):
        with st.spinner("Rekonstruiere historisches Portfolio..."):
            success, msg = db.backfill_historical_performance(backfill_date.strftime('%Y-%m-%d'))
            if success:
                st.success(msg)
                # Automatischer Rerun, damit Tabelle & Chart sofort aktualisiert werden
                # Kurzer Hinweis, damit der Nutzer die Success-Message noch lesen kann
                import time
                time.sleep(2) 
                st.rerun()
            else:
                st.error(msg)

# ==========================================
# UI: HAUPTBEREICH (mit Tabs)
# ==========================================
st.title("KI Investment Dashboard")

tab_report, tab_analytics = st.tabs(["📄 Tagesbericht", "📈 Performance & Analytics"])

# ------------------------------------------
# TAB 1: TAGESBERICHT
# ------------------------------------------

with tab_report:
    st.subheader(f"Marktanalyse vom {selected_date.strftime('%d.%m.%Y')}")

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

# ------------------------------------------
# TAB 2: PERFORMANCE & ANALYTICS
# ------------------------------------------

with tab_analytics:
    def render_analytics():
        st.subheader("Performance vs. MSCI World (SC0J.DE)")
        
        # 1. Daten aus DB holen
        db.cursor.execute("SELECT date, portfolio_value, benchmark_value FROM portfolio_history ORDER BY date ASC")
        rows = db.cursor.fetchall()
        
        if not rows:
            st.warning("Noch keine Historien-Daten vorhanden.")
            return
            
        df = pd.DataFrame(rows, columns=['date', 'Portfolio', 'Benchmark'])
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # 2. Rendite in Prozent normieren (Start bei 0%)
        start_pf = df['Portfolio'].iloc[0]
        start_bm = df['Benchmark'].iloc[0]
        
        df['Portfolio Rendite (%)'] = (df['Portfolio'] / start_pf - 1) * 100
        df['Benchmark Rendite (%)'] = (df['Benchmark'] / start_bm - 1) * 100
        
        # 3. KPI Berechnungen
        tot_ret_pf = df['Portfolio Rendite (%)'].iloc[-1]
        tot_ret_bm = df['Benchmark Rendite (%)'].iloc[-1]
        alpha = tot_ret_pf - tot_ret_bm
        
        # Max Drawdown
        roll_max_pf = df['Portfolio'].cummax()
        drawdown_pf = (df['Portfolio'] - roll_max_pf) / roll_max_pf
        max_dd_pf = drawdown_pf.min() * 100
        
        roll_max_bm = df['Benchmark'].cummax()
        drawdown_bm = (df['Benchmark'] - roll_max_bm) / roll_max_bm
        max_dd_bm = drawdown_bm.min() * 100
        
        # Beta (Kovarianz / Varianz)
        daily_returns_pf = df['Portfolio'].pct_change().dropna()
        daily_returns_bm = df['Benchmark'].pct_change().dropna()
        
        if len(daily_returns_bm) > 1 and daily_returns_bm.var() != 0:
            covariance = np.cov(daily_returns_pf, daily_returns_bm)[0][1]
            variance = np.var(daily_returns_bm)
            beta = covariance / variance
        else:
            beta = 1.0
            
        # CAGR (Jährliche Rendite)
        days_passed = (df.index[-1] - df.index[0]).days
        if days_passed > 0:
            cagr_pf = ((df['Portfolio'].iloc[-1] / start_pf) ** (365.25 / days_passed) - 1) * 100
        else:
            cagr_pf = 0.0
            
        # Gebühren & Steuern
        db.cursor.execute("SELECT SUM(fee), SUM(tax) FROM trade_history")
        fee_tax = db.cursor.fetchone()
        total_fees = fee_tax[0] if fee_tax[0] else 0.0
        total_taxes = fee_tax[1] if fee_tax[1] else 0.0
        
        # 4. Darstellung (KPI Deck)
        st.markdown("##### 🔑 Key Performance Indicators")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📈 Total Return", f"{tot_ret_pf:+.2f} %", delta=f"{tot_ret_bm:+.2f} % (BM)")
        c2.metric("🟢 Alpha", f"{alpha:+.2f} %")
        c3.metric("📉 Max Drawdown", f"{max_dd_pf:.2f} %", delta=f"vs {max_dd_bm:.2f} % (BM)", delta_color="inverse")
        c4.metric("⚖️ Beta", f"{beta:.2f}", delta="vs 1.00 (BM)", delta_color="off")
        
        st.write("") # Abstand
        
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("💰 Gesamtwert", f"{df['Portfolio'].iloc[-1]:,.2f} €")
        c6.metric("⏱️ Rendite p.a.", f"{cagr_pf:+.2f} %")
        c7.metric("💸 Gezahlte Gebühren", f"{total_fees:,.2f} €")
        c8.metric("🏛️ Gezahlte Steuern", f"{total_taxes:,.2f} €")
        
        st.markdown("---")
        
        # 5. Darstellung (Chart)
        st.markdown("##### 📊 Kapitalkurve (Equity Curve)")
        if len(df) < 2:
            st.info("Noch nicht genügend Historien-Daten vorhanden, um einen Graphen zu zeichnen.")
        else:
            st.line_chart(df[['Portfolio Rendite (%)', 'Benchmark Rendite (%)']])

        # 6. Darstellung (Letzte 15 Einträge)
        st.markdown("---")
        st.markdown("##### 📜 Historie (Letzte 15 Einträge)")
        
        # Kopiere die relevanten Spalten der letzten 15 Tage
        df_history = df[['Portfolio', 'Benchmark']].tail(15).copy()
        # Absteigend sortieren, damit das neueste Datum ganz oben steht
        df_history = df_history.sort_index(ascending=False)
        # Datum schöner formatieren
        df_history.index = df_history.index.strftime('%d.%m.%Y')
        df_history.index.name = "Datum"
        
        # Rendern als stylische Tabelle mit Euro-Formatierung
        st.dataframe(
            df_history.style.format("{:,.2f} €"),
            use_container_width=True
        )
    
    # ------------------------------------------
    # Logik für die Aufwärmphase (Grace Period)
    # ------------------------------------------
    if inception_date_str and inception_date_str != "Unbekannt":
        inc_date = datetime.strptime(inception_date_str, "%Y-%m-%d")
        days_active = (datetime.today() - inc_date).days
        
        if days_active < 21:
            unlock_date = (inc_date + timedelta(days=21)).strftime('%d.%m.%Y')
            st.info(f"⏳ **System in der Aufwärmphase (Sammle Daten).** \n\nEin valider Benchmark-Vergleich benötigt Historie und ist erst ab dem **{unlock_date}** aussagekräftig.")
            
            # Dev-Modus: Chart trotzdem anzeigen, wenn man es aufklappt
            with st.expander("🛠️ (Dev-Modus) Analytics trotzdem anzeigen"):
                render_analytics()
        else:
            render_analytics()
    else:
        st.warning("Kein gültiges Startdatum (Inception Date) gefunden. Bitte führe einen System-Reset (Urknall) aus.")