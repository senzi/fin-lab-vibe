from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from finlab.data import build_dashboard, build_stock_snapshot


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/dashboard")
    def dashboard():
        period = request.args.get("period", "6mo")
        return jsonify(build_dashboard(period=period))

    @app.get("/api/stock/<symbol>")
    def stock(symbol: str):
        return jsonify(build_stock_snapshot(symbol))

    @app.get("/api/portfolio")
    def portfolio():
        return jsonify(
            {
                "enabled": False,
                "positions": [],
                "note": "Portfolio tracking is reserved for a future version.",
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050)
