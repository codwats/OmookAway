# OmookAway

OmookAway is an Omarchy-native break reminder that protects scheduled computer work with recurring, enforced screen breaks.

## Language

**Monotropic Worker**:
A person whose attention can remain intensely concentrated on a narrow task long enough that time and body cues are easy to miss. OmookAway's primary users are self-directing Monotropic Workers seeking help interrupting work before exhaustion accumulates.
_Avoid_: Employee, productivity user, distracted user

**Recovery**:
Time away from active screen use intended to interrupt long, uninterrupted work and reduce accumulated strain. OmookAway supports recovery habits but does not claim to diagnose, treat, or prevent burnout or illness.
_Avoid_: Productivity gain, medical treatment, optimization

**Work Interval**:
A configured span of active computer use that must elapse before an upcoming break. The default is 30 minutes; Idle and system downtime do not advance it, and a fresh interval after away-time recovery begins only when active input returns.
_Avoid_: Focus session, work session, timer

**Break**:
A configurable timed rest period that covers every display and prevents ordinary computer interaction while it is active. The default is five minutes; its emergency control becomes a normal completion control after 20 percent has elapsed.
_Avoid_: Pause, timeout, lock screen

**Manual Break**:
A Break requested before the current Work Interval elapses. It has the same completion, emergency escape, counting, and fresh-Work-Interval effects as any other Break, but has no inherited Snooze Budget.
_Avoid_: Quick break, ad hoc timer

**Satisfied Break**:
A Break completed by its timer, ended voluntarily after its minimum duration, or fulfilled by continuous time away through Idle, screen lock, or system sleep lasting at least the configured Break duration. It starts a fresh Work Interval when active use returns.
_Avoid_: Reset, skipped break

**Aborted Break**:
A Break ended through the deliberate emergency escape before it is satisfied. It starts a fresh Work Interval and is not retried.
_Avoid_: Snooze, completed break

**Warning**:
Configurable advance notice that a break is about to begin, during which the person may start the break immediately or use an available snooze. The default is 20 seconds.
_Avoid_: Alert, pre-break

**Upcoming Break**:
A Break that becomes owed when a Work Interval elapses. It remains owed through Warning, Snooze, Pause, and recoverable system failure until it becomes Satisfied, Aborted, or discarded at a Work Hours boundary.
_Avoid_: Pending timer, reminder, notification

**Snooze**:
A configurable postponement of an upcoming break. The default duration is five minutes; each upcoming break has a Snooze Budget of three that is not replenished while snoozing.
_Avoid_: Skip, dismiss, delay

**Snooze Budget**:
The number of snoozes remaining for one upcoming break. The MVP budget begins at three.
_Avoid_: Daily allowance, snooze credits

**Work Hours**:
A weekly, per-day schedule containing the windows in which OmookAway may advance Work Intervals or begin Breaks. OmookAway is dormant outside these hours, and system sleep or downtime never creates catch-up Breaks.
_Avoid_: Office hours, availability, calendar

**Work Hours Window**:
A continuous scheduled span within one calendar day. Each window begins with a fresh Work Interval; progress and Upcoming Breaks never carry across gaps, midnight, or other Work Hours boundaries.
_Avoid_: Shift, session, schedule block

**Pause**:
A user-requested suspension of Work Interval progress or an upcoming Break until a chosen time. It does not consume a Snooze; Work resumes from its previous progress, while an upcoming Break resumes with a fresh Warning and its remaining Snooze Budget.
_Avoid_: Snooze, disable, outside hours

**Idle**:
A continuous absence of detected user input lasting at least the configured idle threshold. Idle does not advance a Work Interval, and time genuinely away through Idle, screen lock, or system sleep creates a Satisfied Break once it lasts at least the configured Break duration.
_Avoid_: Pause, sleep, inactivity event

**Degraded Wall-Clock Mode**:
An explicit user-selected fallback that advances Work Intervals by elapsed wall time when activity detection is unavailable. OmookAway remains dormant rather than entering this mode silently.
_Avoid_: Automatic fallback, active-use mode

**Enforcement Unavailable**:
A dormant error state entered after two consecutive failures to cover every display for a Break. The Upcoming Break remains owed, automatic retries stop, and the user must explicitly retry or restart after inspecting the error.
_Avoid_: Aborted Break, retry loop, partial lock
