from fastapi import FastAPI
from app.routers import exam 
# from app.routers import resources # Hold on to this for now, we will add it later

app = FastAPI(title="BrAInBox AI Service")

app.include_router(exam.router)
# app.include_router(resources.router)

@app.get("/")
def health():
    return {"status": "ok"}