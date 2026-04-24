import BorderGlow from "./BorderGlow";

export default function Card({ title, children, className = "" }) {
  return (
    <BorderGlow className={`card ${className}`.trim()} backgroundColor="#141417">
      {title ? <h3 className="card-title">{title}</h3> : null}
      {children}
    </BorderGlow>
  );
}
