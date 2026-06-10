# Quickstart: Living World RPG Simulation

## Backend

1. Open a terminal in the repository root.
2. Change into the backend directory.
3. Install Python dependencies.
4. Start the API server on port 8000.

```powershell
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Frontend

1. Open a second terminal in the repository root.
2. Change into the frontend directory.
3. Install Node dependencies.
4. Start the Vite dev server.

```powershell
cd frontend
npm install
npm run dev
```

## Demo Checks

- Confirm the browser shows a canvas-based renderer and a basic HUD.
- Confirm the frontend polls the backend every 500ms.
- Confirm the backend returns a render payload even when the world is empty.
- Confirm local conversation and world-tick endpoints are reachable before
  adding deeper simulation behavior.