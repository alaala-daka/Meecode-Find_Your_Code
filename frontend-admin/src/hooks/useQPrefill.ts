import * as React from "react";
import { useSearchParams } from "react-router";

export function useQPrefill(apply: (q: string) => void) {
  const [searchParams] = useSearchParams();
  const [initialQ] = React.useState(() => searchParams.get("q") ?? "");
  const applyRef = React.useRef(apply);
  applyRef.current = apply;
  React.useEffect(() => {
    if (initialQ) applyRef.current(initialQ);
  }, [initialQ]);
}
