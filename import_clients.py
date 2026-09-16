import csv
import sys
from pathlib import Path

from app.db import init_db, db

def to_int(value):
    try:
        return int(str(value or "0").strip() or 0)
    except ValueError:
        return 0

def main(path):
    init_db()
    src = Path(path)
    if not src.exists():
        raise SystemExit(f"Fichier introuvable : {src}")

    with src.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    count = 0
    with db() as con:
        for r in rows:
            bookly_id = (r.get("bookly_id") or "").strip()
            hbc_id = (r.get("hbc_id") or "").strip()
            client_id = bookly_id or (f"HBC-{hbc_id}" if hbc_id else (r.get("master_id") or "").strip())
            if not client_id:
                continue

            con.execute(
                """INSERT INTO clients
                   (id,bookly_id,hbc_id,name,first_name,last_name,phone,email,last_visit,visits,source,match_status)
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
                    (r.get("nom_complet") or "").strip(),
                    (r.get("prenom") or "").strip(),
                    (r.get("nom") or "").strip(),
                    (r.get("telephone") or "").strip(),
                    (r.get("email") or "").strip(),
                    (r.get("dernier_rendez_vous") or "").strip() or None,
                    to_int(r.get("total_rendez_vous")),
                    (r.get("source") or "").strip(),
                    (r.get("statut_rapprochement") or "").strip(),
                )
            )
            count += 1

    print(f"{count} clients importés / mis à jour.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python import_clients.py "/chemin/vers/BASE_MAITRE_CLIENTS_PHENO.csv"')
    main(sys.argv[1])
