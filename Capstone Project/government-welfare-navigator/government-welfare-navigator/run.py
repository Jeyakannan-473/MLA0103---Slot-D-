import os

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    # Convenience for first run: create tables if missing (safe to repeat).
    db.create_all()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
