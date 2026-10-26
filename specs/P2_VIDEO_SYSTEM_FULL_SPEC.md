# P2 — Full Video System: Mapping, Playback, Progress & Learning Journey

> **Status:** implementation-ready specification  
> **Date:** 2026-10-26  
> **Applies to:** NexaLab Content Tool, BE-NexaLab and FE-NexaLab  
> **Scope:** full P2 contract from content mapping to student/teacher learning analytics  
> **Supersedes:** the claim that P2 is fully complete based only on URL mapping, playback and `lastPosition`  
> **Current baseline:** mapped YouTube videos play through the IFrame Player API; FE sends `heartbeat`/`ended`; BE stores one monotonic `progressValue` and `lastPosition` on `StepProgress`.

## 1. Problem

The current implementation proves that an embedded YouTube video can be played, resumed and marked complete. It does not prove which parts the student watched. A student may seek from second 10 to second 500 and the current maximum-position calculation can report progress near second 500 even though the intervening interval was not observed.

Mapped Lesson videos may also share one legacy `VIDEO` step. That conflates progress when a Lesson has two or more videos and cannot answer:

- Which video is the student watching?
- Which time ranges were actually observed?
- Which ranges were skipped or replayed?
- Where should this specific video resume?
- At which Lesson/video/segment is the student currently located?
- What evidence supports completion?

P2 covers the complete video lifecycle: Content Tool discovery/mapping/review, deterministic package export, BE validation/materialization, student playback, server-authoritative segment coverage, resume, learning journey and teacher insight. NexaLab does not need to host the video bytes when an approved external provider is used.

## Current implementation status

| P2 slice | Current status | Completion evidence / gap |
|---|---|---|
| P2-A — Discovery and mapping | **Technical baseline done** | OLM playlist inspected; title-based mapping exists. Needs governed provenance, review state and unmatched/ambiguous queue. |
| P2-B — Content contract and release | **Partial** | `lesson.videos` and `sections[].videos` pass current BE schema and Bài 02 E2E. Documentation, true transcript/equivalent text and one-step-per-video materialization remain open. |
| P2-C — Student playback | **Technical baseline done** | YouTube IFrame playback, URL normalization, heartbeat and resume exist. Multiple-video independence and robust offline/retry semantics remain open. |
| P2-D — Segment progress | **Not implemented** | Current `lastPosition`/maximum percentage is not watched-range evidence. |
| P2-E — Learning journey | **Not implemented** | Student journey projection and current-step history are absent. |
| P2-F — Teacher insight | **Not implemented** | Class summary and student video-range drill-down are absent. |

P2 is complete only when every slice above satisfies this specification and staging E2E.

## 2. Outcome

For every published Lesson video, NexaLab SHALL create a distinct stable `VIDEO` step. While a student plays that video, the client sends bounded playback observations. The backend validates and merges observed intervals, calculates unique watched coverage, stores the last legitimate playback position and derives completion. Student, teacher and progress APIs consume the same backend-derived state.

Example result:

```json
{
  "videoId": "olm-5bylfrs-xtw",
  "durationSeconds": 360,
  "watchedRanges": [
    { "startSecond": 0, "endSecond": 135 },
    { "startSecond": 270, "endSecond": 360 }
  ],
  "watchedSeconds": 225,
  "coveragePercent": 62,
  "lastPosition": 360,
  "status": "IN_PROGRESS"
}
```

## 3. Scope

### In scope

1. Stable identity for every Lesson-level and section-level video.
2. One materialized `VIDEO` `LessonStep` per video.
3. YouTube IFrame API and native HTML video playback observations.
4. Server-side interval validation, merge and coverage calculation.
5. Resume per student, assignment context and video step.
6. Open Curriculum and assigned Lesson progress.
7. Student learning journey and teacher class/student drill-down.
8. Backward-compatible migration from the current single-video aggregate.
9. Data retention, authorization, privacy and abuse limits.

### Out of scope

- Recording video, audio, camera, screen, keystrokes or student attention.
- Claiming that an open tab proves attention or comprehension.
- Frame-level tracking or sub-second analytics.
- Tracking playback on youtube.com outside the NexaLab player.
- Requiring NexaLab-hosted video assets; supported external providers may remain embedded.
- Using watch coverage as proof that the student understood the material.
- A general event warehouse or real-time proctoring system.

## 4. Product semantics

### 4.1 Terms

- **Playback observation:** a bounded statement that the player advanced continuously from one position to another during a session.
- **Watched range:** a server-accepted half-open interval `[startSecond, endSecond)`.
- **Coverage:** union length of accepted watched ranges divided by the canonical duration.
- **Last position:** latest accepted playback position for resume; it is not coverage.
- **Replay seconds:** observed seconds overlapping ranges already watched. It is informative and does not increase unique coverage.
- **Learning journey:** ordered, backend-derived states across Lesson steps and video ranges.

### 4.2 Completion

- Default video completion threshold: `90%` unique coverage.
- `ended` alone SHALL NOT complete a video whose unique coverage is below the threshold.
- A publisher may configure `completionThresholdPercent` from `50` to `100`; absence means `90`.
- Videos of 30 seconds or less require `100%` coverage, allowing at most a two-second measurement tolerance.
- Once completed, a step remains completed for that exact LessonStep/version, but later observations may still update resume and replay analytics.
- `complete-fallback` remains available only when the published step contains reviewed `equivalentText`; completion method SHALL be recorded as `EQUIVALENT_TEXT` rather than video coverage.

### 4.3 Seeking and playback speed

- Seeking changes the current position but does not create coverage for the skipped interval.
- An observation is accepted only for actual playing time between consecutive samples.
- Playback rates from `0.25` through `2.0` are supported. The maximum credible media advance equals elapsed wall time × playback rate plus tolerance.
- Background, paused, buffering, unstarted and ended states do not create coverage.
- Rewinding may update the resume position but does not reduce existing coverage.

## 5. Content contract

### 5.1 Video object

Content Tool SHALL export this versioned shape for both `lesson.videos[]` and `lesson.sections[].videos[]`:

```json
{
  "id": "olm-5bylfrs-xtw",
  "title": "Động năng, thế năng",
  "url": "https://www.youtube.com/watch?v=5bYlFrS-xTw",
  "provider": "YOUTUBE",
  "providerVideoId": "5bYlFrS-xTw",
  "transcript": "Reviewed transcript or equivalent text",
  "captionUrl": null,
  "completionThresholdPercent": 90,
  "provenance": {
    "sourceUrl": "https://www.youtube.com/playlist?list=...",
    "sourceLabel": "OLM KHTN 9 playlist",
    "checkedAt": "2026-10-25T00:00:00.000Z",
    "availability": "AVAILABLE"
  }
}
```

Required rules:

- `id` is stable within the pack and matches the existing authored-ID pattern.
- `(pack key, video id)` is unique, including across Lesson and section lists.
- `provider` is `YOUTUBE` or `DIRECT` for P2.
- YouTube URL and `providerVideoId` must resolve to the same canonical ID.
- Playlist and tracking parameters are removed from the playback URL but retained in provenance when relevant.
- `transcript` must be an actual reviewed transcript or meaningful equivalent learning text. A sentence such as “Video minh họa nội dung...” is metadata and SHALL NOT be labelled as transcript.
- Video mapping does not inherit textbook rights. Provenance and rights/accessibility review remain explicit release evidence.
- External videos use allowlisted HTTPS providers. NexaLab-hosted media continues to use immutable asset versions.

Legacy packs without `videos` remain valid and retain their existing digest. The new fields are optional until a pack includes a mapped video; they must not be defaulted into legacy canonicalization.

### 5.2 Deterministic step identity

Materialization SHALL preserve a deterministic step ID derived from the authored video ID, for example `video:<packKey>:<videoId>`, subject to the database ID constraints. Releasing wording or transcript changes with the same authored video ID preserves the logical identity mapping. Replacing the actual provider video requires a new video ID unless an explicit correction migration is recorded.

Step ordering:

1. `READING`
2. Lesson-level videos in manifest order
3. Section-level videos after their owning section's reading boundary when section-aware reading steps exist; until then, after Lesson-level videos in section/order sequence
4. `BASIC_EXERCISE`
5. remaining configured steps

Every video step config SHALL include its `videoId`, provider, canonical playback resource, transcript/equivalent text and threshold.

## 6. Persistence model

`StepProgress` remains the aggregate used by existing pathway/course-progress consumers. Add two models; names may change to follow repository conventions but semantics must remain.

### 6.1 VideoProgressEvidence

One row per `(studentId, assignmentScope, stepId)`:

```text
id
studentId
stepId
assignmentId nullable
durationSeconds
watchedRanges JSON
watchedSeconds
replaySeconds
coveragePercent
lastPosition
completionMethod VIDEO_COVERAGE | EQUIVALENT_TEXT | LEGACY
startedAt
completedAt nullable
lastObservedAt
createdAt
updatedAt
```

Because PostgreSQL unique constraints treat `NULL` values as distinct in the current schema, free-practice writes SHALL use either:

- a partial unique index for `(studentId, stepId) WHERE assignmentId IS NULL`, plus a unique assigned index; or
- a non-null normalized scope key.

The implementation must not rely only on `@@unique([studentId, assignmentId, stepId])` for null assignment scopes.

### 6.2 VideoPlaybackSession

One row per player session:

```text
id UUID/CUID generated by BE
evidenceId
studentId
stepId
assignmentId nullable
provider
clientSessionId
startedAt
lastSequence
lastPosition
lastClientObservedAt
endedAt nullable
createdAt
updatedAt
```

Raw heartbeats SHALL NOT be retained indefinitely. P2 stores merged ranges plus session summaries. If short-lived raw observations are introduced for diagnosis, retain them no longer than 30 days and exclude them from teacher-facing semantics.

### 6.3 Aggregate projection

After each accepted observation, BE updates `StepProgress` in the same transaction:

- `progressValue = coveragePercent`
- `lastPosition = evidence.lastPosition`
- `status = COMPLETED` only when the threshold is met or equivalent text is completed
- `startedAt` and `completedAt` mirror evidence

No client-supplied percentage is persisted.

## 7. API contract

All routes require authentication. Student routes may update only the caller's own evidence. Assignment access uses the existing explicit `assignmentId` context.

### 7.1 Start/resume

`POST /lessons/:lessonId/steps/:stepId/video-sessions`

Query: optional `assignmentId`.

Request:

```json
{
  "clientSessionId": "uuid-generated-per-player-mount",
  "provider": "YOUTUBE",
  "providerVideoId": "5bYlFrS-xTw",
  "durationSeconds": 360
}
```

Response:

```json
{
  "sessionId": "server-session-id",
  "resumeAt": 135,
  "coveragePercent": 38,
  "watchedRanges": [{ "startSecond": 0, "endSecond": 135 }],
  "status": "IN_PROGRESS",
  "heartbeatIntervalSeconds": 10
}
```

BE verifies Lesson/step access, step type, provider identity and plausible duration. Duration becomes canonical after the first accepted non-zero value; later large changes are rejected and logged.

### 7.2 Observe playback

`PUT /video-sessions/:sessionId/observations`

Request:

```json
{
  "sequence": 4,
  "fromSecond": 120,
  "toSecond": 130,
  "observedMediaSeconds": 10,
  "playbackRate": 1,
  "playerState": "PLAYING",
  "clientObservedAt": "2026-10-26T10:00:10.000Z"
}
```

Rules:

- `sequence` is strictly increasing within a session; duplicate sequence returns the previous result idempotently.
- Range endpoints are integer seconds between `0` and canonical duration.
- `toSecond < fromSecond` represents rewind/seek and creates no watched range.
- Accepted advance is capped by server elapsed time × playback rate plus 3 seconds tolerance.
- A forward jump larger than the credible advance updates resume to the new player position only after the next continuous observation; it does not fill the jump.
- A single observation spans at most 30 media seconds.
- Requests are rate-limited per student/session and payloads are strictly validated with Zod.

Response returns the server aggregate:

```json
{
  "acceptedRange": { "startSecond": 120, "endSecond": 130 },
  "coveragePercent": 41,
  "watchedSeconds": 148,
  "replaySeconds": 7,
  "lastPosition": 130,
  "status": "IN_PROGRESS",
  "completedAt": null
}
```

### 7.3 Pause/end flush

Pause, visibility change, component unmount and ended events flush the last continuous interval through the same observation endpoint. An optional session-close endpoint may set `endedAt`; it does not independently grant completion.

### 7.4 Student journey

`GET /me/learning-journey?courseId=...` returns an ordered, paginated projection:

- course/class context;
- Lesson and step identity;
- step type/state;
- for video: title, coverage, last position, duration, completion method and timestamps;
- next recommended step derived from the existing pathway;
- no raw heartbeat data.

### 7.5 Teacher views

- `GET /classes/:classId/learning-journey/summary`
- `GET /classes/:classId/students/:studentId/learning-journey`

Teacher must own/manage the class. An outsider receives `404` or the repository-standard access denial without leaking class membership. Summary supports assignment/Lesson filters and returns:

- students not started/in progress/completed;
- current Lesson and step;
- video coverage and last active time;
- students stalled since a configurable display cutoff;
- aggregate most-skipped intervals only when the cohort is large enough for the privacy threshold.

The first full P2 release may omit cohort skip heatmaps; individual journey and class completion summary are required.

## 8. Interval algorithm

BE is authoritative:

1. Validate session, sequence, duration, elapsed time, playback rate and access.
2. Convert a credible continuous observation into `[floor(from), ceil(to))`.
3. Clamp to `[0, duration]`.
4. Sort existing and new ranges.
5. Merge overlapping or adjacent ranges with a tolerance of one second.
6. Compute `watchedSeconds` from the union.
7. Compute overlap with prior union as replay seconds.
8. Calculate `floor(watchedSeconds / duration × 100)` capped at 100.
9. Derive completion using the published threshold.
10. Persist evidence, session and `StepProgress` atomically.

The merge function must be deterministic and covered by property-style cases: order independence, idempotency, overlap, adjacency, gaps, rewind and bounds.

## 9. Frontend behavior

### Student player

- Use YouTube IFrame API for YouTube and media events for native video.
- Start a server session when the player is ready and duration is known.
- Sample while `PLAYING`; default flush every 10 seconds, plus pause/end/unmount/visibility change.
- Detect seek by comparing expected media advance with actual position; reset the continuous interval after seek.
- Display “Đã xem X%” from BE response, never from local `currentTime / duration`.
- Resume only after server session response; allow the student to restart from zero.
- Show saved/error/retry states. Queue at most the latest unsent continuous observation in memory; do not fabricate coverage after offline gaps.
- Render each mapped video as a separate pathway item/state.
- Transcript and equivalent text remain accessible without requiring playback.

### Teacher dashboard

Minimum UI:

1. Class table: student, current Lesson, current step, video percentage, last activity, assignment status.
2. Student drawer/page: chronological Lesson steps and each video's watched-range bar.
3. Range bar visually distinguishes watched and not-observed intervals; exact values are also available as text/table for accessibility.
4. Empty, loading, permission and no-evidence states are explicit.

The dashboard states “observed playback coverage”, not “attention” or “understanding”.

## 10. Authorization, privacy and integrity

- Students can write/read only their own evidence.
- Teachers can read only students in classes they own or are authorized to manage.
- Admin access follows existing admin reporting policy and is audited.
- Parents are out of scope until a separate parent-report decision defines the disclosed detail.
- URLs, transcripts and progress payloads are treated as data, never executable markup.
- Do not store IP-derived location, device fingerprint, camera, microphone or cross-site YouTube history.
- Rate limit and cap sessions, ranges and payload size. Compact merged ranges when necessary; a video cannot create unbounded rows.
- Release/version identity is retained so evidence never moves silently to a replacement video.

## 11. Migration and compatibility

1. Add new tables/indexes without deleting or rewriting existing `StepProgress` rows.
2. Materialize one step per video for new pack versions.
3. Existing one-video steps keep their IDs and become `completionMethod = LEGACY` when evidence is first projected.
4. Existing completed progress remains completed; do not invent watched ranges from `progressValue` or `lastPosition`.
5. Existing in-progress rows may retain `lastPosition` for resume, but coverage starts as unknown/zero until new observations arrive. UI labels this as legacy resume evidence.
6. Multi-video Lessons require a new pack/Lesson version. Do not copy one aggregate progress record into every video.
7. Historical attempts/progress remain linked to the old LessonStep/version.
8. Rollout is feature-flagged by environment and can fall back to the current heartbeat endpoint during staging. Do not dual-write after full P2 becomes authoritative.

## 12. Observability

Record metrics without student names in metric labels:

- accepted/rejected/duplicate observations;
- session starts and closes;
- validation rejection reason;
- observation latency and transaction duration;
- ranges per evidence row and compaction count;
- completion method counts;
- mismatch between declared and established duration.

Audit teacher/admin journey access using the existing audit mechanism. Application logs must not dump transcripts, JWTs or full watched-range payloads.

## 13. Acceptance criteria

### Content Tool and release

- A Lesson with three mapped videos exports three stable video IDs and BE materializes three distinct `VIDEO` steps.
- Re-export with unchanged content is deterministic.
- Duplicate video IDs, provider/URL mismatch and placeholder transcript are rejected or block release with actionable errors.
- A legacy pack without `videos` retains its prior schema/digest behavior.

### Tracking

- Continuous playback `0–100` creates coverage `0–100`.
- Playback `0–10`, seek to `90`, playback `90–100` produces 20 seconds coverage, not 100.
- Replaying `0–10` does not increase unique watched seconds and increases replay seconds.
- Out-of-order and duplicate sequences cannot double-count.
- Heartbeats from paused/buffering/hidden gaps do not create coverage.
- Completion occurs only at configured unique coverage or reviewed equivalent-text completion.
- Refresh resumes the correct student, context, video and second.
- Two videos in one Lesson never share progress.

### Authorization and concurrency

- Student A cannot write/read Student B evidence.
- Teacher owner can read the class; outsider cannot infer it.
- Open Curriculum (`assignmentId = null`) concurrent writes result in one evidence aggregate.
- Assigned and free-practice evidence remain separate.
- Two tabs/sessions merge ranges transactionally without losing coverage.

### Journey UI

- Student sees current step and server coverage.
- Teacher sees the correct current Lesson/video and watched-range visualization.
- Journey ordering is stable across refresh and pagination.
- Mobile layout, keyboard navigation and text alternatives pass existing accessibility checks.

### Regression

- Reading, BASIC_EXERCISE, QUIZ, Lab and course progress behavior remain unchanged except that each required video contributes its own evidence.
- Old Lesson versions and historical evidence remain readable.
- FE typecheck/build, BE unit/build and focused integration/E2E suites pass.

## 14. Required tests

### BE unit

- interval validation/merge properties;
- credible-advance rules for rate, seek, pause and elapsed time;
- completion thresholds;
- migration projection rules;
- per-video materialization and stable IDs;
- journey projection and authorization.

### BE integration

- session start → observations → aggregate/StepProgress transaction;
- idempotent sequence retry;
- concurrent open-curriculum observations;
- assignment isolation;
- teacher owner/outsider access;
- new pack version preserves old evidence.

### FE

- YouTube and native players emit continuous observations and reset on seek;
- pause/end/unmount flush;
- retry does not manufacture offline coverage;
- server percentage and resume behavior;
- multiple videos have independent states;
- teacher range bar and accessible text.

### Staging E2E

Use one Lesson with at least two videos and two students:

1. Student A watches disjoint ranges and seeks over the middle.
2. Student B completes one video and does not start the other.
3. Reload verifies resume and distinct video states.
4. Teacher view matches the server aggregates.
5. Release a wording-only update with stable video IDs and verify identity behavior.
6. Release a replacement video with a new ID and verify old evidence remains historical.

## 15. Delivery slices

### P2-A — Discovery, mapping and review

- Import or inspect playlist/video metadata without rerunning book OCR.
- Match by canonical Lesson/section identity; ambiguous/unmatched items enter an explicit review queue.
- Record provider, source playlist/URL, availability, checked time, rights/accessibility state and operator decision.
- Never generate a fake transcript from the title.

### P2-B — Contract and materialization

- Version video schema/provenance.
- Materialize one stable VIDEO step per video.
- Remove the shared-step ambiguity.

### P2-C — Student playback baseline

- Normalize supported video URLs and render YouTube/native players.
- Accessible transcript/equivalent text and explicit unavailable state.
- Independent player state for every mapped video.

### P2-D — Evidence engine

- Add evidence/session persistence and indexes.
- Implement session and observation APIs.
- Project aggregates to StepProgress.

### P2-E — Student experience and journey

- Instrument YouTube/native players.
- Server-derived progress, retry and resume per video.
- Student learning journey.

### P2-F — Teacher insight

- Class summary and student drill-down APIs.
- Journey timeline and watched-range bar.
- Authorization/audit/performance evidence.

P2 is complete only when all six slices and staging E2E pass. URL mapping/playback alone remains the **P2 technical baseline**, not full P2 completion.

## 16. Definition of Done

1. Every mapped video has a stable, distinct LessonStep and version identity.
2. BE derives progress from merged continuous watched ranges, not furthest timestamp.
3. Seek, replay, retry, concurrent tabs and assignment/free-practice isolation behave as specified.
4. Student resume and journey work per video.
5. Authorized teachers can identify the student's current Lesson/video and inspect observed ranges.
6. Content provenance, transcript/equivalent text and release gates are represented honestly.
7. Migration preserves existing progress without inventing historical evidence.
8. Unit, integration, FE and staging E2E evidence is recorded against exact commits and target.

