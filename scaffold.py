# scaffold.py

import os

def create_scaffold():
    print("Initializing environment layout and scaffolding code layers...")

    # Define directories
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static/css", exist_ok=True)
    os.makedirs("services", exist_ok=True)

    # 1. DATABASE CONFIGURATION
    with open("database.py", "w", encoding="utf-8") as f:
        f.write('''# database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./openrouter_studio.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
''')

    # 2. SQLALCHEMY MODELS
    with open("models.py", "w", encoding="utf-8") as f:
        f.write('''# models.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from database import Base

class GenerationHistory(Base):
    __tablename__ = "generation_history"

    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(String(500), nullable=False)
    generated_code = Column(Text, nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
''')

    # 3. PYDANTIC SCHEMAS
    with open("schemas.py", "w", encoding="utf-8") as f:
        f.write('''# schemas.py
from pydantic import BaseModel
from datetime import datetime

class CodeRequest(BaseModel):
    prompt: str
    filename: str

class HistoryResponse(BaseModel):
    id: int
    prompt: str
    generated_code: str
    filename: str
    created_at: datetime

    class Config:
        from_attributes = True
''')

    # 4. UPDATED OPENROUTER SERVICE LAYER
    with open("services/openrouter_service.py", "w", encoding="utf-8") as f:
        f.write('''# services/openrouter_service.py
import os
from decouple import config
from openai import OpenAI

class OpenRouterCodingService:
    def __init__(self, model_name: str = "openrouter/owl-alpha") -> None:
        self.api_key: str = config("OPENROUTER_API_KEY", default="")
        self.base_url: str = "https://openrouter.ai/api/v1"
        self.model_name: str = model_name
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is missing from environment layout.")
            
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://localhost:8000",
                "X-OpenRouter-Title": "Agentic Studio Workspace"
            }
        )

    def generate_code(self, prompt: str) -> str:
        system_instruction = (
            "You are a Senior Python/AI Engineer. Output clean, robust, OOP-compliant code "
            "with strict type hints. Do NOT include markdown blocks like ```python or ```, "
            "do NOT include conversational explanations or prose text. Output ONLY valid, raw executable code."
        )
        
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content or ""
''')

    # 5. FASTAPI APPLICATION CORE
    with open("main.py", "w", encoding="utf-8") as f:
        f.write('''# main.py
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
''')

    # 6. PREMIUM DARK MODE FRONTEND (Tailwind + Custom Scrollbars)
    with open("templates/index.html", "w", encoding="utf-8") as f:
        f.write('''<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-950 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenRouter Agent Studio</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body class="h-full flex flex-col font-sans antialiased selection:bg-cyan-500 selection:text-slate-900">
    
    <header class="border-b border-slate-800 bg-slate-900/50 backdrop-blur px-6 py-4 flex items-center justify-between shadow-xl">
        <div class="flex items-center space-x-3">
            <div class="bg-gradient-to-tr from-cyan-500 to-blue-600 p-2 rounded-xl text-slate-900 shadow-lg shadow-cyan-500/20">
                <i class="fa-solid ba-brain text-xl font-black"></i>
            </div>
            <div>
                <h1 class="text-lg font-bold tracking-tight text-white">Agentic Code Studio</h1>
                <p class="text-xs text-slate-400">Powered by OpenRouter Owl-Alpha Engine</p>
            </div>
        </div>
        <div class="flex items-center space-x-2 bg-slate-950/60 border border-slate-800 px-3 py-1.5 rounded-lg text-xs font-mono text-cyan-400">
            <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse mr-1"></span> Engine Status: Production
        </div>
    </header>

    <main class="flex-1 flex overflow-hidden">
        <section class="w-1/3 border-r border-slate-800 p-6 flex flex-col justify-between bg-slate-900/20 overflow-y-auto">
            <form id="generationForm" class="space-y-6">
                <div>
                    <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Target Component Filepath</label>
                    <div class="relative">
                        <span class="absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500"><i class="fa-solid fa-file-code"></i></span>
                        <input type="text" id="filename" name="filename" required placeholder="e.g., trading/order_book.py"
                               class="w-full pl-10 pr-4 py-3 bg-slate-950/80 border border-slate-800 rounded-xl focus:outline-none focus:border-cyan-500 text-slate-200 placeholder-slate-600 transition font-mono text-sm shadow-inner">
                    </div>
                </div>
                <div>
                    <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Prompt Specification</label>
                    <textarea id="prompt" name="prompt" required rows="6" placeholder="Describe the structural OOP component you want to compile..."
                              class="w-full p-4 bg-slate-950/80 border border-slate-800 rounded-xl focus:outline-none focus:border-cyan-500 text-slate-200 placeholder-slate-600 transition text-sm shadow-inner resize-none"></textarea>
                </div>
                <button type="submit" id="submitBtn"
                        class="w-full bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold py-3.5 px-4 rounded-xl transition shadow-lg shadow-cyan-500/10 flex items-center justify-center space-x-2 group">
                    <span id="btnText">Compile Architecture</span>
                    <i id="btnIcon" class="fa-solid fa-bolt transition group-hover:scale-110"></i>
                </button>
            </form>

            <div id="loaderState" class="hidden mt-6 p-4 bg-slate-950/50 border border-cyan-500/20 rounded-xl items-center space-x-4 animate-pulse">
                <i class="fa-solid fa-circle-notch text-cyan-400 animate-spin text-xl"></i>
                <div class="text-xs font-mono text-slate-300">
                    <p class="font-bold text-cyan-400">Streaming Pipeline...</p>
                    <p class="text-slate-500">Invoking OpenRouter remote cluster models.</p>
                </div>
            </div>
        </section>

        <section class="flex-1 flex flex-col overflow-hidden bg-slate-950">
            <div class="border-b border-slate-800/80 bg-slate-900/10 px-6 py-3 flex items-center justify-between">
                <div class="text-xs font-mono text-slate-400 flex items-center space-x-2">
                    <i class="fa-solid fa-clock-history"></i> <span>Workspace Logs</span>
                </div>
                <button id="copyBtn" class="text-xs bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 px-3 py-1.5 rounded-lg transition flex items-center space-x-1">
                    <i class="fa-regular fa-copy"></i> <span>Copy Raw Buffer</span>
                </button>
            </div>

            <div class="flex-1 flex overflow-hidden">
                <div class="w-2/5 border-r border-slate-800/60 overflow-y-auto p-4 space-y-3" id="historyContainer">
                    {% for item in history %}
                    <div onclick="displayCode('{{ item.id }}')" id="card-{{ item.id }}"
                         class="history-card p-4 bg-slate-900/40 border border-slate-800/80 rounded-xl cursor-pointer hover:border-slate-700 transition relative group shadow-sm">
                        <div class="flex justify-between items-start mb-2">
                            <span class="text-xs font-mono text-cyan-400 truncate max-w-[180px]"><i class="fa-solid fa-file-invoice-dollar text-slate-500 mr-1"></i>{{ item.filename }}</span>
                            <span class="text-[10px] text-slate-500 font-mono">{{ item.created_at.strftime('%m/%d %H:%M') }}</span>
                        </div>
                        <p class="text-xs text-slate-300 line-clamp-2 pr-4 font-sans">{{ item.prompt }}</p>
                        <textarea class="hidden" id="raw-{{ item.id }}">{{ item.generated_code }}</textarea>
                    </div>
                    {% endfor %}
                </div>

                <div class="flex-1 bg-slate-950 p-6 overflow-y-auto">
                    <pre class="h-full"><code id="codeDisplay" class="text-sm font-mono text-emerald-400 leading-relaxed block whitespace-pre-wrap">Select an enterprise architecture workflow from the left trace stack or compile a new model to view logs.</code></pre>
                </div>
            </div>
        </section>
    </main>

    <script>
        const form = document.getElementById('generationForm');
        const submitBtn = document.getElementById('submitBtn');
        const loaderState = document.getElementById('loaderState');
        const historyContainer = document.getElementById('historyContainer');
        const codeDisplay = document.getElementById('codeDisplay');
        const copyBtn = document.getElementById('copyBtn');

        let currentActiveBuffer = "";

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            submitBtn.disabled = true;
            loaderState.classList.remove('hidden');
            loaderState.classList.add('flex');

            const formData = new FormData(form);
            try {
                const response = await fetch('/api/generate', { method: 'POST', body: formData });
                const data = await response.json();
                
                if (response.ok) {
                    // Update main panel
                    codeDisplay.textContent = data.generated_code;
                    currentActiveBuffer = data.generated_code;
                    
                    // Inject fresh card to sidebar pipeline stack
                    const freshCard = document.createElement('div');
                    freshCard.id = `card-${data.id}`;
                    freshCard.className = "history-card p-4 bg-slate-900/40 border border-cyan-500/40 rounded-xl cursor-pointer transition relative group shadow-sm";
                    freshCard.setAttribute('onclick', `displayCode('${data.id}')`);
                    freshCard.innerHTML = `
                        <div class="flex justify-between items-start mb-2">
                            <span class="text-xs font-mono text-cyan-400 truncate max-w-[180px]"><i class="fa-solid fa-file-invoice-dollar text-slate-500 mr-1"></i>\${data.filename}</span>
                            <span class="text-[10px] text-slate-500 font-mono">Just Now</span>
                        </div>
                        <p class="text-xs text-slate-300 line-clamp-2 pr-4 font-sans">\${data.prompt}</p>
                        <textarea class="hidden" id="raw-\${data.id}">\${data.generated_code}</textarea>
                    `;
                    historyContainer.insertBefore(freshCard, historyContainer.firstChild);
                    form.reset();
                } else {
                    alert("Error processing cluster request: " + data.detail);
                }
            } catch (err) {
                alert("Network partition timeout: " + err);
            } finally {
                submitBtn.disabled = false;
                loaderState.classList.add('hidden');
                loaderState.classList.remove('flex');
            }
        });

        function displayCode(id) {
            document.querySelectorAll('.history-card').forEach(c => c.classList.remove('border-cyan-500/50', 'bg-slate-900/80'));
            const selectedCard = document.getElementById(`card-\${id}`);
            if(selectedCard) selectedCard.classList.add('border-cyan-500/50', 'bg-slate-900/80');
            
            const rawCode = document.getElementById(`raw-\${id}`).value;
            codeDisplay.textContent = rawCode;
            currentActiveBuffer = rawCode;
        }

        copyBtn.addEventListener('click', () => {
            if(!currentActiveBuffer) return;
            navigator.clipboard.writeText(currentActiveBuffer);
            const origText = copyBtn.innerHTML;
            copyBtn.innerHTML = "<i class='fa-solid fa-check text-emerald-400'></i> <span class='text-emerald-400'>Copied!</span>";
            setTimeout(() => copyBtn.innerHTML = origText, 2000);
        });
    </script>
</body>
</html>
''')

    # 7. SCROLLBARS AND BRANDING CSS STYLE
    with open("static/css/style.css", "w", encoding="utf-8") as f:
        f.write('''/* Custom Premium Dark Scrollbars */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: #020617; /* Slate 950 */
}
::-webkit-scrollbar-thumb {
    background: #1e293b; /* Slate 800 */
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: #0ea5e9; /* Cyan 500 */
}
''')

    print("[SUCCESS] All architectural scaffolding entities deployed perfectly.")

if __name__ == "__main__":
    create_scaffold()