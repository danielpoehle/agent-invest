import sqlite3
import json
import os
from datetime import datetime

class DatabaseManager:
    """Verwaltet das Portfolio, die Trades und speichert die KI-Berichte in SQLite."""
    
    def __init__(self, db_path="data/investment_system.db"):
        # Stelle sicher, dass der data-Ordner existiert
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Erstellt die Tabellen, falls sie noch nicht existieren."""
        # Tabelle für den aktuellen Cash-Bestand
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS cash_balance (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance REAL NOT NULL
            )
        ''')
        
        # Tabelle für das aktuelle Portfolio (gehaltene Aktien)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                ticker TEXT PRIMARY KEY,
                sector TEXT NOT NULL,
                region TEXT NOT NULL,
                invested_value REAL NOT NULL
            )
        ''')
        
        # Tabelle für die täglichen Berichte
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_reports (
                date TEXT PRIMARY KEY,
                markdown_text TEXT NOT NULL,
                raw_json_data TEXT
            )
        ''')
        self.conn.commit()
        
        # Startkapital setzen, falls die Datenbank ganz neu ist
        self.cursor.execute("SELECT balance FROM cash_balance WHERE id = 1")
        if not self.cursor.fetchone():
            self.cursor.execute("INSERT INTO cash_balance (id, balance) VALUES (1, 100000.0)")
            self.conn.commit()

    def get_portfolio_for_agent(self):
        """Liest die DB aus und formatiert das Portfolio als JSON/Dict für den Risk Agent."""
        self.cursor.execute("SELECT balance FROM cash_balance WHERE id = 1")
        cash = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT ticker, sector, region, invested_value FROM portfolio")
        equities = []
        total_equities_value = 0.0
        
        for row in self.cursor.fetchall():
            value = row[3]
            equities.append({
                "ticker": row[0],
                "sector": row[1],
                "region": row[2],
                "value": value
            })
            total_equities_value += value
            
        return {
            "total_value": cash + total_equities_value,
            "cash": cash,
            "equities": equities
        }

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