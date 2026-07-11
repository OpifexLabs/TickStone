(() => {
  const key = "tickstone-dashboard-last-reload";
  const now = Date.now();
  const previous = Number(sessionStorage.getItem(key) || now);
  sessionStorage.setItem(key, String(now));
  window.setTimeout(() => {
    if (!document.hidden && Date.now() - previous >= 55000) window.location.reload();
  }, 60000);
})();
