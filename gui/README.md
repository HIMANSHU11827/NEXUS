# NEXUS GUI

React 19 + Vite frontend for the NEXUS AI visual control surface.

## Run

Preferred project entrypoint:

```powershell
python -m nexus --gui
```

This starts the `gui.api:app` FastAPI backend on `127.0.0.1:8000` and the Vite dev server on `127.0.0.1:5173`.

Manual development:

```powershell
npm install
python -m uvicorn gui.api:app --host 127.0.0.1 --port 8000
npm run dev
```

## Verify

```powershell
npm run build
```
