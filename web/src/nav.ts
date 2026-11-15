import { useEffect, useState } from "react";

// Real URLs (/network/15169) with the History API. The web server sends
// index.html for any path, so links can be shared and reloaded.

export function navigate(path: string) {
  if (path !== location.pathname) history.pushState(null, "", path);
  window.dispatchEvent(new Event("routeboard:nav"));
  window.scrollTo(0, 0);
}

export function usePath(): string {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => {
    // Links from the first version used #/page; keep them working.
    if (location.hash.startsWith("#/")) history.replaceState(null, "", location.hash.slice(1));
    const sync = () => setPath(location.pathname);
    sync();
    // Let ordinary <a href="/..."> links navigate without a page reload.
    const click = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element).closest?.("a");
      if (!a || a.target || a.hasAttribute("download")) return;
      const href = a.getAttribute("href");
      if (!href || !href.startsWith("/") || href.startsWith("/api/")) return;
      e.preventDefault();
      navigate(href);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("routeboard:nav", sync);
    document.addEventListener("click", click);
    return () => { window.removeEventListener("popstate", sync); window.removeEventListener("routeboard:nav", sync); document.removeEventListener("click", click); };
  }, []);
  return path;
}
