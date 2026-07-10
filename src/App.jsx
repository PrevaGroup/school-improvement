import { useState } from 'react';
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import StudentProfiles from './components/views/StudentProfiles.jsx';
import TransferData from './components/views/TransferData.jsx';
import EnrollStudents from './components/views/EnrollStudents.jsx';
import PlanCourses from './components/views/PlanCourses.jsx';
import CategorizeAttendance from './components/views/CategorizeAttendance.jsx';
import SipAbsence from './components/views/SipAbsence.jsx';
import Behavior from './components/views/Behavior.jsx';
import BehaviorClusters from './components/views/BehaviorClusters.jsx';
import UploadData from './components/views/UploadData.jsx';
import ABCScreening from './components/views/ABCScreening.jsx';
import SchoolImprovementPlan from './components/views/SchoolImprovementPlan.jsx';
import AdditionalTiers from './components/views/AdditionalTiers.jsx';

const VIEWS = {
  student_profiles: { label: 'Set up Student Profiles',    component: StudentProfiles },
  transfer_data:    { label: 'Transfer Student Data',      component: TransferData },
  enroll_students:  { label: 'Enroll Students',            component: EnrollStudents },
  plan_courses:     { label: 'Plan Course Placement',      component: PlanCourses },
  daily_attendance: { label: 'Daily Attendance', component: CategorizeAttendance },
  school_attendance: { label: 'School Attendance', component: SipAbsence },
  behavior: { label: 'Behavior Review', component: Behavior },
  behavior_clusters: { label: 'Behavior Clusters', component: BehaviorClusters },
  upload: { label: 'Upload Data', component: UploadData },
  screening: { label: 'Screening: ABC Clusters', component: ABCScreening },
  sip: { label: 'School Improvement Plans', component: SchoolImprovementPlan },
  weekly_attendance: { label: 'Weekly Attendance (Tier 2)', component: AdditionalTiers },
};

export default function App() {
  const [active, setActive] = useState('daily_attendance');
  const ActiveView = VIEWS[active].component;

  return (
    <div className="app-shell">
      <Header />
      <div className="app-body">
        <Sidebar active={active} onSelect={setActive} />
        <main className="content">
          <ActiveView />
        </main>
      </div>
    </div>
  );
}
