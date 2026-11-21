import json,os
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from serial.tools import list_ports
from research.collector import ProbeService
from research.dashboard import DashboardConfig
from research.detectors import ProbeConfig
from backend.app.probe_api import router,configure
ROOT=Path(__file__).resolve().parents[2]
load_dotenv(ROOT/'.env')
def rooted(value):
    p=Path(value);return p if p.is_absolute() else ROOT/p
svc=None
@asynccontextmanager
async def lifespan(app):
    global svc
    cfg_path=rooted(os.getenv('WIFI_PROBE_CONFIG','configs/probe.json'))
    cfg=ProbeConfig(**json.loads(cfg_path.read_text()))
    dashboard_path = os.getenv('WIFI_DASHBOARD_CONFIG')
    dashboard = DashboardConfig.model_validate_json(rooted(dashboard_path).read_text()) if dashboard_path else DashboardConfig()
    svc=ProbeService(rooted(os.getenv('WIFI_PROBE_DATA_DIR','data/runtime')),cfg,dashboard)
    configure(svc,cfg_path)
    yield
    await svc.stop();svc.store.close()
app=FastAPI(title='WiFi Device Detection — Sherlock adaptation',version='1.1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173','http://localhost:8000','http://127.0.0.1:8000'],allow_methods=['GET','POST','PUT'],allow_headers=['Content-Type'])
app.include_router(router)
@app.get('/api/ports')
async def ports():return [dict(device=p.device,description=p.description) for p in list_ports.comports()]
@app.get('/api/health')
async def health():return dict(ok=True,scope='probe-only',algorithm='Sherlock adaptation')
if (ROOT/'frontend/dist').is_dir():app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='dashboard')
