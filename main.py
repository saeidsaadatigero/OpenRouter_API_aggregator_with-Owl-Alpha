# main.py
import os
from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import engine, get_db
from services.openrouter_service import OpenRouterCodingService

# Build tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="OpenRouter Studio Core")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
coder_service = OpenRouterCodingService()

@app.get("/", response_class=HTMLResponse)
async def index_view(request: Request, db: Session = Depends(get_db)):
    history = db.query(models.GenerationHistory).order_by(models.GenerationHistory.created_at.desc()).all()
    return templates.TemplateResponse("index.html", {"request": request, "history": history})

@app.post("/api/generate")
async def handle_generation(
    prompt: str = Form(...),
    filename: str = Form(...),
    db: Session = Depends(get_db)
):
    if not prompt.strip() or not filename.strip():
        raise HTTPException(status_code=400, detail="Required fields are empty.")
    try:
        raw_code = coder_service.generate_code(prompt=prompt)
        
        # Save exact module file locally
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(raw_code)
            
        history_entry = models.GenerationHistory(
            prompt=prompt,
            generated_code=raw_code,
            filename=filename
        )
        db.add(history_entry)
        db.commit()
        db.refresh(history_entry)
        
        return {
            "id": history_entry.id,
            "prompt": history_entry.prompt,
            "filename": history_entry.filename,
            "generated_code": history_entry.generated_code,
            "created_at": history_entry.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"detail": str(e)})
