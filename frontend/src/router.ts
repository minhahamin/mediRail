import { useEffect, useState } from "react";

/** 의존성 없는 미니 라우터: History API 기반. 배포(nginx)가 모든 경로를 index.html로 돌려주므로 새로고침해도 동작한다. */
export type AuthRoute = "/login" | "/signup" | "/demo";

const normalize = (path: string): AuthRoute => {
  const p = path.replace(/\/+$/, "");
  return p === "/signup" ? "/signup" : p === "/demo" ? "/demo" : "/login";
};

export function navigate(path: string, replace = false) {
  if (window.location.pathname === path) return;
  if (replace) window.history.replaceState(null, "", path);
  else window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useAuthRoute(): AuthRoute {
  const [route, setRoute] = useState<AuthRoute>(() => normalize(window.location.pathname));
  useEffect(() => {
    const on = () => setRoute(normalize(window.location.pathname));
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  return route;
}
