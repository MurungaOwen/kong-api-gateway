import socket

from fastapi import FastAPI, Request

app = FastAPI(title="product-api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/echo")
def echo(request: Request):
    """Returns the headers Kong forwarded, to see what the gateway adds."""
    return {"headers": dict(request.headers)}


@app.get("/quote")
def quote():
    return {"quote": "The best API is the one you can bill for."}


@app.get("/whoami")
def whoami():
    """Which replica answered? Call it repeatedly after `--scale product-api=3`."""
    return {"instance": socket.gethostname()}


@app.get("/report")
def report():
    """The 'expensive' endpoint: Kong bills it at 5 units per call."""
    return {"report": "quarterly-revenue", "rows": [{"quarter": f"Q{i}", "revenue": i * 1000} for i in range(1, 5)]}


@app.get("/translate")
def translate(text: str = "hello gateway"):
    """Stand-in for a heavier endpoint you might add from the dashboard's Endpoints tab."""
    return {"text": text, "translated": text[::-1]}
