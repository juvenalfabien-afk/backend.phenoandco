from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "phenoco.db"

SLOT_MINUTES = 30
CAPACITY_PER_SLOT = 2
TIMEZONE = "Europe/Paris"

OPENING_HOURS = {
    0: None,                # lundi
    1: ("10:00", "17:30"), # mardi
    2: ("12:00", "17:30"), # mercredi
    3: ("10:00", "17:30"), # jeudi
    4: ("10:00", "17:30"), # vendredi
    5: ("10:00", "17:30"), # samedi
    6: None,                # dimanche
}

SERVICES = [
    {"id": "coupe", "name": "Coupe", "duration": 30, "price_from": 25},
    {"id": "coupe-barbe", "name": "Coupe + barbe", "duration": 30, "price_from": 30},
    {"id": "barbe", "name": "Barbe", "duration": 30, "price_from": 10},
]
