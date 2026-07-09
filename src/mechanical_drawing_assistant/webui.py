from __future__ import annotations

import json
import logging
import traceback
import webbrowser
import zipfile
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mechanical_drawing_assistant.diagnostics import diagnose_environment
from mechanical_drawing_assistant.pipeline import run_pipeline, write_json
from mechanical_drawing_assistant.runtime import (
    application_root,
    default_knowledge_path,
    default_samples_path,
    project_root,
)

JsonDict = dict[str, Any]


def run_webui(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    log_dir: Path | None = None,
) -> None:
    server = create_webui_server(host, port, log_dir=log_dir)
    address, actual_port = server.server_address[:2]
    url = f"http://{address}:{actual_port}/"
    print(f"Mechanical Drawing Assistant Web UI: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Web UI.")
    finally:
        server.server_close()


def create_webui_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    log_dir: Path | None = None,
) -> ThreadingHTTPServer:
    log_path = configure_logging(log_dir)
    handler = build_handler(log_path)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def configure_logging(log_dir: Path | None = None) -> Path:
    target_dir = log_dir or (application_root() / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / "mda-webui.log"
    logger = logging.getLogger("mechanical_drawing_assistant.webui")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return log_path


def build_handler(log_path: Path) -> type[BaseHTTPRequestHandler]:
    class MdaWebHandler(BaseHTTPRequestHandler):
        server_version = "MDAWebUI/0.1"

        def log_message(self, format: str, *args: object) -> None:
            logging.getLogger("mechanical_drawing_assistant.webui").info(
                "%s - %s",
                self.address_string(),
                format % args,
            )

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(INDEX_HTML, "text/html; charset=utf-8")
                return
            if parsed.path == "/styles.css":
                self._send_text(STYLES_CSS, "text/css; charset=utf-8")
                return
            if parsed.path == "/app.js":
                self._send_text(APP_JS, "application/javascript; charset=utf-8")
                return
            if parsed.path == "/api/diagnose":
                self._send_json(diagnose_environment(project_root()))
                return
            if parsed.path == "/api/samples":
                self._send_json({"samples": sample_jobs()})
                return
            if parsed.path == "/api/read-output":
                params = parse_qs(parsed.query)
                self._handle_read_output(params.get("path", [""])[0])
                return
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                data = self._read_json_body()
                if parsed.path == "/api/run":
                    self._send_json(run_from_payload(data, log_path))
                    return
                if parsed.path == "/api/support-bundle":
                    self._send_json(create_support_bundle_from_payload(data, log_path))
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            except Exception as exc:
                logging.getLogger("mechanical_drawing_assistant.webui").exception(
                    "Request failed: %s",
                    parsed.path,
                )
                self._send_json(
                    {
                        "ok": False,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def _handle_read_output(self, path_text: str) -> None:
            path = Path(path_text)
            if not path.exists() or not path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND, "Output file not found")
                return
            if path.suffix.lower() not in {".json", ".md", ".txt", ".log"}:
                self._send_error(HTTPStatus.BAD_REQUEST, "Unsupported output file type")
                return
            self._send_text(path.read_text(encoding="utf-8"), "text/plain; charset=utf-8")

        def _read_json_body(self) -> JsonDict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object.")
            return data

        def _send_json(
            self,
            data: object,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(
            self,
            text: str,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"ok": False, "error": message}, status=status)

    return MdaWebHandler


def sample_jobs() -> list[JsonDict]:
    jobs_dir = default_samples_path() / "jobs"
    if not jobs_dir.exists():
        return []
    samples: list[JsonDict] = []
    for path in sorted(jobs_dir.glob("*.json")):
        item: JsonDict = {
            "name": path.name,
            "path": str(path),
        }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                item["job_name"] = data.get("job_name")
                part = data.get("part")
                if isinstance(part, dict):
                    item["part_name"] = part.get("name")
                    item["part_category"] = part.get("category")
        except (OSError, json.JSONDecodeError) as exc:
            item["error"] = str(exc)
        samples.append(item)
    return samples


def run_from_payload(payload: JsonDict, log_path: Path) -> JsonDict:
    output_dir = Path(str(payload.get("output_dir") or default_output_dir()))
    output_dir.mkdir(parents=True, exist_ok=True)

    job_path = resolve_job_path(payload, output_dir)
    knowledge_path = Path(str(payload.get("knowledge_path") or default_knowledge_path()))
    live = bool(payload.get("live", False))

    logging.getLogger("mechanical_drawing_assistant.webui").info(
        "Run requested: job=%s output=%s live=%s knowledge=%s",
        job_path,
        output_dir,
        live,
        knowledge_path,
    )
    run_pipeline(job_path, knowledge_path, output_dir, dry_run=not live)
    run_log = {
        "ok": True,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "job_path": str(job_path),
        "knowledge_path": str(knowledge_path),
        "output_dir": str(output_dir),
        "live": live,
        "files": output_files(output_dir),
        "log_path": str(log_path),
    }
    write_json(output_dir / "webui_run_log.json", run_log)
    report_path = output_dir / "review_report.md"
    run_log["review_report"] = (
        report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    )
    return run_log


def resolve_job_path(payload: JsonDict, output_dir: Path) -> Path:
    job_path_value = str(payload.get("job_path") or "").strip()
    if job_path_value:
        job_path = Path(job_path_value)
        if not job_path.exists():
            raise FileNotFoundError(f"Job file not found: {job_path}")
        return job_path

    job_data = payload.get("job")
    if not isinstance(job_data, dict):
        raise ValueError("Provide either job_path or job object.")
    job_path = output_dir / "webui_job.generated.json"
    write_json(job_path, job_data)
    return job_path


def default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return application_root() / "output" / f"webui-{stamp}"


def output_files(output_dir: Path) -> list[JsonDict]:
    if not output_dir.exists():
        return []
    result: list[JsonDict] = []
    for path in sorted(output_dir.iterdir()):
        if not path.is_file():
            continue
        result.append(
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
            }
        )
    return result


def create_support_bundle_from_payload(payload: JsonDict, log_path: Path) -> JsonDict:
    output_dir = Path(str(payload.get("output_dir") or application_root()))
    bundle_path = Path(str(payload.get("bundle_path") or output_dir / "mda-support-bundle.zip"))
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        diagnose = diagnose_environment(project_root())
        archive.writestr(
            "diagnose.json",
            json.dumps(diagnose, ensure_ascii=False, indent=2) + "\n",
        )
        if log_path.exists():
            archive.write(log_path, "logs/mda-webui.log")
        if output_dir.exists():
            for path in sorted(output_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in {".json", ".md", ".txt", ".log"}:
                    archive.write(path, f"outputs/{path.name}")
    return {
        "ok": True,
        "bundle_path": str(bundle_path),
    }


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mechanical Drawing Assistant</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header class="app-header">
    <div>
      <h1>Mechanical Drawing Assistant</h1>
      <p id="runtimeLine">诊断未运行</p>
    </div>
    <div class="header-actions">
      <button id="diagnoseBtn" type="button">诊断</button>
      <button id="supportBtn" type="button">支持包</button>
    </div>
  </header>

  <main class="app-shell">
    <section class="panel config-panel">
      <div class="section-title">
        <h2>运行配置</h2>
        <span id="modeLabel">dry-run</span>
      </div>

      <div class="segmented" role="group" aria-label="job mode">
        <button class="segment active" type="button" data-mode="sample">样例</button>
        <button class="segment" type="button" data-mode="custom">自定义</button>
      </div>

      <div id="sampleFields" class="field-stack">
        <label>
          <span>样例 job</span>
          <select id="sampleSelect"></select>
        </label>
        <label>
          <span>job 路径</span>
          <input id="jobPath" type="text">
        </label>
      </div>

      <div id="customFields" class="field-stack hidden">
        <label>
          <span>任务名</span>
          <input id="jobName" type="text" value="webui-custom-job">
        </label>
        <label>
          <span>零件名</span>
          <input id="partName" type="text" value="未命名零件">
        </label>
        <label>
          <span>零件类型</span>
          <select id="partCategory">
            <option value="motor_mounting_plate">motor_mounting_plate</option>
            <option value="turned_mounting_sleeve">turned_mounting_sleeve</option>
            <option value="shaft">shaft</option>
            <option value="pulley">pulley</option>
            <option value="basic_mechanical">basic_mechanical</option>
          </select>
        </label>
        <label>
          <span>SolidWorks 模型路径</span>
          <input id="sourceModel" type="text">
        </label>
        <label>
          <span>参考 DWG 路径</span>
          <input id="sourceDwg" type="text">
        </label>
        <label>
          <span>特征模板</span>
          <input id="featureTemplates" type="text" value="basic_mechanical,motor_mounting_plate">
        </label>
        <label>
          <span>输出文件名前缀</span>
          <input id="drawingBasename" type="text" value="webui-drawing">
        </label>
      </div>

      <div class="field-stack">
        <label>
          <span>输出目录</span>
          <input id="outputDir" type="text" value="output/webui-run">
        </label>
        <label>
          <span>规则库路径</span>
          <input id="knowledgePath" type="text">
        </label>
        <label class="check-row">
          <input id="liveRun" type="checkbox">
          <span>live 模式</span>
        </label>
      </div>

      <button id="runBtn" class="primary" type="button">运行</button>
    </section>

    <section class="panel status-panel">
      <div class="section-title">
        <h2>状态</h2>
        <span id="statusPill">idle</span>
      </div>
      <div id="diagnoseGrid" class="status-grid"></div>
      <div class="output-list" id="outputList"></div>
    </section>

    <section class="panel report-panel">
      <div class="section-title">
        <h2>复查报告</h2>
        <span id="reportMeta">等待运行</span>
      </div>
      <pre id="reportView"></pre>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


STYLES_CSS = r""":root {
  color-scheme: light;
  --bg: #f4f6f8;
  --surface: #ffffff;
  --text: #172026;
  --muted: #66727f;
  --border: #d7dee6;
  --accent: #0f766e;
  --accent-strong: #0b5f59;
  --blue: #245b89;
  --warn: #a15c16;
  --error: #b42318;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}

.app-header {
  min-height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  font-size: 21px;
  line-height: 1.25;
  font-weight: 650;
}

h2 {
  font-size: 15px;
  line-height: 1.3;
  font-weight: 650;
}

.app-header p,
.section-title span,
label span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}

.header-actions,
.section-title,
.segmented,
.check-row {
  display: flex;
  align-items: center;
}

.header-actions {
  gap: 8px;
}

.app-shell {
  display: grid;
  grid-template-columns: minmax(300px, 390px) minmax(300px, 1fr);
  grid-template-rows: auto minmax(300px, 1fr);
  gap: 16px;
  padding: 16px;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  min-width: 0;
}

.config-panel {
  grid-row: 1 / span 2;
}

.report-panel {
  min-height: 360px;
}

.section-title {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.field-stack {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

label {
  display: grid;
  gap: 5px;
}

input,
select,
button {
  font: inherit;
}

input,
select {
  width: 100%;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0 10px;
  background: #fbfcfd;
  color: var(--text);
  font-size: 13px;
}

button {
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0 13px;
  background: #f8fafb;
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

button:hover {
  border-color: #aab7c4;
}

.primary {
  width: 100%;
  margin-top: 16px;
  background: var(--accent);
  border-color: var(--accent);
  color: #ffffff;
}

.primary:hover {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
}

.segmented {
  width: 100%;
  gap: 4px;
  padding: 3px;
  background: #edf2f5;
  border-radius: 8px;
}

.segment {
  flex: 1;
  border: 0;
  background: transparent;
}

.segment.active {
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}

.check-row {
  grid-template-columns: 18px 1fr;
  gap: 8px;
}

.check-row input {
  width: 16px;
  height: 16px;
}

.hidden {
  display: none;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  min-height: 58px;
}

.metric strong {
  display: block;
  font-size: 13px;
  margin-bottom: 4px;
}

.metric span {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.output-list {
  margin-top: 14px;
  display: grid;
  gap: 8px;
}

.output-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #e8edf2;
  padding-bottom: 8px;
  font-size: 13px;
}

.output-item span {
  color: var(--muted);
  font-size: 12px;
}

#statusPill,
#modeLabel,
#reportMeta {
  color: var(--blue);
}

#reportView {
  margin: 0;
  min-height: 300px;
  max-height: 58vh;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fbfcfd;
  color: #202830;
  white-space: pre-wrap;
  font: 13px/1.55 Consolas, "Microsoft YaHei UI", monospace;
}

@media (max-width: 900px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .config-panel {
    grid-row: auto;
  }

  .app-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
"""


APP_JS = r"""const state = {
  mode: "sample",
  diagnose: null,
  lastOutputDir: "",
};

const $ = (id) => document.getElementById(id);

function setStatus(text) {
  $("statusPill").textContent = text;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function postJson(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data),
  });
  const body = await response.json();
  if (!response.ok || body.ok === false) throw new Error(body.error || "request failed");
  return body;
}

function renderDiagnose(data) {
  state.diagnose = data;
  const runtime = data.runtime || {};
  const resources = data.resources || {};
  const packages = data.python_packages || {};
  $("runtimeLine").textContent = runtime.frozen
    ? `exe: ${runtime.executable}`
    : `source: ${runtime.application_root}`;
  $("knowledgePath").value = runtime.default_knowledge_path || "";
  const metrics = [
    ["运行模式", runtime.frozen ? "frozen exe" : "source"],
    ["规则库", resources.knowledge?.present ? "present" : "missing"],
    ["样例", resources.samples?.present ? "present" : "missing"],
    ["ezdxf", packages.ezdxf ? "available" : "missing"],
    ["pywin32", packages.pywin32 ? "available" : "missing"],
    ["SolidWorks", data.adapters?.solidworks?.active_instance ? "active" : "not active"],
  ];
  $("diagnoseGrid").innerHTML = metrics.map(([name, value]) =>
    `<div class="metric"><strong>${name}</strong><span>${value}</span></div>`
  ).join("");
}

async function loadSamples() {
  const data = await getJson("/api/samples");
  const select = $("sampleSelect");
  select.innerHTML = "";
  for (const sample of data.samples || []) {
    const option = document.createElement("option");
    option.value = sample.path;
    option.textContent = sample.job_name || sample.name;
    select.appendChild(option);
  }
  if (select.options.length) {
    $("jobPath").value = select.value;
  }
}

function currentJobPayload() {
  const outputDir = $("outputDir").value.trim() || "output/webui-run";
  const common = {
    output_dir: outputDir,
    knowledge_path: $("knowledgePath").value.trim(),
    live: $("liveRun").checked,
  };
  if (state.mode === "sample") {
    return {
      ...common,
      job_path: $("jobPath").value.trim(),
    };
  }

  const category = $("partCategory").value;
  const templates = $("featureTemplates").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return {
    ...common,
    job: {
      job_name: $("jobName").value.trim() || "webui-custom-job",
      part: {
        name: $("partName").value.trim() || "未命名零件",
        category,
        source_model: $("sourceModel").value.trim() || null,
        source_dwg: $("sourceDwg").value.trim() || null,
        material: "",
        process: [],
        notes: ["Web UI generated job"],
      },
      drawing_standard: "GB",
      feature_templates: templates.length ? templates : ["basic_mechanical"],
      views: ["front", "top", "left"],
      output: {
        workdir: outputDir,
        drawing_basename: $("drawingBasename").value.trim() || "webui-drawing",
        export_formats: ["slddrw", "pdf", "dwg", "dxf"],
      },
    },
  };
}

function renderOutputs(result) {
  state.lastOutputDir = result.output_dir || "";
  const files = result.files || [];
  $("outputList").innerHTML = files.map((file) =>
    `<div class="output-item"><strong>${file.name}</strong><span>${file.size} bytes</span></div>`
  ).join("");
  $("reportView").textContent = result.review_report || "未生成复查报告";
  $("reportMeta").textContent = result.output_dir || "无输出";
}

async function runJob() {
  setStatus("running");
  $("runBtn").disabled = true;
  try {
    const result = await postJson("/api/run", currentJobPayload());
    renderOutputs(result);
    setStatus("done");
  } catch (error) {
    $("reportView").textContent = String(error);
    setStatus("error");
  } finally {
    $("runBtn").disabled = false;
  }
}

async function createSupportBundle() {
  setStatus("bundling");
  try {
    const result = await postJson("/api/support-bundle", {
      output_dir: state.lastOutputDir || $("outputDir").value.trim(),
    });
    $("reportView").textContent = `support bundle: ${result.bundle_path}`;
    setStatus("done");
  } catch (error) {
    $("reportView").textContent = String(error);
    setStatus("error");
  }
}

function setMode(mode) {
  state.mode = mode;
  $("sampleFields").classList.toggle("hidden", mode !== "sample");
  $("customFields").classList.toggle("hidden", mode !== "custom");
  for (const button of document.querySelectorAll(".segment")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
}

async function init() {
  document.querySelectorAll(".segment").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  $("sampleSelect").addEventListener("change", (event) => {
    $("jobPath").value = event.target.value;
  });
  $("liveRun").addEventListener("change", () => {
    $("modeLabel").textContent = $("liveRun").checked ? "live" : "dry-run";
  });
  $("runBtn").addEventListener("click", runJob);
  $("supportBtn").addEventListener("click", createSupportBundle);
  $("diagnoseBtn").addEventListener("click", async () => {
    setStatus("diagnosing");
    renderDiagnose(await getJson("/api/diagnose"));
    setStatus("idle");
  });
  await loadSamples();
  renderDiagnose(await getJson("/api/diagnose"));
}

init().catch((error) => {
  setStatus("error");
  $("reportView").textContent = String(error);
});
"""
