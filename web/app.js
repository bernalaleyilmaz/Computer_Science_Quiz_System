"use strict";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[ch]));
const state = {page: "welcome", account: null, userId: null, authMode: "login", authName: "", overview: null, detail: null, sessionId: null, position: 0, choice: null, busy: false, request: 0, profile: null, feedback: null, hostSessionId: 1, hostResults: null, hostShowAll: false};
let polling = false;
let hostToken = "";

const NAVIGATION_KEY="csquiz-navigation-v1";
const navigationPages=new Set(["welcome","sessions","quiz","results","host"]);

function saveNavigation() {
  try {
    sessionStorage.setItem(NAVIGATION_KEY,JSON.stringify({
      version:1,page:state.page,userId:state.userId,sessionId:state.sessionId,
      questionId:state.page==="quiz"?state.detail?.questions[state.position]?.question_id??null:null,
      choice:state.page==="quiz"?state.choice:null,
      hostSessionId:state.hostSessionId,hostShowAll:state.hostShowAll
    }));
  }catch(_) { /* Navigation storage is optional; database answers remain authoritative. */ }
}

function readNavigation() {
  try {
    const saved=JSON.parse(sessionStorage.getItem(NAVIGATION_KEY));
    if(!saved||saved.version!==1||!navigationPages.has(saved.page))return null;
    const validId=(id)=>id===null||(Number.isSafeInteger(id)&&id>0);
    if(!validId(saved.userId)||!validId(saved.sessionId)||!validId(saved.questionId))return null;
    if(saved.choice!==null&&!["A","B","C","D"].includes(saved.choice))return null;
    return saved;
  }catch(_) {return null;}
}

const cat = `<svg class="cat" viewBox="0 0 320 265" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M81 94 69 29Q69 13 86 24L122 57Q160 44 197 58L235 24Q250 14 251 32L241 95" fill="#fff" stroke="#70445c" stroke-width="5" stroke-linejoin="round"/>
  <path d="M77 88Q55 112 59 157Q62 220 157 224Q252 223 261 161Q270 113 238 86Q218 57 161 57Q105 57 77 88Z" fill="#fff" stroke="#70445c" stroke-width="5"/>
  <ellipse cx="118" cy="143" rx="7" ry="10" fill="#70445c"/><ellipse cx="204" cy="143" rx="7" ry="10" fill="#70445c"/>
  <ellipse cx="161" cy="161" rx="11" ry="8" fill="#f7cf70" stroke="#70445c" stroke-width="3"/>
  <path d="M46 134 81 140M39 158 78 158M46 180 82 175M238 140 277 132M241 158 285 158M238 175 278 183" stroke="#70445c" stroke-width="4" stroke-linecap="round"/>
  <ellipse cx="96" cy="170" rx="15" ry="6" fill="#fde5ef"/><ellipse cx="226" cy="170" rx="15" ry="6" fill="#fde5ef"/>
  <path d="M220 66Q191 35 186 65Q181 90 217 84M223 68Q251 43 259 66Q265 91 228 85" fill="#e971a1" stroke="#aa416f" stroke-width="4" stroke-linejoin="round"/>
  <circle cx="222" cy="77" r="12" fill="#f5a6c8" stroke="#aa416f" stroke-width="4"/>
  <path d="M99 218Q98 247 125 247L137 229M185 229 197 247Q223 247 224 216" fill="#fff" stroke="#70445c" stroke-width="4"/>
</svg>`;

function message(text = "", error = false) {
  $("notice").textContent = text;
  $("notice").hidden = !text;
  $("notice").className = error ? "error" : "";
}

async function api(path, body) {
  const headers = {};
  if (hostToken && (path === "/api/overview" || path.startsWith("/api/host-results") || path.startsWith("/api/sessions/"))) {
    headers["X-CSQuiz-Host"] = hostToken;
  }
  // Detect another tab changing accounts while this tab still shows an old quiz.
  if (state.userId && /^(\/api\/(overview|profile|session))(\?|$)/.test(path)) {
    path += `${path.includes("?")?"&":"?"}user_id=${state.userId}`;
  }
  if (state.userId && (path === "/api/answers" || path.startsWith("/api/attempts/"))) {
    body = {...body, user_id: state.userId};
  }
  const response = await fetch(path, body === undefined ? {cache: "no-store", headers} : {
    method: "POST", headers: {...headers, "Content-Type": "application/json"}, body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (response.status === 401 && state.userId && /^\/api\/(overview|profile|session\?|answers|attempts\/)/.test(path)) {
    clearLearner();
    if (state.page !== "host") goto("welcome");
  }
  if (!response.ok) throw Object.assign(new Error(payload.error || "Something went wrong. Please try again."), {status: response.status});
  return payload;
}

async function overview() {
  const data = await api("/api/overview");
  state.overview = data;
  if(state.page==="host")await loadHostResults();
  return data;
}

function user() { return state.account; }
function setLearner(account) { state.account = account; state.userId = account?.user_id ?? null; }
function clearLearner() {
  ++state.request;
  setLearner(null);
  Object.assign(state, {profile: null, detail: null, sessionId: null, position: 0, choice: null, feedback: null});
  practiceDeadline = null;
  practiceKey = null;
  try { sessionStorage.removeItem(NAVIGATION_KEY); } catch (_) {}
}
function statusName(status) { return {pending: "Not started", active: "Live now", finished: "Session ended"}[status]; }
function personalCount(id) { return state.overview.personal_progress.find((item) => item.session_id === id)?.submitted || 0; }

function steps() {
  const number = {welcome: 0, sessions: 1, quiz: 2, results: 3}[state.page];
  $("steps").hidden = state.page === "host";
  $("steps").innerHTML = ["Your account", "Your session", "Your quiz", "Your results"].map((title, index) =>
    `<span class="step ${index === number ? "active" : index < number ? "done" : ""}"><i>${index < number ? "✓" : index + 1}</i>${title}</span>`).join("");
  $("host-link").disabled = state.busy;
  $("host-link").textContent = state.page === "host" ? "Back to learners" : "Host corner";
  $("sign-out").hidden = !state.account;
  $("sign-out").disabled = state.busy;
}

function profilePreview() {
  const profile = state.profile;
  if (!profile) return `<div class="art-title">hello, curious mind!</div>${cat}<div class="sticker">pick a name to meet your profile 🎀</div>`;
  return `<div class="profile-preview"><div class="profile-cat">${cat}</div><span class="eyebrow">YOUR LITTLE LEARNING STORY</span><h2>${esc(profile.username)}</h2><p class="micro">${profile.sessions_joined ? "Every saved answer is a step forward." : "A fresh start. Your first challenge awaits!"}</p><div class="profile-stats"><div><strong>${profile.sessions_joined}</strong><span>Joined</span></div><div><strong>${profile.completed}</strong><span>Completed</span></div><div><strong>${profile.correct}</strong><span>Correct</span></div><div><strong>${profile.accuracy === null ? "—" : profile.accuracy + "%"}</strong><span>Accuracy*</span></div></div><div class="profile-badges">${profile.badges.map((badge)=>`<span>✧ ${esc(badge)}</span>`).join("") || '<span>♡ Your first badge is waiting</span>'}</div><p class="micro">*Correct / selected answers. Blanks are excluded.<br>Profile statistics come from saved answers.</p></div>`;
}

function welcome() {
  const registering = state.authMode === "register";
  return `<div class="welcome"><div class="welcome-copy"><span class="eyebrow">WELCOME TO THE  QUIZ SYSTEM</span>
    <h1>A little quiz.<br>A lot of <em>new information.</em></h1><p class="intro">Use your nickname to sign in and keep track of your quiz results.</p>
    <form id="entry-form" class="entry-form" novalidate>
    <label for="nickname">Nickname</label><input id="nickname" name="nickname" value="${esc(state.authName)}" autocomplete="username" aria-describedby="nickname-error" required ${state.busy?"disabled":""}>
    <p id="nickname-error" class="entry-error" role="alert" hidden></p>
    <label for="learner-password">Password</label><input id="learner-password" name="password" type="password" autocomplete="${registering?"new-password":"current-password"}" aria-describedby="learner-password-error" required ${state.busy?"disabled":""}>
    <p id="learner-password-error" class="entry-error" role="alert" hidden></p>
    <p id="account-error" class="entry-error" role="alert" hidden></p>
    ${registering?'<p class="micro">Use a unique nickname (3–30 characters) and a password with at least 8 characters.</p>':''}
    <button class="button wide join-button" type="submit" ${state.busy?"disabled":""}>${registering?"Create account":"Sign in"} <span aria-hidden="true">♡ →</span></button>
    <button class="text-button" type="button" data-auth-mode="${registering?"login":"register"}" ${state.busy?"disabled":""}>${registering?"Already have an account? Sign in":"New here? Create an account"}</button></form></div>
    <div class="welcome-art"><span class="sparkle s1">✧</span><span class="sparkle s2">✦</span><span class="heart">♡</span><div class="art-title">hello, curious mind!</div>${cat}<div class="sticker">your next quiz awaits 🎀</div></div></div>
    <div class="topic-strip"><span>✧ ARTIFICIAL INTELLIGENCE</span><span>✧ DATABASES</span><span>✧ APIs</span></div>`;
}

function sessions() {
  return `<div class="page-heading"><div><span class="eyebrow">YOUR QUIZ DASHBOARD</span><h1>Pick a session. Make it yours.</h1><p>Session status belongs to everyone. My progress belongs only to you.</p></div><span class="profile-pill">♡ ${esc(user()?.username)}</span></div><div class="session-grid">${state.overview.sessions.map((session)=>{
    const submitted=personalCount(session.session_id);
    const complete=session.question_count>0&&submitted===session.question_count;
    const available=session.status==="active"||(session.status==="finished"&&submitted>0);
    const label=session.status==="pending"?"Coming soon":session.status==="finished"?submitted?"View my results →":"Closed to new entries":complete?"View my results →":submitted?"Continue quiz →":"Join this quiz →";
    const mine=complete?"Completed":submitted?`${submitted}/${session.question_count} saved`:"Not attempted";
    return `<article class="session-card ${session.status}"><div class="card-top"><span class="session-number">${String(session.session_id).padStart(2,"0")}</span><span class="badge ${session.status}">${session.status==="active"?'<i class="live-dot"></i> ':""}${statusName(session.status)}</span></div><h2>${esc(session.title)}</h2><p>${session.question_count} questions · AI + Database + API</p><div class="state-line"><span>Session status</span><strong>${statusName(session.status)}</strong></div><div class="state-line"><span>My progress</span><strong>${mine}</strong></div><progress max="${session.question_count}" value="${submitted}" aria-label="My submitted answers"></progress>
    ${session.status==="pending"?session.scheduled_start_at?`<div class="schedule-label">Starts in <strong data-countdown="${esc(session.scheduled_start_at)}">—</strong></div>`:'<div class="schedule-label">Awaiting host · no start time scheduled</div>':`<div class="live-participation">${session.status==="active"?'<i class="live-dot"></i> ':""}${session.participants} ${session.participants===1?"participant":"participants"} · ${session.submitted_records} saved submissions</div><p class="micro">Shared progress: ${session.progress_percent===null?"No submissions yet":session.progress_percent+"%"}<br>Based on participants who have saved an answer.</p><progress max="100" value="${session.progress_percent||0}" aria-label="Shared session progress"></progress>`}
    <button class="button ${session.status==="active"&&!complete?"":"secondary"}" data-open="${session.session_id}" ${!available||state.busy?"disabled":""}>${label}</button>${session.status==="active"&&submitted>0?`<button class="button secondary small retake-button" data-retake="${session.session_id}" ${state.busy?"disabled":""}>Retake quiz ↻</button>`:""}</article>`;
  }).join("")}</div><div class="section-footer"><span>Sessions with no scheduled time wait for the host.</span></div>${state.profile?`<details class="host-box"><summary>My learner profile</summary>${profilePreview()}</details>`:""}`;
}

function quiz() {
  const detail=state.detail;
  if(!detail?.questions.length)return '<div class="loading">This session is not ready yet.</div>';
  state.position=Math.max(0,Math.min(state.position,detail.questions.length-1));
  const question=detail.questions[state.position];
  const saved=detail.questions.filter((item)=>item.submitted).length;
  const selected=question.submitted?question.selected_option:state.choice;
  const stats=detail.personal_stats[0]||{correct:0,wrong:0,blank:0};
  const feedback=state.feedback;
  return `<div class="quiz-layout"><div class="quiz-toolbar"><button class="text-button" data-page="sessions" ${state.busy?"disabled":""}>← Back to sessions</button><span>♡ ${esc(detail.user.username)}</span></div><div class="quiz-card"><div class="game-topbar"><div class="timer-ring"><span id="attempt-clock">15:00</span><small>remaining</small></div><div class="game-session"><strong>${esc(detail.session.title)}</strong><span>Question ${question.position} / ${detail.questions.length}</span></div><div class="live-score"><strong>${stats.correct}</strong><span>points</span></div></div><div class="question-body"><div class="question-meta"><span>${saved} SAVED · ${detail.questions.length-saved} REMAINING</span><span>${esc(question.topic)}</span></div><progress max="${detail.questions.length}" value="${saved}" aria-label="Saved answers"></progress><h1 class="question-title">${esc(question.question_text)}</h1><div class="options game-options" role="group" aria-label="Answer choices">${["A","B","C","D"].map((letter)=>{
    let verdict="";
    if(question.submitted&&question.revealed_answer){
      if(letter===question.revealed_answer)verdict="correct-option";
      else if(letter===question.selected_option)verdict="wrong-option";
    }
    return `<button class="option tone-${letter.toLowerCase()} ${selected===letter?"selected":""} ${verdict}" data-choice="${letter}" aria-pressed="${selected===letter}" ${question.submitted||state.busy?"disabled":""}><span class="letter">${letter}</span><span>${esc(question["option_"+letter.toLowerCase()])}</span>${verdict?`<span class="verdict-icon">${verdict==="correct-option"?"✓":"✕"}</span>`:""}</button>`;
  }).join("")}</div>
  ${question.submitted?`<div class="answer-feedback ${question.selected_option?question.selected_option===question.revealed_answer?"correct":"wrong":"blank"}" role="status">${question.selected_option?question.selected_option===question.revealed_answer?"✓ Lovely work! Correct answer · +1 point.":`✕ Not quite. The correct answer is ${question.revealed_answer}.`:'Blank answer saved · 0 points.'}</div><button class="button feedback-next" data-continue="1" ${state.busy?"disabled":""}>${saved===detail.questions.length?"See my results →":"Next unanswered question →"}</button>`:`<div class="question-actions"><button class="button" data-submit="answer" ${!state.choice||state.busy?"disabled":""}>${state.busy?"Saving…":"Check my answer →"}</button><button class="button secondary" data-submit="skip" ${state.busy?"disabled":""}>Leave blank</button></div><p class="micro">Your saved answer is final. Next lets you return to an unanswered question later.</p>`}
  </div><div class="question-nav"><button class="button small secondary" data-move="-1" ${state.position===0||state.busy?"disabled":""}>← Previous</button><span>${state.position+1} / ${detail.questions.length}</span><button class="button small secondary" data-move="1" ${state.position===detail.questions.length-1||state.busy?"disabled":""}>Next →</button></div></div><details class="question-map"><summary>Your question map · pink means saved</summary><div>${detail.questions.map((item,index)=>`<button data-position="${index}" class="${item.submitted?"saved":""} ${index===state.position?"current":""}" aria-label="Question ${item.position}${item.submitted?", saved":", unanswered"}" ${state.busy?"disabled":""}>${item.position}</button>`).join("")}</div></details><div class="section-footer"><span>15-minute practice timer · blanks score 0 when time expires.</span><button class="button small" id="finish-quiz" ${state.busy?"disabled":""}>Finish quiz ♡</button></div><details class="live-ranking"><summary>Live session leaderboard · provisional</summary>${ranking(detail.leaderboard,true)}</details></div>`;
}

function ranking(board,provisional=false) {
  if(!board.length)return '<p class="micro">The first submission starts the leaderboard.</p>';
  const metals=["gold","silver","bronze"];
  const top=board.slice(0,3);
  return `<div class="podium">${top.map((item,index)=>`<article class="podium-place ${metals[index]}"><div class="medal">${index===0?"♛":index===1?"✧":"✦"}</div><strong>${esc(item.username)}</strong><span>${item.score} points</span><div class="podium-block">#${item.rank}</div></article>`).join("")}</div><div class="table-wrap"><table><thead><tr><th>Rank</th><th>Learner</th><th>Correct</th><th>Wrong</th><th>Blank</th><th>Saved</th><th>Points</th></tr></thead><tbody>${board.map((item)=>`<tr class="${item.user_id===state.userId?"my-row":""}"><td>${item.rank}</td><td>${esc(item.username)}</td><td>${item.score}</td><td>${item.wrong}</td><td>${item.blank}</td><td>${item.submitted}/30</td><td>${item.score}</td></tr>`).join("")}</tbody></table></div><p class="micro">${provisional?"Live ranking changes as other learners answer.":"Final shared-session ranking."} Equal points share the same rank. Podium slots follow rank, then learner ID.</p>`;
}

function results() {
  const result = state.detail.results;
  const detail = state.detail;
  const labels = {correct: "Correct", wrong: "Wrong", skipped: "Blank", unanswered: "Unanswered"};
  return `<article class="result-card"><span class="eyebrow">${result.participated ? "A LITTLE ROUND OF APPLAUSE" : "THIS SESSION HAS ENDED"}</span><h1>${result.participated ? "You did it, curious mind!" : "No answers recorded."}</h1><p class="intro">${esc(detail.user.username)} · ${esc(detail.session.title)}<br>${detail.session.status === "active" ? "Your quiz is complete. This session stays open for other learners." : "Your saved answers have been scored."}</p>
    <div class="score-circle"><strong>${result.score}</strong><span>out of ${result.total} · ${result.percentage}%</span></div><div class="result-stats">${["correct","wrong","skipped","unanswered"].map((key) => `<div><strong>${result[key]}</strong><span>${labels[key]}</span></div>`).join("")}</div><p class="micro">Correct = 1 point. Wrong, blank and unanswered = 0.<br>All ${result.total} questions count toward your maximum score.</p>
    <div class="result-buttons"><button class="button" data-page="sessions">Choose another session →</button>${detail.session.status==="active"&&result.participated?`<button class="button secondary" data-retake="${state.sessionId}" ${state.busy?"disabled":""}>Retake quiz ↻</button>`:""}</div>
    ${result.questions.length ? `<details class="review"><summary>Review your ${result.total} questions</summary>${result.questions.map((question) => `<article><small>Question ${question.position} · ${esc(question.topic)} · ${labels[question.outcome]}</small><h3>${esc(question.question_text)}</h3><p>Your answer: ${question.selected_option ? `${question.selected_option} · ${esc(question["option_" + question.selected_option.toLowerCase()])}` : labels[question.outcome]}</p><p class="correct">Correct: ${question.correct_option} · ${esc(question["option_" + question.correct_option.toLowerCase()])}</p></article>`).join("")}</details>` : '<p class="micro">Complete answer review unlocks when the shared session ends.</p>'}<section class="result-leaderboard"><span class="eyebrow">YOUR SESSION LEADERBOARD</span><h2>Little stars, big ideas.</h2>${ranking(detail.leaderboard,detail.session.status!=="finished")}</section></article>`;
}

let hostResultsRequest=0;
async function loadHostResults() {
  const id=state.hostSessionId;
  const request=++hostResultsRequest;
  const payload=await api(`/api/host-results?session_id=${id}`);
  if(request===hostResultsRequest&&id===state.hostSessionId)state.hostResults=payload;
}

function hostResultsPanel() {
  const payload=state.hostResults;
  const session=payload?.session;
  const displayed=(payload?.results||[]).filter((item)=>state.hostShowAll||item.saved>0);
  return `<section class="host-box host-results-panel"><span class="eyebrow">SESSION RESULTS · LIVE</span><h2>Every learner, every answer.</h2><div class="host-results-controls"><div><label for="host-results-session">Choose a session</label><select id="host-results-session">${state.overview.sessions.map((item)=>`<option value="${item.session_id}" ${item.session_id===state.hostSessionId?"selected":""}>${esc(item.title)} · ${statusName(item.status)}</option>`).join("")}</select></div><label class="show-all-label"><input id="host-show-all" type="checkbox" ${state.hostShowAll?"checked":""}>Include learners with no saved answers</label></div>${session?`<p class="micro"><strong>${esc(session.title)}</strong> · ${statusName(session.status)} · ${payload.participants}/${payload.results.length} learners have saved answers.<br>${session.status==="finished"?"Session closed. These are the current saved results.":session.status==="active"?"Live results are provisional and refresh every 15 seconds.":"This session has not started yet."} Only the latest attempt counts.</p>`:""}<div class="table-wrap host-results-scroll"><table><thead><tr><th>Rank</th><th>Learner</th><th>Progress</th><th>Correct</th><th>Wrong</th><th>Blank</th><th>Unanswered</th><th>Points</th><th>Success</th></tr></thead><tbody>${displayed.map((item)=>`<tr><td>${item.rank??"—"}</td><td>${esc(item.username)}</td><td>${item.saved===0?"Not attempted":item.saved===item.total?"Completed":session.status==="finished"?"Closed, incomplete":"In progress"}<br><small>${item.saved}/${item.total} saved</small></td><td>${item.saved?item.correct:"—"}</td><td>${item.saved?item.wrong:"—"}</td><td>${item.saved?item.blank:"—"}</td><td>${item.unanswered}</td><td>${item.saved?`${item.correct}/${item.total}`:"—"}</td><td>${item.saved?item.score_percent+"%":"—"}</td></tr>`).join("") || '<tr><td colspan="9">No saved answers in this session yet. Select Include learners to view all profiles.</td></tr>'}</tbody></table></div><p class="micro">Correct = 1 point. Wrong, blank and unanswered = 0. Success uses all assigned questions; it is not the saved-submission progress.</p></section>`;
}

function host() {
  return `<div class="page-heading"><div><span class="eyebrow">THE HOST CORNER</span><h1>A little behind the scenes.</h1><p>Start, finish or reopen the same five sessions. Sessions without saved answers can be postponed. Retaking replaces only that learner’s previous answers.</p></div><button class="button secondary small" id="refresh-host" ${state.busy ? "disabled" : ""}>↻ Refresh</button></div><div class="host-box"><div class="host-list">${state.overview.sessions.map((session) => `<div class="host-row"><div><h3>${esc(session.title)} <span class="badge ${session.status}">${statusName(session.status)}</span></h3><p>${session.participants} participants · ${session.submitted_records} submitted records · ${session.progress_percent===null?"No submissions yet":session.progress_percent+"% progress"}<br>${session.started_at ? `Started: ${esc(session.started_at)} UTC` : "Not started"}${session.ended_at ? ` · Ended: ${esc(session.ended_at)} UTC` : ""}</p></div>${session.status==="pending" || session.submitted_records===0?`<div class="schedule-controls"><label for="schedule-${session.session_id}">Scheduled start (your local time)</label><input type="datetime-local" id="schedule-${session.session_id}" value="${session.scheduled_start_at?localInput(session.scheduled_start_at):""}"><button class="button secondary small" data-schedule="${session.session_id}" ${state.busy?"disabled":""}>${session.status==="pending"?"Save start time":"Postpone session"}</button></div>`:""}<button class="button secondary small" data-host="start" data-id="${session.session_id}" ${session.status === "active" || state.busy ? "disabled" : ""}>${session.status==="finished"?"Reopen session":"Start session"}</button><button class="button small" data-host="finish" data-id="${session.session_id}" ${session.status !== "active" || state.busy ? "disabled" : ""}>Finish session</button></div>`).join("")}</div></div>
    ${hostResultsPanel()}<div class="host-box"><span class="eyebrow">LEADERBOARD · FINISHED SHARED SESSIONS</span><p class="micro">Total points. Equal scores share a rank. Active sessions are excluded.</p><div class="table-wrap"><table><thead><tr><th>Rank</th><th>Learner</th><th>Sessions</th><th>Points</th><th>Success</th></tr></thead><tbody>${state.overview.leaderboard.map((item) => `<tr><td>${item.rank}</td><td>${esc(item.username)}</td><td>${item.session_count}</td><td>${item.score}/${item.maximum_score}</td><td>${item.percentage}%</td></tr>`).join("") || '<tr><td colspan="5">No finished-session scores yet.</td></tr>'}</tbody></table></div></div><p class="micro">Progress is based on learners with at least one submission. Host controls are intended for this local classroom demo.</p>`;
}

function render() {
  steps();
  $("screen").innerHTML = ({welcome, sessions, quiz, results, host}[state.page])();
  saveNavigation();
  updateClocks();
}

function goto(page) {
  state.feedback=null;
  state.page = page;
  message();
  render();
  window.scrollTo({top: 0, behavior: "instant"});
}

async function loadSession(reset = false, keepFeedback = false, renderNow = true) {
  const requestId = ++state.request;
  const detail = await api(`/api/session?session_id=${state.sessionId}`);
  if (requestId !== state.request) return;
  const changed = JSON.stringify(detail) !== JSON.stringify(state.detail);
  state.detail = detail;
  if (reset) {
    const next = detail.questions.findIndex((question) => !question.submitted);
    state.position = next < 0 ? 0 : next;
    state.choice = null;
  }
  if (detail.results && !keepFeedback) state.page = "results";
  else if (detail.session.status === "active") state.page = "quiz";
  else state.page = "sessions";
  if (renderNow && (changed || reset)) render();
}

function busy(value) { state.busy = value; render(); }

async function submit(skip) {
  if (state.busy) return;
  const question = state.detail.questions[state.position];
  if (question.submitted || (!skip && !state.choice)) return;
  const body = {session_id: state.sessionId, question_id: question.question_id, selected_option: skip ? null : state.choice};
  busy(true);
  try {
    state.feedback = await api("/api/answers", body);
    await loadSession(false, true);
    if(state.detail.completed)state.page="results";
    await overview();
    message(state.page === "results" ? "All 30 answers are saved. Here are your results!" : skip ? "Blank answer saved." : "Your answer is saved. Keep going! ♡");
  } catch (error) {
    message(error.message, true);
    try { await loadSession(false); } catch (_) { /* Preserve the original error. */ }
  } finally { busy(false); }
}

function confirm(title, description, label, cancelLabel = "Keep going") {
  $("dialog-title").textContent = title;
  $("dialog-description").textContent = description;
  $("dialog-accept").textContent = label;
  $("confirmation").querySelector('[value="cancel"]').textContent = cancelLabel;
  const dialog = $("confirmation");
  dialog.returnValue = "cancel";
  return new Promise((resolve) => { dialog.addEventListener("close", () => resolve(dialog.returnValue === "accept"), {once:true}); dialog.showModal(); });
}

async function finishQuiz() {
  if (state.busy) return;
  const remaining = state.detail.questions.filter((question) => !question.submitted).length;
  if (!await confirm("Ready for your results?", `${remaining} unanswered ${remaining === 1 ? "question will" : "questions will"} be saved as blank and earn 0 points. Only saved answers count; any current unsaved choice will be left blank. Your quiz will be final. Other learners can keep answering.`, "Finish my quiz")) return;
  busy(true);
  try {
    await api("/api/attempts/finish", {session_id: state.sessionId});
    await loadSession(false);
    await overview();
    message("Your quiz is complete. Here are your results! ♡");
    window.scrollTo({top:0,behavior:"instant"});
  } catch (error) {
    message(error.message, true);
    try { await loadSession(false); } catch (_) { /* Preserve original error. */ }
  } finally { busy(false); }
}

async function retakeQuiz(id) {
  if(state.busy)return;
  if(!await confirm("Retake this quiz?","Your previous answers and score for this session will be removed. Only your new attempt will count. Other learners keep their answers.","Retake quiz","Cancel"))return;
  busy(true);
  try {
    await api("/api/attempts/restart",{session_id:id});
    state.sessionId=id; state.detail=null; state.choice=null; state.feedback=null;
    practiceDeadline=null; practiceKey=null; lastAutoFinishAttempt=0;
    try{localStorage.removeItem(`csquiz-deadline:${state.userId}:${id}`);}catch(_){}
    await overview(); await loadSession(true); startPracticeClock();
    message("Fresh start! Only this attempt counts toward your score.");
    window.scrollTo({top:0,behavior:"instant"});
  }catch(error){message(error.message,true);}
  finally{busy(false);}
}

async function hostAction(action, sessionId) {
  if (state.busy) return;
  const target=state.overview.sessions.find((item)=>item.session_id===sessionId);
  if(action==="start"&&target.status==="finished"&&!await confirm("Reopen this session?","The same session will accept answers again. Existing learner scores stay until each learner chooses Retake quiz. No extra session is created.","Reopen session","Cancel"))return;
  if (action === "finish" && !await confirm("Finish the shared session?", "This closes answering for every learner. Unanswered questions earn 0 points and the host can reopen the same session later.", "Finish session", "Cancel")) return;
  busy(true);
  try { const response = await api(`/api/sessions/${action}`,{session_id:sessionId}); await overview(); message(response.message); }
  catch (error) { message(error.message,true); }
  finally { busy(false); }
}

async function loadProfile() {
  const id = state.userId;
  if (!id) return;
  const profile = await api("/api/profile");
  if (state.userId === id) state.profile = profile;
}

$("screen").addEventListener("change",async(event)=>{
  if(event.target.id==="host-results-session") {
    state.hostSessionId=Number(event.target.value);
    try{await loadHostResults();if(state.page==="host")render();}catch(error){message(error.message,true);}
    return;
  }
  if(event.target.id==="host-show-all") {state.hostShowAll=event.target.checked;render();return;}
});

function localInput(utc) {
  const date=new Date(utc.replace(" ","T")+"Z");
  const pad=(n)=>String(n).padStart(2,"0");
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function duration(seconds,includeHours=false) {
  seconds=Math.max(0,Math.ceil(seconds));
  const pad=(n)=>String(n).padStart(2,"0");
  return includeHours?`${pad(Math.floor(seconds/3600))}:${pad(Math.floor(seconds/60)%60)}:${pad(seconds%60)}`:`${pad(Math.floor(seconds/60))}:${pad(seconds%60)}`;
}
let practiceDeadline=null;
let practiceKey=null;
let autoFinishing=false;
let lastAutoFinishAttempt=0;
function startPracticeClock() {
  if(state.detail?.results)return;
  practiceKey=`csquiz-deadline:${state.userId}:${state.sessionId}`;
  try {practiceDeadline=Number(localStorage.getItem(practiceKey))||Date.now()+15*60*1000; localStorage.setItem(practiceKey,String(practiceDeadline));}
  catch(_){practiceDeadline=Date.now()+15*60*1000;}
  updateClocks();
}
function updateClocks() {
  document.querySelectorAll('[data-countdown]').forEach((element)=>{
    const seconds=(new Date(element.dataset.countdown.replace(" ","T")+"Z").getTime()-Date.now())/1000;
    element.textContent=seconds>0?duration(seconds,true):"Opening…";
  });
  if($("attempt-clock")&&practiceDeadline){
    try{const stored=Number(localStorage.getItem(practiceKey));if(stored>0)practiceDeadline=stored;}catch(_){}
    const seconds=(practiceDeadline-Date.now())/1000;
    $("attempt-clock").textContent=duration(seconds);
    $("attempt-clock").parentElement.classList.toggle("urgent",seconds<60);
    if(seconds<=0&&!state.busy&&!autoFinishing&&!state.detail?.completed&&Date.now()-lastAutoFinishAttempt>15000){
      lastAutoFinishAttempt=Date.now();
      autoFinishing=true;
      state.busy=true;
      api("/api/attempts/finish",{session_id:state.sessionId})
        .then(()=>loadSession(false)).then(()=>{message("Time is up. Remaining questions were saved as blank.");})
        .catch(async(error)=>{message(error.message,true);try{await loadSession(false);}catch(_) {}}).finally(()=>{state.busy=false;autoFinishing=false;render();});
    }
  }
}
setInterval(updateClocks,1000);

async function saveSchedule(id) {
  const value=$("schedule-"+id).value;
  let scheduled=null;
  if(value){const date=new Date(value); if(Number.isNaN(date.getTime()))throw new Error("Choose a valid date and time.");scheduled=date.toISOString().slice(0,19).replace("T"," ");}
  busy(true);
  try {const response=await api("/api/sessions/schedule",{session_id:id,scheduled_start_at:scheduled});await overview();message(response.message);}
  catch(error){message(error.message,true);}
  finally {busy(false);}
}

function showAccountError(field, text = "") {
  const error = $(field ? `${field}-error` : "account-error");
  error.hidden = !text;
  error.textContent = text;
  if (field) {
    const input = $(field);
    if (text) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }
}

function focusAccountError(field) {
  if (field) $(field).focus({preventScroll: true});
  $(field ? `${field}-error` : "account-error").scrollIntoView({block: "nearest"});
}

$("screen").addEventListener("input", (event) => {
  if (!event.target.closest("#entry-form")) return;
  if (event.target.id === "nickname" || event.target.id === "learner-password") {
    showAccountError(event.target.id);
    showAccountError(null);
  }
});

$("screen").addEventListener("submit", async (event) => {
  if (event.target.id !== "entry-form") return;
  event.preventDefault();
  if (state.busy) return;
  const form = event.target;
  const credentials = Object.fromEntries(new FormData(form));
  state.authName = credentials.nickname;
  const nickname = credentials.nickname.trim().normalize("NFKC");
  const nicknameLength = [...nickname].length;
  const passwordLength = [...credentials.password].length;
  const nicknameError = !nickname ? "Enter a nickname." : nicknameLength < 3 || nicknameLength > 30 ?
    "Use a nickname between 3 and 30 characters." : !/^[\p{L}\p{N}][\p{L}\p{N}\p{M}_-]*$/u.test(nickname) ?
    "Use letters, numbers, underscores or hyphens. Start with a letter or number." : "";
  const passwordError = !passwordLength ? "Enter a password." : passwordLength < 8 || passwordLength > 128 ?
    "Use a password between 8 and 128 characters." : "";
  message();
  showAccountError("nickname", nicknameError);
  showAccountError("learner-password", passwordError);
  showAccountError(null);
  if (nicknameError || passwordError) {
    focusAccountError(nicknameError ? "nickname" : "learner-password");
    return;
  }

  // Keep the same form mounted so validation messages and typed values remain visible.
  const setPending = (pending) => {
    state.busy = pending;
    form.setAttribute("aria-busy", String(pending));
    for (const control of form.elements) control.disabled = pending;
    $("host-link").disabled = pending;
  };
  const registering = state.authMode === "register";
  let focusField = null;
  let succeeded = false;
  setPending(true);
  try {
    const {user} = await api(`/api/account/${state.authMode}`, credentials);
    setLearner(user);
    await Promise.all([overview(), loadProfile()]);
    succeeded = true;
  } catch (error) {
    focusField = registering && error.status === 409 ? "nickname" : null;
    showAccountError(focusField, state.account ?
      "You're signed in, but the quiz list could not load. Refresh to try again." :
      error.status ? error.message : "Could not reach CSQuiz. Check that app.py is running and try again.");
  } finally {
    setPending(false);
  }
  if (succeeded) goto("sessions");
  else focusAccountError(focusField);
});

$("screen").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled || state.busy) return;
  try {
    if (button.dataset.authMode) {
      state.authName = $("nickname").value;
      state.authMode = button.dataset.authMode;
      message();
      render();
      $("nickname").focus();
    } else if (button.dataset.page) {
      ++state.request;
      if (button.dataset.page === "sessions") await Promise.all([overview(), loadProfile()]);
      goto(button.dataset.page);
    } else if (button.dataset.retake) {
      await retakeQuiz(Number(button.dataset.retake));
    } else if (button.dataset.open) {
      state.sessionId=Number(button.dataset.open);
      state.detail=null; state.choice=null; state.feedback=null; practiceDeadline=null; practiceKey=null;
      message();
      await loadSession(true);
      startPracticeClock();
      window.scrollTo({top:0,behavior:"instant"});
    } else if(button.dataset.continue){
      state.feedback=null;
      if(state.detail.results){goto("results");}
      else {const next=state.detail.questions.findIndex((question)=>!question.submitted);state.position=next<0?0:next;state.choice=null;render();}
    } else if(button.dataset.schedule){await saveSchedule(Number(button.dataset.schedule));
    } else if (button.dataset.choice) {
      state.choice=button.dataset.choice;
      render();
      $("screen").querySelector(`[data-choice="${state.choice}"]`).focus();
    } else if (button.dataset.move || button.dataset.position !== undefined) {
      state.position = button.dataset.position !== undefined ? Number(button.dataset.position) : state.position + Number(button.dataset.move);
      state.choice=null; render();
    } else if (button.dataset.submit) { await submit(button.dataset.submit === "skip"); }
    else if (button.id === "finish-quiz") { await finishQuiz(); }
    else if (button.dataset.host) { await hostAction(button.dataset.host, Number(button.dataset.id)); }
    else if (button.id === "refresh-host") { await overview(); render(); message("Everything is up to date."); }
  } catch (error) { message(error.message,true); }
});

async function requestHostAccess() {
  const dialog = $("host-login");
  if (dialog.open) return false;
  const form = $("host-login-form");
  const input = $("host-password");
  const error = $("host-login-error");
  const submit = $("host-login-submit");
  const cancel = $("host-login-cancel");
  input.value = "";
  error.hidden = true;
  submit.disabled = false;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    let checking = false;
    let active = true;
    const onCancel = () => dialog.close("cancel");
    const onSubmit = async (event) => {
      event.preventDefault();
      if (checking) return;
      checking = true;
      submit.disabled = true;
      error.hidden = true;
      try {
        const result = await api("/api/host/login", {password: input.value});
        if (!active || !dialog.open) return;
        hostToken = result.token;
        dialog.close("accept");
      } catch (failure) {
        if (active && dialog.open) {
          error.textContent = failure.message;
          error.hidden = false;
          input.select();
        }
      } finally {
        checking = false;
        if (active) submit.disabled = false;
      }
    };
    const onClose = () => {
      active = false;
      form.removeEventListener("submit", onSubmit);
      cancel.removeEventListener("click", onCancel);
      input.value = "";
      resolve(dialog.returnValue === "accept");
    };
    form.addEventListener("submit", onSubmit);
    cancel.addEventListener("click", onCancel);
    dialog.addEventListener("close", onClose, {once: true});
    dialog.showModal();
    input.focus();
  });
}

$("host-link").addEventListener("click", async () => {
  if (state.busy) return;
  ++state.request;
  try {
    const next=state.page === "host" ? state.userId ? "sessions" : "welcome" : "host";
    if (next === "host" && !await requestHostAccess()) return;
    if (next !== "welcome") await overview();
    if(next==="host")await loadHostResults();
    goto(next);
    if (next !== "host") hostToken = "";
  }
  catch (error) { message(error.message,true); }
});

async function poll() {
  if (document.hidden || state.busy || polling || !["sessions","quiz","host","results"].includes(state.page)) return;
  polling = true;
  const page = state.page;
  try {
    if (page === "quiz" || page === "results") {
      await loadSession(false, state.page==="quiz"&&state.feedback!==null);
    } else {
      const old = JSON.stringify([state.overview,state.hostResults]);
      await overview();
      if (state.page === page && old !== JSON.stringify([state.overview,state.hostResults])) render();
    }
  } catch (error) { message(`Live update paused: ${error.message}`,true); }
  finally { polling=false; }
}
setInterval(poll,15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

async function initialize() {
  const saved=readNavigation();
  const {user} = await api("/api/account/me");
  setLearner(user);
  if (user) {
    await Promise.all([overview(), loadProfile()]);
    state.page = "sessions";
  }
  if(saved && user && saved.userId===user.user_id) {
    state.hostSessionId=state.overview.sessions.some((item)=>item.session_id===saved.hostSessionId)
      ?saved.hostSessionId:state.overview.sessions[0]?.session_id||1;
    state.hostShowAll=saved.hostShowAll===true;
    if(saved.page==="host") {
      state.page="sessions";
    }else if(saved.page==="sessions") {
      state.page="sessions";
    }else if(["quiz","results"].includes(saved.page)) {
      const validSession=state.overview.sessions.some((item)=>item.session_id===saved.sessionId);
      if(validSession) {
        state.sessionId=saved.sessionId;
        await loadSession(true,false,false);
        if(state.page==="quiz") {
          const previous=state.detail.questions.findIndex((item)=>item.question_id===saved.questionId);
          if(previous>=0)state.position=previous;
          if(previous>=0&&!state.detail.questions[previous].submitted)state.choice=saved.choice;
        }
      }else {state.page="sessions";}
    }
  }
  render();
  if(state.page==="quiz")startPracticeClock();
}

$("sign-out").addEventListener("click", async () => {
  if (state.busy) return;
  busy(true);
  try {
    await api("/api/account/logout", {});
    clearLearner();
    hostToken = "";
    state.authMode = "login";
    state.authName = "";
    goto("welcome");
  } catch (error) { message(error.message, true); }
  finally { busy(false); }
});

document.querySelector('.brand').addEventListener("click",(event)=>{
  event.preventDefault();
  if(state.busy)return;
  ++state.request;
  hostToken = "";
  goto(state.userId ? "sessions" : "welcome");
});

initialize().catch((error)=>{
  // Keep the saved route on a temporary network failure so refresh can retry it.
  $("screen").innerHTML='<div class="loading">Could not load CSQuiz. Check that app.py is running, then refresh the page.</div>';
  message(error.message,true);
});
