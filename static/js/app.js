(() => {
  const $ = (s) => document.querySelector(s);
  const send = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  /* ---------- toasts + browser notifications ---------- */
  function toast(kind, title, detail) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast " + kind;
    const b = document.createElement("b"); b.textContent = title;
    const s = document.createElement("span"); s.textContent = detail || "";
    el.append(b, s);
    box.prepend(el);
    setTimeout(() => el.remove(), 6000);
    if (kind === "alert" && "Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body: detail });
    }
  }

  /* ---------- dashboard ---------- */
  const COPY = {
    offline:    { title: "Mini-Bot is asleep", sub: "Press Start to wake the camera.", badge: "Waiting", note: "The most recent face the camera saw will show here." },
    no_face:    { title: "Watching the door", sub: "No face in view right now.", badge: "Waiting", note: "Step in front of the camera to be checked." },
    recognized: { title: "", sub: "This face is registered.", badge: "Recognized", note: "Registered face. No alert." },
    unknown:    { title: "Unknown person", sub: "This face is not registered. Buzzer alert sent.", badge: "Not recognized", note: "Not in the database. Add this person on the People page if they should be allowed." },
  };
  let lastEventId = null, faceVersion = -1, tolTouched = 0, running = null;

  function ago(since) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - since));
    return s < 60 ? `${s}s in this state` : `${Math.floor(s / 60)}m ${s % 60}s in this state`;
  }

  function renderDashboard(d) {
    const st = d.state, c = COPY[st.status] || COPY.offline;
    $("#stage").dataset.state = st.status;
    $("#faceModule").dataset.state = st.status;
    $("#verdictTitle").textContent = st.status === "recognized" ? `Hello, ${st.name}` : c.title;
    $("#verdictSub").textContent = c.sub;
    const role = $("#chipRole"), score = $("#chipScore");
    role.hidden = !(st.status === "recognized" && st.role); role.textContent = st.role || "";
    score.hidden = !(st.status === "recognized" && st.score != null); score.textContent = `Match score ${st.score}%`;
    $("#chipSince").textContent = st.status === "offline" ? "Camera paused" : ago(st.since);

    $("#faceBadge").textContent = c.badge;
    $("#faceName").textContent = st.status === "recognized" ? st.name : st.status === "unknown" ? "Unknown person" : "–";
    $("#faceNote").textContent = st.status === "recognized" && st.role ? st.role : c.note;
    if (d.face_version !== faceVersion) {
      faceVersion = d.face_version;
      if (faceVersion > 0) {
        const img = $("#faceImg");
        img.src = `/api/last_face.jpg?v=${faceVersion}`; img.hidden = false; $("#faceEmpty").hidden = true;
      }
    }

    $("#feedMeta").textContent = `${d.mode === "demo" ? "Demo mode" : "Live"} · ${d.camera} · ${d.fps} fps`;
    if (running !== d.running) {
      running = d.running;
      const p = $("#powerBtn"); p.textContent = running ? "Stop" : "Start"; p.classList.toggle("stop", running);
    }

    const bz = d.buzzer;
    $("#buzzerState").textContent = bz.enabled ? (bz.active ? "Buzzer sounding" : "Buzzer on") : "Buzzer off";
    $("#buzzerPin").textContent = `GPIO ${bz.pin}${bz.mock ? " (simulated on this computer)" : ""}`;
    const bi = $("#buzzerIcon"); bi.classList.toggle("on", bz.enabled); bi.classList.toggle("sounding", bz.active);
    if (document.activeElement !== $("#buzzerToggle")) $("#buzzerToggle").checked = bz.enabled;
    if (Date.now() - tolTouched > 1500) { $("#tolerance").value = d.tolerance; $("#tolOut").textContent = Number(d.tolerance).toFixed(2); }

    $("#stRec").textContent = d.stats.recognized; $("#stUnk").textContent = d.stats.unknown;
    $("#stBuz").textContent = d.stats.buzzer; $("#stPpl").textContent = d.people;

    const list = $("#logList");
    list.replaceChildren();
    if (!d.events.length) {
      const li = document.createElement("li"); li.className = "empty";
      li.textContent = "Nothing yet. Events appear here when Mini-Bot sees someone."; list.append(li);
    }
    d.events.forEach((ev) => {
      const li = document.createElement("li"); li.className = ev.kind;
      const dot = document.createElement("span"); dot.className = "dot";
      const body = document.createElement("div"); body.className = "body";
      if (ev.snap) { const im = document.createElement("img"); im.src = `/api/event/${ev.id}.jpg`; im.alt = ""; body.append(im); }
      const t = document.createElement("div");
      const b = document.createElement("b"); b.textContent = ev.title;
      const sm = document.createElement("small"); sm.textContent = ev.detail;
      t.append(b, sm); body.append(t);
      const tm = document.createElement("time"); tm.textContent = ev.time;
      li.append(dot, body, tm); list.append(li);
    });

    // toast for events that arrived since the last poll
    const newest = d.events.length ? d.events[0].id : 0;
    if (lastEventId === null) lastEventId = newest;
    else if (newest > lastEventId) {
      d.events.filter((e) => e.id > lastEventId && e.kind !== "info").reverse().forEach((e) => toast(e.kind, e.title, e.detail));
      lastEventId = newest;
    }
  }

  function setConn(up, text) {
    const c = $("#conn"); c.className = "conn " + (up ? "up" : "down"); c.lastElementChild.textContent = text;
  }

  async function poll() {
    try {
      const d = await (await fetch("/api/status")).json();
      setConn(true, d.running ? (d.mode === "demo" ? "Demo mode" : "Camera live") : "Stopped");
      if ($("#stage")) renderDashboard(d);
    } catch { setConn(false, "Server not reachable"); }
    setTimeout(poll, 800);
  }

  if ($("#stage")) {
    $("#powerBtn").addEventListener("click", () => send("/api/control", { action: running ? "stop" : "start" }));
    $("#testBuzzer").addEventListener("click", () => send("/api/control", { action: "test_buzzer" }));
    $("#buzzerToggle").addEventListener("change", (e) => send("/api/settings", { buzzer_enabled: e.target.checked }));
    $("#tolerance").addEventListener("input", (e) => {
      tolTouched = Date.now(); $("#tolOut").textContent = Number(e.target.value).toFixed(2);
      send("/api/settings", { tolerance: Number(e.target.value) });
    });
    const nb = $("#notifyBtn");
    if (!("Notification" in window)) nb.hidden = true;
    else {
      const sync = () => { if (Notification.permission === "granted") { nb.textContent = "Browser alerts on"; nb.disabled = true; } };
      sync();
      nb.addEventListener("click", () => Notification.requestPermission().then(sync));
    }
  }
  poll();

  /* ---------- people page ---------- */
  const grid = $("#peopleGrid");
  if (grid) {
    const msg = $("#formMsg"), form = $("#enrollForm");
    async function loadPeople() {
      const people = await (await fetch("/api/people")).json();
      grid.replaceChildren();
      if (!people.length) {
        const p = document.createElement("div"); p.className = "people-empty";
        p.textContent = "No one is enrolled yet. Add a face on the left."; grid.append(p); return;
      }
      people.forEach((p) => {
        const card = document.createElement("article"); card.className = "person";
        const img = document.createElement("img"); img.src = `/known_faces/${p.image}`; img.alt = p.name;
        const box = document.createElement("div");
        const b = document.createElement("b"); b.textContent = p.name;
        const s = document.createElement("span"); s.textContent = p.role || "No role set";
        const del = document.createElement("button"); del.type = "button"; del.textContent = "Remove";
        del.addEventListener("click", async () => {
          if (!confirm(`Remove ${p.name}? Their face will no longer be recognized.`)) return;
          await fetch(`/api/people/${p.id}`, { method: "DELETE" }); loadPeople();
        });
        box.append(b, s, document.createElement("br"), del); card.append(img, box); grid.append(card);
      });
    }
    form.addEventListener("change", () => {
      const cam = form.source.value === "camera";
      $("#photoField").hidden = cam; $("#cameraHint").hidden = !cam;
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); msg.className = "form-msg"; msg.textContent = "Adding…";
      const r = await fetch("/api/people", { method: "POST", body: new FormData(form) });
      const data = await r.json();
      if (r.ok) { msg.className = "form-msg ok"; msg.textContent = `${data.name} added.`; form.reset(); form.dispatchEvent(new Event("change")); loadPeople(); }
      else { msg.className = "form-msg err"; msg.textContent = data.error || "Could not add this person."; }
    });
    loadPeople();
  }
})();
