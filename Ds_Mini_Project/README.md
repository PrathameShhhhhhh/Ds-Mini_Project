Student DB Management - Web Frontend

This workspace contains a CLI-based Student DB management tool in `main.py` and a small Flask web frontend under `webapp/`.

Quick start (macOS / zsh):

1. Create a virtual env and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the web app

```bash
cd Ds_Mini_Project/webapp
FLASK_APP=app.py FLASK_ENV=development flask run
```

Notes:
- The web app reuses the existing `Storage` and `StudentDB` classes from `main.py`.
- If you'd like PDF export, install `reportlab` (already in requirements but optional).
