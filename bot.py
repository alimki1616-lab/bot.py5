import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import io
import aiohttp
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8363442271:AAHGrIjbCz1PX10qERyRecxY6UUxbfW-8Es')
CHANNEL_ID = os.environ.get('CHANNEL_ID', '@CryptoAnalysis_Ai')

logger.info(f"✅ Bot Token loaded: {BOT_TOKEN[:10]}...")
logger.info(f"✅ Channel ID: {CHANNEL_ID}")

# Trading pairs - Top 7 cryptos
SYMBOLS = {
    'BTCUSDT': {'name': 'Bitcoin', 'ticker': 'BTC'},
    'ETHUSDT': {'name': 'Ethereum', 'ticker': 'ETH'},
    'SOLUSDT': {'name': 'Solana', 'ticker': 'SOL'},
    'BNBUSDT': {'name': 'BNB', 'ticker': 'BNB'},
    'ADAUSDT': {'name': 'Cardano', 'ticker': 'ADA'},
    'DOGEUSDT': {'name': 'Dogecoin', 'ticker': 'DOGE'},
    'XRPUSDT': {'name': 'Ripple', 'ticker': 'XRP'}
}

# Extended timeframes
TIMEFRAMES = {
    '5m': '5m',
    '15m': '15m',
    '1h': '1h',
    '4h': '4h'
}


class BinanceDataFetcher:
    """Fetch crypto data from multiple sources with fallback - OPTIMIZED"""
    
    def __init__(self):
        # Try multiple Binance endpoints
        self.binance_urls = [
            "https://data-api.binance.vision/api/v3",
            "https://api.binance.com/api/v3",
            "https://api1.binance.com/api/v3",
            "https://api2.binance.com/api/v3"
        ]
        
        # Crypto.com exchange API (no restrictions)
        self.cryptocom_url = "https://api.crypto.com/v2"
        
        # Map symbols
        self.symbol_map = {
            'BTCUSDT': {'cdc': 'BTC_USDT'},
            'ETHUSDT': {'cdc': 'ETH_USDT'},
            'SOLUSDT': {'cdc': 'SOL_USDT'},
            'BNBUSDT': {'cdc': 'BNB_USDT'},
            'ADAUSDT': {'cdc': 'ADA_USDT'},
            'DOGEUSDT': {'cdc': 'DOGE_USDT'},
            'XRPUSDT': {'cdc': 'XRP_USDT'}
        }
        
        # Keep persistent session for better performance
        self.session = None
        
    async def get_session(self):
        """Get or create persistent session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
        
    async def get_ohlcv_binance(self, symbol: str, interval: str, limit: int, base_url: str) -> pd.DataFrame:
        """Try fetching from Binance - OPTIMIZED"""
        try:
            url = f"{base_url}/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': min(limit, 1000)
            }
            
            session = await self.get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
            
            if not data:
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # Convert types
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
            # Filter valid data
            df = df[(df['open'] > 0) & (df['high'] > 0) & (df['low'] > 0) & (df['close'] > 0)]
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
            
            return df.reset_index(drop=True)
            
        except Exception:
            return None
    
    async def get_ohlcv_cryptocom(self, symbol: str, interval: str = '1h') -> pd.DataFrame:
        """Fallback to Crypto.com Exchange API - OPTIMIZED"""
        try:
            mapped = self.symbol_map.get(symbol, {}).get('cdc')
            if not mapped:
                return None
            
            # Map interval
            interval_map = {'5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1D'}
            timeframe = interval_map.get(interval, '1h')
            
            url = f"{self.cryptocom_url}/public/get-candlestick"
            params = {
                'instrument_name': mapped,
                'timeframe': timeframe
            }
            
            session = await self.get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
            
            if data.get('code') != 0 or 'result' not in data:
                return None
            
            candles = data['result']['data']
            if not candles:
                return None
            
            df_list = []
            for candle in candles:
                df_list.append({
                    'timestamp': pd.to_datetime(candle['t'], unit='ms'),
                    'open': float(candle['o']),
                    'high': float(candle['h']),
                    'low': float(candle['l']),
                    'close': float(candle['c']),
                    'volume': float(candle['v'])
                })
            
            df = pd.DataFrame(df_list)
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # Filter valid data
            df = df[(df['open'] > 0) & (df['high'] > 0) & (df['low'] > 0) & (df['close'] > 0)]
            
            return df
            
        except Exception as e:
            logger.error(f"Crypto.com error: {e}")
            return None
        
    async def get_ohlcv(self, symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
        """Get OHLCV data with fallback mechanism - OPTIMIZED"""
        # Try Binance first (all endpoints)
        for base_url in self.binance_urls:
            df = await self.get_ohlcv_binance(symbol, interval, limit, base_url)
            if df is not None and len(df) > 0:
                return df.tail(limit)
        
        # Fallback to Crypto.com
        df = await self.get_ohlcv_cryptocom(symbol, interval)
        if df is not None and len(df) > 0:
            return df.tail(limit)
        
        return None
    
    async def get_current_price(self, symbol: str) -> float:
        """Get current price with fallback - OPTIMIZED"""
        # Try Binance first
        for base_url in self.binance_urls:
            try:
                url = f"{base_url}/ticker/price"
                params = {'symbol': symbol}
                
                session = await self.get_session()
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return float(data.get('price'))
            except Exception:
                continue
        
        # Fallback to Crypto.com
        try:
            mapped = self.symbol_map.get(symbol, {}).get('cdc')
            if not mapped:
                return None
            
            url = f"{self.cryptocom_url}/public/get-ticker"
            params = {'instrument_name': mapped}
            
            session = await self.get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('code') == 0 and 'result' in data:
                        result = data['result']['data'][0]
                        return float(result.get('a', 0))
        except Exception:
            pass
        
        return None
    
    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()


data_fetcher = BinanceDataFetcher()


class AdvancedSmartMoneyAnalyzer:
    """Advanced Smart Money Analyzer with Multiple Filters and Strong Strategy - OPTIMIZED"""
    
    def __init__(self):
        self.lookback_periods = 50
        self.min_rr_ratio = 2.0  # Moderate R/R for balanced signals
        self.volume_threshold = 1.3  # Moderate volume requirement
        self.min_confirmations = 3  # Balanced confirmations (was 4)
        
    def calculate_ema(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Calculate EMA"""
        return df['close'].ewm(span=period, adjust=False).mean()
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean().iloc[-1]
        
        return atr
    
    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate RSI"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1]
    
    def calculate_macd(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD (12, 26, 9)"""
        ema_12 = df['close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['close'].ewm(span=26, adjust=False).mean()
        
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20, std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands"""
        sma = df['close'].rolling(window=period).mean()
        rolling_std = df['close'].rolling(window=period).std()
        
        upper_band = sma + (rolling_std * std)
        lower_band = sma - (rolling_std * std)
        
        return upper_band, sma, lower_band
    
    def calculate_stochastic_rsi(self, df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Tuple[float, float]:
        """Calculate Stochastic RSI"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        rsi_min = rsi.rolling(window=period).min()
        rsi_max = rsi.rolling(window=period).max()
        
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min) * 100
        stoch_rsi = stoch_rsi.fillna(50)
        
        k_line = stoch_rsi.rolling(window=smooth_k).mean()
        d_line = k_line.rolling(window=smooth_d).mean()
        
        return k_line.iloc[-1], d_line.iloc[-1]
    
    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ADX (Average Directional Index) - Trend Strength"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0
    
    def detect_swing_points(self, df: pd.DataFrame) -> Tuple[List, List]:
        """Detect Swing Highs and Swing Lows - More conservative"""
        swing_highs = []
        swing_lows = []
        
        for i in range(3, len(df) - 3):
            if (df['high'].iloc[i] > df['high'].iloc[i-1] and 
                df['high'].iloc[i] > df['high'].iloc[i-2] and
                df['high'].iloc[i] > df['high'].iloc[i-3] and
                df['high'].iloc[i] > df['high'].iloc[i+1] and 
                df['high'].iloc[i] > df['high'].iloc[i+2] and
                df['high'].iloc[i] > df['high'].iloc[i+3]):
                swing_highs.append({
                    'index': i,
                    'price': df['high'].iloc[i],
                    'time': df.index[i]
                })
            
            if (df['low'].iloc[i] < df['low'].iloc[i-1] and 
                df['low'].iloc[i] < df['low'].iloc[i-2] and
                df['low'].iloc[i] < df['low'].iloc[i-3] and
                df['low'].iloc[i] < df['low'].iloc[i+1] and 
                df['low'].iloc[i] < df['low'].iloc[i+2] and
                df['low'].iloc[i] < df['low'].iloc[i+3]):
                swing_lows.append({
                    'index': i,
                    'price': df['low'].iloc[i],
                    'time': df.index[i]
                })
        
        return swing_highs, swing_lows
    
    def detect_strong_bos(self, df: pd.DataFrame, swing_highs: List, swing_lows: List) -> Dict:
        """Detect Strong Break of Structure"""
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return None
        
        current_price = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        last_swing_high = swing_highs[-1]['price']
        prev_swing_high = swing_highs[-2]['price'] if len(swing_highs) >= 2 else last_swing_high
        
        last_swing_low = swing_lows[-1]['price']
        prev_swing_low = swing_lows[-2]['price'] if len(swing_lows) >= 2 else last_swing_low
        
        if current_price > last_swing_high and prev_close < last_swing_high:
            if len(swing_highs) >= 2 and current_price > prev_swing_high:
                return {
                    'type': 'STRONG_BOS_BULLISH',
                    'signal': 'LONG',
                    'level': last_swing_high,
                    'strength': 'VERY_STRONG',
                    'broken_levels': 2
                }
            return {
                'type': 'BOS_BULLISH',
                'signal': 'LONG',
                'level': last_swing_high,
                'strength': 'STRONG',
                'broken_levels': 1
            }
        
        if current_price < last_swing_low and prev_close > last_swing_low:
            if len(swing_lows) >= 2 and current_price < prev_swing_low:
                return {
                    'type': 'STRONG_BOS_BEARISH',
                    'signal': 'SHORT',
                    'level': last_swing_low,
                    'strength': 'VERY_STRONG',
                    'broken_levels': 2
                }
            return {
                'type': 'BOS_BEARISH',
                'signal': 'SHORT',
                'level': last_swing_low,
                'strength': 'STRONG',
                'broken_levels': 1
            }
        
        return None
    
    def detect_order_blocks(self, df: pd.DataFrame, signal_type: str) -> Optional[Dict]:
        """Detect High-Quality Order Blocks"""
        order_blocks = []
        
        for i in range(len(df) - 10, len(df) - 1):
            candle = df.iloc[i]
            next_candle = df.iloc[i + 1]
            
            candle_body = abs(candle['close'] - candle['open'])
            next_body = abs(next_candle['close'] - next_candle['open'])
            
            if signal_type == 'LONG':
                if (candle['close'] < candle['open'] and 
                    next_candle['close'] > next_candle['open'] and
                    next_body > 1.5 * candle_body and
                    candle['volume'] > df['volume'].tail(20).mean()):
                    order_blocks.append({
                        'type': 'BULLISH_OB',
                        'high': candle['high'],
                        'low': candle['low'],
                        'index': i,
                        'volume': candle['volume'],
                        'strength': next_body / candle_body
                    })
            
            elif signal_type == 'SHORT':
                if (candle['close'] > candle['open'] and 
                    next_candle['close'] < next_candle['open'] and
                    next_body > 1.5 * candle_body and
                    candle['volume'] > df['volume'].tail(20).mean()):
                    order_blocks.append({
                        'type': 'BEARISH_OB',
                        'high': candle['high'],
                        'low': candle['low'],
                        'index': i,
                        'volume': candle['volume'],
                        'strength': next_body / candle_body
                    })
        
        if order_blocks:
            return max(order_blocks, key=lambda x: x['strength'])
        return None
    
    def detect_fvg(self, df: pd.DataFrame) -> List[Dict]:
        """Detect Fair Value Gaps"""
        fvgs = []
        
        for i in range(1, len(df) - 1):
            prev_candle = df.iloc[i - 1]
            next_candle = df.iloc[i + 1]
            
            gap_up = next_candle['low'] - prev_candle['high']
            if gap_up > 0:
                gap_percent = (gap_up / prev_candle['high']) * 100
                if gap_percent > 0.2:
                    fvgs.append({
                        'type': 'BULLISH_FVG',
                        'top': next_candle['low'],
                        'bottom': prev_candle['high'],
                        'index': i,
                        'size': gap_up,
                        'percent': gap_percent
                    })
            
            gap_down = prev_candle['low'] - next_candle['high']
            if gap_down > 0:
                gap_percent = (gap_down / prev_candle['low']) * 100
                if gap_percent > 0.2:
                    fvgs.append({
                        'type': 'BEARISH_FVG',
                        'top': prev_candle['low'],
                        'bottom': next_candle['high'],
                        'index': i,
                        'size': gap_down,
                        'percent': gap_percent
                    })
        
        return fvgs[-3:] if fvgs else []
    
    def calculate_premium_discount(self, df: pd.DataFrame, swing_highs: List, swing_lows: List) -> Dict:
        """Calculate Premium and Discount Zones"""
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return None
        
        recent_high = max([sh['price'] for sh in swing_highs[-5:]])
        recent_low = min([sl['price'] for sl in swing_lows[-5:]])
        
        range_size = recent_high - recent_low
        current_price = df['close'].iloc[-1]
        
        equilibrium = recent_low + (range_size * 0.5)
        premium_zone = recent_low + (range_size * 0.618)
        discount_zone = recent_low + (range_size * 0.382)
        
        if current_price >= premium_zone:
            zone = 'PREMIUM'
        elif current_price <= discount_zone:
            zone = 'DISCOUNT'
        else:
            zone = 'EQUILIBRIUM'
        
        return {
            'zone': zone,
            'high': recent_high,
            'low': recent_low,
            'equilibrium': equilibrium,
            'premium_threshold': premium_zone,
            'discount_threshold': discount_zone,
            'current': current_price
        }
    
    def check_macd_confirmation(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """MACD Confirmation Filter"""
        macd_line, signal_line, histogram = self.calculate_macd(df)
        
        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        current_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2]
        
        if signal_direction == 'LONG':
            return current_macd > current_signal and current_hist > prev_hist and current_hist > 0
        else:
            return current_macd < current_signal and current_hist < prev_hist and current_hist < 0
    
    def check_bollinger_confirmation(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """Bollinger Bands Confirmation Filter"""
        upper, middle, lower = self.calculate_bollinger_bands(df)
        
        current_price = df['close'].iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]
        current_middle = middle.iloc[-1]
        
        if signal_direction == 'LONG':
            return current_price <= (current_lower * 1.02) or (current_price > current_lower and current_price < current_middle)
        else:
            return current_price >= (current_upper * 0.98) or (current_price < current_upper and current_price > current_middle)
    
    def check_stochastic_rsi_confirmation(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """Stochastic RSI Confirmation Filter"""
        k_line, d_line = self.calculate_stochastic_rsi(df)
        
        if signal_direction == 'LONG':
            return k_line < 40 or (k_line > d_line and k_line < 60)
        else:
            return k_line > 60 or (k_line < d_line and k_line > 40)
    
    def check_adx_confirmation(self, df: pd.DataFrame) -> bool:
        """ADX Confirmation - Trend Strength"""
        adx = self.calculate_adx(df)
        return adx > 25
    
    def check_volume_confirmation(self, df: pd.DataFrame) -> bool:
        """Strong Volume Confirmation"""
        if len(df) < 20:
            return False
        
        avg_volume = df['volume'].tail(20).mean()
        recent_volume = df['volume'].tail(5).mean()
        
        return recent_volume >= (avg_volume * self.volume_threshold)
    
    def check_trend_alignment(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """Strong Trend Alignment with EMAs"""
        ema_20 = self.calculate_ema(df, 20)
        ema_50 = self.calculate_ema(df, 50)
        ema_200 = self.calculate_ema(df, 200)
        
        current_price = df['close'].iloc[-1]
        
        if signal_direction == 'LONG':
            return (current_price > ema_20.iloc[-1] and 
                    ema_20.iloc[-1] > ema_50.iloc[-1] and
                    ema_50.iloc[-1] > ema_200.iloc[-1])
        else:
            return (current_price < ema_20.iloc[-1] and 
                    ema_20.iloc[-1] < ema_50.iloc[-1] and
                    ema_50.iloc[-1] < ema_200.iloc[-1])
    
    def check_momentum(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """Momentum Check with RSI"""
        rsi = self.calculate_rsi(df)
        
        if signal_direction == 'LONG':
            return 40 <= rsi <= 70
        else:
            return 30 <= rsi <= 60
    
    async def get_higher_timeframe_confirmation(self, symbol: str, current_tf: str, signal_direction: str) -> bool:
        """Multi-Timeframe Confirmation - Check higher timeframe"""
        tf_hierarchy = {'5m': '15m', '15m': '1h', '1h': '4h'}
        higher_tf = tf_hierarchy.get(current_tf)
        
        if not higher_tf:
            return True
        
        try:
            df_higher = await data_fetcher.get_ohlcv(symbol, higher_tf, limit=100)
            if df_higher is None or len(df_higher) < 50:
                return True
            
            df_higher.set_index('timestamp', inplace=True)
            
            ema_20 = self.calculate_ema(df_higher, 20)
            ema_50 = self.calculate_ema(df_higher, 50)
            current_price = df_higher['close'].iloc[-1]
            
            if signal_direction == 'LONG':
                return current_price > ema_20.iloc[-1] and ema_20.iloc[-1] > ema_50.iloc[-1]
            else:
                return current_price < ema_20.iloc[-1] and ema_20.iloc[-1] < ema_50.iloc[-1]
        
        except Exception:
            return True
    
    async def generate_signal(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Generate trading signal with STRONG multi-filter strategy - OPTIMIZED"""
        try:
            df = await data_fetcher.get_ohlcv(symbol, timeframe, limit=300)
            
            if df is None or len(df) < 200:
                return None
            
            df.set_index('timestamp', inplace=True)
            
            swing_highs, swing_lows = self.detect_swing_points(df)
            
            if len(swing_highs) < 5 or len(swing_lows) < 5:
                return None
            
            structure = self.detect_strong_bos(df, swing_highs, swing_lows)
            
            if not structure or structure.get('strength') not in ['STRONG', 'VERY_STRONG']:
                return None
            
            signal_direction = structure['signal']
            
            # ============ MULTIPLE CONFIRMATION FILTERS ============
            confirmations = 0
            confirmation_details = {}
            
            # 1. Volume Confirmation (MANDATORY)
            volume_ok = self.check_volume_confirmation(df)
            if volume_ok:
                confirmations += 1
                confirmation_details['volume'] = True
            else:
                return None
            
            # 2. Trend Alignment (MANDATORY)
            trend_ok = self.check_trend_alignment(df, signal_direction)
            if trend_ok:
                confirmations += 1
                confirmation_details['trend'] = True
            else:
                return None
            
            # 3. ADX - Trend Strength
            adx_ok = self.check_adx_confirmation(df)
            if adx_ok:
                confirmations += 1
                confirmation_details['adx'] = True
            
            # 4. MACD Confirmation
            macd_ok = self.check_macd_confirmation(df, signal_direction)
            if macd_ok:
                confirmations += 1
                confirmation_details['macd'] = True
            
            # 5. Bollinger Bands
            bb_ok = self.check_bollinger_confirmation(df, signal_direction)
            if bb_ok:
                confirmations += 1
                confirmation_details['bollinger'] = True
            
            # 6. Stochastic RSI
            stoch_ok = self.check_stochastic_rsi_confirmation(df, signal_direction)
            if stoch_ok:
                confirmations += 1
                confirmation_details['stochastic'] = True
            
            # 7. Momentum (RSI)
            momentum_ok = self.check_momentum(df, signal_direction)
            if momentum_ok:
                confirmations += 1
                confirmation_details['momentum'] = True
            
            # 8. Multi-Timeframe Confirmation
            mtf_ok = await self.get_higher_timeframe_confirmation(symbol, timeframe, signal_direction)
            if mtf_ok:
                confirmations += 1
                confirmation_details['mtf'] = True
            
            # Require minimum confirmations
            if confirmations < self.min_confirmations:
                return None
            
            # Order block detection
            order_block = self.detect_order_blocks(df, signal_direction)
            if not order_block:
                return None
            
            # FVG and Premium/Discount zones
            fvgs = self.detect_fvg(df)
            pd_zone = self.calculate_premium_discount(df, swing_highs, swing_lows)
            
            # Zone validation (Moderate - allow EQUILIBRIUM)
            if pd_zone:
                if signal_direction == 'LONG' and pd_zone['zone'] == 'PREMIUM':
                    return None  # Don't buy at premium
                elif signal_direction == 'SHORT' and pd_zone['zone'] == 'DISCOUNT':
                    return None  # Don't sell at discount
            
            # Calculate entry, stop loss, and targets
            current_price = df['close'].iloc[-1]
            atr = self.calculate_atr(df)
            rsi = self.calculate_rsi(df)
            adx = self.calculate_adx(df)
            
            ema_20 = self.calculate_ema(df, 20)
            ema_50 = self.calculate_ema(df, 50)
            ema_200 = self.calculate_ema(df, 200)
            
            valid_signal = False
            
            if signal_direction == 'LONG':
                entry_price = current_price
                stop_loss = order_block['low'] - (atr * 1.8)
                risk = entry_price - stop_loss
                
                target1 = entry_price + (risk * 2.5)
                target2 = entry_price + (risk * 4.0)
                target3 = entry_price + (risk * 6.0)
                valid_signal = True
            
            elif signal_direction == 'SHORT':
                entry_price = current_price
                stop_loss = order_block['high'] + (atr * 1.8)
                risk = stop_loss - entry_price
                
                target1 = entry_price - (risk * 2.5)
                target2 = entry_price - (risk * 4.0)
                target3 = entry_price - (risk * 6.0)
                valid_signal = True
            
            if not valid_signal:
                return None
            
            # Calculate R/R ratio
            rr_ratio = abs(target1 - entry_price) / risk
            if rr_ratio < self.min_rr_ratio:
                return None
            
            # Conservative leverage based on risk
            risk_percent = (risk / entry_price) * 100
            if risk_percent < 1.0:
                leverage = 10
            elif risk_percent < 1.5:
                leverage = 8
            elif risk_percent < 2.5:
                leverage = 5
            else:
                leverage = 3
            
            signal = {
                'symbol': symbol,
                'symbol_name': SYMBOLS[symbol]['name'],
                'ticker': SYMBOLS[symbol]['ticker'],
                'timeframe': timeframe,
                'direction': signal_direction,
                'entry_price': round(entry_price, 8),
                'stop_loss': round(stop_loss, 8),
                'targets': [
                    round(target1, 8),
                    round(target2, 8),
                    round(target3, 8)
                ],
                'leverage': leverage,
                'structure_type': structure['type'],
                'order_block': order_block,
                'fvgs': fvgs,
                'pd_zone': pd_zone,
                'df': df,
                'swing_highs': swing_highs,
                'swing_lows': swing_lows,
                'ema_20': ema_20,
                'ema_50': ema_50,
                'ema_200': ema_200,
                'atr': atr,
                'rsi': rsi,
                'adx': adx,
                'rr_ratio': rr_ratio,
                'risk_percent': risk_percent,
                'confirmations': confirmations,
                'confirmation_details': confirmation_details,
                'timestamp': datetime.now(timezone.utc)
            }
            
            logger.info(f"✅ HIGH QUALITY SIGNAL: {symbol} {timeframe} {signal_direction} - {confirmations} confirmations")
            
            return signal
            
        except Exception as e:
            logger.error(f"❌ Error generating signal for {symbol}: {e}")
            return None


class ChartGenerator:
    """Professional chart generator with white background and volume analysis"""
    
    @staticmethod
    def format_price(price: float) -> str:
        """Format price with comma separator - NO decimals"""
        if price < 1:
            return f"${price:.4f}"
        elif price < 10:
            return f"${price:.2f}"
        else:
            return f"${price:,.0f}"
    
    @staticmethod
    def create_chart(signal: Dict) -> io.BytesIO:
        """Create candlestick chart with SMC analysis + Volume - White background"""
        try:
            df = signal['df'].tail(120).copy()
            
            fig, (ax, ax_vol) = plt.subplots(2, 1, figsize=(20, 16), 
                                             gridspec_kw={'height_ratios': [3, 1]},
                                             sharex=True)
            fig.patch.set_facecolor('#FFFFFF')
            ax.set_facecolor('#FFFFFF')
            ax_vol.set_facecolor('#FFFFFF')
            
            # Plot EMAs
            if 'ema_20' in signal and 'ema_50' in signal:
                ema_20_values = signal['ema_20'].tail(120).values
                ema_50_values = signal['ema_50'].tail(120).values
                ema_200_values = signal['ema_200'].tail(120).values
                
                ax.plot(range(len(ema_200_values)), ema_200_values, 
                       color='#FF6B00', linewidth=2.5, label='EMA 200', alpha=0.8, zorder=2)
                ax.plot(range(len(ema_50_values)), ema_50_values, 
                       color='#FFA500', linewidth=2.5, label='EMA 50', alpha=0.85, zorder=2)
                ax.plot(range(len(ema_20_values)), ema_20_values, 
                       color='#0080FF', linewidth=3, label='EMA 20', alpha=0.9, zorder=2)
            
            # Plot candles
            for idx in range(len(df)):
                row = df.iloc[idx]
                
                if pd.isna(row['open']) or pd.isna(row['close']):
                    continue
                
                is_bullish = row['close'] >= row['open']
                candle_color = '#00C853' if is_bullish else '#FF1744'
                
                height = abs(row['close'] - row['open'])
                if height == 0:
                    height = 0.0001
                bottom = min(row['open'], row['close'])
                
                ax.add_patch(Rectangle((idx - 0.425, bottom), 0.85, height, 
                                       facecolor=candle_color, edgecolor=candle_color, 
                                       alpha=0.9, linewidth=0, zorder=3))
                
                ax.plot([idx, idx], [row['low'], row['high']], 
                       color=candle_color, linewidth=2.5, alpha=0.8, zorder=2)
            
            # Premium/Discount Zones
            if signal.get('pd_zone'):
                pd_zone = signal['pd_zone']
                ax.axhspan(pd_zone['premium_threshold'], pd_zone['high'], 
                          alpha=0.15, color='#FF1744', label='Premium Zone', zorder=0)
                ax.axhspan(pd_zone['low'], pd_zone['discount_threshold'], 
                          alpha=0.15, color='#00C853', label='Discount Zone', zorder=0)
                ax.axhline(pd_zone['equilibrium'], color='#FFD700', 
                          linestyle='--', linewidth=2.5, alpha=0.7, label='Equilibrium', zorder=1)
            
            # Order Block
            if signal.get('order_block'):
                ob = signal['order_block']
                ob_color = '#00C853' if signal['direction'] == 'LONG' else '#FF1744'
                ax.axhspan(ob['low'], ob['high'], alpha=0.3, color=ob_color, 
                          label='Order Block', zorder=1, edgecolor=ob_color, linewidth=3)
                
                mid_price = (ob['low'] + ob['high']) / 2
                ax.text(len(df) - 18, mid_price, '📦 ORDER BLOCK', 
                       fontsize=13, fontweight='bold', color='white',
                       bbox=dict(boxstyle='round,pad=0.7', facecolor=ob_color, 
                                edgecolor='black', linewidth=2.5, alpha=1.0), zorder=5)
            
            # Fair Value Gaps
            for fvg in signal.get('fvgs', []):
                fvg_color = '#0080FF' if 'BULLISH' in fvg['type'] else '#FFA500'
                ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.2, 
                          color=fvg_color, zorder=1, linestyle=':', 
                          edgecolor=fvg_color, linewidth=2)
            
            # Swing Points
            for sh in signal.get('swing_highs', [])[-10:]:
                if sh['index'] < len(df):
                    ax.plot(sh['index'], sh['price'], 'v', 
                           color='#FF1744', markersize=14, markeredgecolor='black', 
                           markeredgewidth=2.5, zorder=5)
            
            for sl in signal.get('swing_lows', [])[-10:]:
                if sl['index'] < len(df):
                    ax.plot(sl['index'], sl['price'], '^', 
                           color='#00C853', markersize=14, markeredgecolor='black',
                           markeredgewidth=2.5, zorder=5)
            
            # Current Price Marker
            current_idx = len(df) - 1
            current_price = df['close'].iloc[-1]
            ax.plot(current_idx, current_price, 'o', color='#FFD700', markersize=20, 
                   markeredgecolor='black', markeredgewidth=3, label='CURRENT PRICE', zorder=8)
            
            ax.axhline(current_price, color='#FFD700', linestyle='-', 
                      linewidth=2, alpha=0.6, zorder=1)
            
            price_text = ChartGenerator.format_price(current_price)
            ax.text(len(df) - 3, current_price, f'💰 {price_text}', 
                   fontsize=13, fontweight='bold', color='black',
                   bbox=dict(boxstyle='round,pad=0.7', facecolor='#FFD700', 
                            edgecolor='black', linewidth=2.5, alpha=1.0), 
                   va='center', zorder=9)
            
            # Entry Point
            entry_price = signal['entry_price']
            entry_color = '#0080FF' if signal['direction'] == 'LONG' else '#FF1744'
            ax.plot(current_idx, entry_price, 'D', color=entry_color, markersize=18, 
                   markeredgecolor='black', markeredgewidth=3, label='ENTRY', zorder=7)
            
            ax.axhline(entry_price, color=entry_color, linestyle='-', 
                      linewidth=2.5, alpha=0.6, zorder=1)
            
            # Stop Loss
            ax.axhline(signal['stop_loss'], color='#FF1744', linestyle='--', 
                      linewidth=3, label=f"STOP LOSS", alpha=0.9, zorder=2)
            
            sl_text = ChartGenerator.format_price(signal['stop_loss'])
            ax.text(len(df) - 10, signal['stop_loss'], f'🛑 SL: {sl_text}', 
                   fontsize=12, fontweight='bold', color='white',
                   bbox=dict(boxstyle='round,pad=0.6', facecolor='#FF1744', 
                            edgecolor='black', linewidth=2.5, alpha=1.0), zorder=6)
            
            # Targets
            target_colors = ['#00C853', '#00A843', '#008833']
            target_labels = ['🎯 TP1', '🎯 TP2', '🎯 TP3']
            for i, target in enumerate(signal['targets']):
                ax.axhline(target, color=target_colors[i], linestyle='--', 
                          linewidth=3, label=target_labels[i], alpha=0.9, zorder=2)
                
                tp_text = ChartGenerator.format_price(target)
                ax.text(len(df) - 6, target, f'TP{i+1}: {tp_text}', 
                       fontsize=12, fontweight='bold', color='white',
                       bbox=dict(boxstyle='round,pad=0.6', facecolor=target_colors[i], 
                                edgecolor='black', linewidth=2.5, alpha=1.0), 
                       ha='center', zorder=6)
            
            # Grid
            ax.grid(True, alpha=0.25, color='#CCCCCC', linestyle='-', linewidth=1)
            ax.set_axisbelow(True)
            
            # Styling
            ax.tick_params(colors='#333333', labelsize=12)
            for spine in ax.spines.values():
                spine.set_color('#333333')
                spine.set_linewidth(2.5)
            
            # Title
            direction_emoji = "🟢 LONG" if signal['direction'] == 'LONG' else "🔴 SHORT"
            title = f"{direction_emoji} | {signal['symbol_name']} ({signal['ticker']}/USDT) | {signal['timeframe'].upper()}"
            
            confirmations = signal.get('confirmations', 0)
            subtitle = f"✅ {confirmations} Confirmations | R:R 1:{signal.get('rr_ratio', 0):.1f} | RSI: {signal.get('rsi', 0):.0f} | ADX: {signal.get('adx', 0):.0f} | Risk: {signal.get('risk_percent', 0):.1f}%"
            
            ax.set_title(title, color='#000000', fontsize=24, fontweight='bold', pad=20)
            ax.text(0.5, 1.02, subtitle, transform=ax.transAxes, 
                   fontsize=14, ha='center', color='#333333', fontweight='bold')
            
            ax.set_ylabel('Price (USDT)', color='#333333', fontsize=15, fontweight='bold')
            
            # Legend
            legend = ax.legend(loc='upper left', fontsize=11, framealpha=0.95, 
                              facecolor='#FFFFFF', edgecolor='#333333', 
                              labelcolor='#000000', ncol=2)
            legend.get_frame().set_linewidth(2.5)
            
            # ==================== VOLUME CHART ====================
            
            volume_ma = df['volume'].rolling(window=20).mean()
            
            for idx in range(len(df)):
                row = df.iloc[idx]
                
                if pd.isna(row['open']) or pd.isna(row['close']):
                    continue
                
                is_bullish = row['close'] >= row['open']
                vol_color = '#00C853' if is_bullish else '#FF1744'
                
                ax_vol.add_patch(Rectangle((idx - 0.425, 0), 0.85, row['volume'], 
                                           facecolor=vol_color, edgecolor=vol_color, 
                                           alpha=0.7, linewidth=0, zorder=2))
            
            ax_vol.plot(range(len(volume_ma)), volume_ma.values, 
                       color='#0080FF', linewidth=2.5, label='Volume MA (20)', 
                       alpha=0.9, zorder=3)
            
            high_vol_threshold = volume_ma * 1.5
            for idx in range(len(df)):
                if df['volume'].iloc[idx] > high_vol_threshold.iloc[idx]:
                    ax_vol.plot(idx, df['volume'].iloc[idx], 'o', 
                               color='#FFD700', markersize=8, 
                               markeredgecolor='black', markeredgewidth=1.5, zorder=4)
            
            ax_vol.set_ylabel('Volume', color='#333333', fontsize=14, fontweight='bold')
            ax_vol.set_xlabel('Time Period', color='#333333', fontsize=15, fontweight='bold')
            ax_vol.grid(True, alpha=0.25, color='#CCCCCC', linestyle='-', linewidth=1)
            ax_vol.set_axisbelow(True)
            ax_vol.tick_params(colors='#333333', labelsize=11)
            
            for spine in ax_vol.spines.values():
                spine.set_color('#333333')
                spine.set_linewidth(2.5)
            
            vol_legend = ax_vol.legend(loc='upper left', fontsize=10, framealpha=0.95, 
                                      facecolor='#FFFFFF', edgecolor='#333333', 
                                      labelcolor='#000000')
            vol_legend.get_frame().set_linewidth(2.5)
            
            ax_vol.ticklabel_format(style='plain', axis='y')
            
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, facecolor='#FFFFFF', 
                       edgecolor='none', bbox_inches='tight')
            buf.seek(0)
            plt.close()
            
            return buf
            
        except Exception as e:
            logger.error(f"❌ Error creating chart: {e}")
            return None


class TelegramSignalBot:
    """Telegram signal bot with advanced strategy - OPTIMIZED for SPEED"""
    
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN)
        self.analyzer = AdvancedSmartMoneyAnalyzer()
        self.chart_gen = ChartGenerator()
        self.active_trades = {}
        
    async def save_signal(self, signal: Dict, message_id: int):
        """Save signal to memory"""
        signal_doc = {
            'symbol': signal['symbol'],
            'symbol_name': signal['symbol_name'],
            'ticker': signal['ticker'],
            'timeframe': signal['timeframe'],
            'direction': signal['direction'],
            'entry_price': signal['entry_price'],
            'stop_loss': signal['stop_loss'],
            'targets': signal['targets'],
            'leverage': signal['leverage'],
            'message_id': message_id,
            'status': 'ACTIVE',
            'targets_hit': [],
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        self.active_trades[signal['symbol']] = signal_doc
        logger.info(f"✅ Signal saved: {signal['symbol_name']} {signal['direction']}")
    
    async def update_trade_status(self, symbol: str, status: str, hit_target: Optional[int] = None):
        """Update trade status"""
        if symbol in self.active_trades:
            if hit_target:
                if 'targets_hit' not in self.active_trades[symbol]:
                    self.active_trades[symbol]['targets_hit'] = []
                self.active_trades[symbol]['targets_hit'].append(hit_target)
            else:
                self.active_trades[symbol]['status'] = status
    
    async def monitor_active_trades(self):
        """Monitor active trades"""
        if not self.active_trades:
            return
        
        for symbol, trade in list(self.active_trades.items()):
            try:
                current_price = await data_fetcher.get_current_price(symbol)
                
                if current_price is None:
                    continue
                
                # Check Stop Loss
                if trade['direction'] == 'LONG':
                    if current_price <= trade['stop_loss']:
                        await self.send_trade_update(trade, 'STOP_LOSS', current_price)
                        await self.update_trade_status(symbol, 'CLOSED_SL')
                        del self.active_trades[symbol]
                        continue
                    
                    # Check Targets
                    for i, target in enumerate(trade['targets'], 1):
                        if current_price >= target and i not in trade.get('targets_hit', []):
                            await self.send_trade_update(trade, f'TARGET_{i}', current_price)
                            await self.update_trade_status(symbol, 'ACTIVE', i)
                            
                            if i == len(trade['targets']):
                                await self.update_trade_status(symbol, 'CLOSED_TP')
                                del self.active_trades[symbol]
                
                else:  # SHORT
                    if current_price >= trade['stop_loss']:
                        await self.send_trade_update(trade, 'STOP_LOSS', current_price)
                        await self.update_trade_status(symbol, 'CLOSED_SL')
                        del self.active_trades[symbol]
                        continue
                    
                    for i, target in enumerate(trade['targets'], 1):
                        if current_price <= target and i not in trade.get('targets_hit', []):
                            await self.send_trade_update(trade, f'TARGET_{i}', current_price)
                            await self.update_trade_status(symbol, 'ACTIVE', i)
                            
                            if i == len(trade['targets']):
                                await self.update_trade_status(symbol, 'CLOSED_TP')
                                del self.active_trades[symbol]
            
            except Exception as e:
                logger.error(f"❌ Error monitoring {symbol}: {e}")
    
    async def send_trade_update(self, trade: Dict, update_type: str, current_price: float):
        """Send trade update"""
        try:
            symbol_name = trade['symbol_name']
            
            if update_type == 'STOP_LOSS':
                emoji = "🛑"
                loss_percent = abs((current_price - trade['entry_price']) / trade['entry_price'] * 100)
                message = f"{emoji} *STOP LOSS HIT*\n\n"
                message += f"*{symbol_name}* {trade['direction']}\n"
                message += f"Entry: `{ChartGenerator.format_price(trade['entry_price'])}`\n"
                message += f"Exit: `{ChartGenerator.format_price(current_price)}`\n"
                message += f"Loss: *-{loss_percent:.1f}%*"
            
            elif 'TARGET' in update_type:
                target_num = int(update_type.split('_')[1])
                emoji = "✅"
                
                profit_percent = abs((current_price - trade['entry_price']) / trade['entry_price'] * 100)
                leverage_profit = profit_percent * trade.get('leverage', 1)
                
                message = f"{emoji} *TARGET {target_num} REACHED!*\n\n"
                message += f"*{symbol_name}* {trade['direction']}\n"
                message += f"Entry: `{ChartGenerator.format_price(trade['entry_price'])}`\n"
                message += f"Exit: `{ChartGenerator.format_price(current_price)}`\n"
                message += f"Profit: *+{profit_percent:.1f}%*\n"
                message += f"With {trade.get('leverage', 1)}x Leverage: *+{leverage_profit:.1f}%*"
                
                if target_num == len(trade['targets']):
                    message += f"\n\n🎉 *ALL TARGETS COMPLETED!*"
            
            await self.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode='Markdown',
                reply_to_message_id=trade['message_id']
            )
            
            logger.info(f"✅ Update sent: {symbol_name} - {update_type}")
            
        except Exception as e:
            logger.error(f"❌ Error sending update: {e}")
    
    async def send_signal(self, signal: Dict):
        """Send signal to Telegram - OPTIMIZED"""
        try:
            chart_buffer = self.chart_gen.create_chart(signal)
            
            if not chart_buffer:
                return
            
            direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
            
            rr_ratio = signal.get('rr_ratio', 2.5)
            potential_profit = abs(signal['targets'][0] - signal['entry_price']) / signal['entry_price'] * 100
            risk_percent = signal.get('risk_percent', 1.0)
            confirmations = signal.get('confirmations', 0)
            
            entry_str = ChartGenerator.format_price(signal['entry_price'])
            sl_str = ChartGenerator.format_price(signal['stop_loss'])
            tp_strs = [ChartGenerator.format_price(t) for t in signal['targets']]
            
            message = f"🔥 *PREMIUM SIGNAL* 🔥\n"
            message += f"{direction_emoji} *{signal['direction']}* | {signal['symbol_name']} ({signal['ticker']}) | {signal['timeframe'].upper()}\n\n"
            
            message += f"✅ *{confirmations} Confirmations*\n\n"
            
            message += f"💰 *Entry:* `{entry_str}`\n\n"
            
            message += f"🎯 *Take Profit:*\n"
            for i, tp_str in enumerate(tp_strs, 1):
                message += f"   TP{i}: `{tp_str}`\n"
            
            message += f"\n🛑 *Stop Loss:* `{sl_str}`\n\n"
            
            message += f"⚖️ R:R `1:{rr_ratio:.1f}` | 📊 Leverage: `{signal['leverage']}x`\n"
            message += f"📉 Risk: `{risk_percent:.2f}%` | 📈 RSI: `{signal.get('rsi', 0):.0f}`\n"
            message += f"💪 ADX: `{signal.get('adx', 0):.0f}` | 💹 Profit: `+{potential_profit:.1f}%`\n\n"
            message += f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
            
            sent_message = await self.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=chart_buffer,
                caption=message,
                parse_mode='Markdown'
            )
            
            await self.save_signal(signal, sent_message.message_id)
            
            logger.info(f"✅ Signal sent: {signal['symbol_name']} {signal['direction']} - {confirmations} confirmations")
            
        except TelegramError as e:
            logger.error(f"❌ Telegram error: {e}")
        except Exception as e:
            logger.error(f"❌ Error sending signal: {e}")
    
    async def scan_single_symbol_timeframe(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Scan single symbol and timeframe - OPTIMIZED"""
        try:
            signal = await self.analyzer.generate_signal(symbol, timeframe)
            if signal:
                logger.info(f"✅ SIGNAL FOUND: {symbol} {timeframe} {signal['direction']}")
            return signal
        except Exception as e:
            logger.error(f"❌ Error scanning {symbol} {timeframe}: {e}")
            return None
    
    async def scan_markets(self):
        """Scan markets for signals - PARALLEL PROCESSING"""
        logger.info("🔍 Scanning markets with PARALLEL PROCESSING...")
        
        signals_found = 0
        tasks = []
        
        # Create tasks for all symbols and timeframes in parallel
        for symbol in SYMBOLS.keys():
            # Skip if already have active trade
            if symbol in self.active_trades:
                continue
            
            for timeframe in TIMEFRAMES.values():
                task = self.scan_single_symbol_timeframe(symbol, timeframe)
                tasks.append((symbol, timeframe, task))
        
        # Execute all tasks in parallel
        results = await asyncio.gather(*[task for _, _, task in tasks], return_exceptions=True)
        
        # Process results
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                continue
            
            if result:
                await self.send_signal(result)
                signals_found += 1
                
                # Skip other timeframes for this symbol
                symbol = result['symbol']
                break
        
        logger.info(f"✅ Scan complete in PARALLEL. High-quality signals found: {signals_found}")
    
    async def run(self):
        """Run the bot - OPTIMIZED"""
        logger.info("=" * 70)
        logger.info("🚀 FAST Crypto Signal Bot - MODERATE MODE (Balanced)")
        logger.info("=" * 70)
        
        try:
            me = await self.bot.get_me()
            logger.info(f"✅ Bot: @{me.username}")
            logger.info(f"📢 Channel: {CHANNEL_ID}")
            logger.info(f"📊 Symbols: {', '.join([s['ticker'] for s in SYMBOLS.values()])}")
            logger.info(f"⏱️  Timeframes: {', '.join(TIMEFRAMES.keys())}")
            logger.info(f"🔄 Scan interval: 1 minute (FAST)")
            logger.info(f"⚡ Processing: PARALLEL (ALL SYMBOLS AT ONCE)")
            logger.info(f"🎯 Mode: MODERATE (3 confirmations, R:R 2.0+, Volume 1.3x)")
            logger.info(f"📈 Expected signals: 5-15 per day")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return
        
        logger.info("=" * 70)
        logger.info("🚀 Bot is running: MODERATE MODE (Fast + Balanced Accuracy)")
        logger.info("=" * 70)
        
        while True:
            try:
                start_time = datetime.now()
                
                await self.scan_markets()
                await self.monitor_active_trades()
                
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"⏱️  Scan completed in {elapsed:.1f}s | Active trades: {len(self.active_trades)}")
                
                # Faster scanning: 60 seconds (1 minute)
                logger.info(f"⏸️  Waiting 1 minute before next scan...")
                await asyncio.sleep(60)
                
            except KeyboardInterrupt:
                logger.info("🛑 Stopping bot...")
                break
            except Exception as e:
                logger.error(f"⚠️  Error: {e}")
                await asyncio.sleep(30)
        
        # Cleanup
        await data_fetcher.close()


async def main():
    """Main function"""
    bot = TelegramSignalBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
