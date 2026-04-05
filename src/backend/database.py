import sqlite3
import json
import os
import math
import yfinance as yf
import pandas as pd
from datetime import datetime,  timedelta

class DatabaseManager:
    """Verwaltet das Portfolio, die Trades und speichert die KI-Berichte in SQLite."""
    
    def __init__(self, db_path="data/investment_system.db"):
        # Stelle sicher, dass der data-Ordner existiert
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._migrate_benchmark_if_needed()

    def _create_tables(self):
        """Erstellt die Tabellen, falls sie noch nicht existieren."""

        # 1. System Konfiguration (Startdatum, Startkapital etc.)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

        # 2. Tabelle für den aktuellen Cash-Bestand
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS cash_balance (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance REAL NOT NULL
            )
        ''')
        
        # 3. Tabelle für das aktuelle Portfolio (gehaltene Aktien)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                ticker TEXT PRIMARY KEY,
                sector TEXT NOT NULL,
                region TEXT NOT NULL,
                shares REAL NOT NULL DEFAULT 0,
                avg_price REAL NOT NULL DEFAULT 0,
                invested_value REAL NOT NULL
            )
        ''')

        # MIGRATION: Wir fügen die neuen Spalten nahtlos hinzu, falls es eine alte DB ist
        try:
            self.cursor.execute("ALTER TABLE portfolio ADD COLUMN shares REAL NOT NULL DEFAULT 0")
            self.cursor.execute("ALTER TABLE portfolio ADD COLUMN avg_price REAL NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Spalten existieren bereits
            
        # 4. Tabelle für die Trade-Historie (Das "Kassenbuch")
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL,
                price_per_share REAL NOT NULL,
                fee REAL NOT NULL,
                tax REAL NOT NULL,
                total_amount REAL NOT NULL
            )
        ''')
        
        # 5. Tabelle für die täglichen Berichte
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_reports (
                date TEXT PRIMARY KEY,
                markdown_text TEXT NOT NULL,
                raw_json_data TEXT
            )
        ''')

        # 6. Performance Historie (Equity Curve)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_history (
                date TEXT PRIMARY KEY,
                portfolio_value REAL NOT NULL,
                benchmark_value REAL NOT NULL
            )
        ''')      
        self.conn.commit()
        
        # Initial-Befüllung, falls die Datenbank ganz neu ist
        self.cursor.execute("SELECT balance FROM cash_balance WHERE id = 1")
        if not self.cursor.fetchone():
            default_start = 100000.0
            today_str = datetime.today().strftime('%Y-%m-%d')
            self.cursor.execute("INSERT INTO cash_balance (id, balance) VALUES (1, ?)", (default_start,))
            self.cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('inception_date', ?)", (today_str,))
            self.cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('inception_balance', ?)", (str(default_start),))
            self.conn.commit()
    
    def _migrate_benchmark_if_needed(self):
        """Prüft, ob das fiktive SC0J.DE Benchmark-Portfolio bereits angelegt wurde. Wenn nicht, wird es generiert."""
        self.cursor.execute("SELECT value FROM system_config WHERE key = 'benchmark_shares'")
        if not self.cursor.fetchone():
            inception_date = self.get_system_config('inception_date')
            inception_balance = self.get_system_config('inception_balance')
            
            if inception_date and inception_balance:
                print(f"🔄 Migration: Berechne initiale Benchmark-Anteile (SC0J.DE) für den {inception_date}...")
                self._initialize_benchmark(inception_date, float(inception_balance))
    
    def _initialize_benchmark(self, date_str, start_balance):
        """Simuliert den Kauf des MSCI World ETFs (SC0J.DE) zum Inception Date."""
        benchmark_ticker = "SC0J.DE"
        fee = 1.0 # 1 EUR Ordergebühr Simulation
        
        # Wir suchen den ETF-Preis an oder knapp vor dem Inception Date (falls es ein Wochenende war)
        start_dt = pd.to_datetime(date_str) - timedelta(days=7)
        end_dt = pd.to_datetime(date_str) + timedelta(days=1) # yfinance end ist exklusiv
        
        try:
            data = yf.download(benchmark_ticker, start=start_dt.strftime('%Y-%m-%d'), end=end_dt.strftime('%Y-%m-%d'), progress=False, threads=False)
            
            if not data.empty:
                close_col = 'Close' if 'Close' in data.columns.get_level_values(0) else 'Adj Close'
                if isinstance(data.columns, pd.MultiIndex):
                    price = float(data[close_col][benchmark_ticker].iloc[-1])
                else:
                    price = float(data[close_col].iloc[-1])
                
                # Berechnung: Wieviele ganze Anteile können wir kaufen?
                available_cash = start_balance - fee
                shares = math.floor(available_cash / price)
                leftover_cash = available_cash - (shares * price)
                
                # In der Config speichern
                self.cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('benchmark_ticker', ?)", (benchmark_ticker,))
                self.cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('benchmark_shares', ?)", (str(shares),))
                self.cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('benchmark_cash', ?)", (str(leftover_cash),))
                self.cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('benchmark_start_price', ?)", (str(price),))
                self.conn.commit()
                
                # Den initialen Startwert (Tag 0) direkt in die Historie schreiben
                # (Der Benchmark-Wert an Tag 0 ist exakt start_balance - 1 EUR Gebühr, wir loggen fairerweise den rohen Startwert)
                self.log_portfolio_history(date_str=date_str, portfolio_val=start_balance, benchmark_val=start_balance)
                print(f"✅ Benchmark initialisiert: {shares}x SC0J.DE zu {price:.2f}€. Rest-Cash: {leftover_cash:.2f}€")
            else:
                print(f"⚠️ Konnte keine SC0J.DE Kurse für {date_str} finden. Benchmark bleibt uninitialisiert.")
        except Exception as e:
            print(f"⚠️ Fehler bei der Benchmark-Initialisierung: {e}")
    
    def log_portfolio_history(self, date_str=None, portfolio_val=None, benchmark_val=None):
        """Speichert den täglichen Gesamtwert von unserem Portfolio und vom Benchmark."""
        if not date_str:
            date_str = datetime.today().strftime('%Y-%m-%d')
            
        # Unseren Portfolio-Wert berechnen, falls nicht übergeben
        if portfolio_val is None:
            pf = self.get_portfolio_for_agent()
            portfolio_val = pf['total_value']
            
        # Benchmark-Wert tagesaktuell berechnen, falls nicht übergeben
        if benchmark_val is None:
            shares_str = self.get_system_config('benchmark_shares')
            cash_str = self.get_system_config('benchmark_cash')
            
            if shares_str and cash_str:
                shares = float(shares_str)
                cash = float(cash_str)
                
                try:
                    data = yf.download("SC0J.DE", period="1d", progress=False, threads=False)
                    if not data.empty:
                        close_col = 'Close' if 'Close' in data.columns.get_level_values(0) else 'Adj Close'
                        if isinstance(data.columns, pd.MultiIndex):
                            price = float(data[close_col]["SC0J.DE"].iloc[-1])
                        else:
                            price = float(data[close_col].iloc[-1])
                        benchmark_val = (shares * price) + cash
                    else:
                        # Fallback (Wochenende)
                        benchmark_val = portfolio_val
                except:
                    benchmark_val = portfolio_val # Fallback
            else:
                benchmark_val = portfolio_val
                
        self.cursor.execute('''
            INSERT OR REPLACE INTO portfolio_history (date, portfolio_value, benchmark_value)
            VALUES (?, ?, ?)
        ''', (date_str, portfolio_val, benchmark_val))
        self.conn.commit()

    def reset_database(self, start_date_str, start_balance):
        """DER URKNALL: Löscht alle Daten und setzt das System komplett neu auf."""
        # Alle relevanten Tabellen leeren
        tables = ['cash_balance', 'portfolio', 'trade_history', 'daily_reports', 'system_config']
        for table in tables:
            self.cursor.execute(f"DROP TABLE IF EXISTS {table}")
        
        self.conn.commit()
        
        # Tabellen neu erstellen
        self._create_tables()
        
        # Mit neuen "Urknall"-Werten überschreiben
        self.cursor.execute("UPDATE cash_balance SET balance = ? WHERE id = 1", (start_balance,))
        self.cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('inception_date', ?)", (start_date_str,))
        self.cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('inception_balance', ?)", (str(start_balance),))
        self.conn.commit()

    def get_system_config(self, key):
        """Liest einen Konfigurationswert aus."""
        self.cursor.execute("SELECT value FROM system_config WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def get_portfolio_for_agent(self):
        """Liest die DB aus und formatiert das Portfolio als JSON/Dict für den Risk Agent."""
        self.cursor.execute("SELECT balance FROM cash_balance WHERE id = 1")
        cash_row = self.cursor.fetchone()
        cash = cash_row[0] if cash_row else 0.0
        
        self.cursor.execute("SELECT ticker, sector, region, invested_value, shares, avg_price FROM portfolio")
        equities = []
        total_equities_value = 0.0
        
        for row in self.cursor.fetchall():
            value = row[3]
            equities.append({
                "ticker": row[0],
                "sector": row[1],
                "region": row[2],
                "value": value,
                "shares": row[4],
                "avg_price": row[5]
            })
            total_equities_value += value
            
        return {
            "total_value": cash + total_equities_value,
            "cash": cash,
            "equities": equities
        }
    
    def log_trade(self, date_str, trade_type, ticker, shares, price, fee, tax=0.0):
        """Erfasst einen neuen Trade und aktualisiert Cash und Portfolio mathematisch exakt."""
        import yfinance as yf # Import für dynamisches Sektor-Lookup
        
        self.cursor.execute("SELECT balance FROM cash_balance WHERE id = 1")
        current_cash = self.cursor.fetchone()[0]
        
        # 1. Kosten/Erlöse berechnen
        if trade_type == 'BUY':
            total_amount = (shares * price) + fee
        else:
            total_amount = (shares * price) - fee - tax
            
        # 2. Trade in Historie (Kassenbuch) eintragen
        self.cursor.execute('''
            INSERT INTO trade_history (trade_date, trade_type, ticker, shares, price_per_share, fee, tax, total_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date_str, trade_type, ticker, shares, price, fee, tax, total_amount))
        
        # 3. Portfolio & Cash aktualisieren
        if trade_type == 'BUY':
            if current_cash < total_amount:
                raise ValueError(f"Nicht genug Cash! Benötigt: {total_amount:.2f}€, Vorhanden: {current_cash:.2f}€")
            
            # Cash abziehen
            self.cursor.execute("UPDATE cash_balance SET balance = ? WHERE id = 1", (current_cash - total_amount,))
            
            self.cursor.execute("SELECT shares, invested_value FROM portfolio WHERE ticker = ?", (ticker,))
            row = self.cursor.fetchone()
            
            if row: # Aktie ist schon im Depot (Nachkauf)
                new_shares = row[0] + shares
                new_invested = row[1] + (shares * price)
                avg_price = new_invested / new_shares
                self.cursor.execute("UPDATE portfolio SET shares = ?, avg_price = ?, invested_value = ? WHERE ticker = ?", 
                                  (new_shares, avg_price, new_invested, ticker))
            else: # Neue Aktie
                # Wir holen uns schnell den Sektor über yfinance für den Risk Agent!
                try:
                    info = yf.Ticker(ticker).info
                    sector = info.get('sector', 'ETF/Unknown')
                    region = info.get('country', 'Unknown')
                except:
                    sector, region = 'Unknown', 'Unknown'
                    
                self.cursor.execute("INSERT INTO portfolio (ticker, sector, region, shares, avg_price, invested_value) VALUES (?, ?, ?, ?, ?, ?)", 
                                  (ticker, sector, region, shares, price, shares * price))
                                  
        elif trade_type == 'SELL':
            # Cash gutschreiben
            self.cursor.execute("UPDATE cash_balance SET balance = ? WHERE id = 1", (current_cash + total_amount,))
            
            self.cursor.execute("SELECT shares, avg_price FROM portfolio WHERE ticker = ?", (ticker,))
            row = self.cursor.fetchone()
            if row:
                current_shares, avg_price = row[0], row[1]
                new_shares = current_shares - shares
                
                if new_shares <= 0.0001: # Komplettverkauf (0.0001 wegen Rundungsfehlern bei Bruchstücken)
                    self.cursor.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
                else: # Teilverkauf
                    new_invested = new_shares * avg_price
                    self.cursor.execute("UPDATE portfolio SET shares = ?, invested_value = ? WHERE ticker = ?", 
                                      (new_shares, new_invested, ticker))
        self.conn.commit()

    def update_portfolio(self, ticker, sector, region, amount_eur, is_buy=True):
        """Aktualisiert das Portfolio nach einem Trade (wird später für manuelles Feedback gebraucht)."""
        self.cursor.execute("SELECT balance FROM cash_balance WHERE id = 1")
        current_cash = self.cursor.fetchone()[0]
        
        if is_buy:
            if current_cash < amount_eur:
                raise ValueError("Nicht genug Cash für diesen Trade!")
            
            # Cash reduzieren
            self.cursor.execute("UPDATE cash_balance SET balance = ? WHERE id = 1", (current_cash - amount_eur,))
            
            # Aktie zum Portfolio hinzufügen oder aufstocken
            self.cursor.execute("SELECT invested_value FROM portfolio WHERE ticker = ?", (ticker,))
            row = self.cursor.fetchone()
            if row:
                new_value = row[0] + amount_eur
                self.cursor.execute("UPDATE portfolio SET invested_value = ? WHERE ticker = ?", (new_value, ticker))
            else:
                self.cursor.execute("INSERT INTO portfolio (ticker, sector, region, invested_value) VALUES (?, ?, ?, ?)", 
                                  (ticker, sector, region, amount_eur))
        else:
            # Verkauf (Vereinfacht: Kompletter Verkauf)
            self.cursor.execute("UPDATE cash_balance SET balance = ? WHERE id = 1", (current_cash + amount_eur,))
            self.cursor.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
            
        self.conn.commit()

    def save_daily_report(self, markdown_text, raw_data_dict):
        """Speichert den generierten CrewAI Bericht in der Datenbank."""
        today = datetime.now().strftime('%Y-%m-%d')
        raw_json = json.dumps(raw_data_dict)
        
        # INSERT OR REPLACE überschreibt den Bericht, falls wir das Skript heute zweimal ausführen
        self.cursor.execute('''
            INSERT OR REPLACE INTO daily_reports (date, markdown_text, raw_json_data)
            VALUES (?, ?, ?)
        ''', (today, markdown_text, raw_json))
        self.conn.commit()
    
    def has_report_for_today(self):
        """Prüft, ob für den heutigen Tag bereits ein Bericht existiert."""
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute("SELECT 1 FROM daily_reports WHERE date = ?", (today,))
        return self.cursor.fetchone() is not None

    def get_latest_report(self):
        self.cursor.execute("SELECT markdown_text FROM daily_reports ORDER BY date DESC LIMIT 1")
        row = self.cursor.fetchone()
        return row[0] if row else "Noch kein Bericht vorhanden."

    def __del__(self):
        self.conn.close()