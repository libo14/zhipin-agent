const state = {
  view: "dashboard",
  jobs: [],
  resumes: [],
  outbox: [],
  interviews: [],
  latest: null,
  sample: null,
  emailConfig: {},
  selectedJobId: "sample-ai-agent-engineer",
  selectedResumePaths: new Set(),
  pastedResume: "",
  threshold: 70,
  timezone: "Asia/Shanghai",
  approvalStatus: "pending",
  notificationChannels: "json",
  query: "",
  emailAutoTimer: null,
  emailAutoRunning: false,
  emailLastPayload: null,
  emailIntervalSeconds: 300,
};

const viewMeta = {
  dashboard: ["无人值守招聘流程", "招聘总览"],
  jobs: ["职位从创建到 JD 管理", "职位管理"],
  candidates: ["简历解析、邮箱收件与候选人库", "候选人"],
  screening: ["LangGraph 多 Agent 编排", "AI 筛选"],
  interviews: ["跨时区冲突检测与推荐", "面试安排"],
  reports: ["招聘漏斗与效率指标", "数据报表"],
  settings: ["本地运行、邮箱与通知配置", "系统设置"],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", async () => {
  bindShell();
  bindUploader();
  await loadWorkbench();
});

function bindShell() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#refreshBtn").addEventListener("click", loadWorkbench);
  $("#globalSearch").addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    render();
  });
}

function bindUploader() {
  $("#resumeFiles").addEventListener("change", (event) => {
    if (event.target.files.length) uploadFiles(event.target.files);
    event.target.value = "";
  });
}

async function loadWorkbench() {
  setStatus("加载中", "running");
  try {
    const data = await apiGet("/api/workbench", "工作台数据");
    state.sample = data.data.sample;
    state.jobs = data.data.jobs || [];
    state.resumes = data.data.resumes || [];
    state.outbox = data.data.outbox || [];
    state.interviews = data.data.interviews || [];
    state.emailConfig = data.data.emailConfig || {};
    state.threshold = state.sample?.threshold || 70;
    state.timezone = state.sample?.timezone || "Asia/Shanghai";
    state.approvalStatus = state.sample?.approvalStatus || "pending";
    state.notificationChannels = state.sample?.notificationChannels || "json";
    if (!state.selectedResumePaths.size) {
      state.resumes.slice(0, 8).forEach((resume) => state.selectedResumePaths.add(resume.path));
    }
    setStatus("就绪", "ok");
    render();
  } catch (error) {
    showToast(error.message, "error");
    setStatus("加载失败", "error");
  }
}

function setView(view) {
  state.view = view;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach((panel) => panel.classList.toggle("active", panel.id === `view-${view}`));
  $("#viewEyebrow").textContent = viewMeta[view][0];
  $("#viewTitle").textContent = viewMeta[view][1];
  render();
}

function render() {
  renderDashboard();
  renderJobs();
  renderCandidates();
  renderScreening();
  renderInterviews();
  renderReports();
  renderSettings();
}

function renderDashboard() {
  const matches = filteredMatches();
  const schedules = state.latest?.schedules || [];
  $("#view-dashboard").innerHTML = `
    <section class="metric-grid">
      ${metricTile("开放职位", state.jobs.filter((job) => job.status === "open").length, "职位管理")}
      ${metricTile("候选人", state.resumes.length, `已解析 ${parsedResumeCount()} 份`)}
      ${metricTile("面试推荐", schedules.length || state.interviews.length, "自动排期")}
      ${metricTile("最高匹配", matches[0]?.score?.weighted_total ?? "-", "加权评分")}
    </section>
    <section class="dashboard-grid">
      <article class="panel wide">
        <div class="panel-head">
          <div><h2>候选人匹配列表</h2><p>运行 AI 筛选后自动按综合得分排序。</p></div>
          <button class="ghost-button" type="button" data-action="go-screening">一键筛选</button>
        </div>
        ${renderCandidateTable(matches.slice(0, 6))}
      </article>
      <article class="panel assistant-panel">
        <div class="panel-head"><div><h2>AI 招聘助手</h2><p>根据当前 JD、简历库和流程状态给出下一步。</p></div></div>
        <div class="chat-bubble user">帮我自动收取邮箱里的新简历，并优先筛选匹配候选人。</div>
        <div class="chat-bubble bot">${assistantSummary()}</div>
        <div class="action-row compact">
          <button class="ghost-button" type="button" data-action="go-candidates">候选人库</button>
          <button class="primary-button" type="button" data-action="fetch-email">收取邮箱简历</button>
        </div>
      </article>
      <article class="panel"><div class="panel-head"><div><h2>招聘流程漏斗</h2><p>从简历解析到触达的转化情况。</p></div></div>${renderFunnel()}</article>
      <article class="panel"><div class="panel-head"><div><h2>今日待办</h2><p>面试、审批、触达事件集中处理。</p></div></div>${renderTodoList()}</article>
    </section>
  `;
  bindDynamicActions($("#view-dashboard"));
}

function renderJobs() {
  const selected = selectedJob();
  const jobs = filterList(state.jobs, (job) => `${job.title} ${job.department} ${job.location}`);
  $("#view-jobs").innerHTML = `
    <section class="two-column">
      <article class="panel">
        <div class="panel-head"><div><h2>职位列表</h2><p>选择职位会同步到 AI 筛选工作流。</p></div><button class="ghost-button" data-action="new-job" type="button">新建职位</button></div>
        <div class="job-list">${jobs.map(renderJobCard).join("") || emptyText("没有匹配的职位。")}</div>
      </article>
      <article class="panel">
        <div class="panel-head"><div><h2>JD 编辑器</h2><p>保存后写入 data/jobs，并可直接参与筛选。</p></div></div>
        <form id="jobForm" class="form-grid">
          <label>职位名称<input id="jobTitle" value="${escapeAttr(selected.title)}" /></label>
          <label>部门<input id="jobDepartment" value="${escapeAttr(selected.department)}" /></label>
          <label>地点<input id="jobLocation" value="${escapeAttr(selected.location)}" /></label>
          <label>招聘人数<input id="jobHeadcount" type="number" min="1" value="${Number(selected.headcount || 1)}" /></label>
          <label>状态<select id="jobStatus">${option("open", selected.status, "开放")} ${option("paused", selected.status, "暂停")} ${option("closed", selected.status, "关闭")}</select></label>
          <label class="full">职位 JD<textarea id="jobDescription">${escapeHtml(selected.description || "")}</textarea></label>
          <div class="action-row full">
            <button class="ghost-button" type="button" data-action="load-selected-job">同步到筛选</button>
            <button class="primary-button" type="submit">保存职位</button>
          </div>
        </form>
      </article>
    </section>
  `;
  $("#view-jobs").querySelectorAll("[data-job-id]").forEach((button) => button.addEventListener("click", () => {
    updateSelectedJobFromForm();
    state.selectedJobId = button.dataset.jobId;
    render();
  }));
  $("#jobForm").addEventListener("submit", saveCurrentJob);
  bindJobEditorDraft();
  bindDynamicActions($("#view-jobs"));
}

function renderCandidates() {
  const resumes = filterList(state.resumes, (resume) => {
    const profile = resume.profile || {};
    return `${resume.name} ${resume.source} ${profile.name} ${profile.email} ${(profile.skills || []).join(" ")}`;
  });
  $("#view-candidates").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <div><h2>候选人库</h2><p>支持本地上传，也支持从 Outlook、QQ 邮箱等 IMAP 邮箱自动收取简历附件。</p></div>
        <div class="action-row compact">
          <button class="ghost-button" type="button" data-action="select-all-resumes">全选</button>
          <button class="ghost-button" type="button" data-action="fetch-email">收取邮箱简历</button>
          <button class="primary-button" type="button" data-action="upload-resume">导入简历</button>
        </div>
      </div>
      <div id="uploadDropzone" class="upload-dropzone">
        <svg viewBox="0 0 24 24"><path d="M12 3 7 8h3v6h4V8h3l-5-5ZM5 18h14v2H5v-2Z" /></svg>
        <div><strong>拖入或选择简历文件</strong><span>上传后写入 data/web_uploads；邮箱收取的简历会写入 data/email_resumes。</span></div>
      </div>
      <div class="candidate-grid">${resumes.map(renderResumeCard).join("") || emptyText("还没有候选人，请先导入简历或收取邮箱。")}</div>
    </section>
  `;
  bindCandidateCards();
  bindDropzone();
  bindDynamicActions($("#view-candidates"));
}

function renderScreening() {
  const selected = selectedJob();
  const matches = filteredMatches();
  $("#view-screening").innerHTML = `
    <section class="two-column screening-layout">
      <article class="panel control-card">
        <div class="panel-head"><div><h2>筛选控制台</h2><p>运行完整 5-Agent 招聘工作流。</p></div></div>
        <label>当前职位<select id="screenJob">${state.jobs.map((job) => option(job.id, state.selectedJobId, job.title)).join("")}</select></label>
        <label>筛选阈值<input id="threshold" type="number" min="0" max="100" value="${state.threshold}" /></label>
        <label>时区<input id="timezone" value="${escapeAttr(state.timezone)}" /></label>
        <label>审批状态<select id="approvalStatus">${option("pending", state.approvalStatus, "pending")} ${option("approved", state.approvalStatus, "approved")} ${option("rejected", state.approvalStatus, "rejected")}</select></label>
        <label>通知通道<select id="notificationChannels">${option("json", state.notificationChannels, "json")} ${option("json,smtp", state.notificationChannels, "json,smtp")} ${option("json,feishu", state.notificationChannels, "json,feishu")}</select></label>
        <label class="check-row"><input id="showAllCandidates" type="checkbox" checked />显示所有评分结果</label>
        <label>本次筛选 JD<textarea id="screenJobDescription">${escapeHtml(selected.description || "")}</textarea></label>
        <label>快速粘贴简历<textarea id="pastedResume" placeholder="可选：粘贴一份简历文本。">${escapeHtml(state.pastedResume)}</textarea></label>
        <button class="primary-button" type="button" data-action="run-workflow">运行 AI 筛选</button>
      </article>
      <article class="panel"><div class="panel-head"><div><h2>职位意图</h2><p>由 JD 提取岗位、技能、经验、学历和关键词。</p></div></div>${renderIntent(state.latest?.intent, selected)}</article>
    </section>
    <section class="panel"><div class="panel-head"><div><h2>筛选结果</h2><p>按“技能 60% + 经验 30% + 学历 10%”加权评分。</p></div></div>${renderMatchCards(matches)}</section>
  `;
  $("#screenJob").addEventListener("change", (event) => {
    updateSelectedJobFromScreening();
    state.selectedJobId = event.target.value;
    render();
  });
  $("#screenJobDescription").addEventListener("input", updateSelectedJobFromScreening);
  bindDynamicActions($("#view-screening"));
}

function renderInterviews() {
  const schedules = state.latest?.schedules || [];
  $("#view-interviews").innerHTML = `
    <section class="panel">
      <div class="panel-head"><div><h2>面试排期</h2><p>候选人通过筛选后，系统自动避开冲突并推荐工作日高响应时段。</p></div><button class="primary-button" type="button" data-action="run-workflow">重新生成排期</button></div>
      <div class="schedule-grid">${schedules.map(renderScheduleCard).join("") || emptyText("暂无排期推荐。先运行 AI 筛选即可生成。")}</div>
    </section>
    <section class="panel"><div class="panel-head"><div><h2>已确认面试</h2><p>确认记录会落盘到 data/interviews。</p></div></div>${renderConfirmedInterviews()}</section>
  `;
  bindDynamicActions($("#view-interviews"));
}

function renderReports() {
  $("#view-reports").innerHTML = `
    <section class="metric-grid">
      ${metricTile("简历总量", state.resumes.length, "候选人库")}
      ${metricTile("邮箱简历", state.resumes.filter((item) => item.source === "email_resumes").length, "自动收件")}
      ${metricTile("入围人数", shortlistedCount(), "match 及以上")}
      ${metricTile("平均分", averageScore(), "最近一次筛选")}
    </section>
    <section class="dashboard-grid">
      <article class="panel"><div class="panel-head"><div><h2>招聘流程漏斗</h2><p>从投递到触达的转化效率。</p></div></div>${renderFunnel()}</article>
      <article class="panel"><div class="panel-head"><div><h2>技能覆盖</h2><p>候选人技能标签出现频次。</p></div></div>${renderSkillBars()}</article>
      <article class="panel wide"><div class="panel-head"><div><h2>通知触达记录</h2><p>来自 data/outbox 的邮件草稿和投递记录。</p></div></div>${renderOutboxTable()}</article>
    </section>
  `;
}

function renderSettings() {
  const cfg = state.emailConfig || {};
  $("#view-settings").innerHTML = `
    <section class="two-column">
      <article class="panel">
        <div class="panel-head"><div><h2>邮箱收件 Agent</h2><p>通过 IMAP 收取候选人邮件，自动下载简历附件并解析入库。</p></div></div>
        <form id="emailFetchForm" class="form-grid">
          <label>邮箱类型<select id="imapProvider">${option("", cfg.provider || "", "自定义")} ${option("outlook", cfg.provider || "", "Outlook")} ${option("qq", cfg.provider || "", "QQ 邮箱")} ${option("163", cfg.provider || "", "163 邮箱")} ${option("gmail", cfg.provider || "", "Gmail")}</select></label>
          <label>IMAP Host<input id="imapHost" placeholder="imap.qq.com" value="${escapeAttr(cfg.host || "")}" /></label>
          <label>端口<input id="imapPort" type="number" value="${Number(cfg.port || 993)}" /></label>
          <label>文件夹<input id="imapFolder" value="${escapeAttr(cfg.folder || "INBOX")}" /></label>
          <label>账号<input id="imapUsername" placeholder="hr@example.com" value="${escapeAttr(cfg.username || "")}" /></label>
          <label>授权码/密码<input id="imapPassword" type="password" placeholder="建议使用邮箱授权码" /></label>
          <label>搜索条件<select id="imapSearch">${option("UNSEEN", cfg.search || "UNSEEN", "未读邮件")} ${option("ALL", cfg.search || "UNSEEN", "全部邮件")}</select></label>
          <label>最多收取<input id="imapMaxMessages" type="number" min="1" max="100" value="${Number(cfg.maxMessages || 20)}" /></label>
          <label>自动检查间隔<input id="imapIntervalSeconds" type="number" min="60" step="60" value="${Number(state.emailIntervalSeconds || 300)}" /></label>
          <label class="check-row"><input id="imapUseSsl" type="checkbox" ${cfg.useSsl !== false ? "checked" : ""} />使用 SSL</label>
          <label class="check-row"><input id="imapMarkSeen" type="checkbox" ${cfg.markSeen ? "checked" : ""} />导入后标记已读</label>
          <div class="action-row full">
            <button class="primary-button" type="submit">立即收取邮箱简历</button>
            <button id="emailAutoToggle" class="ghost-button" type="button">${state.emailAutoRunning ? "停止自动收件" : "开启自动收件"}</button>
          </div>
        </form>
      </article>
      <article class="panel">
        <div class="panel-head"><div><h2>配置说明</h2><p>Outlook、QQ 邮箱等通常需要先开启 IMAP，并生成授权码。</p></div></div>
        <div class="settings-list">
          <div><strong>Outlook</strong><span>provider=outlook，默认 imap-mail.outlook.com:993。</span></div>
          <div><strong>QQ 邮箱</strong><span>provider=qq，默认 imap.qq.com:993，密码填写 QQ 邮箱授权码。</span></div>
          <div><strong>自动收件</strong><span>软件打开期间按间隔检查邮箱，发现新简历后自动入库。</span></div>
          <div><strong>落盘目录</strong><span>邮箱简历保存到 data/email_resumes，并自动进入候选人库。</span></div>
          <div><strong>安全建议</strong><span>正式使用时建议把 IMAP_PASSWORD 写入环境变量，不要写进代码。</span></div>
        </div>
      </article>
    </section>
    <section class="two-column">
      <article class="panel"><div class="panel-head"><div><h2>本地运行</h2><p>桌面版使用 WebView 承载本地 Agent API。</p></div></div><div class="settings-list"><div><strong>简历上传</strong><span>data/web_uploads</span></div><div><strong>邮箱简历</strong><span>data/email_resumes</span></div><div><strong>邮件草稿</strong><span>data/outbox</span></div><div><strong>面试确认</strong><span>data/interviews</span></div></div></article>
      <article class="panel"><div class="panel-head"><div><h2>通知集成</h2><p>真实发送需要配置 SMTP、SendGrid 或飞书环境变量。</p></div></div><div class="settings-list"><div><strong>JSON 草稿</strong><span>默认开启，适合演示和安全审查。</span></div><div><strong>SMTP</strong><span>SMTP_HOST / SMTP_FROM_EMAIL / SMTP_USERNAME / SMTP_PASSWORD</span></div><div><strong>飞书</strong><span>FEISHU_WEBHOOK_URL</span></div></div></article>
    </section>
  `;
  $("#emailFetchForm").addEventListener("submit", fetchEmailResumes);
  $("#emailAutoToggle").addEventListener("click", toggleEmailAutoFetch);
}

async function runWorkflow() {
  persistScreeningControls();
  updateSelectedJobFromForm();
  updateSelectedJobFromScreening();
  const job = selectedJob();
  setStatus("运行中", "running");
  try {
    const data = await apiPost("/api/run", {
      jobDescription: job.description,
      resumePaths: Array.from(state.selectedResumePaths),
      pastedResume: state.pastedResume,
      threshold: state.threshold,
      timezone: state.timezone,
      approvalStatus: state.approvalStatus,
      approvedBy: "HR reviewer",
      approvalNotes: "",
      notificationChannels: state.notificationChannels,
      showAllCandidates: $("#showAllCandidates")?.checked ?? true,
    }, "运行接口");
    if (!data.ok) throw new Error(data.error || "运行失败");
    state.latest = data.result;
    await refreshSecondaryData();
    setStatus("已完成", "ok");
    setView("screening");
    showToast("AI 招聘工作流已完成。", "ok");
  } catch (error) {
    showToast(error.message, "error");
    setStatus("运行失败", "error");
  }
}

async function fetchEmailResumes(event, options = {}) {
  if (event) event.preventDefault();
  const payload = emailPayloadFromForm();
  state.emailLastPayload = payload;
  setStatus("收件中", "running");
  try {
    const data = await apiPost("/api/email/fetch", payload, "邮箱收件");
    if (!data.ok) throw new Error(data.error || "收件失败");
    const files = data.result.files || [];
    files.forEach((file) => state.selectedResumePaths.add(file.path));
    await refreshSecondaryData();
    setStatus("已收取", "ok");
    if (!options.stay) setView("candidates");
    if (!options.silent || data.result.importedFiles > 0) {
      showToast(`已从邮箱导入 ${data.result.importedFiles} 份简历。`, "ok");
    }
  } catch (error) {
    showToast(error.message, "error");
    setStatus("收件失败", "error");
    if (options.auto) stopEmailAutoFetch();
  }
}

function emailPayloadFromForm() {
  const password = $("#imapPassword")?.value || state.emailLastPayload?.password || "";
  state.emailIntervalSeconds = Number($("#imapIntervalSeconds")?.value || state.emailIntervalSeconds || 300);
  return {
    provider: $("#imapProvider")?.value || state.emailConfig.provider || "",
    host: $("#imapHost")?.value || state.emailConfig.host || "",
    port: Number($("#imapPort")?.value || state.emailConfig.port || 993),
    username: $("#imapUsername")?.value || state.emailConfig.username || "",
    password,
    folder: $("#imapFolder")?.value || "INBOX",
    search: $("#imapSearch")?.value || "UNSEEN",
    maxMessages: Number($("#imapMaxMessages")?.value || 20),
    useSsl: $("#imapUseSsl")?.checked ?? true,
    markSeen: $("#imapMarkSeen")?.checked ?? false,
  };
}

function toggleEmailAutoFetch() {
  if (state.emailAutoRunning) {
    stopEmailAutoFetch();
    showToast("已停止自动收取邮箱简历。", "ok");
    render();
    return;
  }
  startEmailAutoFetch();
}

function startEmailAutoFetch() {
  const payload = emailPayloadFromForm();
  state.emailLastPayload = payload;
  state.emailIntervalSeconds = Math.max(60, Number(state.emailIntervalSeconds || 300));
  stopEmailAutoFetch(false);
  state.emailAutoRunning = true;
  state.emailAutoTimer = setInterval(() => {
    fetchEmailResumes(null, { silent: true, stay: true, auto: true });
  }, state.emailIntervalSeconds * 1000);
  showToast(`自动收件已开启，每 ${Math.round(state.emailIntervalSeconds / 60)} 分钟检查一次。`, "ok");
  fetchEmailResumes(null, { silent: false, stay: true, auto: true });
  render();
}

function stopEmailAutoFetch(updateFlag = true) {
  if (state.emailAutoTimer) {
    clearInterval(state.emailAutoTimer);
    state.emailAutoTimer = null;
  }
  if (updateFlag) state.emailAutoRunning = false;
}

async function refreshSecondaryData() {
  const [resumes, outbox] = await Promise.all([apiGet("/api/resumes", "简历库"), apiGet("/api/outbox", "发件箱")]);
  state.resumes = resumes.resumes || [];
  state.outbox = outbox.items || [];
}

async function saveCurrentJob(event) {
  event.preventDefault();
  const selected = selectedJob();
  const payload = {
    id: selected.id === "draft" ? undefined : selected.id,
    title: $("#jobTitle").value,
    department: $("#jobDepartment").value,
    location: $("#jobLocation").value,
    headcount: Number($("#jobHeadcount").value || 1),
    status: $("#jobStatus").value,
    description: $("#jobDescription").value,
    createdAt: selected.createdAt,
  };
  const data = await apiPost("/api/jobs/save", payload, "保存职位");
  if (!data.ok) throw new Error(data.error || "保存失败");
  state.selectedJobId = data.job.id;
  state.jobs = (await apiGet("/api/jobs", "职位列表")).jobs || [];
  render();
  showToast("职位已保存。", "ok");
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  setStatus("上传中", "running");
  try {
    const response = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await readJsonResponse(response, "上传接口");
    if (!data.ok) throw new Error(data.error || "上传失败");
    data.files.forEach((file) => state.selectedResumePaths.add(file.path));
    await refreshSecondaryData();
    setStatus("已上传", "ok");
    render();
    showToast(`已导入 ${data.files.length} 份简历。`, "ok");
  } catch (error) {
    showToast(error.message, "error");
    setStatus("上传失败", "error");
  }
}

function bindDynamicActions(root) {
  root.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.action;
      if (action === "run-workflow") runWorkflow();
      if (action === "fetch-email") fetchEmailResumes();
      if (action === "go-screening") setView("screening");
      if (action === "go-candidates") setView("candidates");
      if (action === "upload-resume") $("#resumeFiles").click();
      if (action === "select-all-resumes") {
        state.resumes.forEach((resume) => state.selectedResumePaths.add(resume.path));
        render();
      }
      if (action === "new-job") {
        state.jobs = [{
          id: "draft",
          title: "新建职位",
          department: "AI Platform",
          location: "上海",
          status: "open",
          headcount: 1,
          createdAt: new Date().toISOString(),
          description: "岗位：\n地点：\n\n岗位职责：\n- \n\n任职要求：\n- ",
        }, ...state.jobs.filter((job) => job.id !== "draft")];
        state.selectedJobId = "draft";
        render();
      }
      if (action === "load-selected-job") {
        updateSelectedJobFromForm();
        setView("screening");
      }
      if (action === "confirm-slot") confirmSlot(button);
    });
  });
}

function bindCandidateCards() {
  $$("#view-candidates [data-resume-path]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedResumePaths.add(checkbox.dataset.resumePath);
      else state.selectedResumePaths.delete(checkbox.dataset.resumePath);
      render();
    });
  });
}

function bindDropzone() {
  const dropzone = $("#uploadDropzone");
  if (!dropzone) return;
  dropzone.addEventListener("click", () => $("#resumeFiles").click());
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  }));
  dropzone.addEventListener("drop", (event) => {
    if (event.dataTransfer.files.length) uploadFiles(event.dataTransfer.files);
  });
}

async function confirmSlot(button) {
  const schedule = state.latest.schedules[Number(button.dataset.scheduleIndex)];
  const slot = schedule.slots[Number(button.dataset.slotIndex)];
  const data = await apiPost("/api/interviews/confirm", {
    candidateName: schedule.candidate_name,
    candidateEmail: schedule.candidate_email,
    jobTitle: selectedJob().title,
    slot,
  }, "确认面试");
  if (!data.ok) throw new Error(data.error || "确认失败");
  state.interviews = [data.confirmation, ...state.interviews];
  render();
  showToast("面试时间已确认。", "ok");
}

function persistScreeningControls() {
  state.threshold = Number($("#threshold")?.value || state.threshold || 70);
  state.timezone = $("#timezone")?.value || state.timezone;
  state.approvalStatus = $("#approvalStatus")?.value || state.approvalStatus;
  state.notificationChannels = $("#notificationChannels")?.value || state.notificationChannels;
  state.pastedResume = $("#pastedResume")?.value || "";
}

function bindJobEditorDraft() {
  ["jobTitle", "jobDepartment", "jobLocation", "jobHeadcount", "jobStatus", "jobDescription"].forEach((id) => {
    const input = $(`#${id}`);
    if (!input) return;
    input.addEventListener("input", updateSelectedJobFromForm);
    input.addEventListener("change", updateSelectedJobFromForm);
  });
}

function updateSelectedJobFromForm() {
  if (!$("#jobForm")) return;
  const job = selectedJob();
  if (!job || !job.id) return;
  job.title = $("#jobTitle")?.value || job.title || "未命名职位";
  job.department = $("#jobDepartment")?.value || job.department || "AI Platform";
  job.location = $("#jobLocation")?.value || job.location || "Remote";
  job.headcount = Number($("#jobHeadcount")?.value || job.headcount || 1);
  job.status = $("#jobStatus")?.value || job.status || "open";
  job.description = $("#jobDescription")?.value || job.description || "";
}

function updateSelectedJobFromScreening() {
  const description = $("#screenJobDescription");
  if (!description) return;
  const job = selectedJob();
  if (!job || !job.id) return;
  job.description = description.value;
}

function selectedJob() {
  return state.jobs.find((job) => job.id === state.selectedJobId) || state.jobs[0] || {};
}

function filteredMatches() {
  const matches = state.latest?.candidateMatches || [];
  return filterList(matches, (match) => {
    const candidate = match.candidate || {};
    return `${candidate.name} ${candidate.email} ${candidate.education} ${(candidate.skills || []).join(" ")}`;
  });
}

function filterList(list, textFactory) {
  if (!state.query) return list;
  return list.filter((item) => textFactory(item).toLowerCase().includes(state.query));
}

function renderJobCard(job) {
  return `
    <button class="job-card ${job.id === state.selectedJobId ? "selected" : ""}" type="button" data-job-id="${escapeAttr(job.id)}">
      <span class="tag ${job.status === "open" ? "good" : "warn"}">${escapeHtml(job.status)}</span>
      <strong>${escapeHtml(job.title)}</strong>
      <span>${escapeHtml(job.department)} · ${escapeHtml(job.location)} · HC ${job.headcount}</span>
    </button>
  `;
}

function renderCandidateTable(matches) {
  if (!matches.length) return emptyText("暂无筛选结果。点击“一键筛选”运行工作流。");
  return `
    <table class="data-table">
      <thead><tr><th>姓名</th><th>经验</th><th>匹配度</th><th>状态</th></tr></thead>
      <tbody>${matches.map((match) => `
        <tr>
          <td><strong>${escapeHtml(match.candidate?.name || "未知")}</strong><span>${escapeHtml(match.candidate?.email || "")}</span></td>
          <td>${match.candidate?.years_experience || 0} 年</td>
          <td><div class="score-line"><span style="width:${Number(match.score?.weighted_total || 0)}%"></span></div>${match.score?.weighted_total ?? "-"}</td>
          <td><span class="tag ${tagClass(match.recommendation)}">${recommendationLabel(match.recommendation)}</span></td>
        </tr>
      `).join("")}</tbody>
    </table>
  `;
}

function renderResumeCard(resume) {
  const profile = resume.profile || {};
  const selected = state.selectedResumePaths.has(resume.path);
  const skills = profile.skills || [];
  return `
    <article class="candidate-card">
      <label class="card-check">
        <input type="checkbox" ${selected ? "checked" : ""} data-resume-path="${escapeAttr(resume.path)}" />
        <span>${selected ? "已加入筛选" : "加入筛选"}</span>
      </label>
      <div class="candidate-main">
        <strong>${escapeHtml(profile.name || resume.name)}</strong>
        <span>${escapeHtml(profile.email || "邮箱未识别")} · ${escapeHtml(profile.education || "学历未知")} · ${profile.yearsExperience || 0} 年经验</span>
      </div>
      <div class="tag-row">
        <span class="tag ${resume.parseStatus === "parsed" ? "good" : "bad"}">${resume.parseStatus === "parsed" ? "已解析" : "解析失败"}</span>
        <span class="tag">${sourceLabel(resume.source)}</span>
        ${skills.slice(0, 8).map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("")}
      </div>
      <p>${escapeHtml(resume.name)} · ${formatBytes(resume.size)}</p>
    </article>
  `;
}

function renderMatchCards(matches) {
  if (!matches.length) return emptyText("暂无候选人评分。运行 AI 筛选后会显示详细评分。");
  return `<div class="match-grid">${matches.map((match, index) => {
    const candidate = match.candidate || {};
    const score = match.score || {};
    return `
      <article class="match-card">
        <div class="candidate-head"><div><strong>${index + 1}. ${escapeHtml(candidate.name || "未知候选人")}</strong><span>${escapeHtml(candidate.email || "")}</span></div><div class="score-badge">${score.weighted_total ?? "-"}</div></div>
        <div class="score-grid">${scoreItem("技能", score.skill_score)}${scoreItem("经验", score.experience_score)}${scoreItem("学历", score.education_score)}</div>
        <div class="tag-row"><span class="tag ${tagClass(match.recommendation)}">${recommendationLabel(match.recommendation)}</span>${(score.matched_skills || []).map((skill) => `<span class="tag good">${escapeHtml(skill)}</span>`).join("")}${(score.missing_skills || []).map((skill) => `<span class="tag warn">缺 ${escapeHtml(skill)}</span>`).join("")}</div>
        <p>${escapeHtml(match.rationale || "")}</p>
      </article>
    `;
  }).join("")}</div>`;
}

function renderIntent(intent, job) {
  const data = intent || {};
  return `
    <div class="intent-box">
      <h3>${escapeHtml(data.title || job.title || "待识别岗位")}</h3>
      <div class="tag-row"><span class="tag good">${escapeHtml(data.seniority || "Mid")}</span><span class="tag">${escapeHtml(data.location || job.location || "Remote")}</span><span class="tag">${data.min_years_experience ?? 0} 年经验</span><span class="tag">${escapeHtml(data.education_requirement || "不限")}</span></div>
      <h4>核心技能</h4><div class="tag-row">${(data.required_skills || []).map((skill) => `<span class="tag good">${escapeHtml(skill)}</span>`).join("") || emptyText("运行后识别技能。")}</div>
      <h4>加分项</h4><div class="tag-row">${(data.nice_to_have_skills || []).map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("") || "<span class='muted'>暂无</span>"}</div>
    </div>
  `;
}

function renderScheduleCard(schedule, scheduleIndex) {
  return `
    <article class="schedule-card">
      <div class="panel-head"><div><h3>${escapeHtml(schedule.candidate_name || "候选人")}</h3><p>${escapeHtml(schedule.candidate_email || "")}</p></div><span class="tag good">${(schedule.slots || []).length} 个推荐</span></div>
      <p>${escapeHtml(schedule.reason || "")}</p>
      <div class="slot-list">${(schedule.slots || []).map((slot, slotIndex) => `<button class="slot-button" data-action="confirm-slot" data-schedule-index="${scheduleIndex}" data-slot-index="${slotIndex}" type="button"><strong>${formatSlot(slot)}</strong><span>确认面试</span></button>`).join("")}</div>
    </article>
  `;
}

function renderConfirmedInterviews() {
  if (!state.interviews.length) return emptyText("暂无已确认面试。");
  return `<div class="data-list">${state.interviews.map((item) => `<article class="data-row"><strong>${escapeHtml(item.candidateName)}</strong><span>${escapeHtml(item.jobTitle)} · ${formatSlot(item.slot || {})}</span><span class="tag good">${escapeHtml(item.status)}</span></article>`).join("")}</div>`;
}

function renderFunnel() {
  const rows = [
    ["简历投递", state.resumes.length, "#2f6df6"],
    ["邮箱导入", state.resumes.filter((item) => item.source === "email_resumes").length, "#28a8ea"],
    ["初筛通过", state.latest?.candidateMatches?.length || 0, "#2bbfc8"],
    ["推荐面试", shortlistedCount(), "#35c6a3"],
    ["沟通触达", state.outbox.length, "#76d39b"],
  ];
  const max = Math.max(...rows.map((row) => row[1]), 1);
  return `<div class="funnel">${rows.map(([label, value, color]) => `<div class="funnel-row"><span>${label}</span><div><i style="width:${Math.max(12, value / max * 100)}%; background:${color}"></i></div><strong>${value}</strong></div>`).join("")}</div>`;
}

function renderTodoList() {
  const items = [
    ["收件", state.emailConfig.configured ? "邮箱 IMAP 已有配置，可收取简历" : "配置 IMAP 后可自动收取简历", state.emailConfig.configured ? "可用" : "待配置"],
    ["面试", state.latest?.schedules?.[0]?.candidate_name || "等待生成候选人排期", state.latest?.schedules?.length ? "进行中" : "待处理"],
    ["审批", state.approvalStatus === "approved" ? "候选人触达已放行" : "HR 审批候选人通知", state.approvalStatus],
  ];
  return `<div class="todo-list">${items.map(([type, text, status]) => `<div><span class="tag">${type}</span><strong>${escapeHtml(text)}</strong><em>${escapeHtml(status)}</em></div>`).join("")}</div>`;
}

function renderSkillBars() {
  const counts = {};
  state.resumes.forEach((resume) => (resume.profile?.skills || []).forEach((skill) => { counts[skill] = (counts[skill] || 0) + 1; }));
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const max = Math.max(...rows.map((row) => row[1]), 1);
  return `<div class="skill-bars">${rows.map(([skill, count]) => `<div><span>${escapeHtml(skill)}</span><div><i style="width:${count / max * 100}%"></i></div><strong>${count}</strong></div>`).join("") || emptyText("暂无技能标签。")}</div>`;
}

function renderOutboxTable() {
  if (!state.outbox.length) return emptyText("暂无通知草稿。");
  return `<table class="data-table"><thead><tr><th>类型</th><th>收件人</th><th>主题</th><th>文件</th></tr></thead><tbody>${state.outbox.slice(0, 12).map((item) => `<tr><td><span class="tag">${escapeHtml(item.category)}</span></td><td>${escapeHtml(item.recipient)}</td><td>${escapeHtml(item.subject)}</td><td>${escapeHtml(item.name)}</td></tr>`).join("")}</tbody></table>`;
}

function metricTile(label, value, note) {
  return `<article class="metric-tile"><span>${label}</span><strong>${value}</strong><em>${note}</em></article>`;
}

function scoreItem(label, value) {
  return `<div class="score-item"><span>${label}</span><strong>${value ?? "-"}</strong></div>`;
}

function assistantSummary() {
  const matches = state.latest?.candidateMatches || [];
  if (!matches.length) return "可以先从邮箱收取候选人简历，再运行 AI 筛选。系统会完成意图识别、简历评分、排期推荐、技术面评和通知草稿生成。";
  const strong = matches.filter((item) => ["strong_match", "match"].includes(item.recommendation)).length;
  const top = matches[0];
  return `已完成 ${matches.length} 位候选人筛选，其中 ${strong} 位达到推荐标准。当前最高匹配为 ${top.candidate?.name || "候选人"}，综合得分 ${top.score?.weighted_total ?? "-"}。`;
}

function parsedResumeCount() {
  return state.resumes.filter((resume) => resume.parseStatus === "parsed").length;
}

function shortlistedCount() {
  return (state.latest?.candidateMatches || []).filter((item) => ["strong_match", "match"].includes(item.recommendation)).length;
}

function averageScore() {
  const matches = state.latest?.candidateMatches || [];
  if (!matches.length) return "-";
  const total = matches.reduce((sum, item) => sum + Number(item.score?.weighted_total || 0), 0);
  return (total / matches.length).toFixed(1);
}

function option(value, current, label) {
  return `<option value="${escapeAttr(value)}" ${value === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
}

function tagClass(value) {
  if (value === "strong_match" || value === "match") return "good";
  if (value === "backup" || value === "pending") return "warn";
  return "bad";
}

function recommendationLabel(value) {
  return { strong_match: "强匹配", match: "推荐", backup: "备选", reject: "不匹配" }[value] || value || "未知";
}

function sourceLabel(value) {
  return { resumes: "样例库", web_uploads: "手动上传", email_resumes: "邮箱收件", email_attachment: "邮箱附件", email_body: "邮件正文" }[value] || value || "未知来源";
}

function formatSlot(slot) {
  const start = slot.starts_at ? slot.starts_at.replace("T", " ").slice(0, 16) : "";
  const end = slot.ends_at ? slot.ends_at.replace("T", " ").slice(11, 16) : "";
  return `${start} - ${end} ${slot.timezone || ""}`;
}

function setStatus(text, variant) {
  const pill = $("#statusPill");
  pill.textContent = text;
  pill.className = `status-pill ${variant || ""}`.trim();
}

function showToast(message, variant = "ok") {
  const old = $(".toast");
  if (old) old.remove();
  const toast = document.createElement("div");
  toast.className = `toast ${variant}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3600);
}

async function apiGet(url, label) {
  return readJsonResponse(await fetch(url), label);
}

async function apiPost(url, payload, label) {
  return readJsonResponse(await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }), label);
}

async function readJsonResponse(response, label) {
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) throw new Error(`${label} 没有返回 JSON：${text.replace(/\s+/g, " ").slice(0, 120)}`);
  const data = JSON.parse(text);
  if (!response.ok) throw new Error(data.error || `${label} 请求失败`);
  return data;
}

function emptyText(text) {
  return `<div class="empty-inline">${escapeHtml(text)}</div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}
