import assert from 'node:assert/strict';
import {once} from 'node:events';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtemp, rm} from 'node:fs/promises';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {test} from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DASHBOARD_TEST_PYTHON ?? join(root, '.venv/bin/python');
const playwright = process.env.DASHBOARD_PLAYWRIGHT_MODULE;

test('real dashboard renders demo, replay, missing data and mobile layouts', {timeout: 40_000}, async () => {
  const {chromium} = await import(playwright ? pathToFileURL(playwright).href : 'playwright');
  const runtime = await mkdtemp(join(tmpdir(), 'pbl3-dashboard-test-'));
  const reserve = createServer();
  reserve.listen(0, '127.0.0.1');
  await once(reserve, 'listening');
  const {port} = reserve.address();
  await new Promise(resolve => reserve.close(resolve));
  const url = `http://127.0.0.1:${port}`;
  let api, browser;
  try {
    const seed = spawnSync(python, ['-c', `
from pathlib import Path
import json, sys
from scripts.probe_fixture import generate
folder = Path(sys.argv[1]) / 'experiments' / 'browser-replay'
generate(folder)
path = folder / 'metadata.json'
path.write_text(json.dumps(dict(json.loads(path.read_text()), id='browser-replay', synthetic=False)))
`, runtime], {cwd: root, encoding: 'utf8'});
    assert.equal(seed.status, 0, seed.stderr || String(seed.error));
    api = spawn(python, ['-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', String(port)], {
      cwd: root, env: {...process.env, WIFI_PROBE_DATA_DIR: runtime, WIFI_DASHBOARD_CONFIG: ''}, stdio: 'ignore',
    });
    let healthy = false;
    for (let retry = 0; retry < 60 && !healthy; retry++) {
      healthy = await fetch(`${url}/api/health`).then(response => response.ok, () => false);
      if (!healthy) await delay(100);
    }
    assert.ok(healthy, 'FastAPI failed to start');

    browser = await chromium.launch({executablePath: process.env.DASHBOARD_TEST_CHROME ?? '/usr/bin/google-chrome'});
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    await page.goto(url);
    const estimate = page.getByTestId('room-estimate');
    await estimate.waitFor();
    assert.equal(await estimate.textContent(), 'UNKNOWN');
    await page.getByText('Nguồn thu đã ngắt hoặc đang kết nối lại.').waitFor();

    const replay = async name => {
      const response = await page.request.post(`${url}/api/probe/replay`, {data: {name, speed: 100}});
      assert.ok(response.ok(), await response.text());
    };
    await replay('synthetic-probe-demo');
    await page.getByText('DEMO · Mô phỏng', {exact: true}).waitFor();
    const table = page.getByRole('region', {name: 'Bảng Device Cluster'});
    await table.waitFor();
    await page.getByLabel('Cửa sổ biểu đồ').selectOption('60');
    await page.getByRole('img', {name: /60 giây/}).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.ok(await table.evaluate(element => element.scrollWidth > element.clientWidth));
    await table.getByText('Lý do và lịch sử').first().click();
    await table.getByText('Liên kết MAC', {exact: true}).first().waitFor();
    assert.equal(await estimate.textContent(), 'UNKNOWN');

    await page.getByRole('button', {name: 'Ngắt nguồn', exact: true}).click();
    await page.getByText('Nguồn thu đã ngắt hoặc đang kết nối lại.').waitFor();
    await replay('browser-replay');
    await page.getByText('REPLAY · Phát lại', {exact: true}).waitFor();
    await table.waitFor();
    await page.setViewportSize({width: 1280, height: 900});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

    await page.route('**/api/probe/dashboard', route => route.abort());
    await page.getByText('Không đọc được dữ liệu phân tích', {exact: false}).waitFor();
    assert.equal(await estimate.textContent(), 'UNKNOWN');
    assert.equal(await table.count(), 0);
  } finally {
    await browser?.close();
    if (api?.exitCode === null && api?.signalCode === null) {
      api.kill();
      await once(api, 'exit');
    }
    await rm(runtime, {recursive: true, force: true});
  }
});
