// Two apps share one build: the company's public front page at "/" and the ERP under "/next/". Each is its own
// bundle with its own styles, so opening one never downloads or restyles the other.
if (location.pathname === '/') void import('./features/site/boot')
else void import('./boot-app')
