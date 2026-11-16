/* Browser workflow only. Scientific rules remain in filing_check.js and the shared JSON. */
(function () {
  'use strict';
  var form = document.getElementById('f'), out = document.getElementById('result');
  var check = document.getElementById('check'), download = document.getElementById('export');
  var note = document.getElementById('sample-note'), rules = null, report = null;
  var ids = ['total_hours_worked', 'annual_average_employees', 'total_deaths', 'total_dafw_cases', 'total_djtr_cases', 'total_other_cases', 'no_injuries_illnesses'];
  var limit = 'This is a plausibility screen, not an audit or a compliance determination. No flag does not establish that a filing is accurate. A flag does not identify which field is wrong. Inputs are processed locally in this browser.';
  ids.forEach(function (id) { document.getElementById(id).setAttribute('aria-describedby', 'input-help'); });
  function invalidate(message) { report = null; download.hidden = true; out.textContent = message || ''; }
  fetch('plausibility_rules.json').then(function (response) {
    if (!response.ok) throw new Error('rules unavailable');
    return response.json();
  }).then(function (value) { rules = value; check.disabled = false; check.textContent = 'Check filing'; })
    .catch(function () { check.textContent = 'Screening unavailable'; out.textContent = 'Could not load screening rules. Reload this page to retry; if opened as a file, serve this folder over HTTP.'; });
  form.addEventListener('input', function (event) {
    event.target.setCustomValidity(''); event.target.removeAttribute('aria-invalid');
    note.textContent = ''; invalidate('Inputs changed. Check the filing to update the result.');
  });
  form.addEventListener('change', function () { invalidate('Inputs changed. Check the filing to update the result.'); });
  form.addEventListener('reset', function () {
    ids.forEach(function (id) { var input = document.getElementById(id); input.setCustomValidity(''); input.removeAttribute('aria-invalid'); });
    note.textContent = ''; invalidate('All fields cleared. Enter a filing or load a sample.');
    document.getElementById(ids[0]).focus();
  });
  function sample(excessive) {
    form.reset();
    var values = [excessive ? 2000000 : 200000, 100, 0, 1, 1, 0, '1'];
    ids.forEach(function (id, i) { document.getElementById(id).value = values[i]; });
    invalidate();
    note.textContent = 'Invented sample loaded: ' + (excessive ? 'excessive hours for the employee count.' : 'typical hours for the employee count.') + ' Select Check filing to apply the rules.';
    check.focus();
  }
  document.getElementById('sample-typical').addEventListener('click', function () { sample(false); });
  document.getElementById('sample-hours').addEventListener('click', function () { sample(true); });
  form.addEventListener('submit', function (event) {
    event.preventDefault(); if (!rules) return;
    var record = {}, invalid = null;
    ids.forEach(function (id) {
      var input = document.getElementById(id), raw = input.value.trim(), value = raw.replace(/,/g, '');
      var valid = raw === '' || (/^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(raw) && Number.isFinite(Number(value)));
      if (valid && id.indexOf('total_') === 0 && id !== 'total_hours_worked' && raw !== '') valid = Number.isInteger(Number(value));
      input.setCustomValidity(valid ? '' : 'Enter a valid ' + (id !== 'total_hours_worked' && id.indexOf('total_') === 0 ? 'whole number of cases' : 'number') + ', or leave this field blank if unknown.');
      if (!valid) { input.setAttribute('aria-invalid', 'true'); if (!invalid) invalid = input; } else input.removeAttribute('aria-invalid');
      record[id] = raw === '' ? null : Number(value);
    });
    if (invalid) { invalidate('Correct the highlighted input before checking. Blank values may be screened as missing.'); invalid.focus(); invalid.reportValidity(); return; }
    var result = FilingCheck.checkFiling(record, rules);
    out.textContent = '';
    var heading = document.createElement('h2');
    heading.textContent = result.implausible ? 'Implausible' : 'No plausibility flag raised';
    heading.className = result.implausible ? 'bad' : 'ok'; out.appendChild(heading);
    var messages = result.messages.length ? result.messages : ['No rule fired.'];
    var list = document.createElement('ul'); messages.forEach(function (message) { var li = document.createElement('li'); li.textContent = message; list.appendChild(li); }); out.appendChild(list);
    var flags = Object.keys(result.flags).filter(function (key) { return result.flags[key]; });
    var bounds = 'Bounds: ' + rules.params.min_hours_per_employee + ' to ' + rules.params.max_hours_per_employee + ' hours per average employee.';
    var detail = document.createElement('p'); detail.className = 'note'; detail.textContent = 'Rules fired: ' + (flags.join(', ') || 'none') + '. ' + bounds; out.appendChild(detail);
    var caveat = document.createElement('p'); caveat.className = 'note'; caveat.textContent = limit; out.appendChild(caveat);
    report = ['Form 300A plausibility screening report', 'Created: ' + new Date().toISOString(), '', 'INPUTS'].concat(ids.map(function (id) { return id + ': ' + (record[id] === null ? 'missing' : record[id]); }), ['', 'RESULT', heading.textContent], messages, ['Rules fired: ' + (flags.join(', ') || 'none'), bounds, '', 'LIMITATIONS', limit, 'Rule specification: ' + new URL('plausibility_rules.json', location.href).href]).join('\n');
    download.hidden = false;
  });
  download.addEventListener('click', function () {
    if (!report) return;
    var url = URL.createObjectURL(new Blob([report], { type: 'text/plain;charset=utf-8' }));
    var link = document.createElement('a'); link.href = url; link.download = 'filing-screening-report.txt'; link.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  });
})();
