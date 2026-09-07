const API = "/api";

// ---- Live preview -----------------------------------------------------------
let currentPreview = null; // { kind: "upload"|"stream", id, label }
const uploadJobStatuses = new Map(); // job_id -> status string
const streamStatuses = new Map(); // stream_id -> status string

function setPreview(kind, id, label) {
  currentPreview = { kind, id, label };

  const img = document.getElementById("preview-img");
  const emptyNote = document.getElementById("preview-empty");
  const sourceLabel = document.getElementById("preview-source-label");
  const frame = document.getElementById("preview-frame");

  const url = kind === "upload" ? `${API}/videos/${id}/preview` : `${API}/streams/${id}/preview`;
  img.src = `${url}?t=${Date.now()}`; // cache-bust so a fresh stream connection is opened
  img.hidden = false;
  emptyNote.hidden = true;
  sourceLabel.textContent = label;

  let badge = document.getElementById("preview-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.id = "preview-badge";
    badge.className = "preview-badge";
    badge.innerHTML = `<span class="dot"></span><span id="preview-badge-text"></span>`;
    frame.appendChild(badge);
  }
  updatePreviewBadge();

  document.querySelectorAll(".item-list li").forEach((li) => li.classList.remove("active"));
  const activeLi = document.getElementById(`${kind}-${id}`);
  if (activeLi) activeLi.classList.add("active");
}

function updatePreviewBadge() {
  const badge = document.getElementById("preview-badge");
  if (!badge || !currentPreview) return;
  const text = document.getElementById("preview-badge-text");

  const status =
    currentPreview.kind === "upload"
      ? uploadJobStatuses.get(currentPreview.id) || "processing"
      : streamStatuses.get(currentPreview.id) || "running";

  const isLive = currentPreview.kind === "stream" && status === "running";
  badge.classList.toggle("live", isLive);
  text.textContent = isLive ? "LIVE" : status;
}

// ---- Clock ----------------------------------------------------------------
function tickClock() {
  const now = new Date();
  document.getElementById("clock").textContent = now.toLocaleTimeString();
}
setInterval(tickClock, 1000);
tickClock();

// ---- API status dot ---------------------------------------------------------
async function checkHealth() {
  const dot = document.getElementById("api-status");
  try {
    const res = await fetch(`${API}/health`);
    dot.classList.toggle("offline", !res.ok);
  } catch {
    dot.classList.add("offline");
  }
}

// ---- Live counts / tally board -------------------------------------------
let previousCounts = {};

function animateIfChanged(el, key, newValue) {
  if (previousCounts[key] !== newValue) {
    el.classList.remove("roll");
    void el.offsetWidth; // restart animation
    el.classList.add("roll");
  }
  previousCounts[key] = newValue;
}

async function refreshLiveCounts() {
  try {
    const res = await fetch(`${API}/counts/live`);
    const data = await res.json();

    document.getElementById("today-date").textContent = data.date;

    const totalEl = document.getElementById("total-count");
    const totalText = String(data.total).padStart(4, "0");
    totalEl.textContent = totalText;
    animateIfChanged(totalEl, "__total__", totalText);

    const board = document.getElementById("tally-board");
    [...board.querySelectorAll(".tally-card:not(.tally-total)")].forEach((n) => n.remove());

    const entries = Object.entries(data.counts).sort((a, b) => b[1] - a[1]);
    document.getElementById("tally-empty").hidden = entries.length > 0;

    for (const [name, count] of entries) {
      const card = document.createElement("div");
      card.className = "tally-card";
      const numberText = String(count).padStart(4, "0");
      card.innerHTML = `
        <div class="tally-number mono">${numberText}</div>
        <div class="tally-label">${name}</div>
      `;
      board.appendChild(card);
      animateIfChanged(card.querySelector(".tally-number"), name, numberText);
    }
  } catch (err) {
    console.error("Failed to refresh live counts", err);
  }
}

// ---- Vehicle type registry -------------------------------------------------
async function refreshVehicleTypes() {
  try {
    const res = await fetch(`${API}/vehicle-types`);
    const types = await res.json();
    const strip = document.getElementById("manifest-strip");
    strip.innerHTML = "";
    document.getElementById("manifest-empty").hidden = types.length > 0;

    for (const t of types) {
      const chip = document.createElement("div");
      chip.className = "manifest-chip";
      const firstSeen = new Date(t.first_seen_at).toLocaleDateString();
      chip.innerHTML = `<span class="chip-name">${t.name}</span><span class="chip-date">since ${firstSeen}</span>`;
      strip.appendChild(chip);
    }
  } catch (err) {
    console.error("Failed to refresh vehicle types", err);
  }
}

// ---- Video upload -----------------------------------------------------------
const uploadJobs = new Map(); // job_id -> filename

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("video-file");
  const file = fileInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API}/videos/upload`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    const data = await res.json();
    uploadJobs.set(data.job_id, file.name);
    uploadJobStatuses.set(data.job_id, "processing");
    fileInput.value = "";
    renderJobList();
    setPreview("upload", data.job_id, file.name);
  } catch (err) {
    alert(`Couldn't upload ${file.name}. ${err.message}`);
  }
});

function renderJobList() {
  const list = document.getElementById("job-list");
  list.innerHTML = "";
  for (const [jobId, filename] of uploadJobs) {
    const li = document.createElement("li");
    li.id = `upload-${jobId}`;
    li.className = "clickable";

    const nameSpan = document.createElement("span");
    nameSpan.className = "item-name";
    nameSpan.textContent = filename; // textContent, not innerHTML: filenames aren't trusted input

    const statusSpan = document.createElement("span");
    statusSpan.className = "item-status processing";
    statusSpan.id = `job-status-${jobId}`;
    statusSpan.textContent = "processing";

    li.appendChild(nameSpan);
    li.appendChild(statusSpan);
    li.addEventListener("click", () => setPreview("upload", jobId, filename));
    list.appendChild(li);
  }
}

async function pollUploadJobs() {
  for (const [jobId] of uploadJobs) {
    try {
      const res = await fetch(`${API}/videos/${jobId}/status`);
      const job = await res.json();
      uploadJobStatuses.set(jobId, job.status);

      const statusEl = document.getElementById(`job-status-${jobId}`);
      if (statusEl) {
        statusEl.textContent =
          job.status === "processing" ? `processing (${job.frames_processed} frames)` : job.status;
        statusEl.className = `item-status ${job.status}`;
      }
      if (currentPreview?.kind === "upload" && currentPreview.id === jobId) {
        updatePreviewBadge();
      }
    } catch (err) {
      console.error("Failed to poll job", jobId, err);
    }
  }
}

// ---- Live streams -------------------------------------------------------------
document.getElementById("stream-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("stream-name").value.trim();
  const url = document.getElementById("stream-url").value.trim();
  if (!name || !url) return;

  try {
    const res = await fetch(`${API}/streams`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, url }),
    });
    if (!res.ok) throw new Error(`Couldn't start stream (${res.status})`);
    const stream = await res.json();
    document.getElementById("stream-name").value = "";
    document.getElementById("stream-url").value = "";
    await refreshStreams();
    setPreview("stream", stream.stream_id, name);
  } catch (err) {
    alert(`Couldn't start watching ${name}. ${err.message}`);
  }
});

async function stopStream(streamId) {
  try {
    await fetch(`${API}/streams/${streamId}`, { method: "DELETE" });
    refreshStreams();
  } catch (err) {
    console.error("Failed to stop stream", err);
  }
}

async function refreshStreams() {
  try {
    const res = await fetch(`${API}/streams`);
    const streams = await res.json();
    const list = document.getElementById("stream-list");
    list.innerHTML = "";

    for (const s of streams) {
      streamStatuses.set(s.stream_id, s.status);

      const li = document.createElement("li");
      li.id = `stream-${s.stream_id}`;
      li.className = "clickable";

      const left = document.createElement("span");
      const nameSpan = document.createElement("span");
      nameSpan.className = "item-name";
      nameSpan.textContent = s.name; // textContent: camera names aren't trusted input
      const metaSpan = document.createElement("span");
      metaSpan.className = "item-meta";
      metaSpan.textContent = ` — ${s.frames_processed} frames`;
      left.appendChild(nameSpan);
      left.appendChild(metaSpan);

      const right = document.createElement("span");
      right.style.display = "flex";
      right.style.alignItems = "center";
      right.style.gap = "8px";
      const statusSpan = document.createElement("span");
      statusSpan.className = `item-status ${s.status}`;
      statusSpan.textContent = s.status;
      right.appendChild(statusSpan);

      if (s.status === "running") {
        const stopBtn = document.createElement("button");
        stopBtn.className = "stop-btn";
        stopBtn.textContent = "Stop";
        stopBtn.addEventListener("click", (evt) => {
          evt.stopPropagation(); // don't also trigger the li's preview click
          stopStream(s.stream_id);
        });
        right.appendChild(stopBtn);
      }

      li.appendChild(left);
      li.appendChild(right);
      li.addEventListener("click", () => setPreview("stream", s.stream_id, s.name));
      list.appendChild(li);

      if (currentPreview?.kind === "stream" && currentPreview.id === s.stream_id) {
        updatePreviewBadge();
      }
    }
  } catch (err) {
    console.error("Failed to refresh streams", err);
  }
}

// ---- History ------------------------------------------------------------------
async function refreshHistory(date) {
  try {
    const url = date ? `${API}/counts/history?date=${date}` : `${API}/counts/history`;
    const res = await fetch(url);
    const rows = await res.json();
    const body = document.getElementById("history-body");
    body.innerHTML = "";
    document.getElementById("history-empty").hidden = rows.length > 0;

    for (const day of rows) {
      const entries = Object.entries(day.counts);
      entries.forEach(([vehicleType, count], i) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${i === 0 ? day.date : ""}</td>
          <td>${vehicleType}</td>
          <td>${count}</td>
        `;
        body.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Failed to refresh history", err);
  }
}

document.getElementById("history-date").addEventListener("change", (e) => {
  refreshHistory(e.target.value || null);
});
document.getElementById("history-clear").addEventListener("click", () => {
  document.getElementById("history-date").value = "";
  refreshHistory(null);
});

// ---- Boot -----------------------------------------------------------------------
checkHealth();
refreshLiveCounts();
refreshVehicleTypes();
refreshStreams();
refreshHistory(null);

setInterval(checkHealth, 10000);
setInterval(refreshLiveCounts, 3000);
setInterval(refreshVehicleTypes, 10000);
setInterval(refreshStreams, 3000);
setInterval(pollUploadJobs, 2000);
