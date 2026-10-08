/**
 * The application mark: an "A" drawn as three connected nodes, for a team of
 * analysts working as one. It sits on the brand colour and follows the theme.
 * Decorative wherever the application name is written beside it.
 *
 * To use a company logo instead, replace this component and public/favicon.svg.
 */
export function LogoMark({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden focusable="false"
         className={`shrink-0 ${className}`}>
      <rect width="32" height="32" rx="8" className="fill-brand-600" />
      <g className="stroke-white" strokeWidth={2.5} strokeLinecap="round"
         strokeLinejoin="round" fill="none">
        <path d="M9 23 16 9l7 14" />
        <path d="M12.5 17.5h7" />
      </g>
      <g className="fill-white">
        <circle cx="16" cy="9" r="3" />
        <circle cx="9" cy="23" r="3" />
        <circle cx="23" cy="23" r="3" />
      </g>
    </svg>
  )
}
