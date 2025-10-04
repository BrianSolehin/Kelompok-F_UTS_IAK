from flask import Flask
from flask_cors import CORS
from orders import orders_bp

app = Flask(__name__)
app.secret_key = "retail-secret-key"  # wajib untuk session
CORS(app)

# register blueprint
app.register_blueprint(orders_bp, url_prefix="/api/orders")

@app.get("/")
def index():
    return {"service": "retail", "status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
