"""Lance les étapes du pipeline depuis l'API (pour l'interface graphique).

Une seule tâche à la fois. Chaque étape est le script CLI correspondant, exécuté dans un sous-processus :
l'interface affiche donc exactement ce que tu verrais dans le terminal.

    POST /pipeline/{step}   step = collect | features | clustering | train | rebuild
    POST /pipeline/cancel
    GET  /pipeline/status
    GET  /pipeline/logs?since=N
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).parent
MAX_LINES = 5000

# étape -> liste de commandes exécutées l'une après l'autre (arrêt à la première erreur)
STEPS: dict[str, list[list[str]]] = {
    "collect": [["collect_labels.py", "--all"]],
    "features": [["features.py", "--offline"]],
    "clustering": [["clustering.py"]],
    "train": [["classifier.py"]],
    # tout sauf la collecte (qui consomme le quota Etherscan)
    "rebuild": [["features.py", "--offline"], ["clustering.py"], ["classifier.py"]],
}
LABELS = {
    "collect": "Collecte des transactions",
    "features": "Calcul des features",
    "clustering": "Clustering",
    "train": "Entraînement du modèle",
    "rebuild": "Features + clustering + entraînement",
}

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_lock = threading.Lock()
_state: dict = {"state": "idle", "step": None, "label": None, "started_at": None,
                "finished_at": None, "returncode": None}
_lines: list[str] = []
_dropped = 0  # lignes supprimées en tête quand MAX_LINES est dépassé
_proc: subprocess.Popen | None = None
_cancel = False


def _log(line: str) -> None:
    global _dropped
    _lines.append(line)
    if len(_lines) > MAX_LINES:
        del _lines[: len(_lines) - MAX_LINES]
        _dropped += 1


def _run(step: str) -> None:
    global _proc
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    code = 0
    for cmd in STEPS[step]:
        _log(f"$ python {' '.join(cmd)}")
        _proc = subprocess.Popen([sys.executable, *cmd], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for raw in _proc.stdout:
            # les barres de progression écrivent avec \r : on garde la dernière version de la ligne
            _log(raw.rstrip("\r\n").split("\r")[-1])
        code = _proc.wait()
        if code != 0 or _cancel:
            break
    with _lock:
        _state.update(finished_at=time.time(), returncode=code,
                      state="cancelled" if _cancel else ("done" if code == 0 else "failed"))
        _proc = None
    _log({"cancelled": "-- annulé --", "done": "-- terminé --", "failed": f"-- échec (code {code}) --"}[_state["state"]])


@router.get("/steps")
def steps():
    return [{"step": s, "label": LABELS[s]} for s in STEPS]


@router.get("/status")
def status():
    with _lock:
        return {**_state, "lines_total": _dropped + len(_lines)}


@router.get("/logs")
def logs(since: int = 0):
    """Lignes à partir de l'index global `since` ; renvoyer `next` comme `since` au prochain appel."""
    with _lock:
        total = _dropped + len(_lines)
        start = max(since, _dropped)
        return {"lines": _lines[start - _dropped:], "next": total}


@router.post("/cancel")
def cancel():
    global _cancel
    with _lock:
        if _state["state"] != "running" or _proc is None:
            raise HTTPException(status_code=409, detail="Aucune tâche en cours.")
        _cancel = True
        _proc.terminate()
    return {"cancelling": True}


@router.post("/{step}")
def start(step: str):
    global _cancel, _dropped
    if step not in STEPS:
        raise HTTPException(status_code=404, detail=f"Étape inconnue : {step}. Choix : {', '.join(STEPS)}")
    if step == "collect" and not os.getenv("ETHERSCAN_API_KEY"):
        raise HTTPException(status_code=400, detail="ETHERSCAN_API_KEY manquante dans .env : collecte impossible.")
    with _lock:
        if _state["state"] == "running":
            raise HTTPException(status_code=409, detail=f"Une tâche est déjà en cours : {_state['label']}.")
        _cancel = False
        _lines.clear()
        _dropped = 0
        _state.update(state="running", step=step, label=LABELS[step], started_at=time.time(),
                      finished_at=None, returncode=None)
    threading.Thread(target=_run, args=(step,), daemon=True).start()
    return {"started": step}
