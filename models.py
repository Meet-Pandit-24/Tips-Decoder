from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Tip(db.Model):
    __tablename__ = 'decoded_tips'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Decoded Info
    symbol = db.Column(db.String(100), nullable=False)
    token = db.Column(db.String(50), nullable=True)
    underlying = db.Column(db.String(50), nullable=False)
    strike = db.Column(db.Float, nullable=False)
    expiry = db.Column(db.String(20), nullable=False)
    opt_type = db.Column(db.String(10), nullable=False) # CE/PE
    lot_size = db.Column(db.Integer, nullable=False)
    instrument_type = db.Column(db.String(20), nullable=False) # OPTIDX / OPTSTK

    # Pricing Info
    entry_price = db.Column(db.Float, nullable=False) # Parsed from tip
    entry_ltp = db.Column(db.Float, nullable=False) # Live price when saved
    
    # Trade Management
    target_price = db.Column(db.Float, nullable=True)
    stop_loss = db.Column(db.Float, nullable=True)
    exit_price = db.Column(db.Float, nullable=True)
    
    # "OBSERVER" for paper trades, "TRADED" for real trades
    mode = db.Column(db.String(20), default="OBSERVER") # OBSERVER or TRADED
    notes = db.Column(db.Text, nullable=True)
    
    # Status
    status = db.Column(db.String(20), default='OPEN') # OPEN, TARGET_HIT, SL_HIT, MANUAL_EXIT, EXPIRED

    def to_dict(self):
        # Calculate analytics dynamically
        expected_profit = None
        if self.target_price and self.entry_price:
            expected_profit = round((self.target_price - self.entry_price) * self.lot_size, 2)
            
        expected_loss = None
        if self.stop_loss and self.entry_price:
            expected_loss = round((self.entry_price - self.stop_loss) * self.lot_size, 2)
            
        rr_ratio = None
        if expected_profit and expected_loss and expected_loss > 0:
            rr_ratio = round(expected_profit / expected_loss, 2)

        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'symbol': self.symbol,
            'token': self.token,
            'underlying': self.underlying,
            'strike': self.strike,
            'expiry': self.expiry,
            'opt_type': self.opt_type,
            'lot_size': self.lot_size,
            'instrument_type': self.instrument_type,
            'entry_price': self.entry_price,
            "entry_ltp": self.entry_ltp,
            "target_price": self.target_price,
            "stop_loss": self.stop_loss,
            "exit_price": self.exit_price,
            "mode": self.mode,
            "status": self.status,
            "notes": self.notes,
            'expected_profit': expected_profit,
            'expected_loss': expected_loss,
            'rr_ratio': rr_ratio
        }

class PrevCloseCache(db.Model):
    __tablename__ = 'prev_close_cache'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(50), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    prev_close = db.Column(db.Float, nullable=False)
    
    # Ensure token + date is unique
    __table_args__ = (db.UniqueConstraint('token', 'date', name='uq_token_date'),)

class AccessLog(db.Model):
    __tablename__ = 'access_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), nullable=False) # 'admin' or 'guest'
    endpoint = db.Column(db.String(200), nullable=False)
    user_agent = db.Column(db.String(500))

class InstrumentCache(db.Model):
    """Stores filtered F&O option instruments from Angel One's ScripMaster.
    Refreshed daily on weekdays at 9:15 AM IST via APScheduler."""
    __tablename__ = 'instrument_cache'
    id = db.Column(db.Integer, primary_key=True)
    cache_date = db.Column(db.Date, nullable=False, index=True)
    
    # Core instrument fields
    token = db.Column(db.String(50), nullable=False)
    symbol = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    expiry = db.Column(db.String(20), nullable=False)
    strike = db.Column(db.String(50), nullable=False)  # Raw string, converted later
    lotsize = db.Column(db.String(20), nullable=False)
    instrumenttype = db.Column(db.String(20), nullable=False)
    exch_seg = db.Column(db.String(10), nullable=False)
    tick_size = db.Column(db.String(20), nullable=True)

