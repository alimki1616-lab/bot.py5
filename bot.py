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
CHANNEL_ID = os.environ.get('CHANNEL_ID', '@Livepricee')

logger.info(f"✅ Bot Token loaded: {BOT_TOKEN[:10]}...")
logger.info(f"✅ Channel ID: {CHANNEL_ID}")

# Trading pairs - Using Binance tickers
SYMBOLS = {
    'BTCUSDT': {'name': 'Bitcoin', 'ticker': 'BTC'},
    'ETHUSDT': {'name': 'Ethereum', 'ticker': 'ETH'},
    'SOLUSDT': {'name': 'Solana', 'ticker': 'SOL'},
    'BNBUSDT': {'name': 'BNB', 'ticker': 'BNB'},
    'ADAUSDT': {'name': 'Cardano', 'ticker': 'ADA'},
    'DOGEUSDT': {'name': 'Dogecoin', 'ticker': 'DOGE'},
    'XRPUSDT': {'name': 'Ripple', 'ticker': 'XRP'}
}

TIMEFRAMES = {
    '15m': '15m',
    '1h': '1h'
}


class BinanceDataFetcher:
    """Fetch crypto data from multiple sources with fallback"""
    
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
        
    async def get_ohlcv_binance(self, symbol: str, interval: str, limit: int, base_url: str) -> pd.DataFrame:
        """Try fetching from Binance"""
        try:
            url = f"{base_url}/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': min(limit, 1000)
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
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
        """Fallback to Crypto.com Exchange API"""
        try:
            mapped = self.symbol_map.get(symbol, {}).get('cdc')
            if not mapped:
                return None
            
            # Map interval
            interval_map = {'15m': '15m', '1h': '1h', '4h': '4h', '1d': '1D'}
            timeframe = interval_map.get(interval, '1h')
            
            url = f"{self.cryptocom_url}/public/get-candlestick"
            params = {
                'instrument_name': mapped,
                'timeframe': timeframe
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
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
        
    async def get_ohlcv(self, symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
        """Get OHLCV data with fallback mechanism"""
        # Try Binance first (all endpoints)
        for base_url in self.binance_urls:
            df = await self.get_ohlcv_binance(symbol, interval, limit, base_url)
            if df is not None and len(df) > 0:
                logger.debug(f"✅ Data from Binance")
                return df.tail(limit)
        
        # Fallback to Crypto.com
        logger.info(f"⚠️  Binance failed, using Crypto.com for {symbol}")
        df = await self.get_ohlcv_cryptocom(symbol, interval)
        if df is not None and len(df) > 0:
            logger.info(f"✅ Data from Crypto.com")
            return df.tail(limit)
        
        logger.error(f"❌ All sources failed for {symbol}")
        return None
    
    async def get_current_price(self, symbol: str) -> float:
        """Get current price with fallback"""
        # Try Binance first
        for base_url in self.binance_urls:
            try:
                url = f"{base_url}/ticker/price"
                params = {'symbol': symbol}
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
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
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == 0 and 'result' in data:
                            result = data['result']['data'][0]
                            return float(result.get('a', 0))  # ask price
        except Exception as e:
            logger.error(f"❌ Error fetching price: {e}")
        
        return None


data_fetcher = BinanceDataFetcher()


class SmartMoneyAnalyzer:
    """Enhanced Smart Money Concept Analyzer with balanced filters"""
    
    def __init__(self):
        self.lookback_periods = 50
        self.min_rr_ratio = 2.0  # Balanced R/R
        self.volume_threshold = 1.4  # Balanced volume threshold
        
    def detect_swing_points(self, df: pd.DataFrame) -> Tuple[List, List]:
        """Detect Swing Highs and Swing Lows"""
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(df) - 2):
            # Balanced swing detection with 2 candles on each side
            if (df['high'].iloc[i] > df['high'].iloc[i-1] and 
                df['high'].iloc[i] > df['high'].iloc[i-2] and
                df['high'].iloc[i] > df['high'].iloc[i+1] and 
                df['high'].iloc[i] > df['high'].iloc[i+2]):
                swing_highs.append({
                    'index': i,
                    'price': df['high'].iloc[i],
                    'time': df.index[i]
                })
            
            if (df['low'].iloc[i] < df['low'].iloc[i-1] and 
                df['low'].iloc[i] < df['low'].iloc[i-2] and
                df['low'].iloc[i] < df['low'].iloc[i+1] and 
                df['low'].iloc[i] < df['low'].iloc[i+2]):
                swing_lows.append({
                    'index': i,
                    'price': df['low'].iloc[i],
                    'time': df.index[i]
                })
        
        return swing_highs, swing_lows
    
    def detect_bos_choch(self, df: pd.DataFrame, swing_highs: List, swing_lows: List) -> Dict:
        """Detect Break of Structure (BOS)"""
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None
        
        last_swing_high = swing_highs[-1]['price']
        last_swing_low = swing_lows[-1]['price']
        current_price = df['close'].iloc[-1]
        
        # Bullish BOS
        if current_price > last_swing_high:
            return {
                'type': 'BOS_BULLISH',
                'signal': 'LONG',
                'level': last_swing_high,
                'strength': 'STRONG'
            }
        
        # Bearish BOS
        if current_price < last_swing_low:
            return {
                'type': 'BOS_BEARISH',
                'signal': 'SHORT',
                'level': last_swing_low,
                'strength': 'STRONG'
            }
        
        return None
    
    def detect_order_blocks(self, df: pd.DataFrame, signal_type: str) -> Optional[Dict]:
        """Detect Order Blocks"""
        order_blocks = []
        avg_volume = df['volume'].tail(50).mean()
        
        for i in range(len(df) - 10, len(df) - 1):
            candle = df.iloc[i]
            next_candle = df.iloc[i + 1]
            
            if signal_type == 'LONG':
                # Bearish candle followed by bullish move
                if (candle['close'] < candle['open'] and 
                    next_candle['close'] > next_candle['open'] and
                    (next_candle['close'] - next_candle['open']) > 1.5 * abs(candle['close'] - candle['open'])):
                    order_blocks.append({
                        'type': 'BULLISH_OB',
                        'high': candle['high'],
                        'low': candle['low'],
                        'index': i,
                        'volume': candle['volume']
                    })
            
            elif signal_type == 'SHORT':
                # Bullish candle followed by bearish move
                if (candle['close'] > candle['open'] and 
                    next_candle['close'] < next_candle['open'] and
                    (next_candle['open'] - next_candle['close']) > 1.5 * abs(candle['close'] - candle['open'])):
                    order_blocks.append({
                        'type': 'BEARISH_OB',
                        'high': candle['high'],
                        'low': candle['low'],
                        'index': i,
                        'volume': candle['volume']
                    })
        
        return order_blocks[-1] if order_blocks else None
    
    def detect_fvg(self, df: pd.DataFrame) -> List[Dict]:
        """Detect Fair Value Gaps"""
        fvgs = []
        
        for i in range(1, len(df) - 1):
            prev_candle = df.iloc[i - 1]
            next_candle = df.iloc[i + 1]
            
            # Bullish FVG - Gap up
            if next_candle['low'] > prev_candle['high']:
                gap_size = next_candle['low'] - prev_candle['high']
                if gap_size > 0:
                    fvgs.append({
                        'type': 'BULLISH_FVG',
                        'top': next_candle['low'],
                        'bottom': prev_candle['high'],
                        'index': i,
                        'size': gap_size
                    })
            
            # Bearish FVG - Gap down
            if next_candle['high'] < prev_candle['low']:
                gap_size = prev_candle['low'] - next_candle['high']
                if gap_size > 0:
                    fvgs.append({
                        'type': 'BEARISH_FVG',
                        'top': prev_candle['low'],
                        'bottom': next_candle['high'],
                        'index': i,
                        'size': gap_size
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
        premium_zone = recent_low + (range_size * 0.618)  # 61.8% Fibonacci
        discount_zone = recent_low + (range_size * 0.382)  # 38.2% Fibonacci
        
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
    
    def check_volume_confirmation(self, df: pd.DataFrame) -> bool:
        """Volume confirmation"""
        if len(df) < 20:
            return False
        
        avg_volume = df['volume'].tail(20).mean()
        recent_volume = df['volume'].tail(5).mean()
        
        # Recent volume should be above average
        return recent_volume >= (avg_volume * self.volume_threshold)
    
    def check_trend_alignment(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """Check trend alignment with EMAs"""
        ema_20 = self.calculate_ema(df, 20)
        ema_50 = self.calculate_ema(df, 50)
        
        current_price = df['close'].iloc[-1]
        
        if signal_direction == 'LONG':
            # Bullish: EMA20 > EMA50 OR price > EMA20
            return ema_20.iloc[-1] > ema_50.iloc[-1] or current_price > ema_20.iloc[-1]
        else:
            # Bearish: EMA20 < EMA50 OR price < EMA20
            return ema_20.iloc[-1] < ema_50.iloc[-1] or current_price < ema_20.iloc[-1]
    
    def check_momentum(self, df: pd.DataFrame, signal_direction: str) -> bool:
        """Check momentum with RSI"""
        rsi = self.calculate_rsi(df)
        
        if signal_direction == 'LONG':
            # For long: RSI should be between 35-75 (not extremely overbought)
            return 35 <= rsi <= 75
        else:
            # For short: RSI should be between 25-65 (not extremely oversold)
            return 25 <= rsi <= 65
    
    async def generate_signal(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Generate trading signal with enhanced filters"""
        try:
            df = await data_fetcher.get_ohlcv(symbol, timeframe, limit=250)
            
            if df is None or len(df) < 200:
                return None
            
            df.set_index('timestamp', inplace=True)
            
            swing_highs, swing_lows = self.detect_swing_points(df)
            
            if len(swing_highs) < 5 or len(swing_lows) < 5:
                return None
            
            structure = self.detect_bos_choch(df, swing_highs, swing_lows)
            
            if not structure or structure.get('strength') != 'STRONG':
                return None
            
            # Volume confirmation
            volume_confirmed = self.check_volume_confirmation(df)
            if not volume_confirmed:
                logger.debug(f"❌ {symbol} - Volume not confirmed")
                return None
            
            # Trend alignment
            trend_aligned = self.check_trend_alignment(df, structure['signal'])
            if not trend_aligned:
                logger.debug(f"❌ {symbol} - Trend not aligned")
                return None
            
            # Momentum check
            momentum_ok = self.check_momentum(df, structure['signal'])
            if not momentum_ok:
                logger.debug(f"❌ {symbol} - Momentum not favorable")
                return None
            
            # Order block
            order_block = self.detect_order_blocks(df, structure['signal'])
            if not order_block:
                logger.debug(f"❌ {symbol} - No order block found")
                return None
            
            fvgs = self.detect_fvg(df)
            pd_zone = self.calculate_premium_discount(df, swing_highs, swing_lows)
            
            current_price = df['close'].iloc[-1]
            atr = self.calculate_atr(df)
            rsi = self.calculate_rsi(df)
            
            ema_20 = self.calculate_ema(df, 20)
            ema_50 = self.calculate_ema(df, 50)
            ema_200 = self.calculate_ema(df, 200)
            
            valid_signal = False
            
            if structure['signal'] == 'LONG':
                # Prefer discount zone but allow equilibrium
                if pd_zone and pd_zone['zone'] in ['DISCOUNT', 'EQUILIBRIUM']:
                    valid_signal = True
                    entry_price = current_price
                    stop_loss = order_block['low'] - (atr * 0.5)
                    risk = entry_price - stop_loss
                    
                    # Balanced targets
                    target1 = entry_price + (risk * 2.0)
                    target2 = entry_price + (risk * 3.5)
                    target3 = entry_price + (risk * 5.0)
            
            elif structure['signal'] == 'SHORT':
                # Prefer premium zone but allow equilibrium
                if pd_zone and pd_zone['zone'] in ['PREMIUM', 'EQUILIBRIUM']:
                    valid_signal = True
                    entry_price = current_price
                    stop_loss = order_block['high'] + (atr * 0.5)
                    risk = stop_loss - entry_price
                    
                    # Balanced targets
                    target1 = entry_price - (risk * 2.0)
                    target2 = entry_price - (risk * 3.5)
                    target3 = entry_price - (risk * 5.0)
            
            if not valid_signal:
                return None
            
            rr_ratio = abs(target1 - entry_price) / risk
            if rr_ratio < self.min_rr_ratio:
                logger.debug(f"❌ {symbol} - R/R too low: {rr_ratio:.2f}")
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
                'direction': structure['signal'],
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
                'rr_ratio': rr_ratio,
                'timestamp': datetime.now(timezone.utc)
            }
            
            return signal
            
        except Exception as e:
            logger.error(f"❌ Error generating signal for {symbol}: {e}")
            return None


class ChartGenerator:
    """Professional chart generator with clean styling"""
    
    @staticmethod
    def create_chart(signal: Dict) -> io.BytesIO:
        """Create candlestick chart with SMC analysis"""
        try:
            df = signal['df'].tail(120).copy()
            
            fig, ax = plt.subplots(figsize=(20, 12))
            fig.patch.set_facecolor('#0B0E11')
            ax.set_facecolor('#0B0E11')
            
            # Plot EMAs
            if 'ema_20' in signal and 'ema_50' in signal:
                ema_20_values = signal['ema_20'].tail(120).values
                ema_50_values = signal['ema_50'].tail(120).values
                ema_200_values = signal['ema_200'].tail(120).values
                
                ax.plot(range(len(ema_200_values)), ema_200_values, 
                       color='#FF6B00', linewidth=2, label='EMA 200', alpha=0.7, zorder=2)
                ax.plot(range(len(ema_50_values)), ema_50_values, 
                       color='#FFA800', linewidth=2, label='EMA 50', alpha=0.8, zorder=2)
                ax.plot(range(len(ema_20_values)), ema_20_values, 
                       color='#00D4FF', linewidth=2.5, label='EMA 20', alpha=0.9, zorder=2)
            
            # Plot candles
            for idx in range(len(df)):
                row = df.iloc[idx]
                
                if pd.isna(row['open']) or pd.isna(row['close']):
                    continue
                
                is_bullish = row['close'] >= row['open']
                candle_color = '#00FF88' if is_bullish else '#FF3B69'
                
                height = abs(row['close'] - row['open'])
                if height == 0:
                    height = 0.0001
                bottom = min(row['open'], row['close'])
                
                ax.add_patch(Rectangle((idx - 0.35, bottom), 0.7, height, 
                                       facecolor=candle_color, edgecolor=candle_color, 
                                       alpha=0.95, linewidth=0, zorder=3))
                
                ax.plot([idx, idx], [row['low'], row['high']], 
                       color=candle_color, linewidth=2, alpha=0.85, zorder=2)
            
            # Premium/Discount Zones
            if signal.get('pd_zone'):
                pd_zone = signal['pd_zone']
                ax.axhspan(pd_zone['premium_threshold'], pd_zone['high'], 
                          alpha=0.12, color='#FF3B69', label='Premium Zone', zorder=0)
                ax.axhspan(pd_zone['low'], pd_zone['discount_threshold'], 
                          alpha=0.12, color='#00FF88', label='Discount Zone', zorder=0)
                ax.axhline(pd_zone['equilibrium'], color='#FFD700', 
                          linestyle='--', linewidth=2, alpha=0.6, label='Equilibrium', zorder=1)
            
            # Order Block
            if signal.get('order_block'):
                ob = signal['order_block']
                ob_color = '#00FF88' if signal['direction'] == 'LONG' else '#FF3B69'
                ax.axhspan(ob['low'], ob['high'], alpha=0.3, color=ob_color, 
                          label='Order Block', zorder=1, edgecolor=ob_color, linewidth=3)
                
                mid_price = (ob['low'] + ob['high']) / 2
                ax.text(len(df) - 18, mid_price, '📦 ORDER BLOCK', 
                       fontsize=12, fontweight='bold', color='white',
                       bbox=dict(boxstyle='round,pad=0.6', facecolor=ob_color, 
                                edgecolor='white', linewidth=2, alpha=0.9), zorder=5)
            
            # Fair Value Gaps
            for fvg in signal.get('fvgs', []):
                fvg_color = '#00D4FF' if 'BULLISH' in fvg['type'] else '#FFA800'
                ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.2, 
                          color=fvg_color, zorder=1, linestyle=':', 
                          edgecolor=fvg_color, linewidth=2)
            
            # Swing Points
            for sh in signal.get('swing_highs', [])[-10:]:
                if sh['index'] < len(df):
                    ax.plot(sh['index'], sh['price'], 'v', 
                           color='#FF3B69', markersize=12, markeredgecolor='white', 
                           markeredgewidth=2, zorder=5)
            
            for sl in signal.get('swing_lows', [])[-10:]:
                if sl['index'] < len(df):
                    ax.plot(sl['index'], sl['price'], '^', 
                           color='#00FF88', markersize=12, markeredgecolor='white',
                           markeredgewidth=2, zorder=5)
            
            # Entry Point
            entry_idx = len(df) - 1
            entry_price = signal['entry_price']
            entry_color = '#00D4FF' if signal['direction'] == 'LONG' else '#FF3B69'
            ax.plot(entry_idx, entry_price, 'D', color=entry_color, markersize=18, 
                   markeredgecolor='white', markeredgewidth=3, label='ENTRY', zorder=7)
            
            ax.axhline(entry_price, color=entry_color, linestyle='-', 
                      linewidth=2.5, alpha=0.6, zorder=1)
            
            # Stop Loss
            ax.axhline(signal['stop_loss'], color='#FF3B69', linestyle='--', 
                      linewidth=3, label=f"STOP LOSS", alpha=0.9, zorder=2)
            
            # Format price display
            if entry_price < 1:
                price_format = f"${signal['stop_loss']:.6f}"
            elif entry_price < 100:
                price_format = f"${signal['stop_loss']:.2f}"
            else:
                price_format = f"${signal['stop_loss']:,.2f}"
            
            ax.text(len(df) - 10, signal['stop_loss'], f'SL: {price_format}', 
                   fontsize=11, fontweight='bold', color='white',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='#FF3B69', 
                            edgecolor='white', linewidth=2, alpha=0.95), zorder=6)
            
            # Targets
            target_colors = ['#00FF88', '#00D4AA', '#00B88F']
            target_labels = ['🎯 TP1', '🎯 TP2', '🎯 TP3']
            for i, target in enumerate(signal['targets']):
                ax.axhline(target, color=target_colors[i], linestyle='--', 
                          linewidth=3, label=target_labels[i], alpha=0.9, zorder=2)
                
                if target < 1:
                    tp_format = f"${target:.6f}"
                elif target < 100:
                    tp_format = f"${target:.2f}"
                else:
                    tp_format = f"${target:,.2f}"
                
                ax.text(len(df) - 6, target, f'TP{i+1}: {tp_format}', 
                       fontsize=11, fontweight='bold', color='white',
                       bbox=dict(boxstyle='round,pad=0.5', facecolor=target_colors[i], 
                                edgecolor='white', linewidth=2, alpha=0.95), 
                       ha='center', zorder=6)
            
            # Grid
            ax.grid(True, alpha=0.15, color='#1E2329', linestyle='-', linewidth=1)
            ax.set_axisbelow(True)
            
            # Styling
            ax.tick_params(colors='#848E9C', labelsize=11)
            for spine in ax.spines.values():
                spine.set_color('#1E2329')
                spine.set_linewidth(2)
            
            # Title
            direction_emoji = "🟢 LONG" if signal['direction'] == 'LONG' else "🔴 SHORT"
            title = f"{direction_emoji} | {signal['symbol_name']} ({signal['ticker']}/USDT) | {signal['timeframe'].upper()}"
            subtitle = f"Smart Money Concept | R/R: 1:{signal.get('rr_ratio', 0):.1f} | RSI: {signal.get('rsi', 0):.1f}"
            
            ax.set_title(title, color='white', fontsize=22, fontweight='bold', pad=20)
            ax.text(0.5, 1.02, subtitle, transform=ax.transAxes, 
                   fontsize=13, ha='center', color='#848E9C', fontweight='bold')
            
            ax.set_xlabel('Time Period', color='#848E9C', fontsize=14, fontweight='bold')
            ax.set_ylabel('Price (USDT)', color='#848E9C', fontsize=14, fontweight='bold')
            
            # Legend
            legend = ax.legend(loc='upper left', fontsize=10, framealpha=0.9, 
                              facecolor='#0B0E11', edgecolor='#1E2329', 
                              labelcolor='white', ncol=2)
            legend.get_frame().set_linewidth(2)
            
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, facecolor='#0B0E11', 
                       edgecolor='none', bbox_inches='tight')
            buf.seek(0)
            plt.close()
            
            return buf
            
        except Exception as e:
            logger.error(f"❌ Error creating chart: {e}")
            return None


class TelegramSignalBot:
    """Telegram signal bot with real-time monitoring"""
    
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN)
        self.analyzer = SmartMoneyAnalyzer()
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
                message += f"Entry: `${trade['entry_price']:,.4f}`\n"
                message += f"Exit: `${current_price:,.4f}`\n"
                message += f"Loss: *-{loss_percent:.2f}%*"
            
            elif 'TARGET' in update_type:
                target_num = int(update_type.split('_')[1])
                emoji = "✅"
                
                profit_percent = abs((current_price - trade['entry_price']) / trade['entry_price'] * 100)
                leverage_profit = profit_percent * trade.get('leverage', 1)
                
                message = f"{emoji} *TARGET {target_num} HIT!*\n\n"
                message += f"*{symbol_name}* {trade['direction']}\n"
                message += f"Entry: `${trade['entry_price']:,.4f}`\n"
                message += f"Target: `${current_price:,.4f}`\n"
                message += f"Profit: *+{profit_percent:.2f}%*\n"
                message += f"With {trade.get('leverage', 1)}x: *+{leverage_profit:.2f}%*"
                
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
        """Send signal to Telegram"""
        try:
            chart_buffer = self.chart_gen.create_chart(signal)
            
            if not chart_buffer:
                return
            
            direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
            
            rr_ratio = signal.get('rr_ratio', 2.5)
            potential_profit = abs(signal['targets'][0] - signal['entry_price']) / signal['entry_price'] * 100
            
            # Format prices based on value
            entry = signal['entry_price']
            if entry < 1:
                entry_str = f"${entry:.6f}"
                sl_str = f"${signal['stop_loss']:.6f}"
                tp_strs = [f"${t:.6f}" for t in signal['targets']]
            elif entry < 100:
                entry_str = f"${entry:.2f}"
                sl_str = f"${signal['stop_loss']:.2f}"
                tp_strs = [f"${t:.2f}" for t in signal['targets']]
            else:
                entry_str = f"${entry:,.2f}"
                sl_str = f"${signal['stop_loss']:,.2f}"
                tp_strs = [f"${t:,.2f}" for t in signal['targets']]
            
            message = f"{direction_emoji} *{signal['direction']}* | {signal['symbol_name']} | {signal['timeframe'].upper()}\n\n"
            
            message += f"📍 *Entry:* `{entry_str}`\n\n"
            
            message += f"🎯 *Targets:*\n"
            for i, tp_str in enumerate(tp_strs, 1):
                message += f"TP{i}: `{tp_str}`\n"
            
            message += f"\n🛑 *Stop Loss:* `{sl_str}`\n\n"
            
            message += f"⚖️ Risk/Reward: `1:{rr_ratio:.1f}`\n"
            message += f"📊 Leverage: `{signal['leverage']}x`\n"
            message += f"📈 RSI: `{signal.get('rsi', 0):.1f}`\n"
            message += f"💹 Potential: `+{potential_profit:.1f}%`\n\n"
            message += f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
            
            sent_message = await self.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=chart_buffer,
                caption=message,
                parse_mode='Markdown'
            )
            
            await self.save_signal(signal, sent_message.message_id)
            
            logger.info(f"✅ Signal sent: {signal['symbol_name']} {signal['direction']}")
            
        except TelegramError as e:
            logger.error(f"❌ Telegram error: {e}")
        except Exception as e:
            logger.error(f"❌ Error sending signal: {e}")
    
    async def scan_markets(self):
        """Scan markets for signals"""
        logger.info("🔍 Scanning markets...")
        
        signals_found = 0
        
        for symbol in SYMBOLS.keys():
            # Skip if already have active trade
            if symbol in self.active_trades:
                continue
            
            for timeframe in TIMEFRAMES.values():
                try:
                    logger.info(f"🔎 Analyzing {symbol} {timeframe}...")
                    signal = await self.analyzer.generate_signal(symbol, timeframe)
                    
                    if signal:
                        logger.info(f"✅ SIGNAL: {symbol} {timeframe} {signal['direction']}")
                        await self.send_signal(signal)
                        signals_found += 1
                        break
                    
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Error scanning {symbol} {timeframe}: {e}")
                    continue
        
        logger.info(f"✅ Scan complete. Signals found: {signals_found}")
    
    async def run(self):
        """Run the bot"""
        logger.info("=" * 70)
        logger.info("🤖 Crypto Signal Bot - Smart Money Concept")
        logger.info("=" * 70)
        
        try:
            me = await self.bot.get_me()
            logger.info(f"✅ Bot: @{me.username}")
            logger.info(f"📢 Channel: {CHANNEL_ID}")
            logger.info(f"📊 Symbols: {', '.join([s['ticker'] for s in SYMBOLS.values()])}")
            logger.info(f"⏱️  Timeframes: {', '.join(TIMEFRAMES.keys())}")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return
        
        logger.info("=" * 70)
        logger.info("🚀 Bot is running...")
        logger.info("=" * 70)
        
        while True:
            try:
                await self.scan_markets()
                await self.monitor_active_trades()
                
                logger.info(f"⏸️  Waiting 5 minutes... Active trades: {len(self.active_trades)}")
                await asyncio.sleep(300)  # 5 minutes
                
            except KeyboardInterrupt:
                logger.info("🛑 Stopping bot...")
                break
            except Exception as e:
                logger.error(f"⚠️  Error: {e}")
                await asyncio.sleep(60)


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
