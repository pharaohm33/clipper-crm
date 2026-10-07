/**
 * CLIPPER CRM — Google Sheets + Apps Script
 * Goal: $5,000/mo clipping podcasts. Find podcasts on YouTube -> pull their socials
 * (Instagram / X / TikTok / link-in-bio, NO email) -> DM a free sample clip -> track $ per influencer.
 *
 * SETUP (2 min):
 *  1. New Google Sheet -> Extensions -> Apps Script -> delete default code -> paste this file -> Save.
 *  2. Run setupCRM() once (approve permissions). Reload the sheet; a "Clipper CRM" menu appears.
 *  3. Settings tab: paste a free YouTube Data API v3 key (console.cloud.google.com -> enable
 *     "YouTube Data API v3" -> Credentials -> API key).
 *  4. Menu: Clipper CRM -> Find podcasts (from Search Queue)   [fills Leads]
 *     Menu: Clipper CRM -> Build today's outreach list         [fills Today tab]
 */

var SHEETS = {
  dash: 'Dashboard', leads: 'Leads', today: 'Today', clients: 'Clients',
  pay: 'Payments', team: 'Team Pay', log: 'Daily Outreach Log', kpi: 'KPI Summary', queue: 'Search Queue', quick: 'Quick Add', helper: 'Search Helper', settings: 'Settings'
};
var STATUSES = ['New', 'Sample Sent', 'Replied', 'Interested', 'Client', 'No Response', 'Not Interested'];
var L = { added: 1, name: 2, niche: 3, url: 4, subs: 5, last: 6, episode: 7, ig: 8, x: 9, tt: 10, web: 11,
          status: 12, sent: 13, follow: 14, notes: 15, dm: 16, cid: 17 };
var QUERY_TEMPLATES = ['{n} podcast full episode', '{n} podcast interview', 'how to start a {n} podcast', '{n} podcast new episode'];
var MAX_MS = 5 * 60 * 1000;

/* ---------------------------------------------------------------- menu / setup */

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Clipper CRM')
    .addItem("Build today's outreach list", 'buildTodayList')
    .addItem('Find podcasts (from Search Queue)', 'findPodcasts')
    .addItem('Process Quick Add links', 'processQuickAdd')
    .addSeparator()
    .addItem('Mark selected Leads rows as Sample Sent', 'markSelectedSent')
    .addItem('Refresh Search Helper links', 'buildSearchHelper')
    .addItem('Set website sync password', 'setSyncPassword')
    .addItem('Run setup again (safe, keeps data)', 'setupCRM')
    .addToUi();
}

function setupCRM() {
  var ss = SpreadsheetApp.getActive();
  var names = Object.keys(SHEETS).map(function (k) { return SHEETS[k]; });
  names.forEach(function (n) { if (!ss.getSheetByName(n)) ss.insertSheet(n); });
  var first = ss.getSheetByName('Sheet1');
  if (first && ss.getSheets().length > 1 && first.getLastRow() === 0) ss.deleteSheet(first);
  names.forEach(function (n, i) { ss.setActiveSheet(ss.getSheetByName(n)); ss.moveActiveSheet(i + 1); });

  setupSettings_(ss); setupLeads_(ss); setupClients_(ss); setupPayments_(ss); setupTeam_(ss);
  setupQueue_(ss); setupQuick_(ss); setupToday_(ss); setupDashboard_(ss); setupBotTabs_(ss); buildSearchHelper();
  ss.setActiveSheet(ss.getSheetByName(SHEETS.dash));
  SpreadsheetApp.getUi().alert('CRM ready. Paste your YouTube API key in Settings!B2, then use the Clipper CRM menu.');
}

function header_(sh, labels, color) {
  sh.getRange(1, 1, 1, labels.length).setValues([labels]).setFontWeight('bold')
    .setBackground(color || '#111827').setFontColor('#ffffff');
  sh.setFrozenRows(1);
}

function setupSettings_(ss) {
  var sh = ss.getSheetByName(SHEETS.settings);
  if (sh.getLastRow() > 1) return; // keep user's values
  var rows = [
    ['Setting', 'Value', 'Notes'],
    ['YouTube API Key', '', 'Free key from Google Cloud Console (YouTube Data API v3)'],
    ['Monthly Goal ($)', 5000, ''],
    ['Daily Outreach Goal', 100, 'Samples sent per day'],
    ['Min Subscribers', 1000, 'Skip tiny channels'],
    ['Max Subscribers', 150000, 'Skip channels with gatekeepers'],
    ['Max Days Since Last Upload', 60, 'Only active podcasts'],
    ['Follow-Up Days', 3, 'Days after sample before follow-up is due'],
    ['Query Templates Per Niche', 3, '1-4. Each costs 100 API quota units (10,000/day free)'],
    ['DM Template', 'Hey! Just watched your latest episode on {niche} and loved it. I made a quick clip from it because it deserved more eyes. Totally free, just thought you\'d like to see it. Here\'s the full episode I pulled it from: {episode}',
     'Tokens: {name} {niche} {episode}. Attach the clip when you DM.']
  ];
  sh.getRange(1, 1, rows.length, 3).setValues(rows);
  header_(sh, rows[0]);
  sh.setColumnWidth(1, 220); sh.setColumnWidth(2, 420); sh.setColumnWidth(3, 420);
  sh.getRange('B10').setWrap(true);
  ss.setNamedRange('GOAL', sh.getRange('B3'));
  ss.setNamedRange('DAILY_GOAL', sh.getRange('B4'));
  ss.setNamedRange('DM_TEMPLATE', sh.getRange('B10'));
}

function setting_(label) {
  var sh = SpreadsheetApp.getActive().getSheetByName(SHEETS.settings);
  var data = sh.getRange(1, 1, sh.getLastRow(), 2).getValues();
  for (var i = 0; i < data.length; i++) if (data[i][0] === label) return data[i][1];
  return '';
}

function setupLeads_(ss) {
  var sh = ss.getSheetByName(SHEETS.leads);
  header_(sh, ['Date Added', 'Podcast / Channel', 'Niche', 'YouTube Channel', 'Subscribers', 'Last Upload', 'Episode To Clip',
    'Instagram', 'X / Twitter', 'TikTok', 'Website / Link-in-bio', 'Status', 'Sample Sent', 'Follow-Up Due', 'Notes', 'DM Draft', 'Channel ID']);
  sh.getRange('P2').setFormula('=ARRAYFORMULA(IF(B2:B="","",SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(DM_TEMPLATE,"{name}",B2:B),"{niche}",C2:C),"{episode}",G2:G)))');
  sh.getRange('A2:A').setNumberFormat('yyyy-mm-dd');
  sh.getRange('F2:F').setNumberFormat('yyyy-mm-dd');
  sh.getRange('M2:N').setNumberFormat('yyyy-mm-dd');
  sh.getRange('E2:E').setNumberFormat('#,##0');
  sh.getRange('L2:L2000').setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUSES, true).build());
  var rules = [
    ['Client', '#bbf7d0'], ['Interested', '#fde68a'], ['Replied', '#bfdbfe'], ['Sample Sent', '#e9d5ff'],
    ['Not Interested', '#fecaca'], ['No Response', '#e5e7eb']
  ].map(function (p) {
    return SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(p[0]).setBackground(p[1]).setRanges([sh.getRange('L2:L2000')]).build();
  });
  sh.setConditionalFormatRules(rules);
  [100, 220, 120, 200, 90, 90, 220, 190, 150, 150, 200, 110, 100, 100, 220, 380, 150].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.hideColumns(L.cid);
  if (!sh.getFilter()) sh.getRange(1, 1, sh.getMaxRows(), 17).createFilter();
}

function setupClients_(ss) {
  var sh = ss.getSheetByName(SHEETS.clients);
  header_(sh, ['Influencer / Podcast', 'Instagram / Contact', 'Deal (e.g. $/clip, retainer)', 'Start Date', 'Status', 'Clips Posted', 'Total Earned', 'This Month', 'Notes'], '#065f46');
  sh.getRange('G2').setFormula('=ARRAYFORMULA(IF(A2:A="","",SUMIF(Payments!B:B,A2:A,Payments!C:C)))');
  sh.getRange('H2').setFormula('=ARRAYFORMULA(IF(A2:A="","",SUMIFS(Payments!C:C,Payments!B:B,A2:A,Payments!A:A,">="&DATE(YEAR(TODAY()),MONTH(TODAY()),1))))');
  sh.getRange('G2:H').setNumberFormat('$#,##0.00');
  sh.getRange('D2:D').setNumberFormat('yyyy-mm-dd');
  sh.getRange('E2:E1000').setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(['Active', 'Paused', 'Ended'], true).build());
  [220, 190, 220, 100, 90, 90, 110, 110, 260].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
}

function setupPayments_(ss) {
  var sh = ss.getSheetByName(SHEETS.pay);
  header_(sh, ['Date', 'Influencer / Podcast', 'Amount ($)', 'Source', 'Notes'], '#1d4ed8');
  sh.getRange('A2:A').setNumberFormat('yyyy-mm-dd');
  sh.getRange('C2:C').setNumberFormat('$#,##0.00');
  sh.getRange('B2:B2000').setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInRange(ss.getSheetByName(SHEETS.clients).getRange('A2:A1000'), true).setAllowInvalid(true).build());
  sh.getRange('D2:D2000').setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInList(['Retainer', 'Per clip', 'Rev share', 'Whop', 'Bonus', 'Other'], true).build());
  [110, 240, 110, 120, 300].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
}

function setupTeam_(ss) {
  var sh = ss.getSheetByName(SHEETS.team);
  header_(sh, ['Date', 'Clipper (employee)', 'Influencer / Podcast', 'Clips Delivered', 'Pay Per Clip ($)', 'Owed ($)', 'Paid?'], '#4338ca');
  sh.getRange('F2').setFormula('=ARRAYFORMULA(IF(D2:D="","",D2:D*E2:E))');
  sh.getRange('A2:A').setNumberFormat('yyyy-mm-dd');
  sh.getRange('E2:F').setNumberFormat('$#,##0.00');
  sh.getRange('G2:G1000').insertCheckboxes();
  [110, 190, 240, 110, 120, 100, 70].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.getRange('A1').setNote('Once you hire: log clips each clipper delivers. Dashboard subtracts Owed from earnings to show profit.');
}

/** Tabs your Telegram Executive Coach bot reads/writes (same names/columns as its CRM template). */
function setupBotTabs_(ss) {
  var log = ss.getSheetByName(SHEETS.log);
  if (log.getLastRow() < 1) header_(log, ['Date', 'Contacts Made', 'Follow-ups', 'Replies', 'Meetings Booked', 'Sales Closed', 'Notes'], '#0f766e');
  log.setColumnWidths(1, 7, 120);
  var kpi = ss.getSheetByName(SHEETS.kpi);
  kpi.clear();
  var rows = [
    ['Metric', 'Value', 'Notes'],
    ['Monthly Income', '=Dashboard!B5', 'Auto: payments this month'],
    ['Monthly Expenses', '=Dashboard!B29', 'Auto: team pay owed this month'],
    ['Monthly Profit', '=B2-B3', 'Auto-calculated'],
    ['12-Month Income Goal', '=GOAL*12', 'Auto: monthly goal x 12'],
    ['Total Contacts (samples sent)', '=Dashboard!B21', 'Auto from Leads'],
    ['Total Sales Closed (clients won)', '=Dashboard!B24', 'Auto from Leads'],
    ['Contacts per Sale', '=IF(B7=0,"",B6/B7)', 'Auto-calculated — lower is better'],
    ['DMs sent today vs goal', '=Dashboard!B13&" / "&DAILY_GOAL', 'Auto'],
    ['Follow-ups due', '=Dashboard!B18', 'Auto']
  ];
  kpi.getRange(1, 1, rows.length, 3).setValues(rows);
  kpi.getRange(1, 1, 1, 3).setFontWeight('bold').setBackground('#0f766e').setFontColor('#fff');
  kpi.getRange('B2:B5').setNumberFormat('$#,##0');
  kpi.setColumnWidths(1, 3, 240);
}

function setupQueue_(ss) {
  var sh = ss.getSheetByName(SHEETS.queue);
  header_(sh, ['Niche / Keyword (one per row)', 'Last Run', 'New Leads Found'], '#7c2d12');
  if (sh.getLastRow() < 2) {
    var niches = ['real estate', 'personal finance', 'fitness', 'entrepreneurship', 'mental health', 'true crime', 'faith christian', 'sports betting', 'parenting', 'health longevity'];
    sh.getRange(2, 1, niches.length, 1).setValues(niches.map(function (n) { return [n]; }));
  }
  sh.getRange('B2:B').setNumberFormat('yyyy-mm-dd hh:mm');
  sh.setColumnWidth(1, 260); sh.setColumnWidth(2, 150); sh.setColumnWidth(3, 130);
}

function setupQuick_(ss) {
  var sh = ss.getSheetByName(SHEETS.quick);
  header_(sh, ['Paste YouTube video / channel / @handle links (one per row)', 'Niche (optional)', 'Result'], '#7c2d12');
  sh.setColumnWidth(1, 460); sh.setColumnWidth(2, 160); sh.setColumnWidth(3, 260);
}

function setupToday_(ss) {
  var sh = ss.getSheetByName(SHEETS.today);
  header_(sh, ['Podcast', 'Instagram (click to open)', 'Other Contact', 'Episode', 'DM Draft', 'Sent?', 'Channel ID'], '#be123c');
  [220, 230, 230, 220, 480, 60, 100].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.hideColumns(7);
}

function setupDashboard_(ss) {
  var sh = ss.getSheetByName(SHEETS.dash);
  sh.clear();
  var monthStart = 'DATE(YEAR(TODAY()),MONTH(TODAY()),1)';
  var f = [
    ['CLIPPER CRM', ''],
    ['', ''],
    ['MONEY GOAL', ''],
    ['Monthly goal', '=GOAL'],
    ['Earned this month', '=SUMIFS(Payments!C:C,Payments!A:A,">="&' + monthStart + ',Payments!A:A,"<"&EDATE(' + monthStart + ',1))'],
    ['Remaining', '=MAX(0,B4-B5)'],
    ['Progress', '=IFERROR(B5/B4,0)'],
    ['Days left in month', '=EOMONTH(TODAY(),0)-TODAY()+1'],
    ['Need per day to hit goal', '=B6/B8'],
    ['All-time earned', '=SUM(Payments!C:C)'],
    ['', ''],
    ['OUTREACH (daily goal)', ''],
    ['Samples sent today (ticks + bot log)', '=COUNTIFS(Leads!M:M,">="&TODAY(),Leads!M:M,"<"&TODAY()+1)+SUMIFS(\'Daily Outreach Log\'!B:B,\'Daily Outreach Log\'!A:A,">="&TODAY(),\'Daily Outreach Log\'!A:A,"<"&TODAY()+1)'],
    ['Daily goal', '=DAILY_GOAL'],
    ['Still to send today', '=MAX(0,B14-B13)'],
    ['Sent this week', '=COUNTIFS(Leads!M:M,">="&TODAY()-WEEKDAY(TODAY(),2)+1,Leads!M:M,"<"&TODAY()+1)+SUMIFS(\'Daily Outreach Log\'!B:B,\'Daily Outreach Log\'!A:A,">="&TODAY()-WEEKDAY(TODAY(),2)+1,\'Daily Outreach Log\'!A:A,"<"&TODAY()+1)'],
    ['Fresh leads in queue', '=COUNTIF(Leads!L:L,"New")'],
    ['Follow-ups due', '=COUNTIFS(Leads!N:N,"<="&TODAY(),Leads!N:N,">0",Leads!L:L,"Sample Sent")'],
    ['', ''],
    ['FUNNEL', ''],
    ['Samples sent (all-time)', '=COUNT(Leads!M2:M)+SUM(\'Daily Outreach Log\'!B2:B)'],
    ['Replies (replied+interested+client)', '=COUNTIF(Leads!L:L,"Replied")+COUNTIF(Leads!L:L,"Interested")+COUNTIF(Leads!L:L,"Client")'],
    ['Reply rate', '=IFERROR(B22/B21,0)'],
    ['Clients won', '=COUNTIF(Leads!L:L,"Client")'],
    ['Close rate (clients / samples)', '=IFERROR(B24/B21,0)'],
    ['Active paying influencers', '=COUNTIF(Clients!E:E,"Active")'],
    ['', ''],
    ['PROFIT (after team pay)', ''],
    ['Team pay owed this month', '=SUMIFS(\'Team Pay\'!F:F,\'Team Pay\'!A:A,">="&' + monthStart + ',\'Team Pay\'!A:A,"<"&EDATE(' + monthStart + ',1))'],
    ['Unpaid team balance', '=SUMIF(\'Team Pay\'!G:G,FALSE,\'Team Pay\'!F:F)'],
    ['Profit this month', '=B5-B29']
  ];
  sh.getRange(1, 1, f.length, 2).setValues(f);
  sh.getRange('A1').setFontSize(20).setFontWeight('bold');
  ['A3', 'A12', 'A20', 'A28'].forEach(function (a) { sh.getRange(a).setFontWeight('bold').setBackground('#111827').setFontColor('#fff'); sh.getRange(a).offset(0, 1).setBackground('#111827'); });
  sh.getRange('B4:B6').setNumberFormat('$#,##0'); sh.getRange('B9:B10').setNumberFormat('$#,##0');
  sh.getRange('B7').setNumberFormat('0%'); sh.getRange('B23').setNumberFormat('0.0%'); sh.getRange('B25').setNumberFormat('0.0%');
  sh.getRange('C7').setFormula('=SPARKLINE(B5,{"charttype","bar";"max",B4;"color1","#16a34a"})');
  sh.getRange('C13').setFormula('=SPARKLINE(B13,{"charttype","bar";"max",B14;"color1","#e11d48"})');
  sh.getRange('B29:B31').setNumberFormat('$#,##0'); sh.getRange('B3:B31').setHorizontalAlignment('right');

  sh.getRange('E3').setValue('EARNINGS PER INFLUENCER').setFontWeight('bold').setBackground('#065f46').setFontColor('#fff');
  sh.getRange('F3:H3').setBackground('#065f46');
  sh.getRange('E4').setFormula('=IFERROR(QUERY(Clients!A2:H,"select A,G,H where A is not null order by G desc label A \'Influencer\', G \'All-Time\', H \'This Month\'",1),"Add influencers on the Clients tab")');
  sh.getRange('F4:G40').setNumberFormat('$#,##0.00');

  sh.getRange('J3').setValue('LAST 14 DAYS OUTREACH').setFontWeight('bold').setBackground('#be123c').setFontColor('#fff');
  sh.getRange('K3').setBackground('#be123c'); sh.getRange('L3').setBackground('#be123c');
  var rows = [];
  for (var i = 0; i < 14; i++) {
    var r = 4 + i;
    rows.push(['=TODAY()-' + i, '=COUNTIFS(Leads!M:M,">="&J' + r + ',Leads!M:M,"<"&J' + r + '+1)+SUMIFS(\'Daily Outreach Log\'!B:B,\'Daily Outreach Log\'!A:A,">="&J' + r + ',\'Daily Outreach Log\'!A:A,"<"&J' + r + '+1)',
      '=SPARKLINE(K' + r + ',{"charttype","bar";"max",DAILY_GOAL;"color1","#e11d48"})']);
  }
  sh.getRange(4, 10, 14, 3).setFormulas(rows);
  sh.getRange('J4:J17').setNumberFormat('ddd mmm d');
  sh.setColumnWidth(1, 250); sh.setColumnWidth(2, 110); sh.setColumnWidth(3, 160); sh.setColumnWidth(4, 30);
  sh.setColumnWidth(5, 220); sh.setColumnWidth(6, 100); sh.setColumnWidth(7, 100); sh.setColumnWidth(8, 30);
  sh.setColumnWidth(9, 30); sh.setColumnWidth(10, 110); sh.setColumnWidth(11, 60); sh.setColumnWidth(12, 180);
  sh.setHiddenGridlines(true);
}

function buildSearchHelper() {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(SHEETS.helper);
  sh.clear();
  header_(sh, ['Niche', 'Google: full episodes', 'Google: new / audio-only shows', 'Google AI-style: who to clip', 'Reddit r/podcasting', 'Instagram user search'], '#7c2d12');
  var q = ss.getSheetByName(SHEETS.queue);
  var n = Math.max(0, q.getLastRow() - 1);
  if (!n) return;
  var niches = q.getRange(2, 1, n, 1).getValues();
  var rows = niches.map(function (r, i) {
    var row = i + 2, c = '$A' + row;
    return [r[0],
      '=HYPERLINK("https://www.google.com/search?q="&ENCODEURL("site:youtube.com ""full episode"" "&' + c + '&" podcast"),"open")',
      '=HYPERLINK("https://www.google.com/search?q="&ENCODEURL("site:youtube.com "&' + c + '&" podcast ""no video yet"" OR ""audio only"" OR ""how to start a podcast"""),"open")',
      '=HYPERLINK("https://www.google.com/search?udm=50&q="&ENCODEURL("Small ' + '"&' + c + '&" podcasts with 5k-100k YouTube subscribers, list host Instagram handles"),"open")',
      '=HYPERLINK("https://www.google.com/search?q="&ENCODEURL("site:reddit.com/r/podcasting "&' + c + '&" clips OR editing OR promote"),"open")',
      '=HYPERLINK("https://www.instagram.com/explore/search/keyword/?q="&ENCODEURL(' + c + '&" podcast"),"open")'];
  });
  sh.getRange(2, 1, rows.length, 6).setValues(rows);
  sh.setColumnWidths(1, 6, 190);
  sh.getRange('A1').setNote('Found a good podcast manually? Paste its YouTube link in Quick Add and run "Process Quick Add links".');
}

/* ---------------------------------------------------------------- YouTube helpers */

function yt_(path, params) {
  var key = String(setting_('YouTube API Key')).trim();
  if (!key) throw new Error('Paste your YouTube API key in Settings!B2 first.');
  var qs = Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
  var res = UrlFetchApp.fetch('https://www.googleapis.com/youtube/v3/' + path + '?' + qs + '&key=' + key, { muteHttpExceptions: true });
  var j = JSON.parse(res.getContentText());
  if (j.error) throw new Error('YouTube API: ' + j.error.message);
  return j;
}

function chunk_(arr, n) { var out = []; for (var i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n)); return out; }

function existingChannelIds_() {
  var sh = SpreadsheetApp.getActive().getSheetByName(SHEETS.leads);
  var map = {};
  if (sh.getLastRow() > 1) sh.getRange(2, L.cid, sh.getLastRow() - 1, 1).getValues().forEach(function (r) { if (r[0]) map[r[0]] = true; });
  return map;
}

function extractSocials_(text) {
  var out = { ig: '', x: '', tt: '', web: '' };
  // YouTube wraps outbound links as /redirect?q=<encoded url>
  var decoded = text.replace(/\\u0026/g, '&').replace(/\\\//g, '/');
  var m, re = /[?&]q=(https?%3A%2F%2F[^&"'\\\s<]+)/g;
  while ((m = re.exec(decoded))) { try { decoded += ' ' + decodeURIComponent(m[1]); } catch (e) {} }
  var igBad = /^(p|reel|reels|explore|accounts|stories|tv|youtube|about|direct)$/i;
  var xBad = /^(intent|share|i|home|search|hashtag|youtube|login|signup|settings|privacy|tos|explore)$/i;
  var ig = /instagram\.com\/([A-Za-z0-9._]{2,30})/ig;
  while ((m = ig.exec(decoded))) if (!igBad.test(m[1])) { out.ig = 'https://instagram.com/' + m[1].replace(/\.$/, ''); break; }
  var x = /(?:twitter|x)\.com\/([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])/ig;
  while ((m = x.exec(decoded))) if (!xBad.test(m[1])) { out.x = 'https://x.com/' + m[1]; break; }
  var tt = /tiktok\.com\/@([A-Za-z0-9._]{2,30})/ig;
  if ((m = tt.exec(decoded))) out.tt = 'https://tiktok.com/@' + m[1];
  var bio = /https?:\/\/(?:www\.)?(?:linktr\.ee|beacons\.ai|stan\.store|bio\.link|linkin\.bio|lnk\.bio|campsite\.bio|solo\.to|carrd\.co)\/[^\s"'\\<>]+/i;
  var any = /https?:\/\/(?:www\.)?(?!(?:[a-z0-9.-]*)(?:youtube|youtu\.be|instagram|twitter|x\.com|tiktok|facebook|spotify|apple|google|amazon|patreon|gstatic|ggpht|googleusercontent|w3\.org|schema\.org))[a-z0-9.-]+\.[a-z]{2,}[^\s"'\\<>%]*/i;
  var b = bio.exec(decoded) || any.exec(decoded.replace(/https?%3A[^\s]*/g, ''));
  if (b) out.web = b[0].replace(/[),.]+$/, '');
  return out;
}

function aboutPageText_(channelId) {
  try {
    var res = UrlFetchApp.fetch('https://www.youtube.com/channel/' + channelId + '/about', {
      muteHttpExceptions: true, headers: { 'Cookie': 'CONSENT=YES+1; SOCS=CAI', 'Accept-Language': 'en-US,en;q=0.9',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36' }
    });
    return res.getContentText();
  } catch (e) { return ''; }
}

/** Turn candidate channels [{id, video, niche}] into Leads rows. Returns rows added. */
function addChannels_(cands, deadline) {
  var minS = Number(setting_('Min Subscribers')) || 0, maxS = Number(setting_('Max Subscribers')) || 1e12;
  var maxDays = Number(setting_('Max Days Since Last Upload')) || 36500;
  var followDays = Number(setting_('Follow-Up Days')) || 3;
  var exist = existingChannelIds_(), seen = {};
  cands = cands.filter(function (c) { if (exist[c.id] || seen[c.id]) return false; seen[c.id] = true; return true; });
  var rows = [], today = new Date();
  chunk_(cands, 50).forEach(function (grp) {
    if (Date.now() > deadline) return;
    var byId = {}; grp.forEach(function (c) { byId[c.id] = c; });
    var j = yt_('channels', { part: 'snippet,statistics,contentDetails', id: grp.map(function (c) { return c.id; }).join(','), maxResults: 50 });
    (j.items || []).forEach(function (ch) {
      if (Date.now() > deadline) return;
      var c = byId[ch.id];
      var subs = ch.statistics.hiddenSubscriberCount ? '' : Number(ch.statistics.subscriberCount || 0);
      if (!c.force && subs !== '' && (subs < minS || subs > maxS)) return;
      var last = '';
      try {
        var up = ch.contentDetails.relatedPlaylists.uploads;
        var pi = yt_('playlistItems', { part: 'contentDetails', playlistId: up, maxResults: 1 });
        if (pi.items && pi.items[0]) last = new Date(pi.items[0].contentDetails.videoPublishedAt);
      } catch (e) {}
      if (!c.force && last && (today - last) / 86400000 > maxDays) return;
      var soc = extractSocials_(ch.snippet.description || '');
      if (!soc.ig || !soc.x || !soc.tt) {
        var s2 = extractSocials_(aboutPageText_(ch.id));
        soc.ig = soc.ig || s2.ig; soc.x = soc.x || s2.x; soc.tt = soc.tt || s2.tt; soc.web = soc.web || s2.web;
      }
      if (!c.force && !(soc.ig || soc.x || soc.tt || soc.web)) return; // no contact info — not worth DMing
      var vid = c.video ? 'https://www.youtube.com/watch?v=' + c.video : '';
      var d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      rows.push([d, ch.snippet.title, c.niche || '', 'https://www.youtube.com/channel/' + ch.id, subs, last, vid,
        soc.ig, soc.x, soc.tt, soc.web, 'New', '', '', '', '', ch.id]);
    });
  });
  if (rows.length) {
    var sh = SpreadsheetApp.getActive().getSheetByName(SHEETS.leads);
    var start = Math.max(2, sh.getLastRow() + 1);
    // skip col P (formula): write A:O and Q separately
    sh.getRange(start, 1, rows.length, 15).setValues(rows.map(function (r) { return r.slice(0, 15); }));
    sh.getRange(start, L.cid, rows.length, 1).setValues(rows.map(function (r) { return [r[16]]; }));
  }
  return rows.length;
}

/* ---------------------------------------------------------------- find podcasts */

function findPodcasts() {
  var ss = SpreadsheetApp.getActive(), ui = SpreadsheetApp.getUi();
  var deadline = Date.now() + MAX_MS;
  var q = ss.getSheetByName(SHEETS.queue);
  var n = q.getLastRow() - 1;
  if (n < 1) { ui.alert('Add niches to the Search Queue tab first.'); return; }
  var tplCount = Math.min(4, Math.max(1, Number(setting_('Query Templates Per Niche')) || 3));
  var niches = q.getRange(2, 1, n, 1).getValues();
  var lastRun = q.getRange(2, 2, n, 1).getValues();
  // oldest-run niches first so repeated runs cycle through the list
  var order = niches.map(function (r, i) { return i; }).filter(function (i) { return niches[i][0]; })
    .sort(function (a, b) { return (lastRun[a][0] ? +lastRun[a][0] : 0) - (lastRun[b][0] ? +lastRun[b][0] : 0); });
  var total = 0, done = 0, err = '';
  try {
    for (var k = 0; k < order.length; k++) {
      if (Date.now() > deadline - 60000) break;
      var i = order[k], niche = String(niches[i][0]).trim(), cands = {};
      for (var t = 0; t < tplCount; t++) {
        var j = yt_('search', { part: 'snippet', type: 'video', videoDuration: 'long', maxResults: 50, order: 'relevance', q: QUERY_TEMPLATES[t].replace('{n}', niche) });
        (j.items || []).forEach(function (it) {
          var id = it.snippet.channelId;
          if (!cands[id]) cands[id] = { id: id, video: it.id.videoId, niche: niche };
        });
      }
      var added = addChannels_(Object.keys(cands).map(function (id) { return cands[id]; }), deadline);
      q.getRange(i + 2, 2).setValue(new Date()); q.getRange(i + 2, 3).setValue(added);
      total += added; done++;
    }
  } catch (e) { err = '\n\nStopped: ' + e.message; }
  ui.alert('Added ' + total + ' new leads from ' + done + ' niche(s).' + err +
    '\n\nTip: leads with no Instagram can still be reached via X/TikTok/link-in-bio — filter the Leads tab.');
}

/* ---------------------------------------------------------------- quick add */

function resolveChannelId_(url) {
  url = String(url).trim();
  var m;
  if ((m = url.match(/youtube\.com\/channel\/(UC[\w-]{20,})/))) return { id: m[1] };
  if ((m = url.match(/youtube\.com\/(@[\w.-]+)/))) {
    var j = yt_('channels', { part: 'id', forHandle: m[1] });
    return j.items && j.items[0] ? { id: j.items[0].id } : null;
  }
  var vid = null;
  if ((m = url.match(/[?&]v=([\w-]{11})/)) || (m = url.match(/youtu\.be\/([\w-]{11})/)) || (m = url.match(/youtube\.com\/(?:live|shorts|embed)\/([\w-]{11})/))) vid = m[1];
  if (vid) {
    var v = yt_('videos', { part: 'snippet', id: vid });
    return v.items && v.items[0] ? { id: v.items[0].snippet.channelId, video: vid } : null;
  }
  return null;
}

function processQuickAdd() {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName(SHEETS.quick);
  var n = sh.getLastRow() - 1;
  if (n < 1) return;
  var data = sh.getRange(2, 1, n, 3).getValues();
  var deadline = Date.now() + MAX_MS, cands = [], idx = [];
  data.forEach(function (r, i) {
    if (!r[0] || r[2]) return;
    try {
      var c = resolveChannelId_(r[0]);
      if (c) { c.niche = r[1]; c.force = true; cands.push(c); idx.push(i); }
      else sh.getRange(i + 2, 3).setValue('Could not read link');
    } catch (e) { sh.getRange(i + 2, 3).setValue('Error: ' + e.message); }
  });
  var exist = existingChannelIds_();
  var added = addChannels_(cands, deadline);
  idx.forEach(function (i, k) {
    sh.getRange(i + 2, 3).setValue(exist[cands[k].id] ? 'Already in Leads' : 'Added');
  });
  SpreadsheetApp.getActive().toast(added + ' lead(s) added.', 'Quick Add', 5);
}

/* ---------------------------------------------------------------- daily outreach list */

function spin_(t) {
  var re = /\{([^{}]*\|[^{}]*)\}/, m;
  while ((m = re.exec(t))) { var o = m[1].split('|'); t = t.replace(re, o[Math.floor(Math.random() * o.length)]); }
  return t;
}

function buildTodayList() {
  var ss = SpreadsheetApp.getActive(), leads = ss.getSheetByName(SHEETS.leads), t = ss.getSheetByName(SHEETS.today);
  var goal = Number(setting_('Daily Outreach Goal')) || 100;
  var sentToday = Number(ss.getSheetByName(SHEETS.dash).getRange('B13').getValue()) || 0;
  var want = Math.max(1, goal - sentToday);
  t.getRange(2, 1, Math.max(1, t.getMaxRows() - 1), 7).clearContent().clearDataValidations();
  var n = leads.getLastRow() - 1;
  if (n < 1) return;
  var data = leads.getRange(2, 1, n, 17).getValues();
  var fresh = data.filter(function (r) { return r[L.status - 1] === 'New' && (r[L.ig - 1] || r[L.x - 1] || r[L.tt - 1]); });
  // Instagram first (that's where you DM), then by subscriber count ascending (smaller = more likely to reply)
  fresh.sort(function (a, b) {
    var ia = a[L.ig - 1] ? 0 : 1, ib = b[L.ig - 1] ? 0 : 1;
    return ia - ib || (Number(a[L.subs - 1]) || 0) - (Number(b[L.subs - 1]) || 0);
  });
  fresh = fresh.slice(0, want);
  if (!fresh.length) { SpreadsheetApp.getUi().alert('No New leads with contact info. Run "Find podcasts" first.'); return; }
  var tpl = String(setting_('DM Template'));
  var rows = fresh.map(function (r) {
    var ig = r[L.ig - 1], other = r[L.x - 1] || r[L.tt - 1] || r[L.web - 1] || '';
    var dm = spin_(tpl).replace(/\s*[\u2014\u2013]\s*/g, ', ').replace(/\{name\}/g, r[L.name - 1]).replace(/\{niche\}/g, r[L.niche - 1]).replace(/\{episode\}/g, r[L.episode - 1]);
    return [r[L.name - 1], ig, other, r[L.episode - 1], dm, false, r[L.cid - 1]];
  });
  t.getRange(2, 1, rows.length, 7).setValues(rows);
  t.getRange(2, 6, rows.length, 1).insertCheckboxes();
  t.setActiveSelection('A2');
  SpreadsheetApp.getActive().toast(rows.length + ' leads ready. Tick "Sent?" after each DM — the CRM logs it for you.', 'Today', 8);
}

/* ---------------------------------------------------------------- status automation */

function markSent_(leadsSheet, row) {
  var today = new Date(); today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  var follow = new Date(+today + (Number(setting_('Follow-Up Days')) || 3) * 86400000);
  leadsSheet.getRange(row, L.status).setValue('Sample Sent');
  if (!leadsSheet.getRange(row, L.sent).getValue()) leadsSheet.getRange(row, L.sent).setValue(today);
  leadsSheet.getRange(row, L.follow).setValue(follow);
}

function addClientIfMissing_(name, ig) {
  var c = SpreadsheetApp.getActive().getSheetByName(SHEETS.clients);
  var n = Math.max(0, c.getLastRow() - 1);
  var names = n ? c.getRange(2, 1, n, 1).getValues().map(function (r) { return r[0]; }) : [];
  if (names.indexOf(name) > -1) return;
  var row = 2; while (c.getRange(row, 1).getValue() !== '') row++;
  c.getRange(row, 1, 1, 5).setValues([[name, ig || '', '', new Date(), 'Active']]);
}

function onEdit(e) {
  try {
    var sh = e.range.getSheet(), name = sh.getName(), row = e.range.getRow();
    if (row < 2) return;
    var leads = e.source.getSheetByName(SHEETS.leads);
    if (name === SHEETS.leads && e.range.getColumn() === L.status) {
      var v = e.range.getValue();
      if (v === 'Sample Sent') markSent_(leads, row);
      if (v === 'Client') addClientIfMissing_(sh.getRange(row, L.name).getValue(), sh.getRange(row, L.ig).getValue());
    }
    if (name === SHEETS.today && e.range.getColumn() === 6 && e.range.getValue() === true) {
      var cid = sh.getRange(row, 7).getValue();
      var ids = leads.getRange(2, L.cid, Math.max(1, leads.getLastRow() - 1), 1).getValues();
      for (var i = 0; i < ids.length; i++) if (ids[i][0] === cid) { markSent_(leads, i + 2); break; }
    }
  } catch (err) {}
}

function markSelectedSent() {
  var sh = SpreadsheetApp.getActiveSheet();
  if (sh.getName() !== SHEETS.leads) { SpreadsheetApp.getUi().alert('Select rows on the Leads tab first.'); return; }
  var r = sh.getActiveRange();
  for (var i = 0; i < r.getNumRows(); i++) if (r.getRow() + i > 1) markSent_(sh, r.getRow() + i);
}


/* ---------------------------------------------------------------- website sync (web app) */
/* Deploy: Deploy -> New deployment -> Web app -> Execute as: Me, Who has access: Anyone.
   Then Clipper CRM -> Set website sync password, and paste the web app URL + password in the website's Settings. */

function setSyncPassword() {
  var ui = SpreadsheetApp.getUi();
  var r = ui.prompt('Website sync password', 'Choose a password (8+ characters). You will paste the same one into the website.', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  var pw = r.getResponseText().trim();
  if (pw.length < 8) { ui.alert('Too short — use 8+ characters.'); return; }
  PropertiesService.getScriptProperties().setProperty('SYNC_SECRET', pw);
  ui.alert('Saved.');
}

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function doGet() { return json_({ ok: true, msg: 'Clipper CRM sync endpoint' }); }

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
    var b = JSON.parse(e.postData.contents);
    var secret = PropertiesService.getScriptProperties().getProperty('SYNC_SECRET');
    if (!secret || b.secret !== secret) return json_({ ok: false, error: 'Wrong or unset password' });
    if (b.action === 'pull') return json_({ ok: true, state: readState_() });
    if (b.action === 'append') return json_({ ok: true, added: appendLeads_(b.leads || []) });
    writeState_(b.state);
    return json_({ ok: true, at: new Date().toISOString() });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally { try { lock.releaseLock(); } catch (x) {} }
}

function d_(s) { if (!s) return ''; var p = String(s).split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
function s_(d) { return d instanceof Date ? Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd') : (d || ''); }

function replaceRows_(sh, cols, rows) {
  var max = sh.getMaxRows();
  if (max > 1) sh.getRange(2, 1, max - 1, cols).clearContent();
  if (!rows.length) return;
  if (sh.getMaxRows() < rows.length + 1) sh.insertRowsAfter(sh.getMaxRows(), rows.length + 1 - sh.getMaxRows());
  sh.getRange(2, 1, rows.length, cols).setValues(rows);
}

function writeState_(st) {
  var ss = SpreadsheetApp.getActive();
  var leads = ss.getSheetByName(SHEETS.leads);
  var lr = (st.leads || []).map(function (l) {
    return [d_(l.added), l.name, l.niche, l.url, l.subs || '', d_(l.last), l.episode, l.ig, l.x, l.tt, l.web,
            l.status, d_(l.sent), d_(l.follow), l.notes || ''];
  });
  replaceRows_(leads, 15, lr);
  var cid = ss.getSheetByName(SHEETS.leads);
  var max = cid.getMaxRows();
  if (max > 1) cid.getRange(2, L.cid, max - 1, 1).clearContent();
  if (lr.length) cid.getRange(2, L.cid, lr.length, 1).setValues((st.leads || []).map(function (l) { return [l.id]; }));

  replaceRows_(ss.getSheetByName(SHEETS.pay), 5, (st.payments || []).map(function (p) { return [d_(p.date), p.who, p.amount, 'Other', '']; }));
  replaceRows_(ss.getSheetByName(SHEETS.team), 5, (st.team || []).map(function (t) { return [d_(t.date), t.who, '', t.clips, t.rate]; }));
  (st.clients || []).forEach(function (n) { addClientIfMissing_(n, ''); });

  var g = st.settings || {};
  var set = ss.getSheetByName(SHEETS.settings);
  if (g.goal) set.getRange('B3').setValue(g.goal);
  if (g.daily) set.getRange('B4').setValue(g.daily);
}

function readState_() {
  var ss = SpreadsheetApp.getActive();
  var ls = ss.getSheetByName(SHEETS.leads), n = ls.getLastRow() - 1, leads = [];
  if (n > 0) {
    var cids = ls.getRange(2, L.cid, n, 1).getValues();
    leads = ls.getRange(2, 1, n, 15).getValues().map(function (r, i) {
      return { id: cids[i][0] || ('row' + (i + 2)), added: s_(r[0]), name: r[1], niche: r[2], url: r[3], subs: r[4] || 0, last: s_(r[5]),
        episode: r[6], ig: r[7], x: r[8], tt: r[9], web: r[10], status: r[11] || 'New', sent: s_(r[12]), follow: s_(r[13]), notes: r[14] };
    }).filter(function (l) { return l.name; });
  }
  var ps = ss.getSheetByName(SHEETS.pay), pn = ps.getLastRow() - 1;
  var payments = pn > 0 ? ps.getRange(2, 1, pn, 3).getValues().filter(function (r) { return r[1] && r[2] !== ''; })
    .map(function (r) { return { date: s_(r[0]), who: r[1], amount: Number(r[2]) }; }) : [];
  var ts = ss.getSheetByName(SHEETS.team), tn = ts.getLastRow() - 1;
  var team = tn > 0 ? ts.getRange(2, 1, tn, 5).getValues().filter(function (r) { return r[1] && r[3] !== ''; })
    .map(function (r) { return { date: s_(r[0]), who: r[1], clips: Number(r[3]), rate: Number(r[4]) }; }) : [];
  var cs = ss.getSheetByName(SHEETS.clients), cn = cs.getLastRow() - 1;
  var clients = cn > 0 ? cs.getRange(2, 1, cn, 1).getValues().map(function (r) { return r[0]; }).filter(String) : [];
  return { leads: leads, payments: payments, team: team, clients: clients };
}


function appendLeads_(leads) {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName(SHEETS.leads);
  var names = sh.getRange(2, L.name, Math.max(1, sh.getMaxRows() - 1), 1).getValues();
  var last = 1; for (var i = 0; i < names.length; i++) if (names[i][0] !== '') last = i + 2;
  var have = {};
  if (last > 1) sh.getRange(2, L.cid, last - 1, 1).getValues().forEach(function (r) { if (r[0]) have[r[0]] = true; });
  var fresh = leads.filter(function (l) { if (!l.id || have[l.id]) return false; have[l.id] = true; return true; });
  if (!fresh.length) return 0;
  if (sh.getMaxRows() < last + fresh.length) sh.insertRowsAfter(sh.getMaxRows(), last + fresh.length - sh.getMaxRows());
  sh.getRange(last + 1, 1, fresh.length, 15).setValues(fresh.map(function (l) {
    return [d_(l.added), l.name, l.niche, l.url, l.subs || '', d_(l.last), l.episode, l.ig, l.x, l.tt, l.web,
            l.status || 'New', d_(l.sent), d_(l.follow), l.notes || ''];
  }));
  sh.getRange(last + 1, L.cid, fresh.length, 1).setValues(fresh.map(function (l) { return [l.id]; }));
  return fresh.length;
}
