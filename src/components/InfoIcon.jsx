export default function InfoIcon({ children, ariaLabel = 'More information', width = 640, align = 'left' }) {
  const positionStyle = align === 'right' ? { right: 0, left: 'auto' } : { left: 0 };
  return (
    <span className="info-icon" tabIndex={0} aria-label={ariaLabel}>
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="8" cy="4.5" r="0.9" fill="currentColor" />
        <rect x="7.25" y="6.6" width="1.5" height="5.4" rx="0.75" fill="currentColor" />
      </svg>
      <div className="info-popover" role="tooltip" style={{ width, ...positionStyle }}>
        {children}
      </div>
    </span>
  );
}
