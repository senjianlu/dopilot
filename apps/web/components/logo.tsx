import * as React from "react";

// Brand mark rendered from apps/web/public/logo.svg. It is inlined as a React
// component (rather than referenced as an <img>/next-image) so `currentColor`
// picks up the surrounding foreground color — an external image would render a
// fixed black mark and would not adapt to the sidebar-primary box in dark mode.
export function Logo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 280 160"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      aria-hidden
      {...props}
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M0 0H280V120H240V160H0ZM40 40V120H120V40ZM160 40V120H240V40Z"
      />
    </svg>
  );
}
