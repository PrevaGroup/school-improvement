const STEPS = [
  "Ready the team",
  "Scan indicators",
  "Prioritize",
  "Analyze root causes",
  "Develop a theory of action",
  "Select interventions",
  "Plan for implementation",
];

export function StepsInfo({ active }: { active: string }) {
  return (
    <span className="info" tabIndex={0}>
      i
      <span className="tip">
        <b>Continuous-improvement cycle</b>
        <ol className="steps">
          {STEPS.map((st) => (
            <li key={st} className={st === active ? "on" : ""}>{st}</li>
          ))}
        </ol>
      </span>
    </span>
  );
}
