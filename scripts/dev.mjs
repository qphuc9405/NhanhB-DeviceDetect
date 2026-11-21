import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=path.join(root,'.venv/bin/python');
const backend=spawn(python,['-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8000'],{cwd:root,stdio:'inherit'});
const ui=spawn(process.execPath,[path.join(root,'frontend/node_modules/vite/bin/vite.js')],{cwd:path.join(root,'frontend'),stdio:'inherit'});
let stopped=false;
function stop(code=0){if(stopped)return;stopped=true;backend.kill();ui.kill();setTimeout(()=>process.exit(code),300).unref();}
for(const p of [backend,ui]){p.on('error',e=>{console.error(e);stop(1)});p.on('exit',code=>stop(code||0));}
process.on('SIGINT',()=>stop());process.on('SIGTERM',()=>stop());
