/**
 * TELEGRAM COACH — keeps you on track with short DeepSeek-written nudges.
 * Runs inside the same Google Sheet (no server). Your keys live only in YOUR Settings tab.
 *
 * Setup:
 *  1. Telegram: message @BotFather -> /newbot -> copy the token into Settings "Telegram Bot Token".
 *  2. DeepSeek: platform.deepseek.com -> API keys -> paste into Settings "DeepSeek API Key".
 *  3. Apps Script: Project Settings -> set your time zone (reminders use it).
 *  4. Menu: Clipper CRM -> Start Telegram coach. Then send /start to your bot once (it saves your chat id).
 *
 * Chat commands: /status  /today  /pay 150 Podcast Name  /help  — anything else = chat with the coach.
 */

var COACH_ROWS = [
  ['Telegram Bot Token', '', 'From @BotFather. Keep private.'],
  ['Telegram Chat ID', '', 'Auto-filled when you send /start to your bot'],
  ['DeepSeek API Key', '', 'platform.deepseek.com — optional; without it you get plain reminders'],
  ['Reminder Times (24h, comma separated)', '09:00,12:00,15:00,18:00,20:30', 'In the Apps Script project time zone'],
  ['Coach Style', 'Direct, upbeat, 1-2 short sentences, no fluff. Push me to hit my daily DM goal.', 'Personality for the DeepSeek replies']
];

function addCoachSettings_() {
  var sh = SpreadsheetApp.getActive().getSheetByName(SHEETS.settings);
  var labels = sh.getRange(1, 1, sh.getLastRow(), 1).getValues().map(function (r) { return r[0]; });
  COACH_ROWS.forEach(function (r) {
    if (labels.indexOf(r[0]) === -1) sh.appendRow(r);
  });
}

function setSetting_(label, value) {
  var sh = SpreadsheetApp.getActive().getSheetByName(SHEETS.settings);
  var data = sh.getRange(1, 1, sh.getLastRow(), 1).getValues();
  for (var i = 0; i < data.length; i++) if (data[i][0] === label) { sh.getRange(i + 1, 2).setValue(value); return; }
}

/* ------------------------------------------------ Telegram + DeepSeek plumbing */

function tg_(method, payload) {
  var token = String(setting_('Telegram Bot Token')).trim();
  if (!token) throw new Error('Add your Telegram Bot Token in Settings.');
  var res = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/' + method, {
    method: 'post', contentType: 'application/json', payload: JSON.stringify(payload || {}), muteHttpExceptions: true });
  return JSON.parse(res.getContentText());
}

function send_(text) {
  var chat = String(setting_('Telegram Chat ID')).trim();
  if (!chat) return;
  tg_('sendMessage', { chat_id: chat, text: text });
}

function stats_() {
  var d = SpreadsheetApp.getActive().getSheetByName(SHEETS.dash);
  var v = d.getRange('B4:B31').getValues().map(function (r) { return r[0]; });
  return { goal: v[0], earned: v[1], remaining: v[2], daysLeft: v[4], perDay: v[5],
           sentToday: v[9], dailyGoal: v[10], toSend: v[11], fresh: v[13], followups: v[14],
           replies: v[18], clients: v[20] };
}

function statsLine_() {
  var s = stats_();
  return 'Sent today: ' + s.sentToday + '/' + s.dailyGoal + ' | Follow-ups due: ' + s.followups +
    ' | Fresh leads: ' + s.fresh + ' | Earned this month: $' + Math.round(s.earned) + ' of $' + s.goal +
    ' | Need ~$' + Math.round(s.perDay) + '/day | Clients: ' + s.clients;
}

function deepseek_(userText) {
  var key = String(setting_('DeepSeek API Key')).trim();
  if (!key) return null;
  var props = PropertiesService.getScriptProperties();
  var hist = JSON.parse(props.getProperty('coach_hist') || '[]');
  var sys = 'You are a personal accountability coach for a solo podcast-clipper trying to earn $' + setting_('Monthly Goal ($)') +
    '/month by DMing free sample clips to podcasters. ' + setting_('Coach Style') +
    ' Never exceed 2 short sentences. Live stats: ' + statsLine_() + '. Local time: ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'EEE HH:mm') + '.';
  var msgs = [{ role: 'system', content: sys }].concat(hist.slice(-6), [{ role: 'user', content: userText }]);
  try {
    var res = UrlFetchApp.fetch('https://api.deepseek.com/chat/completions', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: { Authorization: 'Bearer ' + key },
      payload: JSON.stringify({ model: 'deepseek-chat', messages: msgs, max_tokens: 120, temperature: 0.8 }) });
    var out = JSON.parse(res.getContentText()).choices[0].message.content.trim();
    hist.push({ role: 'user', content: userText }, { role: 'assistant', content: out });
    props.setProperty('coach_hist', JSON.stringify(hist.slice(-12)));
    return out;
  } catch (e) { return null; }
}

/* ------------------------------------------------ message handling */

function handleMessage_(text) {
  var t = text.trim(), m;
  if (/^\/(start|help)/i.test(t)) {
    return "Coach online. /status = numbers, /today = what's left, /pay 150 Podcast Name = log money. Or just talk to me.";
  }
  if (/^\/status/i.test(t)) return statsLine_();
  if (/^\/today/i.test(t)) {
    var s = stats_();
    return s.toSend > 0 ? s.toSend + ' DMs to go today. Open the Today tab and knock out the next 10.' : 'Daily goal hit. Clip tomorrow\'s batch or work follow-ups (' + s.followups + ' due).';
  }
  if ((m = t.match(/^\/pay\s+\$?([\d.]+)\s*(.*)$/i))) {
    SpreadsheetApp.getActive().getSheetByName(SHEETS.pay).appendRow([new Date(), m[2] || 'Unassigned', Number(m[1]), 'Other', 'via Telegram']);
    return 'Logged $' + m[1] + (m[2] ? ' for ' + m[2] : '') + '. ' + (deepseek_('I just got paid $' + m[1] + '. React in one short line.') || 'Nice work.');
  }
  return deepseek_(t) || 'Add a DeepSeek API key in Settings for chat. Try /status or /today.';
}

function pollTelegram_() {
  var token = String(setting_('Telegram Bot Token')).trim();
  if (!token) return;
  var props = PropertiesService.getScriptProperties();
  var offset = Number(props.getProperty('tg_offset') || 0);
  var r = tg_('getUpdates', { offset: offset, timeout: 0, allowed_updates: ['message'] });
  (r.result || []).forEach(function (u) {
    offset = u.update_id + 1;
    var msg = u.message;
    if (!msg || !msg.text) return;
    var chat = String(setting_('Telegram Chat ID')).trim();
    if (!chat) { setSetting_('Telegram Chat ID', String(msg.chat.id)); chat = String(msg.chat.id); }
    if (String(msg.chat.id) !== chat) return; // ignore strangers
    send_(handleMessage_(msg.text));
  });
  props.setProperty('tg_offset', String(offset));
}

function remindersDue_() {
  var times = String(setting_('Reminder Times (24h, comma separated)')).split(',').map(function (x) { return x.trim(); }).filter(Boolean);
  var tz = Session.getScriptTimeZone(), now = new Date();
  var today = Utilities.formatDate(now, tz, 'yyyy-MM-dd');
  var nowMin = Number(Utilities.formatDate(now, tz, 'H')) * 60 + Number(Utilities.formatDate(now, tz, 'm'));
  var props = PropertiesService.getScriptProperties();
  times.forEach(function (t) {
    var p = t.split(':'), mins = Number(p[0]) * 60 + Number(p[1] || 0), key = 'rem_' + today + '_' + t;
    if (nowMin >= mins && nowMin < mins + 30 && !props.getProperty(key)) {
      props.setProperty(key, '1');
      var s = stats_();
      var fallback = 'Check-in: ' + s.sentToday + '/' + s.dailyGoal + ' DMs sent. ' + (s.toSend > 0 ? 'Send the next 10 now.' : 'Goal hit — work follow-ups.');
      send_(deepseek_('Time for my scheduled check-in. Nudge me based on my stats.') || fallback);
    }
  });
}

function coachTick() {
  try { pollTelegram_(); } catch (e) {}
  try { remindersDue_(); } catch (e) {}
}

/* ------------------------------------------------ menu actions */

function startCoach() {
  addCoachSettings_();
  stopCoach(true);
  ScriptApp.newTrigger('coachTick').timeBased().everyMinutes(1).create();
  SpreadsheetApp.getUi().alert('Coach started. Open your bot in Telegram and send /start once. It checks messages every minute.');
}

function stopCoach(silent) {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'coachTick') ScriptApp.deleteTrigger(t); });
  if (silent !== true) SpreadsheetApp.getUi().alert('Coach stopped.');
}

function testCoach() {
  var chat = String(setting_('Telegram Chat ID')).trim();
  if (!chat) { SpreadsheetApp.getUi().alert('Send /start to your bot first (and keep the coach running), so it learns your chat id.'); return; }
  send_(deepseek_('Say hi and tell me what to do right now, based on my stats.') || 'Test message from your Clipper CRM coach.');
}
