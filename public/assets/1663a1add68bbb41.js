
const header = document.querySelector(".site-header");
addEventListener("scroll", () => header.classList.toggle("is-scrolled", scrollY > 36), { passive:true });

let returnFocus;
const overlays = [...document.querySelectorAll(".consultation-backdrop, .information-backdrop")];
const staticConsultationForm = document.querySelector("#static-consultation-form");
const staticConsultationSuccess = document.querySelector("#static-consultation-success");
const surfaces = [...document.querySelectorAll('.site-header, main, .site-footer')];
const closeOverlays = () => { overlays.forEach(o => {o.hidden=true;}); surfaces.forEach(s=>s.inert=false); document.body.classList.remove('modal-open'); returnFocus?.focus(); };
const openOverlay = (id) => { closeOverlays(); const overlay = document.querySelector(id); if (!overlay) return; overlay.hidden = false; surfaces.forEach(s=>s.inert=true); document.body.classList.add("modal-open"); requestAnimationFrame(() => overlay.querySelector("input, button")?.focus()); };

document.addEventListener("click", (event) => {
  const target = event.target.closest("button, a");
  if (!target) return;
  if (target.matches("[data-consultation]")) { event.preventDefault(); staticConsultationForm.hidden = false; staticConsultationSuccess.hidden = true; openOverlay("#consultation-overlay"); }
  if (target.matches("[data-about]")) { event.preventDefault(); openOverlay("#about-overlay"); }
  if (target.matches("[data-privacy]")) { event.preventDefault(); openOverlay("#privacy-overlay"); }
  if (target.matches("[data-close-overlay]")) { event.preventDefault(); closeOverlays(); }
  if (target.matches("[data-service-detail]")) {
    event.preventDefault();
    const template = document.querySelector(`template[data-service-template="${target.dataset.serviceDetail}"]`);
    const content = document.querySelector("#service-detail-content");
    content.replaceChildren(template.content.cloneNode(true));
    openOverlay("#service-detail-overlay");
  }
});

overlays.forEach((overlay) => overlay.addEventListener("mousedown", (event) => { if (event.target === overlay) closeOverlays(); }));
addEventListener("keydown", (event) => { if (event.key === "Escape") closeOverlays(); });

const dateValue = document.querySelector("#static-date-value");
const timeValue = document.querySelector("#static-time-value");
const dateTrigger = document.querySelector("#static-date-trigger");
const timeTrigger = document.querySelector("#static-time-trigger");
const calendarPanel = document.querySelector("#static-calendar-panel");
const timePanel = document.querySelector("#static-time-panel");
const calendarMonth = document.querySelector("#static-calendar-month");
const calendarDays = document.querySelector("#static-calendar-days");
const previousMonth = document.querySelector("#static-prev-month");
const nextMonth = document.querySelector("#static-next-month");
const timeDate = document.querySelector("#static-time-date");
const scheduleError = document.querySelector("#static-schedule-error");
const timeButtons = [...document.querySelectorAll("[data-time-value]")];

const indiaParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).formatToParts(new Date());
const indiaDate = Object.fromEntries(indiaParts.map(({ type, value }) => [type, value]));
const minimumDate = `${indiaDate.year}-${indiaDate.month}-${indiaDate.day}`;
let visibleMonth = new Date(Number(indiaDate.year), Number(indiaDate.month) - 1, 1);

const isoDate = (year, month, day) => `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
const friendlyDate = (value) => value
  ? new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${value}T12:00:00`))
  : "Choose a date";
const setTriggerText = (trigger, value) => { trigger.querySelector("span").textContent = value; };
const closeSchedulePanels = () => {
  calendarPanel.hidden = true;
  timePanel.hidden = true;
  dateTrigger.setAttribute("aria-expanded", "false");
  timeTrigger.setAttribute("aria-expanded", "false");
};

function renderCalendar() {
  const year = visibleMonth.getFullYear();
  const month = visibleMonth.getMonth();
  const todayMonth = new Date(`${minimumDate}T12:00:00`);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const leadingBlanks = new Date(year, month, 1).getDay();

  calendarMonth.textContent = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(visibleMonth);
  previousMonth.disabled = year === todayMonth.getFullYear() && month === todayMonth.getMonth();
  calendarDays.replaceChildren();

  for (let index = 0; index < leadingBlanks; index += 1) calendarDays.append(document.createElement("span"));
  for (let day = 1; day <= daysInMonth; day += 1) {
    const value = isoDate(year, month, day);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = String(day);
    const maximum = new Date(`${minimumDate}T12:00:00`);
    maximum.setDate(maximum.getDate()+180);
    const maximumDate = isoDate(maximum.getFullYear(), maximum.getMonth(), maximum.getDate());
    button.disabled = value < minimumDate || value > maximumDate;
    button.setAttribute("aria-label", friendlyDate(value));
    button.classList.toggle("is-selected", value === dateValue.value);
    button.addEventListener("click", () => {
      dateValue.value = value;
      timeValue.value = "";
      setTriggerText(dateTrigger, friendlyDate(value));
      setTriggerText(timeTrigger, "Choose a time");
      dateTrigger.classList.add("has-value");
      timeTrigger.classList.remove("has-value");
      timeTrigger.disabled = false;
      timeButtons.forEach((slot) => slot.classList.remove("is-selected"));
      timeDate.textContent = friendlyDate(value);
      scheduleError.hidden = true;
      calendarPanel.hidden = true;
      dateTrigger.setAttribute("aria-expanded", "false");
      timePanel.hidden = false;
      timeTrigger.setAttribute("aria-expanded", "true");
      renderCalendar();
    });
    calendarDays.append(button);
  }
}

dateTrigger.addEventListener("click", () => {
  const willOpen = calendarPanel.hidden;
  closeSchedulePanels();
  calendarPanel.hidden = !willOpen;
  dateTrigger.setAttribute("aria-expanded", String(willOpen));
});

timeTrigger.addEventListener("click", () => {
  if (!dateValue.value) return;
  const willOpen = timePanel.hidden;
  closeSchedulePanels();
  timePanel.hidden = !willOpen;
  timeTrigger.setAttribute("aria-expanded", String(willOpen));
});

previousMonth.addEventListener("click", () => {
  visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1);
  renderCalendar();
});

nextMonth.addEventListener("click", () => {
  visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1);
  renderCalendar();
});

timeButtons.forEach((button) => button.addEventListener("click", () => {
  timeValue.value = button.dataset.timeValue;
  setTriggerText(timeTrigger, button.querySelector("span").textContent);
  timeTrigger.classList.add("has-value");
  timeButtons.forEach((slot) => slot.classList.toggle("is-selected", slot === button));
  scheduleError.hidden = true;
  closeSchedulePanels();
}));

renderCalendar();
let pendingSubmission;

staticConsultationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!dateValue.value || !timeValue.value) {
    scheduleError.textContent = !dateValue.value ? "Please choose a consultation date." : "Please choose a consultation time.";
    scheduleError.hidden = false;
    closeSchedulePanels();
    if (!dateValue.value) {
      calendarPanel.hidden = false;
      dateTrigger.setAttribute("aria-expanded", "true");
    } else {
      timePanel.hidden = false;
      timeTrigger.setAttribute("aria-expanded", "true");
    }
    return;
  }
  const form = staticConsultationForm;
  const submit = form.querySelector('button[type="submit"]');
  if (form.getAttribute('aria-busy') === 'true') return;
  const payload = JSON.stringify(Object.fromEntries(new FormData(form)));
  if (!pendingSubmission || pendingSubmission.payload !== payload) {
    pendingSubmission = {payload, key: crypto.randomUUID()};
  }
  form.setAttribute('aria-busy', 'true');
  submit.disabled = true;
  scheduleError.hidden = true;
  try {
    const response = await fetch('/api/enquiries', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': pendingSubmission.key},
      body: pendingSubmission.payload,
      signal: AbortSignal.timeout(15000)
    });
    const result = await response.json();
    if (!response.ok || result.status !== 'received') throw new Error(result.error || 'Unable to send your enquiry.');
  } catch (error) {
    scheduleError.textContent = error.name === 'TimeoutError'
      ? 'We could not confirm receipt. Please contact info@blueeyemedia.in before retrying.'
      : (error.message || 'Please try again or email info@blueeyemedia.in.');
    scheduleError.hidden = false;
    submit.disabled = false;
    form.removeAttribute("aria-busy");
    return;
  }
  submit.disabled = false;
  form.removeAttribute("aria-busy");
  pendingSubmission = undefined;
  form.reset();
  dateValue.value = "";
  timeValue.value = "";
  setTriggerText(dateTrigger, "Choose a date");
  setTriggerText(timeTrigger, "Choose date first");
  dateTrigger.classList.remove("has-value");
  timeTrigger.classList.remove("has-value");
  timeTrigger.disabled = true;
  timeButtons.forEach((slot) => slot.classList.remove("is-selected"));
  closeSchedulePanels();
  renderCalendar();
  staticConsultationForm.hidden = true;
  staticConsultationSuccess.hidden = false;
});


document.addEventListener('click', e => {
  const trigger = e.target.closest('[data-consultation],[data-about],[data-privacy],[data-service-detail]');
  if(trigger && !trigger.closest('.consultation-backdrop,.information-backdrop')) returnFocus=trigger;
}, true);
document.addEventListener('keydown', e => {
  const active=overlays.find(o=>!o.hidden);
  if(!active || e.key !== 'Tab') return;
  const items=[...active.querySelectorAll('button,a[href],input,textarea,select')].filter(x=>!x.disabled && x.getClientRects().length && x.tabIndex >= 0);
  const first=items[0],last=items.at(-1);
  if(e.shiftKey && document.activeElement===first){e.preventDefault();last?.focus();}
  else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first?.focus();}
});
