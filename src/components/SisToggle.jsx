export default function SisToggle({ value, onChange, label = 'Utilize SIS' }) {
  return (
    <label className="sis-toggle">
      <span className="label-text">{label}</span>
      <span
        className={`switch ${value ? 'on' : ''}`}
        onClick={() => onChange(!value)}
        role="switch"
        aria-checked={value}
      />
      <span className="state">{value ? 'True' : 'False'}</span>
    </label>
  );
}
