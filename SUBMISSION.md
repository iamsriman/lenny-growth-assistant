# Lenny Growth Assistant - Final Submission

## ✅ Status: COMPLETE & WORKING

### Demo
- **Local**: Run following README.md instructions
- **Transcripts**: 10 real Lenny's Podcast episodes
- **Chunks**: 853 total (embedded with nomic-embed-text)
- **Features**: Grounded Q&A, citations, 4 artifact types, streaming

### GitHub Repository
https://github.com/YOUR-USERNAME/lenny-growth-assistant

### Key Files
- **Backend**: FastAPI + SQLAlchemy + RAG pipeline
- **Frontend**: React + Vite + streaming chat UI
- **Data**: 10 real transcripts from Lenny's Podcast
- **Deployment**: Ready for Render/Railway with env vars

### How to Run Locally
\\\ash
# Terminal 1: Backend
cd backend
="sqlite:///D:/lga.db"
="ollama"
uvicorn app.main:app --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: Ollama (if not running)
ollama serve
\\\

Then open: http://localhost:5173

### Test Questions
- "What predicts retention?"
- "How should we think about pricing?"
- "What are growth loops?"

All return grounded answers with citations from transcripts.

### Architecture
- **RAG**: Hybrid BM25 + dense embeddings (0.62 * cosine + 0.38 * BM25)
- **Router**: Stage 1 regex + Stage 2 LLM classifier
- **Skills**: Grounded answer, Ship 30 essay, artifact generation
- **Security**: Bleach + DOMPurify + CSP + iframe sandbox

### Next Steps (Optional)
Deploy to Render/Railway/Vercel using environment variables for:
- Anthropic API (LLM)
- OpenAI API (embeddings)
- Supabase/Railway Postgres (database)
