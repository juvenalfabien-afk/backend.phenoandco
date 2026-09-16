from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Optional
import csv
import io

from .config import OPENING_HOURS, SLOT_MINUTES, CAPACITY_PER_SLOT, SERVICES
from .db import init_db, db, row_to_dict
from .models import ClientCreate, AppointmentCreate, AppointmentPatch, ClosureCreate
from .utils import norm_text, norm_phone, hhmm_to_minutes, minutes_to_hhmm, new_id

app = FastAPI(
    title="PHENO&CO Backend",
    version="0.3.0",
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
        "version": "0.3.0",
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


def _to_int(value):
    try:
        return int(float(str(value or "0").strip() or 0))
    except (ValueError, TypeError):
        return 0

def _clean_id(value):
    value = str(value or "").strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value

@app.post(
    "/api/admin/import-clients",
    summary="Importer la base clients CSV",
    description=(
        "Importe / met à jour la base maître PHENO&CO depuis un fichier CSV. "
        "Route temporaire de migration : à retirer ou protéger avant la production."
    ),
)
async def import_clients_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Le fichier doit être un CSV.")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV trop volumineux (maximum 5 Mo).")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "Le CSV doit être encodé en UTF-8.")

    reader = csv.DictReader(io.StringIO(text))
    required = {
        "master_id", "source", "statut_rapprochement", "bookly_id", "hbc_id",
        "nom_complet", "prenom", "nom", "telephone", "email",
        "dernier_rendez_vous", "total_rendez_vous",
    }
    headers = set(reader.fieldnames or [])
    missing = sorted(required - headers)
    if missing:
        raise HTTPException(400, "Colonnes manquantes : " + ", ".join(missing))

    imported = 0
    skipped = 0
    skipped_examples = []

    with db() as con:
        for line_no, r in enumerate(reader, start=2):
            master_id = _clean_id(r.get("master_id"))
            bookly_id = _clean_id(r.get("bookly_id"))
            hbc_id = _clean_id(r.get("hbc_id"))

            client_id = bookly_id or (f"HBC-{hbc_id}" if hbc_id else master_id)
            if not client_id:
                skipped += 1
                if len(skipped_examples) < 5:
                    skipped_examples.append({"line": line_no, "reason": "aucun identifiant"})
                continue

            con.execute(
                """INSERT INTO clients
                   (id,bookly_id,hbc_id,name,first_name,last_name,phone,email,
                    last_visit,visits,source,match_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     bookly_id=excluded.bookly_id,
                     hbc_id=excluded.hbc_id,
                     name=excluded.name,
                     first_name=excluded.first_name,
                     last_name=excluded.last_name,
                     phone=excluded.phone,
                     email=excluded.email,
                     last_visit=excluded.last_visit,
                     visits=excluded.visits,
                     source=excluded.source,
                     match_status=excluded.match_status,
                     updated_at=CURRENT_TIMESTAMP
                """,
                (
                    client_id,
                    bookly_id or None,
                    hbc_id or None,
                    str(r.get("nom_complet") or "").strip(),
                    str(r.get("prenom") or "").strip(),
                    str(r.get("nom") or "").strip(),
                    str(r.get("telephone") or "").strip(),
                    str(r.get("email") or "").strip(),
                    str(r.get("dernier_rendez_vous") or "").strip() or None,
                    _to_int(r.get("total_rendez_vous")),
                    str(r.get("source") or "").strip(),
                    str(r.get("statut_rapprochement") or "").strip(),
                ),
            )
            imported += 1

        total = con.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]

    return {
        "ok": True,
        "file": file.filename,
        "imported_or_updated": imported,
        "skipped": skipped,
        "clients_in_database": total,
        "skipped_examples": skipped_examples,
        "message": "Import terminé."
    }

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

    with db() as con:
        total = con.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]

    return {"count": len(rows_out), "total": total, "items": rows_out}

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
