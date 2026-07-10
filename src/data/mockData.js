// All data here is fabricated. Used to demonstrate UX only.

export const attendanceStudents = [
  {
    id: 'S-10421',
    name: 'Marcus T.',
    grade: 9,
    school: 'Lincoln HS',
    unexplainedDays: 7,
    ytdAbsenceRate: 0.18,
    lastContact: '2026-05-11',
    severity: 'Moderate',
    conversation: [
      { from: 'agent', t: '2026-05-12 08:14', text: "Good morning — this is Lincoln HS reaching out about Marcus. He's been marked absent the last three days. Can you share what's going on?" },
      { from: 'guardian', t: '2026-05-12 08:31', text: "Hi yes. He just won't get out of bed. Says his stomach hurts but then he's fine by lunch." },
      { from: 'agent', t: '2026-05-12 08:32', text: "That pattern is worth flagging. Has anything changed at school recently — schedule, friends, a specific class?" },
      { from: 'guardian', t: '2026-05-12 08:40', text: "He mentioned 4th period is rough. Group project drama I think." },
      { from: 'agent', t: '2026-05-12 08:41', text: "Got it. I'll loop in his counselor about period 4. In the meantime, can we agree on a same-day check-in tomorrow morning?" },
      { from: 'guardian', t: '2026-05-12 08:46', text: "Yes that's fine." },
    ],
    clusters: {
      typology:    { label: 'School refusal', value: 0.78 },
      function:    { label: 'Avoidance of aversive social/eval', value: 0.71 },
      developmental:{ label: 'High school (9–12)', value: 0.90 },
      ecological: { label: 'Peer / classroom', value: 0.62 },
      severity:    { label: 'Moderate', value: 0.55 },
    },
  },
  {
    id: 'S-10487',
    name: 'Aisha R.',
    grade: 4,
    school: 'Oakridge ES',
    unexplainedDays: 11,
    ytdAbsenceRate: 0.24,
    lastContact: '2026-05-09',
    severity: 'High',
    conversation: [
      { from: 'agent', t: '2026-05-09 07:50', text: "Hi — checking in on Aisha. We've logged 11 unexplained absences this semester. How can we support?" },
      { from: 'guardian', t: '2026-05-09 09:12', text: "I work nights. Some mornings nobody is home to make sure she's on the bus." },
      { from: 'agent', t: '2026-05-09 09:14', text: "Thank you for sharing that. We have a morning-walker program with a neighbor family — would you like us to coordinate?" },
      { from: 'guardian', t: '2026-05-09 09:30', text: "Yes please that would help a lot." },
      { from: 'agent', t: '2026-05-09 09:31', text: "Great. I'll send the form by 3pm and a counselor will call to confirm." },
    ],
    clusters: {
      typology:    { label: 'Truancy / family-condoned', value: 0.66 },
      function:    { label: 'Tangible reinforcement (home)', value: 0.48 },
      developmental:{ label: 'Elementary (K–5)', value: 0.95 },
      ecological: { label: 'Family / caregiver', value: 0.83 },
      severity:    { label: 'High (chronic)', value: 0.81 },
    },
  },
  {
    id: 'S-10512',
    name: 'Diego F.',
    grade: 7,
    school: 'Cedar MS',
    unexplainedDays: 5,
    ytdAbsenceRate: 0.11,
    lastContact: '2026-05-14',
    severity: 'Low',
    conversation: [
      { from: 'agent', t: '2026-05-14 09:01', text: "Hello — Diego missed school yesterday with no note. Is everything ok?" },
      { from: 'guardian', t: '2026-05-14 09:22', text: "Doctor appointment, I forgot to send a note. Sorry!" },
      { from: 'agent', t: '2026-05-14 09:23', text: "No problem — I'll mark it excused. Could you send the doctor's note when convenient?" },
      { from: 'guardian', t: '2026-05-14 12:05', text: "Just emailed it." },
    ],
    clusters: {
      typology:    { label: 'Excused / documented', value: 0.22 },
      function:    { label: 'External obligation', value: 0.30 },
      developmental:{ label: 'Middle school (6–8)', value: 0.88 },
      ecological: { label: 'Individual / health', value: 0.55 },
      severity:    { label: 'Low', value: 0.18 },
    },
  },
  {
    id: 'S-10644',
    name: 'Hannah K.',
    grade: 11,
    school: 'Lincoln HS',
    unexplainedDays: 14,
    ytdAbsenceRate: 0.31,
    lastContact: '2026-05-05',
    severity: 'High',
    conversation: [
      { from: 'agent', t: '2026-05-05 08:00', text: "Hi — Hannah's attendance has dropped sharply in the last six weeks. Want to set up a time to talk?" },
      { from: 'guardian', t: '2026-05-05 08:44', text: "Honestly we're struggling. She got a job and we need the income. School feels less of a priority right now." },
      { from: 'agent', t: '2026-05-05 08:46', text: "I hear that. There are options — flexible scheduling, work-based credit, and a counselor who can help you plan. Want me to set that up?" },
      { from: 'guardian', t: '2026-05-05 09:01', text: "Yes." },
    ],
    clusters: {
      typology:    { label: 'School withdrawal (economic)', value: 0.74 },
      function:    { label: 'Tangible reinforcement (work)', value: 0.81 },
      developmental:{ label: 'High school (9–12)', value: 0.90 },
      ecological: { label: 'Family / economic', value: 0.78 },
      severity:    { label: 'High (chronic)', value: 0.86 },
    },
  },
];

export const clusterDimensions = [
  { key: 'typology',     name: 'Typology',              desc: 'Refusal / truancy / withdrawal / exclusion' },
  { key: 'function',     name: 'Functional analysis',   desc: 'What is the absence achieving for the student?' },
  { key: 'developmental',name: 'Developmental band',    desc: 'Pre-K / Elementary / Middle / High' },
  { key: 'ecological',   name: 'Ecological level',      desc: 'Individual / family / peer / school / community' },
  { key: 'severity',     name: 'Severity',              desc: 'Low / Moderate / High (chronic)' },
];

// -------- Roster · Student Profile setup --------

export const studentProfileRoster = [
  {
    id: 'S-10421', name: 'Marcus T.', grade: 9, school: 'Lincoln HS',
    completeness: 92, duplicates: 0,
    missing: ['Emergency contact #2', 'Photo release form'],
  },
  {
    id: 'S-10487', name: 'Aisha R.', grade: 4, school: 'Oakridge ES',
    completeness: 71, duplicates: 1,
    missing: ['Parent email', 'Race/ethnicity', 'Language preference'],
  },
  {
    id: 'S-10512', name: 'Diego F.', grade: 7, school: 'Cedar MS',
    completeness: 88, duplicates: 0,
    missing: ['Annual review signature'],
  },
  {
    id: 'S-10644', name: 'Hannah K.', grade: 11, school: 'Lincoln HS',
    completeness: 64, duplicates: 0,
    missing: ['Guardian phone', 'EL screener', '504 acknowledgement (current year)'],
  },
];

export const studentProfileAiSuggestions = {
  'S-10487': {
    fillIns: [
      { field: 'Home language', suggested: 'Spanish', confidence: 0.91, source: 'Prior enrollment form (2025)' },
      { field: 'Lunch status',  suggested: 'Free / reduced', confidence: 0.88, source: 'Cross-walked sibling record' },
      { field: 'Caregiver email', suggested: 'reyes.family@example.com', confidence: 0.74, source: 'Bus enrollment form' },
    ],
    duplicates: [
      { id: 'S-99012', name: 'Aisha R. Reynolds', similarity: 0.94, reason: 'Matching DOB + caregiver name + sibling ID' },
    ],
    tagSuggestions: ['EL-2 likely (M/L screener)', 'Free-lunch eligible (sibling roster)', 'Bilingual outreach preferred'],
  },
};

// -------- Roster · Transfer student data --------

export const transferStudents = [
  {
    id: 'TS-001', name: 'A. Patel',
    fromSchool: 'Northwood HS', fromDistrict: 'Northwood USD',
    fromState: 'CA', grade: 10,
    transcript: { status: 'received',  format: 'PESC HS Transcript v1.6' },
    folder:     { status: 'complete',  missing: [] },
  },
  {
    id: 'TS-002', name: 'M. Reyes',
    fromSchool: 'Lincoln MS', fromDistrict: 'Capitol City Schools',
    fromState: 'TX', grade: 7,
    transcript: { status: 'pending',   format: 'Ed-Fi (TX) — request sent' },
    folder:     { status: 'partial',   missing: ['Immunization records', 'Discipline summary'] },
  },
  {
    id: 'TS-003', name: 'S. Okafor',
    fromSchool: 'Bayside Prep', fromDistrict: 'Out-of-state private',
    fromState: 'FL', grade: 11,
    transcript: { status: 'received',  format: 'CLR 2.0 (badge bundle) + PESC' },
    folder:     { status: 'partial',   missing: ['Standardized test scores', 'Counselor notes'] },
  },
  {
    id: 'TS-004', name: 'J. Lim',
    fromSchool: 'Riverbend ES', fromDistrict: 'Same district',
    fromState: 'CA', grade: 5,
    transcript: { status: 'auto-linked', format: 'Internal SIS' },
    folder:     { status: 'complete',  missing: [] },
  },
  {
    id: 'TS-005', name: 'D. Owens',
    fromSchool: 'Western HS', fromDistrict: 'Western USD',
    fromState: 'IN', grade: 9,
    transcript: { status: 'received',  format: 'Ed-Fi (IN) v3.3' },
    folder:     { status: 'partial',   missing: ['504 plan (current year)'] },
  },
];

export const transferTranscripts = {
  'TS-001': {
    student: 'A. Patel', fromSchool: 'Northwood HS',
    cumulativeGPA: 3.62, weightedGPA: 3.81,
    years: [
      {
        year: '2024–25 · Grade 9',
        courses: [
          { course: 'English 9 (Honors)',         grade: 'A−', cr: 1.0, t: { course: 'Eng 9 H',           cr: 1.0, accepted: true } },
          { course: 'Algebra I',                  grade: 'B+', cr: 1.0, t: { course: 'Algebra I',         cr: 1.0, accepted: true } },
          { course: 'Biology',                    grade: 'A',  cr: 1.0, t: { course: 'Biology',           cr: 1.0, accepted: true } },
          { course: 'World Geography',            grade: 'B',  cr: 1.0, t: { course: 'World Geography',   cr: 1.0, accepted: true } },
          { course: 'Spanish I',                  grade: 'A',  cr: 1.0, t: { course: 'Spanish I',         cr: 1.0, accepted: true } },
          { course: 'PE 9',                       grade: 'P',  cr: 0.5, t: { course: 'PE 9',              cr: 0.5, accepted: true } },
          { course: 'Computer Science Elective',  grade: 'A',  cr: 0.5, t: { course: 'CS Intro',          cr: 0.5, accepted: true, note: 'Mapped to CS-Intro (closest equivalent)' } },
        ],
      },
      {
        year: '2025–26 · Grade 10 (in progress)',
        courses: [
          { course: 'English 10 (Honors)',        grade: 'A',  cr: 1.0, t: { course: 'Eng 10 H',          cr: 1.0, accepted: true } },
          { course: 'Geometry (Honors)',          grade: 'B+', cr: 1.0, t: { course: 'Geometry H',        cr: 1.0, accepted: true } },
          { course: 'Chemistry',                  grade: 'B',  cr: 1.0, t: { course: 'Chemistry',         cr: 1.0, accepted: true } },
          { course: 'World History',              grade: 'A−', cr: 1.0, t: { course: 'World History',    cr: 1.0, accepted: true } },
          { course: 'Spanish II',                 grade: 'B+', cr: 1.0, t: { course: 'Spanish II',        cr: 1.0, accepted: true } },
          { course: 'AP Human Geography',         grade: 'IP', cr: 1.0, t: { course: 'AP Hum Geo',        cr: 1.0, accepted: 'pending', note: 'Awaiting Q3 progress report' } },
          { course: 'Theater Arts (Elective)',    grade: 'A',  cr: 0.5, t: { course: 'Fine Arts Elective', cr: 0.5, accepted: true, note: 'Counts toward Fine Arts req' } },
        ],
      },
    ],
  },
  'TS-003': {
    student: 'S. Okafor', fromSchool: 'Bayside Prep',
    cumulativeGPA: 3.91, weightedGPA: 4.12,
    years: [
      {
        year: '2023–24 · Grade 9',
        courses: [
          { course: 'English 9',                  grade: 'A',  cr: 1.0, t: { course: 'Eng 9',             cr: 1.0, accepted: true } },
          { course: 'Algebra I',                  grade: 'A−', cr: 1.0, t: { course: 'Algebra I',         cr: 1.0, accepted: true } },
          { course: 'Physical Science',           grade: 'A',  cr: 1.0, t: { course: 'Earth Science',     cr: 1.0, accepted: true, note: 'Mapped to district Earth Science equivalent' } },
          { course: 'World History',              grade: 'A',  cr: 1.0, t: { course: 'World History',    cr: 1.0, accepted: true } },
          { course: 'French I',                   grade: 'B+', cr: 1.0, t: { course: 'French I',         cr: 1.0, accepted: true } },
          { course: 'Choir',                      grade: 'A',  cr: 0.5, t: { course: 'Fine Arts Elective', cr: 0.5, accepted: true } },
        ],
      },
      {
        year: '2024–25 · Grade 10',
        courses: [
          { course: 'English 10 (Honors)',        grade: 'A',  cr: 1.0, t: { course: 'Eng 10 H',          cr: 1.0, accepted: true } },
          { course: 'Geometry',                   grade: 'A',  cr: 1.0, t: { course: 'Geometry',          cr: 1.0, accepted: true } },
          { course: 'Biology (Honors)',           grade: 'A−', cr: 1.0, t: { course: 'Biology H',         cr: 1.0, accepted: true } },
          { course: 'US History',                 grade: 'A',  cr: 1.0, t: { course: 'US History',        cr: 1.0, accepted: true } },
          { course: 'French II',                  grade: 'A−', cr: 1.0, t: { course: 'French II',        cr: 1.0, accepted: true } },
          { course: 'Robotics (Capstone)',        grade: 'A',  cr: 1.0, t: { course: 'CTE Elective',      cr: 1.0, accepted: true, note: 'No exact equivalent; mapped to CTE Elective' } },
        ],
      },
      {
        year: '2025–26 · Grade 11 (mid-year transfer)',
        courses: [
          { course: 'AP English Language',        grade: 'A',  cr: 1.0, t: { course: 'AP Eng Lang',       cr: 1.0, accepted: true } },
          { course: 'Algebra II / Trig',          grade: 'A−', cr: 1.0, t: { course: 'Algebra II',        cr: 1.0, accepted: true } },
          { course: 'AP Chemistry',               grade: 'B+', cr: 1.0, t: { course: 'AP Chemistry',      cr: 1.0, accepted: 'pending', note: 'Confirm AP score / mid-year transfer credit' } },
          { course: 'AP US History',              grade: 'A',  cr: 1.0, t: { course: 'AP US History',     cr: 1.0, accepted: true } },
          { course: 'CLR Badge — Data Literacy',  grade: '—',  cr: 0.5, t: { course: 'CTE Elec (badge)',  cr: 0.5, accepted: 'review', note: 'Verified via CLR 2.0 issuer signature' } },
        ],
      },
    ],
  },
  'TS-005': {
    student: 'D. Owens', fromSchool: 'Western HS',
    cumulativeGPA: 2.94, weightedGPA: 2.94,
    years: [
      {
        year: '2025–26 · Grade 9 (Q1–Q2)',
        courses: [
          { course: 'English 9',                  grade: 'C+', cr: 0.5, t: { course: 'Eng 9',              cr: 0.5, accepted: true,    note: 'Half-credit partial year' } },
          { course: 'Algebra I',                  grade: 'C',  cr: 0.5, t: { course: 'Algebra I',          cr: 0.5, accepted: true } },
          { course: 'Biology',                    grade: 'B−', cr: 0.5, t: { course: 'Biology',            cr: 0.5, accepted: true } },
          { course: 'US Geography',               grade: 'B',  cr: 0.5, t: { course: 'World Geography',    cr: 0.5, accepted: 'review', note: 'Course-name mismatch — counselor review' } },
          { course: 'PE 9',                       grade: 'P',  cr: 0.25, t: { course: 'PE 9',              cr: 0.25, accepted: true } },
        ],
      },
    ],
  },
};

// -------- Roster · Enroll students --------

export const enrollmentQueue = [
  { id: 'EN-204', name: 'L. Garcia',  grade: 'K',  docsComplete: 0.92, residency: 'verified', prior: 'Out-of-district transfer',  aiGrade: 'K',  confidence: 0.96,
    notes: 'All documents present and verified. Auto-approve recommended.', flags: [] },
  { id: 'EN-205', name: 'M. Reyes',   grade: '7',  docsComplete: 0.45, residency: 'pending',  prior: 'Same-district transfer',    aiGrade: '7',  confidence: 0.62,
    notes: 'Missing immunization records and proof of residency. Flag for follow-up.', flags: ['Immunizations', 'Residency'] },
  { id: 'EN-206', name: 'S. Patel',   grade: '10', docsComplete: 0.81, residency: 'verified', prior: 'Out-of-state',              aiGrade: '10', confidence: 0.78,
    notes: 'Out-of-state transcripts received; credits await registrar review.', flags: ['Transcripts (under review)'] },
  { id: 'EN-207', name: 'J. Lim',     grade: '2',  docsComplete: 0.97, residency: 'verified', prior: 'Returning (within district)', aiGrade: '2', confidence: 0.99,
    notes: 'Returning student. Prior record auto-linked. Reactivate.', flags: [] },
];

export const enrollmentDetail = {
  'EN-205': {
    docs: [
      { name: 'Birth certificate',           status: 'ok' },
      { name: 'Proof of residency',          status: 'missing' },
      { name: 'Immunization records',        status: 'missing' },
      { name: 'Prior school transcript',     status: 'ok' },
      { name: 'EL screener (if applicable)', status: 'ok' },
      { name: 'IEP / 504 (if applicable)',   status: 'na' },
    ],
    aiActions: [
      { label: 'Auto-email guardian with missing-document checklist',         tone: 'good' },
      { label: 'Pre-fill nurse intake from prior SIS immunization fields',    tone: 'good' },
      { label: 'Hold final placement pending residency verification',         tone: 'warn' },
    ],
  },
};

// -------- Roster · Plan course placement --------

export const placementRoster = [
  { id: 'P-001', student: 'A. Patel',     grade: 8,  current: 'Pre-Algebra',
    aiPlacement: 'Algebra I',              confidence: 0.84, delta: 'up',
    signals: ['MAP 92nd %ile', 'Gr-7 final: A', 'Teacher rec: ready'] },
  { id: 'P-002', student: 'J. Cho',       grade: 10, current: 'Geometry',
    aiPlacement: 'Geometry',               confidence: 0.94, delta: 'same',
    signals: ['MAP 67th %ile', 'Geo B+', 'On-pace'] },
  { id: 'P-003', student: 'M. Williams',  grade: 8,  current: 'Algebra I',
    aiPlacement: 'Pre-Algebra (review)',   confidence: 0.71, delta: 'down',
    signals: ['MAP 28th %ile', 'Q3 grade: D', '3 missing major assignments'] },
  { id: 'P-004', student: 'R. Carter',    grade: 6,  current: 'Math 6',
    aiPlacement: 'Math 6 + intervention',  confidence: 0.79, delta: 'add',
    signals: ['MAP 35th %ile', 'Q3 grade: C–', 'Tier 2 review pending'] },
  { id: 'P-005', student: 'L. Brennan',   grade: 11, current: 'AP Bio',
    aiPlacement: 'AP Bio',                 confidence: 0.92, delta: 'same',
    signals: ['Honors Bio: A', 'Teacher rec: yes', 'AP score (proxy): 4 likely'] },
  { id: 'P-006', student: 'D. Owens',     grade: 9,  current: 'Eng I',
    aiPlacement: 'Eng I + reading-lab',    confidence: 0.66, delta: 'add',
    signals: ['Reading: 4 grade-levels below', 'Recent ODR-driven absences', 'Counselor flag'] },
];

export const placementEquityFlag = {
  pair: [
    { name: 'Student α', latent: 'MAP 88, ELA A, Sci A',  placement: 'Algebra I + Honors track', meta: ['Race: White', 'IEP: No'], tone: 'good' },
    { name: 'Student β', latent: 'MAP 89, ELA A, Sci A−', placement: 'Pre-Algebra (standard)',   meta: ['Race: Black', 'IEP: No'], tone: 'bad' },
  ],
  note: 'Same prep, same signals — different placements. Flag for counselor review.',
};

// -------- SIP Absence: temporal / contextual patterns --------
//
// Each pattern describes an absence behavior that aggregates to the SAME
// daily-rate-% as another, but represents a different intervention profile.
// `days` strings encode 30 weekdays: P=present, a=absent, t=tardy, h=holiday.

function dayCells(s, marks = {}) {
  return [...s].map((c, i) => ({
    state: c === 'P' ? 'present' : c === 'a' ? 'absent' : c === 't' ? 'tardy' : 'holiday',
    mark: marks[i] || null,
  }));
}

export const sipAbsencePatterns = [
  {
    id: 'calendar',
    name: 'Calendar-coupled absences',
    blurb: "The Friday-before-3-day-weekend kid, the day-before-Thanksgiving kid. Periodicity locks to the school calendar, not the weekly cycle alone.",
    miss: "Two students with identical 8% rates look identical to Tier 2 logic — one is family-driven extended-weekend, the other transition-day anxiety.",
    student: 'A. Patel (Gr 7) · 8.2% YTD',
    signal: '6 of 9 absences fall the school-day before a 3-day weekend.',
    viz: 'days',
    days: dayCells(
      'PPPPaPPPPPPPPPaPPPPPPPPPaPPPPa',
      { 4: 'pre-Indigenous Peoples Day', 14: 'pre-conference release', 24: 'pre-Veterans Day', 29: 'pre-Thanksgiving' },
    ),
  },
  {
    id: 'assessment',
    name: 'Assessment-avoidant patterns',
    blurb: "Absences correlate with the assessment calendar — state windows, unit tests, semester finals.",
    miss: "Behaviorally this is test anxiety / academic shame / GPA-protection via planned make-up — a very different intervention than chronic disengagement.",
    student: 'J. Cho (Gr 10) · 7.8% YTD',
    signal: '4 of 5 absences land on unit-test or state-window days.',
    viz: 'days',
    days: dayCells(
      'PPaPPPPPPaPPPPPPPaPPPPaPPPPPPa',
      { 2: 'Algebra II unit test', 9: 'Chem unit test', 17: 'state ELA window', 22: 'state Math window', 29: 'semester midterm' },
    ),
  },
  {
    id: 'period',
    name: 'Period-specific skipping',
    blurb: "Present for homeroom and 1st period, absent for 4th. Pure within-day patterns.",
    miss: "Daily rate looks fine while the student is functionally truant from one teacher. Invisible to most tier systems — they aggregate to day-level.",
    student: 'M. Williams (Gr 8) · 1.4% daily, 78% P4-truant',
    signal: 'Skips P4 (Pre-Algebra w/ Mr. Rivera) on 21 of 27 days.',
    viz: 'period',
    periods: [
      { day: 'Mon', cells: ['P','P','P','a','P','P','P'] },
      { day: 'Tue', cells: ['P','P','P','a','P','P','P'] },
      { day: 'Wed', cells: ['P','P','P','P','P','P','P'] },
      { day: 'Thu', cells: ['P','P','P','a','P','P','P'] },
      { day: 'Fri', cells: ['P','P','P','a','P','P','P'] },
    ],
    periodLabels: ['HR','P1','P2','P3','P4','P5','P6'],
  },
  {
    id: 'postdiscipline',
    name: 'Post-discipline cliffs',
    blurb: "Attendance pattern shifts after an ODR or suspension. The VAE picks up the regime change; tiering sees rising absences weeks later.",
    miss: "Tightly coupled to the B (behavior) data. By the time the rate moves enough to trigger tiering, the student has been disengaging for 3–4 weeks.",
    student: 'D. Owens (Gr 9) · 3.1% → 18% post-ODR',
    signal: 'ODR-3411 on day 11. Absence rate triples over the following 19 days.',
    viz: 'days',
    days: dayCells(
      'PPPPPPPPPPaPPaPaPPaaPaPPaPaPaa',
      { 10: 'ODR · 2-day OSS' },
    ),
    eventIndex: 10,
    eventLabel: 'ODR / OSS',
  },
  {
    id: 'illness_vs_drift',
    name: 'Illness-cluster vs. chronic-drift',
    blurb: "Two students miss 12 days. One in two illness clusters. One as a slow rising trend across the year.",
    miss: "Same tier, opposite trajectories, opposite prognoses. A sequence-VAE separates these naturally; aggregate dashboards can't.",
    viz: 'dual_days',
    seriesA: {
      label: 'Sasha L. — illness clusters',
      summary: 'Two 6-day blocks (flu, then family event). Trend flat.',
      days: dayCells('PPPPPaaaaaaPPPPPPPPaaaaaaPPPPP'),
    },
    seriesB: {
      label: 'Tomás R. — chronic drift',
      summary: 'Scattered absences, slowly rising. No obvious cluster.',
      days: dayCells('PPaPPPPaPPPaPPaPPaPaPaPaPaaPaa'),
    },
  },
  {
    id: 'busroute',
    name: 'Bus-route / first-period chronics',
    blurb: "Reliably absent or tardy only for early-morning periods. Transportation / home-logistics, not school-engagement.",
    miss: "Solvable with a bus-route change, not a SART meeting. Standard tiering will eventually escalate this to Tier 3 attendance with the wrong intervention.",
    student: 'R. Carter (Gr 6) · 24% P1-tardy, 0% otherwise',
    signal: 'P1 tardy/absent on 19 of 27 days. Perfect P2–P6 attendance.',
    viz: 'period',
    periods: [
      { day: 'Mon', cells: ['t','P','P','P','P','P','P'] },
      { day: 'Tue', cells: ['a','P','P','P','P','P','P'] },
      { day: 'Wed', cells: ['t','P','P','P','P','P','P'] },
      { day: 'Thu', cells: ['t','P','P','P','P','P','P'] },
      { day: 'Fri', cells: ['a','P','P','P','P','P','P'] },
    ],
    periodLabels: ['P1','P2','P3','P4','P5','P6','P7'],
  },
  {
    id: 'coabsence',
    name: 'Co-absence clusters',
    blurb: "Students whose absence days correlate with each other above chance. Social/peer-driven skipping.",
    miss: "Only emerges when you cluster in a space that preserves the day-by-day vector — not the aggregate rate. Looks unrelated in standard reports.",
    signal: 'Group of 4 Gr-11 peers, ρ ≈ 0.72 on shared absence days.',
    viz: 'coabsence',
    peers: [
      { name: 'L. Brennan',  days: dayCells('PPaPPPaPPPPPaaPPPaPPPPaPPaPPPP') },
      { name: 'K. Otieno',   days: dayCells('PPaPPPaPPPPPaaPPPaPPPPPPPaPPPP') },
      { name: 'C. Vidal',    days: dayCells('PPPPPPaPPPPPaaPPPaPPPPaPPaPPPP') },
      { name: 'S. Mehta',    days: dayCells('PPaPPPaPPPPPaPPPPaPPPPaPPaPPPP') },
    ],
  },
  {
    id: 'seasonal',
    name: 'Seasonal / SAD-like patterns',
    blurb: "Attendance degrades October through February, then recovers in spring.",
    miss: "Looks like 'improving' under standard reporting because spring is read as recent. The VAE catches the annual shape; year-to-date averages erase it.",
    student: 'E. Lindgren (Gr 11) · 6.4% YTD',
    signal: 'Oct–Feb absence rate ≈ 14%, Mar–May ≈ 2%.',
    viz: 'season',
    months: [
      { m: 'Aug', v: 98 },
      { m: 'Sep', v: 96 },
      { m: 'Oct', v: 88 },
      { m: 'Nov', v: 82 },
      { m: 'Dec', v: 79 },
      { m: 'Jan', v: 76 },
      { m: 'Feb', v: 81 },
      { m: 'Mar', v: 91 },
      { m: 'Apr', v: 96 },
      { m: 'May', v: 98 },
    ],
  },
  {
    id: 'recovery',
    name: 'Recovery vs. relapse trajectories',
    blurb: "Two students hit Tier 3, got an AIP, then either sustained improvement or regressed at week 6.",
    miss: "If you encode intervention events in the input, the latent space can separate 'responsive to Tier 2 light-touch' from 'needs Tier 3 wraparound from day one' — the holy grail for triage.",
    viz: 'trajectory',
    interventionWeek: 8,
    weeks: 16,
    series: [
      { label: 'Responder · stays at Tier 2',
        color: '#16a34a',
        values: [72, 70, 68, 64, 60, 58, 55, 52, 60, 68, 75, 82, 86, 89, 91, 92] },
      { label: 'Relapser · needed Tier 3 from week 1',
        color: '#dc2626',
        values: [70, 68, 65, 61, 58, 55, 52, 50, 56, 60, 58, 51, 45, 40, 36, 32] },
    ],
  },
];

// -------- Behavior (ODR) --------

export const odrRecords = [
  {
    id: 'ODR-7821',
    student: 'Marcus T. (Gr 9)',
    location: 'Hallway B',
    time: '2026-05-15 10:42',
    problem: 'Disrespect / defiance',
    motivation: 'Peer attention',
    others: 'Two peers (witnesses)',
    decision: 'Restorative conversation',
  },
  {
    id: 'ODR-7822',
    student: 'Aisha R. (Gr 4)',
    location: 'Classroom 204',
    time: '2026-05-15 13:15',
    problem: 'Disruption',
    motivation: 'Escape task',
    others: 'Teacher referral only',
    decision: 'Tier 2 check-in/check-out enroll',
  },
  {
    id: 'ODR-7823',
    student: 'J. Ramirez (Gr 10)',
    location: 'Cafeteria',
    time: '2026-05-15 12:04',
    problem: 'Physical contact (minor)',
    motivation: 'Peer conflict',
    others: 'One peer',
    decision: 'Mediation + parent contact',
  },
  {
    id: 'ODR-7824',
    student: 'P. Nguyen (Gr 6)',
    location: 'PE locker room',
    time: '2026-05-14 14:50',
    problem: 'Inappropriate language',
    motivation: 'Adult attention',
    others: 'Coach + 2 peers',
    decision: 'Reteach expectation + reflection',
  },
  {
    id: 'ODR-7825',
    student: 'Hannah K. (Gr 11)',
    location: 'Parking lot',
    time: '2026-05-14 11:30',
    problem: 'Skipping / leaving campus',
    motivation: 'Escape academic demand',
    others: 'None reported',
    decision: 'Attendance contract + counselor',
  },
  {
    id: 'ODR-7826',
    student: 'L. Adebayo (Gr 3)',
    location: 'Bus 17',
    time: '2026-05-14 07:35',
    problem: 'Disruption',
    motivation: 'Sensory / regulation',
    others: 'Bus driver',
    decision: 'Sensory plan + caregiver call',
  },
];

// -------- Behavior clusters (latent patterns from B-data) --------

export const behaviorClusters = [
  {
    id: 'escalation',
    name: 'Escalation-pattern kids',
    blurb: "Referrals start minor (defiance, disruption) and progress to major (fighting, threats) over weeks. The shape is a ramp.",
    miss: "Very different intervention than students whose referrals are flat-severity over time. A VAE picks up the trajectory; an ODR count does not.",
    student: 'B. Chen (Gr 7) · 6 ODRs over 15 weeks',
    signal: 'Severity 1→3 across 15 weeks. Most-recent two were major.',
    viz: 'timeline',
    weeks: 18,
    incidents: [
      { week: 2,  severity: 1, type: 'Disruption' },
      { week: 4,  severity: 1, type: 'Defiance' },
      { week: 7,  severity: 2, type: 'Disrespect' },
      { week: 10, severity: 2, type: 'Verbal threat' },
      { week: 13, severity: 3, type: 'Physical contact' },
      { week: 15, severity: 3, type: 'Fighting' },
    ],
  },
  {
    id: 'single_teacher',
    name: 'Single-teacher conflict',
    blurb: "80%+ of referrals come from one staff member. Often a relational mismatch, not a student-wide behavioral issue.",
    miss: "Standard tier response (FBA, BIP, Tier 3 behavior plan) is the wrong intervention — the right one is a schedule change or a teacher coaching conversation.",
    student: 'M. Diallo (Gr 9) · 10 ODRs',
    signal: '8 of 10 ODRs come from one teacher. Other 5 classes: zero.',
    viz: 'bar',
    barLabel: 'ODRs by class',
    bars: [
      { label: 'Ms. Howell · P3 Algebra I',  value: 8, color: '#dc2626' },
      { label: 'Mr. Park · P1 ELA',          value: 1 },
      { label: 'Ms. Adisa · P2 Science',     value: 1 },
      { label: 'Coach Reyes · P5 PE',        value: 0 },
      { label: 'Mr. Lin · P6 Social St.',    value: 0 },
      { label: 'Ms. Tate · P7 Art',          value: 0 },
    ],
  },
  {
    id: 'setting',
    name: 'Setting-specific',
    blurb: "Referrals cluster in unstructured time — cafeteria, hallway, recess, bus, PE — rather than instructional time.",
    miss: "Environmental / supervision issue more than a student skill deficit. Different intervention: change the setting, not the student.",
    student: 'Gr 6–8 cohort · 14 students, 90 ODRs',
    signal: '76% of group ODRs are during transitions or unstructured time.',
    viz: 'bar',
    barLabel: 'ODRs by location',
    bars: [
      { label: 'Cafeteria',             value: 28, color: '#d97706' },
      { label: 'Hallway / transition',  value: 22, color: '#d97706' },
      { label: 'Bus / bus loop',        value: 17, color: '#d97706' },
      { label: 'PE / locker room',      value: 11, color: '#d97706' },
      { label: 'Classroom',             value: 8 },
      { label: 'Other',                 value: 4 },
    ],
  },
  {
    id: 'timeofday',
    name: 'Time-of-day patterns',
    blurb: "Pre-lunch hunger spikes, post-lunch crashes, end-of-day fatigue, Monday re-entry.",
    miss: "Correlates with executive function, medication timing, sleep, food security. A VAE with timestamp features surfaces this; the discipline log alone doesn't.",
    student: 'Gr 4 cohort · n=18 students, 64 ODRs',
    signal: 'Spikes at 11:00–11:30 (pre-lunch) and 13:30–14:00 (post-lunch).',
    viz: 'timeOfDay',
    hours: [
      { h: '8:00',  n: 2 },
      { h: '9:00',  n: 3 },
      { h: '10:00', n: 4 },
      { h: '11:00', n: 9 },
      { h: '11:30', n: 12 },
      { h: '12:00', n: 3 },
      { h: '13:00', n: 4 },
      { h: '13:30', n: 11 },
      { h: '14:00', n: 8 },
      { h: '15:00', n: 8 },
    ],
  },
  {
    id: 'antecedent',
    name: 'Antecedent-coupled',
    blurb: "Referrals predictably follow specific triggers — substitute teachers, fire drills, schedule changes, peer absences, home-life events.",
    miss: "If your B-data has antecedent codes (SWIS does, inconsistently), this becomes learnable. Otherwise invisible.",
    student: 'A. Romero (Gr 5) · 7 ODRs',
    signal: '5 of 7 ODRs follow a known antecedent within 48 hours.',
    viz: 'bar',
    barLabel: 'ODRs by antecedent',
    bars: [
      { label: 'Substitute teacher present', value: 3, color: '#9333ea' },
      { label: 'Best-friend peer absent',    value: 2, color: '#9333ea' },
      { label: 'Schedule change / assembly', value: 1 },
      { label: 'Fire drill / lockdown',      value: 1 },
      { label: 'No identified antecedent',   value: 2 },
    ],
  },
  {
    id: 'int_ext',
    name: 'Internalizing vs. externalizing',
    blurb: "Same total signal, opposite clinical profiles. Externalizing kids dominate ODR data; internalizing kids are nearly invisible in B-data.",
    miss: "You find internalizing kids through A + C (attendance + grades) — part of why ABC together matters.",
    viz: 'intExt',
    pair: {
      ext: {
        name: 'J. Kowalski (Gr 6)',
        kind: 'Externalizing',
        total: 14,
        unit: 'ODRs',
        breakdown: [
          { k: 'Disruption / non-compliance', v: 10 },
          { k: 'Work refusal',                v: 3 },
          { k: 'Talking back',                v: 1 },
        ],
        profile: 'Frequent, low-severity. Highly visible to teachers and admin.',
      },
      int: {
        name: 'R. Han (Gr 6)',
        kind: 'Internalizing',
        total: 14,
        unit: 'A+C signals',
        breakdown: [
          { k: 'Quiet absences (unexplained)',     v: 11 },
          { k: 'Missed assignments',               v: 12 },
          { k: 'Withdrawal / on-task w/o output',  v: 14 },
        ],
        profile: 'Zero ODRs. Surfaces only via attendance + grade decline.',
        note: 'B-data is silent for this student.',
      },
    },
  },
  {
    id: 'reactive',
    name: 'Reactive / retaliatory',
    blurb: "Referrals follow being a victim of another incident, often within days. The student is responding to something done to them.",
    miss: "Standard discipline punishes the response and misses the precipitating event. A subject-and-target event sequence separates this.",
    student: 'I. Berisha (Gr 8) · 3 ODRs as subject, 3 as target',
    signal: 'Each subject-ODR is within 5 school days of a target-ODR.',
    viz: 'timeline',
    weeks: 18,
    incidents: [
      { week: 3,  severity: 1, type: 'Bullied',              role: 'target' },
      { week: 3,  severity: 2, type: 'Verbal escalation',    role: 'subject' },
      { week: 8,  severity: 1, type: 'Excluded by peers',    role: 'target' },
      { week: 9,  severity: 2, type: 'Disruption',           role: 'subject' },
      { week: 14, severity: 2, type: 'Pushed in hallway',    role: 'target' },
      { week: 15, severity: 3, type: 'Fighting',             role: 'subject' },
    ],
  },
  {
    id: 'honeymoon',
    name: 'Honeymoon-then-collapse',
    blurb: "Clean record for the first 4–8 weeks of school, then a sharp onset.",
    miss: "Different from chronic kids who arrive with a history. End-of-quarter aggregates look like normal severity; only temporal models catch the onset.",
    student: 'S. Park (Gr 5) · 0 → 6 ODRs after week 7',
    signal: 'Zero incidents through week 7. Six incidents in weeks 8–13.',
    viz: 'timeline',
    weeks: 18,
    incidents: [
      { week: 8,  severity: 1, type: 'Disruption' },
      { week: 9,  severity: 2, type: 'Defiance' },
      { week: 10, severity: 2, type: 'Verbal' },
      { week: 11, severity: 2, type: 'Defiance' },
      { week: 12, severity: 3, type: 'Property destruction' },
      { week: 13, severity: 3, type: 'Threatening' },
    ],
  },
  {
    id: 'restorative',
    name: 'Restorative-responsive vs. -resistant',
    blurb: "Get a referral, go through a restorative / Tier 2 intervention. Either no recurrence for 60+ days, or recurrence within 2 weeks.",
    miss: "If intervention events are in the input, this becomes one of the most actionable axes in latent space — Tier 2 responder vs. needs-Tier-3-from-day-one.",
    viz: 'dualTimeline',
    interventionWeek: 5,
    interventionLabel: 'Tier 2 restorative',
    weeks: 18,
    students: [
      {
        name: 'Responsive · K. Mensah (Gr 7)',
        tone: 'good',
        incidents: [
          { week: 2, severity: 2, type: 'Disrespect' },
          { week: 5, severity: 2, type: 'Disruption' },
        ],
        note: '13 weeks recurrence-free since intervention.',
      },
      {
        name: 'Resistant · Z. Aroyan (Gr 7)',
        tone: 'bad',
        incidents: [
          { week: 2, severity: 2, type: 'Disrespect' },
          { week: 5, severity: 2, type: 'Disruption' },
          { week: 6, severity: 2, type: 'Defiance' },
          { week: 7, severity: 3, type: 'Threat' },
          { week: 9, severity: 3, type: 'Fighting' },
          { week: 13, severity: 2, type: 'Disruption' },
        ],
        note: 'Recurrence in week 6 — needed Tier 3 from intake.',
      },
    ],
  },
  {
    id: 'peer_network',
    name: 'Co-occurrence / peer-network clusters',
    blurb: "Students whose incidents involve overlapping peer sets. Group dynamics rather than individual pathology.",
    miss: "Individual-record ODR review misses this entirely. A VAE alone won't recover it — engineer peer-overlap features or do a graph step first.",
    signal: 'Gr-10 group of 5 peers · 9 of 12 incidents involve ≥ 2 of them.',
    viz: 'peerNetwork',
    nodes: [
      { id: 'A', x: 0.50, y: 0.45, label: 'A.N.', size: 6 },
      { id: 'B', x: 0.18, y: 0.22, label: 'B.O.', size: 5 },
      { id: 'C', x: 0.85, y: 0.28, label: 'C.P.', size: 4 },
      { id: 'D', x: 0.25, y: 0.80, label: 'D.Q.', size: 5 },
      { id: 'E', x: 0.82, y: 0.78, label: 'E.R.', size: 3 },
    ],
    edges: [
      { from: 'A', to: 'B', weight: 4 },
      { from: 'A', to: 'C', weight: 3 },
      { from: 'A', to: 'D', weight: 3 },
      { from: 'A', to: 'E', weight: 2 },
      { from: 'B', to: 'D', weight: 2 },
      { from: 'C', to: 'E', weight: 2 },
    ],
  },
  {
    id: 'stable_low',
    name: 'Severity-stable, low-frequency',
    blurb: "2–3 referrals a year, all moderate, spread across contexts.",
    miss: "Some district policies tier these students up by raw count. Behaviorally typical — the VAE puts them near the 'no concerns' centroid.",
    student: 'T. Okafor (Gr 6) · 3 ODRs over 32 weeks',
    signal: 'Severity flat at 2. Locations and teachers all different.',
    viz: 'timeline',
    weeks: 32,
    incidents: [
      { week: 6,  severity: 2, type: 'Tardy / disrespect' },
      { week: 16, severity: 2, type: 'Disruption' },
      { week: 26, severity: 2, type: 'Defiance' },
    ],
  },
  {
    id: 'disparity',
    name: 'Discipline-disparity flags',
    blurb: "Cluster in latent space, then check whether similar-position students receive systematically different consequences by race, IEP, or EL status.",
    miss: "Not a behavioral cluster per se — but this is where the VAE becomes an equity tool, not just a triage tool. Increasingly required for district monitoring.",
    signal: 'Cosine similarity 0.97 in z-space · consequence severity differs by 2 tiers.',
    viz: 'disparity',
    pair: {
      a: {
        name: 'Student α', latent: 'z ≈ (0.42, −0.18, …)',
        meta: ['Race: White', 'IEP: No', 'EL: No'],
        consequence: 'Restorative conversation',
        tone: 'good',
      },
      b: {
        name: 'Student β', latent: 'z ≈ (0.39, −0.20, …)',
        meta: ['Race: Black', 'IEP: No', 'EL: No'],
        consequence: '2-day OSS',
        tone: 'bad',
      },
    },
  },
];

// -------- Upload data --------

export const uploadOutputTypes = [
  { id: 'panorama_students',     label: 'Panorama — Student Roster (CSV)' },
  { id: 'panorama_attendance',   label: 'Panorama — Attendance Events (CSV)' },
  { id: 'panorama_behavior',     label: 'Panorama — Behavior Incidents (CSV)' },
  { id: 'powerschool_enroll',    label: 'PowerSchool — Enrollment Import (TAB)' },
  { id: 'powerschool_attendance',label: 'PowerSchool — Attendance Daily (TAB)' },
  { id: 'powerschool_grades',    label: 'PowerSchool — Grades (TAB)' },
  { id: 'powerschool_sect',      label: 'PowerSchool — Sections / Schedules (TAB)' },
  { id: 'ews_aimsweb',           label: 'EWS — aimswebPlus Composite (CSV)' },
];

// -------- VAE / ABC Screening --------

// Pre-baked UMAP / PCA projections of mu vectors for ~120 students,
// colored by cluster assignment. Coords are illustrative.
//
// Each VAE model is parameterized by (centerScale, baseSpread):
//   - centerScale stretches cluster centers further apart
//   - baseSpread tightens or loosens within-cluster scatter
// The projector then multiplies baseSpread (PCA messier than UMAP).
function buildScatter(seed, centerScale, spread) {
  const baseCenters = [
    { c: 0, label: 'On-track',                 cx: -1.4, cy:  0.8, sx: 1.6, sy: 1.4 },
    { c: 1, label: 'Slipping (Tier 2)',        cx:  0.2, cy:  1.4, sx: 1.7, sy: 1.5 },
    { c: 2, label: 'Behaviorally disengaged',  cx:  1.3, cy: -0.4, sx: 1.5, sy: 1.6 },
    { c: 3, label: 'Chronic absentee',         cx: -0.4, cy: -1.3, sx: 1.6, sy: 1.5 },
    { c: 4, label: 'Disengaged (Tier 4–5)',    cx:  1.9, cy:  1.2, sx: 1.4, sy: 1.3 },
  ];
  const counts = [42, 28, 22, 18, 10];
  const stragglerRate = 0.12;
  const pts = [];
  let s = seed;
  const rand = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  const gauss = () => {
    const u1 = Math.max(rand(), 1e-6);
    const u2 = rand();
    return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  };
  baseCenters.forEach((c, i) => {
    const cx = c.cx * centerScale;
    const cy = c.cy * centerScale;
    for (let n = 0; n < counts[i]; n++) {
      const isStraggler = rand() < stragglerRate;
      const mult = isStraggler ? 2.4 : 1.0;
      pts.push({
        x: cx + gauss() * c.sx * spread * mult * 0.6,
        y: cy + gauss() * c.sy * spread * mult * 0.6,
        cluster: c.c,
        clusterLabel: c.label,
      });
    }
  });
  return pts;
}

// VAE model "quality" — disentanglement strength, governs how well clusters separate.
//   vanilla    → original heavy-overlap look (preserved unchanged)
//   factor_vae → moderate separation
//   beta_vae   → mostly clustered (default in the view)
//   tcvae      → cleanest separation
const MODEL_CONFIG = {
  vanilla:    { centerScale: 1.0, baseSpread: 1.0  },
  factor_vae: { centerScale: 1.4, baseSpread: 0.85 },
  beta_vae:   { centerScale: 1.9, baseSpread: 0.65 },
  tcvae:      { centerScale: 2.5, baseSpread: 0.50 },
};

// Projector messiness multiplier on top of model spread.
const PROJ_SPREAD_MULT = { umap: 1.0, tsne: 1.25, pca: 1.7 };
const PROJ_SEED        = { umap: 7,   tsne: 31,   pca: 53  };

export const clusterPalette = [
  { c: 0, label: 'On-track',                color: '#16a34a' },
  { c: 1, label: 'Slipping (Tier 2)',       color: '#2563eb' },
  { c: 2, label: 'Behaviorally disengaged', color: '#9333ea' },
  { c: 3, label: 'Chronic absentee',        color: '#d97706' },
  { c: 4, label: 'Disengaged (Tier 4–5)',   color: '#dc2626' },
];

export const projections = Object.fromEntries(
  Object.entries(MODEL_CONFIG).map(([modelId, cfg]) => [
    modelId,
    {
      umap: buildScatter(PROJ_SEED.umap, cfg.centerScale, cfg.baseSpread * PROJ_SPREAD_MULT.umap),
      tsne: buildScatter(PROJ_SEED.tsne, cfg.centerScale, cfg.baseSpread * PROJ_SPREAD_MULT.tsne),
      pca:  buildScatter(PROJ_SEED.pca,  cfg.centerScale, cfg.baseSpread * PROJ_SPREAD_MULT.pca),
    },
  ]),
);

// Latent-dimension heatmap: rows = clusters, cols = latent dims (z0..z7)
// values are mean z-value per cluster per dim (illustrative).
export const latentHeatmap = {
  dims: ['z0','z1','z2','z3','z4','z5','z6','z7'],
  rows: [
    { label: 'On-track',                values: [ 0.10,  0.05, -0.20, -0.15,  0.00,  0.08, -0.05,  0.12] },
    { label: 'Slipping (Tier 2)',       values: [ 0.85,  0.32,  0.10, -0.40,  0.18,  0.05, -0.10,  0.30] },
    { label: 'Behaviorally disengaged', values: [ 0.20,  1.42, -0.30,  0.78, -0.05,  0.55,  1.10, -0.20] },
    { label: 'Chronic absentee',        values: [ 1.65,  0.40, -0.85, -1.10,  0.95,  0.60, -0.20,  0.80] },
    { label: 'Disengaged (Tier 4–5)',   values: [ 1.95,  1.20, -1.20, -1.60,  1.40,  1.10,  0.85,  1.25] },
  ],
};

// Decoded centroids -> reconstructed ABC profile per cluster.
// Each cluster has a few feature scores (0-100).
export const decodedCentroids = [
  {
    cluster: 0, label: 'On-track',
    features: [
      { k: 'Unexcused absence rate', v: 8 },
      { k: 'GPA trajectory',         v: 86 },
      { k: 'Behavior referrals',     v: 5 },
      { k: 'Engagement signals',     v: 78 },
      { k: 'Tardy frequency',        v: 12 },
      { k: 'Course pass rate',       v: 95 },
    ],
  },
  {
    cluster: 1, label: 'Slipping (Tier 2)',
    features: [
      { k: 'Unexcused absence rate', v: 22 },
      { k: 'GPA trajectory',         v: 64 },
      { k: 'Behavior referrals',     v: 18 },
      { k: 'Engagement signals',     v: 52 },
      { k: 'Tardy frequency',        v: 41 },
      { k: 'Course pass rate',       v: 78 },
    ],
  },
  {
    cluster: 2, label: 'Behaviorally disengaged',
    features: [
      { k: 'Unexcused absence rate', v: 30 },
      { k: 'GPA trajectory',         v: 48 },
      { k: 'Behavior referrals',     v: 72 },
      { k: 'Engagement signals',     v: 35 },
      { k: 'Tardy frequency',        v: 58 },
      { k: 'Course pass rate',       v: 60 },
    ],
  },
  {
    cluster: 3, label: 'Chronic absentee',
    features: [
      { k: 'Unexcused absence rate', v: 68 },
      { k: 'GPA trajectory',         v: 35 },
      { k: 'Behavior referrals',     v: 22 },
      { k: 'Engagement signals',     v: 28 },
      { k: 'Tardy frequency',        v: 35 },
      { k: 'Course pass rate',       v: 42 },
    ],
  },
  {
    cluster: 4, label: 'Disengaged (Tier 4–5)',
    features: [
      { k: 'Unexcused absence rate', v: 85 },
      { k: 'GPA trajectory',         v: 18 },
      { k: 'Behavior referrals',     v: 58 },
      { k: 'Engagement signals',     v: 12 },
      { k: 'Tardy frequency',        v: 70 },
      { k: 'Course pass rate',       v: 22 },
    ],
  },
];

// Bootstrap stability: how often each pair of clusters appears together (illustrative)
export const bootstrapStability = [
  { cluster: 'On-track',                 stability: 0.93, n: 42 },
  { cluster: 'Slipping (Tier 2)',        stability: 0.71, n: 28 },
  { cluster: 'Behaviorally disengaged',  stability: 0.82, n: 22 },
  { cluster: 'Chronic absentee',         stability: 0.88, n: 18 },
  { cluster: 'Disengaged (Tier 4–5)',    stability: 0.79, n: 10 },
];

// -------- School Improvement Plan metrics --------

export const sipMetrics = [
  {
    label: 'Tier-2 attendance referrals contacted ≤ 5 days',
    value: 64, target: 90, delta: '+8 vs last month', deltaGood: true, denomLabel: '184 of 287 referrals',
  },
  {
    label: 'Behavior referrals → restorative conversation',
    value: 52, target: 85, delta: 'avg lag 9.2 days', deltaGood: false, denomLabel: '96 of 184 referrals',
  },
  {
    label: 'EWS-flagged students with assigned adult',
    value: 81, target: 100, delta: '+12 this semester', deltaGood: true, denomLabel: '212 of 261 students',
  },
  {
    label: 'EWS-flagged students with 1st check-in completed',
    value: 58, target: 100, delta: 'median lag 11 days', deltaGood: false, denomLabel: '152 of 261 students',
  },
  {
    label: 'Tier-2 interventions on-schedule for progress monitoring',
    value: 47, target: 80, delta: '−4 vs last month', deltaGood: false, denomLabel: '108 of 230 interventions',
  },
  {
    label: 'Tier-3 plans dated within last 90 days',
    value: 73, target: 95, delta: '+5 vs Q3', deltaGood: true, denomLabel: '54 of 74 plans',
  },
  {
    label: 'IEP/504 accommodations acknowledged by teachers',
    value: 88, target: 100, delta: 'this semester', deltaGood: true, denomLabel: '4,212 of 4,790 teacher×student',
  },
];

// -------- Additional tiers --------

export const tierFramework = [
  {
    tier: 1, color: 'tier-1',
    title: 'Schoolwide universal supports',
    blurb: 'Applies to all students. Positive climate, clear expectations, recognition.',
    items: [
      'Schoolwide attendance recognition (perfect-week celebrations)',
      'Positive climate / SEL curriculum embedded across grade bands',
      'Clear posted expectations + reteach cycle on transitions',
      'Universal screening 3× per year (attendance + ABC composite)',
    ],
  },
  {
    tier: 2, color: 'tier-2',
    title: 'Light-touch early interventions',
    blurb: 'Catch slipping attendance before chronic. Letters home, mentor check-ins, barrier ID.',
    items: [
      'Attendance letters home at 3 / 5 / 8 unexcused days',
      'Mentor check-in / check-out (CICO) cycles',
      'Parent contact log + barrier intake form',
      'Small group skill-building (executive function, social)',
    ],
  },
  {
    tier: 3, color: 'tier-3',
    title: 'Personalized interventions',
    blurb: 'Success plans, attendance contracts, small-group support, home visits, wraparound.',
    items: [
      'Individual success plan with named adult + dated goals',
      'Attendance contract w/ family',
      'Home visits with bilingual liaison',
      'Connection to wraparound (food, housing, mental health)',
    ],
  },
  {
    tier: 4, color: 'tier-4',
    title: 'Intensive case management',
    blurb: 'Multidisciplinary team review, deeper family engagement, social worker / community partner involvement.',
    items: [
      'Weekly multi-disciplinary case team',
      'Assigned social worker / community liaison',
      'Modified schedule or alternative pathways considered',
      'Trauma-informed services coordination',
    ],
  },
  {
    tier: 5, color: 'tier-5',
    title: 'Court / alternative placement / disengaged',
    blurb: 'Court involvement, truancy proceedings, alternative placement, or students who have effectively disengaged.',
    items: [
      'Truancy court referrals (only after lower tiers exhausted)',
      'Alternative placement evaluation (e.g., online, hybrid)',
      'Re-engagement campaign for fully disengaged students',
      'Final-step legal / DSS coordination',
    ],
  },
];
