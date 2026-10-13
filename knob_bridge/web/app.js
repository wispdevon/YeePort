'use strict';
const $ = (id) => document.getElementById(id);
const base = document.querySelector('meta[name="yeeport-base"]').content;
const labels = {color: 'Brightness, color and white temperature', brightness: 'Brightness and on/off', switch: 'On/off'};
let snapshot = null;
let updating = false;

function message(text, error = false) {
  $('error').hidden = !error;
  $('error').textContent = error ? text : '';
  $('status').textContent = error ? '' : text;
}

async function request(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(base + path, {signal: controller.signal,
      ...(body === undefined ? {} : {method: 'POST', headers: {
        'Content-Type': 'application/json', 'X-YeePort-CSRF': snapshot.csrf}, body: JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not connect to YeePort.');
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function selected(records) {
  return records.map(({entity_id, name}) => ({entity_id, name}));
}

function render() {
  const s = snapshot;
  const used = s.builtins.length + s.imported.length;
  $('capacity').textContent = `${used} of 8 entries`;
  $('builtins').replaceChildren(...s.builtins.map((name) => element('li', name)));
  $('empty').hidden = s.imported.length > 0;
  $('imported').replaceChildren(...s.imported.map((light) => {
    const row = element('li', undefined, 'light-row');
    const details = element('div', undefined, 'light-details');
    const available = s.lights.find((item) => item.entity_id === light.entity_id)?.available;
    details.append(element('strong', light.name), element('small', light.entity_id),
      element('small', `${labels[light.controls]}${available ? '' : ' · Unavailable'}`));
    const remove = element('button', 'Remove', 'remove');
    remove.type = 'button';
    remove.setAttribute('aria-label', `Remove ${light.name}`);
    remove.disabled = updating || !s.ready || s.restarting;
    remove.addEventListener('click', () => save(selected(s.imported.filter((item) => item.entity_id !== light.entity_id))));
    row.append(element('span', light.slot, 'slot'), details, remove);
    return row;
  }));
  const previous = $('light').value;
  const imported = new Set(s.imported.map((item) => item.entity_id));
  const placeholder = new Option('Choose a light…', '', true, true);
  placeholder.disabled = true;
  $('light').replaceChildren(placeholder, ...s.lights.filter((light) => !imported.has(light.entity_id)).map((light) => {
    const option = new Option(`${light.name}${light.available ? '' : ' (unavailable)'}`, light.entity_id);
    option.disabled = !light.available;
    return option;
  }));
  $('light').value = [...$('light').options].some((option) => option.value === previous) ? previous : '';
  const disabled = updating || !s.ready || s.restarting || s.setup_needed || !s.control_enabled || s.remaining === 0;
  for (const id of ['light', 'name', 'import-button']) $(id).disabled = disabled;
  $('refresh').disabled = updating;
  $('room').textContent = s.remaining > 0 ? `${s.remaining} menu ${s.remaining === 1 ? 'entry' : 'entries'} available. A group uses one entry.` :
    'Menu full. Remove an imported light to make room. For more space, disable separate brightness controls in the app configuration.';
  $('import-form').setAttribute('aria-busy', String(updating));
}

async function waitForMenu(target) {
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    try {
      snapshot = await request('api/state');
      if (snapshot.restart_failed) throw new Error('Restart YeePort from its app page to apply the saved imports.');
      if (snapshot.ready && !snapshot.restarting && JSON.stringify(selected(snapshot.imported)) === JSON.stringify(target)) {
        updating = false;
        $('import-form').reset();
        $('light-help').textContent = 'A light group controls all its members from one menu entry.';
        for (const input of [$('light'), $('name')]) input.removeAttribute('aria-invalid');
        render();
        message('Menu updated. Hold the light’s icon on your knob to open its controls.');
        return;
      }
      render();
      message('Updating your knob’s menu… Keep it nearby and awake.');
    } catch (error) {
      if (snapshot?.restart_failed) {
        updating = false;
        render();
        message(error.message, true);
        return;
      }
      message('Reconnecting to YeePort…');
    }
  }
  updating = false;
  render();
  message('The menu is still updating. Wake the knob, then press Refresh to check again.', true);
}

async function load() {
  try {
    snapshot = await request('api/state');
    render();
    if (snapshot.setup_needed || !snapshot.control_enabled) {
      message('Import setup is incomplete. Enable light control and set the recovered display device key in the app configuration.', true);
    } else if (!snapshot.ready || snapshot.restarting) {
      updating = true;
      render();
      message('Updating your knob’s menu… Keep it nearby and awake.');
      await waitForMenu(selected(snapshot.imported));
    } else {
      message('Connected to Home Assistant. Your existing controls are ready.');
    }
  } catch (error) {
    message(error.message, true);
  }
}

async function save(lights) {
  updating = true;
  render();
  message('Saving your menu…');
  try {
    const result = await request('api/import', {lights});
    message('Updating your knob’s menu… YeePort will briefly restart.');
    await waitForMenu(selected(result.lights));
  } catch (error) {
    updating = false;
    render();
    message(error.message, true);
  }
}

$('light').addEventListener('change', () => {
  const light = snapshot.lights.find((item) => item.entity_id === $('light').value);
  if (!light) return;
  const name = light.name.replace(/[^\x20-\x7E]/g, '').trim() || light.entity_id.slice(6).replaceAll('_', ' ');
  $('name').value = name.slice(0, 24);
  $('light-help').textContent = `${labels[light.controls]}. ${light.entity_id}`;
});
$('import-form').addEventListener('submit', (event) => {
  event.preventDefault();
  save([...selected(snapshot.imported), {entity_id: $('light').value, name: $('name').value.trim()}]);
});
for (const input of [$('light'), $('name')]) {
  input.addEventListener('invalid', () => input.setAttribute('aria-invalid', 'true'));
  input.addEventListener('input', () => {
    if (input.validity.valid) input.removeAttribute('aria-invalid');
  });
}
$('refresh').addEventListener('click', load);
load();
