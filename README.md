<img width="1917" height="914" alt="image" src="https://github.com/user-attachments/assets/72d4f627-f7a3-4e9d-925e-18088010f96f" />

<div align="center">

# 🌌 OWL Studio — Intelligence Terminal
### *Next-Gen Asynchronous AI Chat & Code Generation Engine*

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-C11921?style=for-the-badge&logo=python&logoColor=white)](https://www.sqlalchemy.org)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-494949?style=for-the-badge&logo=gunicorn&logoColor=white)](https://www.uvicorn.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-Owl--Alpha-7C3AED?style=for-the-badge&logo=openai&logoColor=white)](https://openrouter.ai)

<p align="center">
  A high-performance, asynchronous AI chat studio powered by OpenRouter. Featuring real-time background task processing with polling, persistent multi-session chat history, path-traversal security sandboxing, and a cyberpunk dark-mode terminal interface.
</p>

[✨ Core Features](#-core-features) • [🏗️ Architecture](#-architecture-blueprint) • [🚀 Quickstart](#-quickstart-pipeline) • [📁 Project Structure](#-system-directory-layout)

---
</div>

## ✨ Core Features

* **💬 Multi-Session Chat Engine**: Create, rename, and delete chat sessions with persistent message history stored in SQLite via SQLAlchemy ORM.
* **⚡ Background Task Processing**: Non-blocking LLM requests via FastAPI `BackgroundTasks` with frontend polling for real-time response delivery.
* **🔄 Message Retry & Copy**: Retry failed responses and copy user messages or assistant code blocks to clipboard instantly.
* **🛡️ Secure Workspace Sandboxing**: Structural filename validation (`..`, `/`, `~` mitigation) with target base directory lockouts preventing path traversal attacks.
* **📊 Persistent Audit Trail**: Full conversation history, session metadata, and message status tracking (`pending` → `done`/`error`) in relational database.
* **🎨 Cyberpunk Terminal UI**: Immersive dark-mode interface with syntax-highlighted code blocks, typing wave-bar animations, and glassmorphism effects.

---

## 🏗️ Architecture Blueprint

Decoupled three-tier architecture separating routing, business logic, and data persistence: