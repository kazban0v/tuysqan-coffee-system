'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),child=require('node:child_process');
const source=fs.readFileSync('static/js/admin-datepicker.js','utf8');
const helpers=source.slice(source.indexOf(' const pad='),source.indexOf(' // DOM binding.'));
const dates=vm.runInNewContext(helpers+';({parseISO,parseDisplay,formatted,iso,moved,monthGrid,dateValue,inRange,monthDays})',{Date});
assert.equal(dates.iso(dates.parseISO('2026-11-08')),'2026-11-08');
assert.equal(dates.formatted('2026-11-08'),'08.11.2026');
assert.equal(dates.iso(dates.parseDisplay('08.11.2026')),'2026-11-08');
assert.equal(dates.iso(dates.parseDisplay('08112026')),'2026-11-08','Numeric mobile keyboards need no punctuation key');
assert.equal(dates.parseDisplay('31022026'),null);
assert.equal(dates.iso(dates.parseDisplay('2026-11-08')),'2026-11-08','Pasted ISO dates remain supported');
assert.equal(dates.iso(dates.parseISO('0023-01-04')),'0023-01-04','Years below100 must not silently become 1900+');
for(const invalid of ['2026-02-29','1900-02-29','2024-04-31','2024-13-01','2024-00-01','0000-01-01','2026-11-00','08.11.2026','not-a-date'])assert.equal(dates.parseISO(invalid),null,invalid);
assert.equal(dates.iso(dates.parseISO('2000-02-29')),'2000-02-29');
assert.equal(dates.iso(dates.parseDisplay('29.02.2024')),'2024-02-29');
assert.equal(dates.parseDisplay('31.02.2024'),null);
assert.equal(dates.formatted(''),'', 'Empty filters stay empty');
assert.equal(dates.iso(dates.moved(dates.parseISO('2024-01-31'),1)),'2024-02-29');
assert.equal(dates.iso(dates.moved(dates.parseISO('2024-02-29'),12)),'2025-02-28');
assert.equal(dates.iso(dates.moved(dates.parseISO('2026-01-01'),0,-1)),'2025-12-31');
assert.equal(dates.iso(dates.moved(dates.parseISO('2026-03-07'),0,2)),'2026-03-09','Arrow-day arithmetic crosses DST correctly');
const grid=dates.monthGrid(2026,10);
assert.equal(grid.length,42);assert.equal(grid[0].getDay(),1);assert.equal(grid[41].getDay(),0);
assert.equal(dates.iso(grid[0]),'2026-10-26');assert.equal(dates.iso(grid[41]),'2026-12-06');
assert.equal(grid.filter(date=>date.getMonth()===10).length,30);
assert(dates.inRange('2026-11-08','2026-11-01','2026-11-30'));assert(!dates.inRange('2026-10-31','2026-11-01','2026-11-30'));
assert(dates.inRange('2026-11-08','',''));
if(!process.argv.includes('--timezone')){
 for(const zone of ['UTC','Asia/Aqtobe','America/New_York','Pacific/Kiritimati']){
  const result=child.spawnSync(process.execPath,[__filename,'--timezone'],{env:{...process.env,TZ:zone},encoding:'utf8'});
  assert.equal(result.status,0,zone+': '+result.stderr);
 }
 console.log('Admin calendar: ISO/manual dates, leap years, Monday grid, month/year/DST navigation and bounds across four timezones PASS');
}
