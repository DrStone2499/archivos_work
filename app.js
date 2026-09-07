const live = document.getElementById("live");
const crop = document.getElementById("crop");
const cropEmpty = document.getElementById("crop-empty");
const lamp = document.getElementById("lamp");
const statusEl = document.getElementById("status");
const fpsEl = document.getElementById("fps");
const stabilityEl = document.getElementById("stability");
const faultEl = document.getElementById("fault");
const toast = document.getElementById("toast");
const printBtn = document.getElementById("btn-print");

let lastOcrText = "";
let lastCropPath = "";

const LAMP = {
  "etiqueta lista": "go",
  "estabilizando": "hold",
  "buscando caja": "hold",
  "caja sin etiqueta visible": "hold",
  "sin senal": "stop",
};

function showToast(message, kind) {
  toast.textContent = message;
  toast.dataset.kind = kind || "ok";
  toast.hidden = false;
  setTimeout(() => { toast.hidden = true; }, 6000);
}

function applyFields(fields) {
  Object.entries(fields).forEach(([key, info]) => {
    const wrap = document.querySelector(`.field[data-key="${key}"]`);
    const input = document.getElementById(`f-${key}`);
    if (!wrap || !input) return;

    input.value = info.value || "";
    wrap.classList.remove("high", "low");
    const conf = info.confidence || 0;
    const confEl = wrap.querySelector(".conf");

    if (!info.value) {
      wrap.classList.add("low");
      confEl.textContent = "no se encontro en la etiqueta, captura a mano";
    } else if (conf >= 0.7) {
      wrap.classList.add("high");
      confEl.textContent = `leido con ${Math.round(conf * 100)}% de confianza`;
    } else {
      wrap.classList.add("low");
      confEl.textContent = `confianza baja (${Math.round(conf * 100)}%), verifica`;
    }
  });
}

const source = new EventSource("/api/stream");

source.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.frame) live.src = `data:image/jpeg;base64,${data.frame}`;
  statusEl.textContent = data.status;
  lamp.dataset.state = LAMP[data.status] || "wait";
  fpsEl.textContent = `${data.fps} fps`;
  stabilityEl.textContent = `estabilidad ${data.stable}`;

  if (data.error) {
    faultEl.textContent = data.error;
    faultEl.hidden = false;
  } else {
    faultEl.hidden = true;
  }

  if (data.result) {
    applyFields(data.result.fields);
    lastOcrText = data.result.text || "";
    lastCropPath = data.result.crop_path || "";
    if (data.result.crop_b64) {
      crop.src = `data:image/jpeg;base64,${data.result.crop_b64}`;
      crop.style.display = "block";
      cropEmpty.hidden = true;
    }
  }
};

source.onerror = () => {
  lamp.dataset.state = "stop";
  statusEl.textContent = "sin conexion con el servicio";
};

document.getElementById("btn-read").addEventListener("click", () => {
  fetch("/api/read", { method: "POST" });
});

document.getElementById("btn-clear").addEventListener("click", () => {
  window.FIELD_KEYS.forEach((key) => {
    document.getElementById(`f-${key}`).value = "";
    const wrap = document.querySelector(`.field[data-key="${key}"]`);
    wrap.classList.remove("high", "low");
    wrap.querySelector(".conf").textContent = "sin leer";
  });
});

printBtn.addEventListener("click", async () => {
  const fields = {};
  window.FIELD_KEYS.forEach((key) => {
    fields[key] = document.getElementById(`f-${key}`).value.trim();
  });

  printBtn.disabled = true;
  printBtn.textContent = "Imprimiendo...";
  try {
    const res = await fetch("/api/relabel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, ocr_text: lastOcrText, crop_path: lastCropPath }),
    });
    const out = await res.json();
    if (out.ok) {
      showToast(out.printed ? `Etiqueta impresa y guardada (folio ${out.id})`
                            : `Guardado sin imprimir (folio ${out.id})`);
      loadHistory();
    } else {
      showToast(out.error, "error");
    }
  } catch (err) {
    showToast(`No se pudo completar: ${err}`, "error");
  } finally {
    printBtn.disabled = false;
    printBtn.textContent = "Imprimir etiqueta nueva";
  }
});

async function loadHistory() {
  const list = document.getElementById("history-list");
  const rows = await (await fetch("/api/history")).json();
  if (!rows.length) {
    list.innerHTML = '<li class="empty">Sin registros todavia.</li>';
    return;
  }
  list.innerHTML = rows.map((r) => {
    const first = Object.values(r.fields)[0] || "";
    return `<li>${r.created_at} · ${first} ${r.printed ? "· impreso" : ""}</li>`;
  }).join("");
}

loadHistory();
