from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Tip(db.Model):
    __tablename__ = 'decoded_tips'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Decoded Info
    symbol = db.Column(db.String(50), nullable=False)
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
    mode = db.Column(db.String(20), default='OBSERVER') # OBSERVER or TRADED
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
            'underlying': self.underlying,
            'strike': self.strike,
            'expiry': self.expiry,
            'opt_type': self.opt_type,
            'lot_size': self.lot_size,
            'instrument_type': self.instrument_type,
            'entry_price': self.entry_price,
            'entry_ltp': self.entry_ltp,
            'target_price': self.target_price,
            'stop_loss': self.stop_loss,
            'mode': self.mode,
            'notes': self.notes,
            'status': self.status,
            'expected_profit': expected_profit,
            'expected_loss': expected_loss,
            'rr_ratio': rr_ratio
        }
