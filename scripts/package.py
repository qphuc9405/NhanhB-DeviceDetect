from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
root=Path(__file__).resolve().parents[1]
out=root.parent/'output/WiFi_Device_Sherlock_Source.zip'
ignored={'.venv','node_modules','__pycache__','.pytest_cache','.git','build','runtime','results'}
with ZipFile(out,'w',ZIP_DEFLATED) as z:
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if not p.is_file() or any(x in ignored for x in rel.parts) or p.name in ('sdkconfig','sdkconfig.old','.env'):continue
        z.write(p,'wifi-device-sherlock/'+str(rel))
print(out)
