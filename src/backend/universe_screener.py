import pandas as pd
import yfinance as yf
import os
import yaml
import requests
from io import StringIO
from datetime import datetime

class UniverseScreener:
    """
    Sucht dynamisch nach allen Ticker-Symbolen großer Indizes, 
    führt einen Grob-Filter durch (Trend) und aktualisiert die settings.yaml.
    """
    def __init__(self):
        # Wir tarnen unser Skript als normalen Webbrowser, um 403 Forbidden Fehler zu vermeiden
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def get_sp500_tickers(self):
        """Holt dynamisch die 500 S&P Ticker von Wikipedia."""
        print("Lade S&P 500 Ticker...")
        try:
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            response = requests.get(url, headers=self.headers)
            table = pd.read_html(StringIO(response.text))
            
            df = table[0]
            # yfinance braucht Bindestriche statt Punkte bei Tickern wie BRK.B
            tickers = df['Symbol'].str.replace('.', '-').tolist()
            return tickers
        except Exception as e:
            print(f"Fehler beim Laden des S&P 500: {e}")
            return []

    def get_nasdaq100_tickers(self):
        """Holt dynamisch die Nasdaq 100 Ticker von Wikipedia."""
        print("Lade NASDAQ 100 Ticker...")
        try:
            url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            response = requests.get(url, headers=self.headers)
            table = pd.read_html(StringIO(response.text))
            
            # Die Wikipedia Seite hat mehrere Tabellen
            # Wir suchen dynamisch die Tabelle, die die Spalte 'Ticker' hat
            for df in table:
                if 'Ticker' in df.columns:
                    return df['Ticker'].tolist()
            return []
        except Exception as e:
            print(f"Fehler beim Laden des NASDAQ 100: {e}")
            return []
        
    def get_stoxx_europe600_tickers(self):
        """Holt dynamisch die STOXX Europe 600 Ticker von Wikipedia und mappt Suffixe für yfinance."""
        print("Lade STOXX Europe 600 Ticker...")
        try:
            url = 'https://en.wikipedia.org/wiki/STOXX_Europe_600'
            response = requests.get(url, headers=self.headers)
            table = pd.read_html(StringIO(response.text))
            
            # Mapping der europäischen Länder zu Yahoo Finance Suffixen
            country_to_suffix = {
                'Germany': '.DE',
                'France': '.PA',
                'United Kingdom': '.L',
                'Switzerland': '.SW',
                'Netherlands': '.AS',
                'Spain': '.MC',
                'Italy': '.MI',
                'Sweden': '.ST',
                'Denmark': '.CO',
                'Finland': '.HE',
                'Norway': '.OL',
                'Belgium': '.BR',
                'Ireland': '.IR',
                'Austria': '.VI',
                'Portugal': '.LS',
                'Poland': '.WA',
                'Luxembourg': '.PA' # Oft an der Euronext Paris gelistet
            }
            
            for df in table:
                if 'Ticker' in df.columns and 'Country' in df.columns:
                    df = df.dropna(subset=['Ticker', 'Country'])
                    tickers = []
                    
                    for _, row in df.iterrows():
                        base_ticker = str(row['Ticker']).replace('.', '-')
                        country = str(row['Country'])
                        
                        suffix = country_to_suffix.get(country, '')
                        
                        # Wikipedia nutzt manchmal Bloomberg-Ticker (z.B. "NOVN SW"). 
                        # Wir splitten am Leerzeichen und nehmen nur das reine Symbol.
                        clean_ticker = base_ticker.split(' ')[0] 
                        
                        yf_ticker = f"{clean_ticker}{suffix}"
                        tickers.append(yf_ticker)
                        
                    return tickers
            return []
        except Exception as e:
            print(f"Fehler beim Laden des STOXX Europe 600: {e}")
            return []

    def get_dax_tickers(self):
        """Holt dynamisch die DAX 40 Ticker."""
        print("Lade DAX 40 Ticker...")
        try:
            url = 'https://en.wikipedia.org/wiki/DAX'
            response = requests.get(url, headers=self.headers)
            table = pd.read_html(StringIO(response.text))
            
            # Die DAX-Tabelle auf Wikipedia ändert sich gelegentlich, 
            # wir suchen sicherheitshalber nach der Spalte 'Ticker'
            for df in table:
                if 'Ticker' in df.columns:
                    return df['Ticker'].tolist()
                    
            # Fallback, falls die Spalte anders heißt (oft ist es Tabelle 4)
            df = table[4]
            if 'Ticker' in df.columns:
                return df['Ticker'].tolist()
                
            return []
        except Exception as e:
            print(f"Fehler beim Laden des DAX: {e}")
            return []

    def build_universe(self):
        """Führt alle Listen zusammen und entfernt Duplikate."""
        tickers = []
        tickers.extend(self.get_sp500_tickers())
        tickers.extend(self.get_nasdaq100_tickers())
        tickers.extend(self.get_stoxx_europe600_tickers())
        tickers.extend(self.get_dax_tickers())
        
        # Duplikate entfernen (z.B. Apple ist in Nasdaq und S&P500)
        unique_tickers = list(set(tickers))
        print(f"\nUniversum erstellt: {len(unique_tickers)} eindeutige Aktien.")
        return unique_tickers

    def run_coarse_filter(self, tickers, max_candidates=100):
        """
        Der Grobfilter: Lädt 1 Jahr Daten und wirft alles raus, 
        was unter der 200-Tage-Linie liegt. Das reduziert die Last für die Agenten massiv.
        """
        print(f"\nStarte Grob-Screening für {len(tickers)} Aktien (Download der letzten 250 Tage)...")
        # Wir schalten threads=True wieder ein, da wir nur 1 Jahr laden
        data = yf.download(tickers, period="1y", progress=False, threads=True)
        
        col = 'Close' if 'Close' in data.columns.get_level_values(0) else 'Adj Close'
        price_df = data[col]
        
        survivors = []
        
        # Vektorisiertes Filtern
        for ticker in tickers:
            try:
                # Hole die Preis-Serie der letzten 250 Tage für diesen Ticker
                if len(tickers) > 1:
                    p = price_df[ticker].dropna()
                else:
                    p = price_df.dropna()
                    
                if len(p) < 200:
                    continue # Nicht genug Daten für 200-Tage-Linie
                    
                current_price = p.iloc[-1]
                sma_200 = p.tail(200).mean()
                sma_50 = p.tail(50).mean()
                
                # GROBFILTER 1 & 2: Preis über SMA200 UND SMA50 über SMA200
                if current_price > sma_200 and sma_50 > sma_200:
                    # Berechne das Momentum (prozentualer Abstand des Preises zum SMA200)
                    # Dies hilft uns beim Ranking, falls es zu viele Kandidaten gibt
                    momentum = (current_price / sma_200) - 1
                    survivors.append({
                        'ticker': ticker,
                        'momentum': momentum
                    })
            except Exception:
                pass
                
        print(f"Filter-Ergebnis: {len(survivors)} Aktien erfüllen die Kriterien (Preis > SMA200 & SMA50 > SMA200).")

        # Ranking: Sortiere die Überlebenden nach dem höchsten Momentum
        survivors_sorted = sorted(survivors, key=lambda x: x['momentum'], reverse=True)
        
        # Schneide die Liste auf 'max_candidates' ab (z.B. die besten 80)
        final_tickers = [item['ticker'] for item in survivors_sorted[:max_candidates]]
        
        if len(survivors) > max_candidates:
            print(f"Reduziere Auswahl auf die Top {max_candidates} Kandidaten mit dem stärksten Momentum.")
            
        return final_tickers

    def update_settings_file(self, new_tickers):
        """Schreibt die überlebenden Ticker automatisch in die settings.yaml."""
        base_dir = os.path.dirname(os.path.abspath(os.path.join(__file__, '..')))
        config_path = os.path.join(base_dir, 'config', 'settings.yaml')
        
        # Aktuelle Settings laden
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            config = {"trading": {"cash_parking_etfs": ["XEON.DE", "EUN3.DE"]}}
            
        # Ticker aktualisieren
        if 'trading' not in config:
            config['trading'] = {}
            
        # Wir sortieren sie alphabetisch für bessere Lesbarkeit in der YAML
        config['trading']['tickers'] = sorted(new_tickers)
        
        # Zurückschreiben
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
        print(f"Die Datei 'settings.yaml' wurde erfolgreich mit {len(new_tickers)} Kandidaten aktualisiert!")

# ==========================================
# AUSFÜHRUNG / TESTLAUF
# ==========================================
if __name__ == "__main__":
    screener = UniverseScreener()
    
    # 1. Listen aus dem Internet laden
    universe = screener.build_universe()
    
    # 2. Die schwachen Aktien rigoros aussortieren
    if universe:
        strong_stocks = screener.run_coarse_filter(universe)
        print(strong_stocks)
        
        # 3. Das System-Konfigurationsfile für den nächsten Lauf updaten
        screener.update_settings_file(strong_stocks)
    else:
        print("Keine Ticker im Universum gefunden. Überprüfe deine Internetverbindung oder das Scraping-Skript.")