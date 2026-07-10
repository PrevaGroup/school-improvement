const SECTIONS = [
  {
    title: 'Roster Students Grouping',
    items: [
      { key: 'student_profiles', label: 'Set up Student Profiles' },
      { key: 'transfer_data',    label: 'Transfer Student Data' },
      { key: 'enroll_students',  label: 'Enroll Students' },
      { key: 'plan_courses',     label: 'Plan Course Placement' },
    ],
  },
  {
    title: 'Attendance',
    items: [
      { key: 'daily_attendance',   label: 'Daily Attendance' },
      { key: 'school_attendance',  label: 'School Attendance' },
      { key: 'weekly_attendance',  label: 'Weekly Attendance (Tier 2)' },
    ],
  },
  {
    title: 'Behavior',
    items: [
      { key: 'behavior',          label: 'Behavior Review' },
      { key: 'behavior_clusters', label: 'Behavior Clusters' },
    ],
  },
  {
    title: 'Screening',
    items: [{ key: 'screening', label: 'ABC Clusters (VAE)' }],
  },
  {
    title: 'Plans & Operations',
    items: [
      { key: 'sip',    label: 'School Improvement Plans' },
      { key: 'upload', label: 'Upload Data' },
    ],
  },
];

export default function Sidebar({ active, onSelect }) {
  return (
    <nav className="sidebar">
      {SECTIONS.map((section) => (
        <div key={section.title}>
          <div className="group-title">{section.title}</div>
          {section.items.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${active === item.key ? 'active' : ''}`}
              onClick={() => onSelect(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
