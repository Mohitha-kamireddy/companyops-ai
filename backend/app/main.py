from fastapi import FastAPI

app = FastAPI(title="CompanyOps AI")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
