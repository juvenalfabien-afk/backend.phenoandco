# PHENO&CO — Backend Python

Backend de travail destiné à relier :
- le site public PHENO&CO,
- le dashboard admin,
- une base centrale.

## Stack
- Python
- FastAPI
- SQLite en développement
- PostgreSQL conseillé en production

## Démarrage

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8787
```

Puis ouvrir :
- API : http://127.0.0.1:8787
- Documentation interactive : http://127.0.0.1:8787/docs
- Documentation alternative : http://127.0.0.1:8787/redoc

## Import des clients réels

Ne pas mettre le CSV clients dans un dépôt GitHub public.

Placer le fichier maître localement puis lancer :

```bash
python import_clients.py "/chemin/vers/BASE_MAITRE_CLIENTS_PHENO.csv"
```

## Ce que le backend gère déjà

- santé du serveur
- clients : recherche / détail / création
- rendez-vous : liste / création / modification / annulation
- disponibilité par date
- 2 places par créneau
- créneaux de 30 minutes
- horaires habituels
- fermetures / exceptions
- prestations
- validation anti double-réservation simple
- CORS prêt pour site + dashboard
- documentation automatique FastAPI

## À faire avant production

- PostgreSQL
- authentification admin
- rôles et permissions
- vraie politique CORS
- logs
- sauvegardes
- anti-spam / rate limiting
- validation RGPD
- emails / SMS
- tests automatiques
