from fastapi import FastAPI

app = FastAPI(title="AI Football Predictor API")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ai-football-predictor-api",
    }
