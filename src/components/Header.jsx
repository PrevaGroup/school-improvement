export default function Header() {
  return (
    <header className="header">
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <h1>ABC SIP Prototype</h1>
        <span className="disclaimer">Prototype — no real student data</span>
      </div>
      <div className="right">v0.1 · mock SIS</div>
    </header>
  );
}
