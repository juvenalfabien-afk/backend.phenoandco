from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Optional

from .config import OPENING_HOURS, SLOT_MINUTES, CAPACITY_PER_SLOT, SERVICES
from .db import init_db, db, row_to_dict
from .models import ClientCreate, AppointmentCreate, AppointmentPatch, ClosureCreate
from .utils import norm_text, norm_phone, hhmm_to_minutes, minutes_to_hhmm, new_id

app = FastAPI(
    title="PHENO&CO Backend",
    version="0.2.0",
    description="API commune au site de réservation et au dashboard PHENO&CO."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

def availability_for_date(date_str: str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Date invalide, format attendu YYYY-MM-DD")

    hours = OPENING_HOURS.get(d.weekday())
    if not hours:
        return []

    start = hhmm_to_minutes(hours[0])
    end = hhmm_to_minutes(hours[1])

    with db() as con:
        closures = con.execute(
            "SELECT date,time FROM closures WHERE date=?",
            (date_str,)
        ).fetchall()
        appointments = con.execute(
            """SELECT time,seat,status FROM appointments
               WHERE date=? AND status!='cancelled'""",
            (date_str,)
        ).fetchall()

    closure_times = {r["time"] for r in closures if r["time"]}
    whole_day_closed = any(r["time"] is None for r in closures)

    out = []
    for minute in range(start, end, SLOT_MINUTES):
        time = minutes_to_hhmm(minute)
        booked = [r["seat"] for r in appointments if r["time"] == time]
        closed = whole_day_closed or time in closure_times
        available = 0 if closed else max(0, CAPACITY_PER_SLOT - len(booked))
        out.append({
            "time": time,
            "capacity": CAPACITY_PER_SLOT,
            "booked": len(booked),
            "available": available,
            "closed": closed,
        })
    return out

@app.get("/")
def root():
    return {
        "name": "PHENO&CO Backend",
        "version": "0.2.0",
        "docs": "/docs",
        "status": "ok"
    }

@app.get("/api/health")
def health():
    with db() as con:
        clients = con.execute("SELECT COUNT(*) n FROM clients").fetchone()["n"]
        appointments = con.execute("SELECT COUNT(*) n FROM appointments").fetchone()["n"]
    return {"ok": True, "clients": clients, "appointments": appointments}

@app.get("/api/settings")
def settings():
    return {
        "slot_minutes": SLOT_MINUTES,
        "capacity_per_slot": CAPACITY_PER_SLOT,
        "opening_hours": OPENING_HOURS,
    }

@app.get("/api/services")
def services():
    return SERVICES

@app.get("/api/availability")
def availability(date: str):
    return {"date": date, "slots": availability_for_date(date)}

@app.get("/api/clients")
def clients(search: str = "", limit: int = Query(100, ge=1, le=500)):
    with db() as con:
        rows = con.execute("SELECT * FROM clients ORDER BY name LIMIT 5000").fetchall()

    if search:
        q = norm_text(search)
        qp = norm_phone(search)
        filtered = []
        for row in rows:
            item = row_to_dict(row)
            hay = norm_text(" ".join([
                item["name"], item["first_name"], item["last_name"], item["email"]
            ]))
            phone = norm_phone(item["phone"])
            if (q and q in hay) or (len(qp) >= 2 and qp in phone):
                filtered.append(item)
        rows_out = filtered[:limit]
    else:
        rows_out = [row_to_dict(r) for r in rows[:limit]]

    return {"count": len(rows_out), "items": rows_out}

@app.get("/api/clients/{client_id}")
def client_detail(client_id: str):
    with db() as con:
        row = con.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Client introuvable")
    return row_to_dict(row)

@app.post("/api/clients", status_code=201)
def create_client(payload: ClientCreate):
    client_id = new_id("C")
    with db() as con:
        con.execute(
            """INSERT INTO clients
               (id,name,first_name,last_name,phone,email,source,match_status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                client_id, payload.name, payload.first_name, payload.last_name,
                payload.phone, payload.email, "SITE", "Créé par API"
            )
        )
        row = con.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return row_to_dict(row)

@app.get("/api/appointments")
def appointments(date: Optional[str] = None):
    with db() as con:
        if date:
            rows = con.execute(
                "SELECT * FROM appointments WHERE date=? ORDER BY time,seat",
                (date,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM appointments ORDER BY date,time,seat"
            ).fetchall()
    return {"count": len(rows), "items": [row_to_dict(r) for r in rows]}

@app.post("/api/appointments", status_code=201)
def create_appointment(payload: AppointmentCreate):
    slots = availability_for_date(payload.date)
    slot = next((s for s in slots if s["time"] == payload.time), None)
    if not slot or slot["available"] < 1:
        raise HTTPException(409, "Créneau complet ou fermé")

    with db() as con:
        client = con.execute("SELECT id FROM clients WHERE id=?", (payload.client_id,)).fetchone()
        if not client:
            raise HTTPException(404, "Client introuvable")

        used = con.execute(
            """SELECT seat FROM appointments
               WHERE date=? AND time=? AND status!='cancelled'""",
            (payload.date, payload.time)
        ).fetchall()
        used_seats = {r["seat"] for r in used}

        seat = 0
        while seat in used_seats:
            seat += 1
        if seat >= CAPACITY_PER_SLOT:
            raise HTTPException(409, "Créneau complet")

        appointment_id = new_id("R")
        con.execute(
            """INSERT INTO appointments
               (id,client_id,date,time,seat,service,status,source,notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                appointment_id, payload.client_id, payload.date, payload.time,
                seat, payload.service, "confirmed", payload.source, payload.notes
            )
        )
        row = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    return row_to_dict(row)

@app.patch("/api/appointments/{appointment_id}")
def patch_appointment(appointment_id: str, payload: AppointmentPatch):
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "Aucune modification")

    allowed = {"date","time","service","status","notes"}
    changes = {k:v for k,v in changes.items() if k in allowed}

    with db() as con:
        row = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Rendez-vous introuvable")

        # Si date/heure change, vérifier la disponibilité cible.
        new_date = changes.get("date", row["date"])
        new_time = changes.get("time", row["time"])
        if new_date != row["date"] or new_time != row["time"]:
            slots = availability_for_date(new_date)
            slot = next((s for s in slots if s["time"] == new_time), None)
            if not slot or slot["available"] < 1:
                raise HTTPException(409, "Créneau cible complet ou fermé")

        cols = ", ".join([f"{k}=?" for k in changes.keys()])
        vals = list(changes.values()) + [appointment_id]
        con.execute(
            f"UPDATE appointments SET {cols}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            vals
        )
        out = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    return row_to_dict(out)

@app.delete("/api/appointments/{appointment_id}")
def cancel_appointment(appointment_id: str):
    with db() as con:
        row = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Rendez-vous introuvable")
        con.execute(
            "UPDATE appointments SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (appointment_id,)
        )
        out = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    return row_to_dict(out)

@app.get("/api/closures")
def closures():
    with db() as con:
        rows = con.execute("SELECT * FROM closures ORDER BY date,time").fetchall()
    return {"count": len(rows), "items": [row_to_dict(r) for r in rows]}

@app.post("/api/closures", status_code=201)
def create_closure(payload: ClosureCreate):
    with db() as con:
        cur = con.execute(
            "INSERT INTO closures(date,time,reason) VALUES (?,?,?)",
            (payload.date, payload.time, payload.reason)
        )
        row = con.execute("SELECT * FROM closures WHERE id=?", (cur.lastrowid,)).fetchone()
    return row_to_dict(row)

@app.delete("/api/closures/{closure_id}")
def delete_closure(closure_id: int):
    with db() as con:
        row = con.execute("SELECT * FROM closures WHERE id=?", (closure_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Fermeture introuvable")
        con.execute("DELETE FROM closures WHERE id=?", (closure_id,))
    return {"ok": True}
