import sys
import os
import json
from typing import List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Dict
import hashlib
import sqlite3

# Ensure imports resolve using absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db.setup import init_db, get_connection
from patterns.factory import FaultReportFactory
from patterns.strategy import DispatchEngine, NearestFirstStrategy, BestRatedFirstStrategy
from patterns.singleton import RatingManager
from ui.status_screen import fetch_job, advance_job_status
from ui.mechanic_dash import fetch_all_mechanics, fetch_job_history, fetch_analytics

app = FastAPI(title="FixKar Enterprise API")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(client_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle messages from client if needed
    except WebSocketDisconnect:
        manager.disconnect(client_id)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    zone: str
    vehicle_type: str

class MechanicRegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    zone: str
    skill: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UserUpdateRequest(BaseModel):
    name: str
    zone: str
    vehicle_type: str

class JobRequest(BaseModel):
    user_id: int
    zone: str
    vehicle_type: str
    problem_type: str
    detailed_address: str
    user_description: str
    strategy: str = "Nearest First"

class RatingRequest(BaseModel):
    job_id: int
    mechanic_id: int
    score: int

class AmountRequest(BaseModel):
    amount: float

@app.post("/api/register")
def register(req: RegisterRequest):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (name, email, password_hash, zone, vehicle_type) VALUES (?,?,?,?,?)",
                  (req.name, req.email, hash_password(req.password), req.zone, req.vehicle_type))
        user_id = c.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    conn.close()
    return {"id": user_id, "name": req.name, "email": req.email, "zone": req.zone, "vehicle_type": req.vehicle_type}

@app.post("/api/login")
def login(req: LoginRequest):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, email, zone, vehicle_type FROM users WHERE email=? AND password_hash=?",
              (req.email, hash_password(req.password)))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return dict(user)

@app.post("/api/mechanics/register")
def register_mechanic(req: MechanicRegisterRequest):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO mechanics (name, email, password_hash, zone, skill) VALUES (?,?,?,?,?)",
                  (req.name, req.email, hash_password(req.password), req.zone, req.skill))
        mechanic_id = c.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    conn.close()
    return {"id": mechanic_id, "name": req.name, "email": req.email, "zone": req.zone, "skill": req.skill}

@app.post("/api/mechanics/login")
def login_mechanic(req: LoginRequest):
    # Admin login check
    if req.email == "fixkar" and req.password == "fixkar87611":
        return {"id": 0, "name": "Admin", "is_admin": True}

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, email, zone, skill FROM mechanics WHERE email=? AND password_hash=?",
              (req.email, hash_password(req.password)))
    mechanic = c.fetchone()
    conn.close()
    if not mechanic:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return dict(mechanic)

@app.put("/api/users/{user_id}")
def update_user(user_id: int, req: UserUpdateRequest):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET name=?, zone=?, vehicle_type=? WHERE id=?", 
              (req.name, req.zone, req.vehicle_type, user_id))
    conn.commit()
    conn.close()
    return {"message": "User updated successfully"}

@app.get("/api/users/{user_id}/stats")
def get_user_stats(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=?", (user_id,))
    total_jobs = c.fetchone()[0]
    conn.close()
    return {"total_jobs": total_jobs}

def load_mechanics():
    from models.models import Mechanic
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mechanics WHERE is_free=1")
    rows = c.fetchall()
    conn.close()
    return [Mechanic(
        id=r["id"], name=r["name"], skill=r["skill"],
        zone=r["zone"], rating=r["rating"],
        is_free=bool(r["is_free"]), total_jobs=r["total_jobs"]
    ) for r in rows]

def save_job(job, mechanic_id=None, offered_mechanic_id=None, ranked_mechanics=None):
    conn = get_connection()
    c = conn.cursor()
    ranked_str = json.dumps(ranked_mechanics) if ranked_mechanics else "[]"
    c.execute(
        """INSERT INTO jobs
           (user_id, mechanic_id, problem_type, vehicle_type, urgency,
            required_skill, status, user_zone, detailed_address, user_description, offered_mechanic_id, ranked_mechanics)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job.user_id, mechanic_id, job.problem_type, job.vehicle_type,
         job.urgency, job.required_skill, job.status, job.user_zone, job.detailed_address, job.user_description, offered_mechanic_id, ranked_str)
    )
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id

@app.post("/api/jobs")
async def create_job(req: JobRequest):
    try:
        job = FaultReportFactory.create(
            req.problem_type, req.vehicle_type, req.user_id, req.zone, 
            req.detailed_address, req.user_description
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    strategy = NearestFirstStrategy() if req.strategy == "Nearest First" else BestRatedFirstStrategy()
    engine = DispatchEngine(strategy)
    
    mechanics = load_mechanics()
    ranked = engine.rank_mechanics(mechanics, job)
    
    if not ranked:
        raise HTTPException(status_code=404, detail="No mechanics available for this problem right now.")
        
    ranked_ids = [m.id for m in ranked]
    first_choice = ranked_ids.pop(0)
    
    job.status = "Offered"
    
    job_id = save_job(job, offered_mechanic_id=first_choice, ranked_mechanics=ranked_ids)
    
    # Notify mechanic
    await manager.send_personal_message({"type": "new_offer", "job_id": job_id}, f"mechanic_{first_choice}")
    
    return {
        "job_id": job_id,
        "status": "Offered",
        "offered_to": first_choice
    }

@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT j.*, m.name as mechanic_name, m.rating as mechanic_rating, m.zone as mechanic_zone
        FROM jobs j
        LEFT JOIN mechanics m ON j.mechanic_id = m.id
        WHERE j.id = ?
    """, (job_id,))
    job = c.fetchone()
    conn.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(job)

@app.get("/api/mechanics/{mechanic_id}/offers")
def get_mechanic_offers(mechanic_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE status='Offered' AND offered_mechanic_id=?", (mechanic_id,))
    jobs = [dict(r) for r in c.fetchall()]
    conn.close()
    return jobs

@app.get("/api/mechanics/{mechanic_id}/active_jobs")
def get_mechanic_active_jobs(mechanic_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE status IN ('Assigned', 'In Progress') AND mechanic_id=?", (mechanic_id,))
    jobs = [dict(r) for r in c.fetchall()]
    conn.close()
    return jobs

@app.post("/api/jobs/{job_id}/accept")
async def accept_job(job_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()
    if not job or job['status'] != 'Offered':
        conn.close()
        raise HTTPException(status_code=400, detail="Job not available to accept")
    
    mechanic_id = job['offered_mechanic_id']
    c.execute("UPDATE jobs SET status='Assigned', mechanic_id=?, offered_mechanic_id=NULL WHERE id=?", (mechanic_id, job_id))
    c.execute("UPDATE mechanics SET is_free=0 WHERE id=?", (mechanic_id,))
    conn.commit()
    conn.close()
    
    # Notify user
    await manager.send_personal_message({"type": "job_update", "job_id": job_id, "status": "Assigned"}, f"user_{job['user_id']}")
    # Notify mechanic dashboard to refresh (move from offers to active)
    await manager.send_personal_message({"type": "mechanic_refresh"}, f"mechanic_{mechanic_id}")
    
    return {"message": "Job accepted"}

@app.post("/api/jobs/{job_id}/decline")
async def decline_job(job_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()
    if not job or job['status'] != 'Offered':
        conn.close()
        raise HTTPException(status_code=400, detail="Job not available to decline")
    
    ranked_mechanics = json.loads(job['ranked_mechanics']) if job['ranked_mechanics'] else []
    
    if ranked_mechanics:
        next_mechanic = ranked_mechanics.pop(0)
        c.execute("UPDATE jobs SET offered_mechanic_id=?, ranked_mechanics=? WHERE id=?", 
                  (next_mechanic, json.dumps(ranked_mechanics), job_id))
        # Notify next mechanic
        await manager.send_personal_message({"type": "new_offer", "job_id": job_id}, f"mechanic_{next_mechanic}")
    else:
        c.execute("UPDATE jobs SET status='Declined', offered_mechanic_id=NULL WHERE id=?", (job_id,))
        # Notify user of decline
        await manager.send_personal_message({"type": "job_update", "job_id": job_id, "status": "Declined"}, f"user_{job['user_id']}")
    
    conn.commit()
    conn.close()
    return {"message": "Job declined"}

@app.post("/api/jobs/{job_id}/complete")
async def complete_job(job_id: int, req: AmountRequest):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()
    if not job or job['status'] not in ('Assigned', 'In Progress'):
        conn.close()
        raise HTTPException(status_code=400, detail="Job cannot be completed")
        
    mechanic_id = job['mechanic_id']
    c.execute("UPDATE jobs SET status='Completed', amount=? WHERE id=?", (req.amount, job_id))
    c.execute("UPDATE mechanics SET is_free=1, total_jobs=total_jobs+1 WHERE id=?", (mechanic_id,))
    conn.commit()
    conn.close()
    
    # Notify user
    await manager.send_personal_message({"type": "job_update", "job_id": job_id, "status": "Completed"}, f"user_{job['user_id']}")
    # Notify mechanic dashboard to refresh
    await manager.send_personal_message({"type": "mechanic_refresh"}, f"mechanic_{mechanic_id}")
    
    return {"message": "Job completed"}

@app.get("/api/mechanics/{mechanic_id}/profile")
def get_mechanic_profile(mechanic_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, email, zone, skill, rating, total_jobs FROM mechanics WHERE id=?", (mechanic_id,))
    mech = c.fetchone()
    conn.close()
    if not mech:
        raise HTTPException(status_code=404, detail="Mechanic not found")
    return dict(mech)

@app.post("/api/ratings")
async def submit_rating(req: RatingRequest):
    rm = RatingManager()
    rm.add_rating(req.job_id, req.mechanic_id, req.score)
    # Notify mechanic that their rating was updated
    await manager.send_personal_message({"type": "mechanic_refresh"}, f"mechanic_{req.mechanic_id}")
    return {"message": "Rating submitted"}

@app.get("/api/mechanics")
def get_mechanics():
    return fetch_all_mechanics()

@app.post("/api/mechanics/{mechanic_id}/delete")
def delete_mechanic(mechanic_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM jobs WHERE mechanic_id=? OR offered_mechanic_id=?", (mechanic_id, mechanic_id))
    c.execute("DELETE FROM ratings WHERE mechanic_id=?", (mechanic_id,))
    c.execute("DELETE FROM mechanics WHERE id=?", (mechanic_id,))
    conn.commit()
    conn.close()
    return {"message": "Mechanic deleted"}

@app.get("/api/analytics")
def get_analytics():
    return fetch_analytics()

@app.get("/api/history")
def get_history():
    return fetch_job_history()

static_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
app.mount("/static", StaticFiles(directory=static_path), name="static")

@app.get("/")
def serve_frontend():
    index_path = os.path.join(static_path, "index.html")
    return FileResponse(index_path)

if __name__ == "__main__":
    import uvicorn
    # Create static dir if it doesn't exist
    os.makedirs(static_path, exist_ok=True)
    # Get port from environment or default to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
