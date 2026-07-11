const state = { habits: [], token: "", saved: "", busy: true };
const list = document.querySelector("#habits");
const template = document.querySelector("#habit-template");
const saveButton = document.querySelector("#save");
const addButton = document.querySelector("#add");
const syncButton = document.querySelector("#sync");
const connection = document.querySelector("#connection");
const notice = document.querySelector("#notice");

function snapshot() { return JSON.stringify(state.habits); }
function setNotice(message, error = false) {
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = !message;
}
function updateControls() {
  document.querySelector("#count").textContent = state.habits.length;
  document.querySelector("#empty").hidden = state.habits.length !== 0 || state.busy;
  addButton.disabled = state.busy || state.habits.length >= 10;
  saveButton.disabled = state.busy || snapshot() === state.saved || list.querySelector(":invalid") !== null;
}

function normalizeInput(input) {
  input.value = input.value.toUpperCase().replace(input.classList.contains("code") ? /[^A-Z0-9]/g : /[^A-Z0-9 ]/g, "");
}

function render() {
  list.replaceChildren();
  state.habits.sort((a, b) => a.id - b.id).forEach((habit) => {
    const row = template.content.firstElementChild.cloneNode(true);
    row.dataset.id = habit.id;
    row.querySelector(".slot").textContent = habit.id + 1;
    const code = row.querySelector(".code");
    const name = row.querySelector(".name");
    const minutes = row.querySelector(".minutes");
    const minutesField = row.querySelector(".minutes-field");
    code.value = habit.code;
    name.value = habit.name;
    minutes.value = habit.minutes;
    row.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.name = `mode-${habit.id}`;
      radio.checked = radio.value === habit.mode;
    });
    minutes.disabled = habit.mode === "count";
    minutesField.hidden = habit.mode === "count";

    [code, name].forEach((input) => input.addEventListener("input", () => {
      normalizeInput(input);
      habit[input.classList.contains("code") ? "code" : "name"] = input.value.trimStart();
      updateControls();
    }));
    minutes.addEventListener("input", () => {
      habit.minutes = Number(minutes.value);
      updateControls();
    });
    row.querySelectorAll('input[type="radio"]').forEach((radio) => radio.addEventListener("change", () => {
      if (!radio.checked) return;
      habit.mode = radio.value;
      if (habit.mode === "count") habit.minutes = 1;
      minutes.value = habit.minutes;
      minutes.disabled = habit.mode === "count";
      minutesField.hidden = habit.mode === "count";
      updateControls();
    }));
    row.querySelector(".remove").addEventListener("click", () => {
      state.habits = state.habits.filter((item) => item.id !== habit.id);
      render();
    });
    list.append(row);
  });
  list.setAttribute("aria-busy", String(state.busy));
  updateControls();
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Ett oväntat fel inträffade.");
  return payload;
}

async function load() {
  state.busy = true;
  render();
  try {
    const payload = await request("/api/config");
    state.habits = payload.habits;
    state.token = payload.token;
    state.saved = snapshot();
    connection.textContent = `Ansluten via ${payload.port}`;
    connection.classList.add("connected");
    setNotice("");
  } catch (error) {
    connection.textContent = "Ingen TickStone hittades";
    connection.classList.remove("connected");
    setNotice(error.message, true);
  } finally {
    state.busy = false;
    render();
  }
}

addButton.addEventListener("click", () => {
  const used = new Set(state.habits.map((habit) => habit.id));
  const id = Array.from({ length: 10 }, (_, index) => index).find((index) => !used.has(index));
  if (id === undefined) return;
  state.habits.push({ id, code: "", name: "", mode: "count", minutes: 1 });
  render();
  list.querySelector(`[data-id="${id}"] .code`).focus();
});

saveButton.addEventListener("click", async () => {
  if (list.querySelector(":invalid") !== null) return;
  state.busy = true;
  setNotice("");
  updateControls();
  try {
    const payload = await request("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-TickStone-Token": state.token },
      body: JSON.stringify({ habits: state.habits }),
    });
    state.habits = payload.habits;
    state.saved = snapshot();
    setNotice("Inställningarna är sparade på TickStone.");
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    state.busy = false;
    render();
  }
});

syncButton.addEventListener("click", async () => {
  syncButton.disabled = true;
  try {
    await request("/api/sync", { method: "POST", headers: { "X-TickStone-Token": state.token } });
    setNotice("Bluetooth-synk är tillgänglig i upp till 60 sekunder.");
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    syncButton.disabled = false;
  }
});

load();
