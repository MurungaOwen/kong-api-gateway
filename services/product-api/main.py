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
